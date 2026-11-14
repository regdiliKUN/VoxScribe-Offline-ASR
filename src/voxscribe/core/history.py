"""Local transcription history (SQLite, WAL, corruption-tolerant)."""
from __future__ import annotations

import json
import logging
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path

from .errors import VoxScribeError
from .paths import history_file
from .transcriber import TranscriptResult

log = logging.getLogger("voxscribe.history")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS transcripts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    source TEXT,
    engine TEXT,
    duration REAL,
    audio_path TEXT,
    text TEXT,
    segments_json TEXT,
    warnings_json TEXT
);
CREATE INDEX IF NOT EXISTS idx_transcripts_created ON transcripts(created_at DESC);
"""


class HistoryError(VoxScribeError):
    user_message = "历史记录读写失败，已自动重建数据库。"
    code = "VOX_HISTORY"


class HistoryDB:
    def __init__(self, path: str | Path | None = None):
        self.path = Path(path) if path else history_file()
        self._lock = threading.RLock()
        self._init()

    def _connect(self) -> sqlite3.Connection:
        conn = None
        try:
            conn = sqlite3.connect(str(self.path), timeout=10)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            return conn
        except Exception:
            # A half-open connection keeps a Windows file handle and would
            # prevent the corrupt-file quarantine below from renaming it.
            if conn is not None:
                try:
                    conn.close()
                except sqlite3.Error:
                    pass
            raise

    @contextmanager
    def _session(self):
        """Connection scope that always closes (sqlite3's `with` does not)."""
        conn = self._connect()
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _init(self) -> None:
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            try:
                with self._session() as conn:
                    conn.executescript(_SCHEMA)
            except sqlite3.DatabaseError as exc:
                log.warning("History DB unusable (%s); rebuilding", exc)
                try:
                    backup = self.path.with_suffix(self.path.suffix + ".bad")
                    self.path.replace(backup)
                    for suffix in ("-wal", "-shm"):
                        Path(str(self.path) + suffix).unlink(missing_ok=True)
                except OSError:
                    pass
                try:
                    with self._session() as conn:
                        conn.executescript(_SCHEMA)
                except sqlite3.DatabaseError as exc2:
                    raise HistoryError(detail=str(exc2), cause=exc2) from exc2

    def add(self, result: TranscriptResult) -> int:
        with self._lock, self._session() as conn:
            cur = conn.execute(
                "INSERT INTO transcripts(created_at, source, engine, duration, audio_path,"
                " text, segments_json, warnings_json) VALUES(?,?,?,?,?,?,?,?)",
                (result.created_at, result.source, result.engine, result.duration,
                 result.audio_path, result.text,
                 json.dumps([s.as_dict() for s in result.segments], ensure_ascii=False),
                 json.dumps(result.warnings, ensure_ascii=False)),
            )
            return int(cur.lastrowid)

    def _row_to_dict(self, row: sqlite3.Row) -> dict:
        d = dict(row)
        raw_segments = d.pop("segments_json", "[]")
        raw_warnings = d.pop("warnings_json", "[]")
        for key, raw in (("segments", raw_segments), ("warnings", raw_warnings)):
            try:
                d[key] = json.loads(raw or "[]")
            except (json.JSONDecodeError, TypeError):
                d[key] = []
        return d

    def list(self, limit: int = 50, offset: int = 0) -> list[dict]:
        with self._lock, self._session() as conn:
            rows = conn.execute(
                "SELECT * FROM transcripts ORDER BY id DESC LIMIT ? OFFSET ?",
                (max(1, min(1000, int(limit))), max(0, int(offset)))).fetchall()
        return [self._row_to_dict(r) for r in rows]

    def get(self, rec_id: int) -> dict | None:
        with self._lock, self._session() as conn:
            row = conn.execute("SELECT * FROM transcripts WHERE id=?", (rec_id,)).fetchone()
        return self._row_to_dict(row) if row else None

    def search(self, keyword: str, limit: int = 50) -> list[dict]:
        with self._lock, self._session() as conn:
            rows = conn.execute(
                "SELECT * FROM transcripts WHERE text LIKE ? OR source LIKE ?"
                " ORDER BY id DESC LIMIT ?",
                (f"%{keyword}%", f"%{keyword}%", max(1, min(1000, int(limit))))).fetchall()
        return [self._row_to_dict(r) for r in rows]

    def delete(self, rec_id: int) -> bool:
        with self._lock, self._session() as conn:
            cur = conn.execute("DELETE FROM transcripts WHERE id=?", (rec_id,))
            return cur.rowcount > 0

    def clear(self) -> None:
        with self._lock, self._session() as conn:
            conn.execute("DELETE FROM transcripts")

    def count(self) -> int:
        with self._lock, self._session() as conn:
            return int(conn.execute("SELECT COUNT(*) FROM transcripts").fetchone()[0])

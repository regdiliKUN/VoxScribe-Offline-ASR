"""Crash-safe JSON settings.

Every write is atomic (temp file + os.replace). A corrupt or partially written
file is quarantined as ``settings.json.bad`` and defaults are restored, so a
single bad shutdown can never brick the application.
"""
from __future__ import annotations

import copy
import json
import math
import os
import tempfile
import threading
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any

from .errors import ConfigError
from .paths import settings_file

# Kept in sync with engines.base.SPECS by tests/test_config_history.py.
# Defined here (rather than imported) to avoid a config -> engines import cycle.
VALID_ENGINES = ("auto", "qwen3", "sensevoice", "paraformer")
VALID_LANGUAGES = ("auto", "zh", "en", "ja", "ko", "yue")


def _as_int(value, default: int) -> int:
    """Best-effort int conversion; corrupt values fall back instead of raising.

    ``json.loads('1e999')`` yields ``inf``; ``int(inf)`` raises OverflowError.
    Without this guard one bad numeric field quarantines the whole settings
    file and silently resets every user preference.
    """
    try:
        f = float(value)
        return int(f) if math.isfinite(f) else default
    except (TypeError, ValueError, OverflowError):
        return default


def _as_float(value, default: float) -> float:
    """Best-effort float conversion; NaN/Inf/corrupt values fall back."""
    try:
        f = float(value)
        return f if math.isfinite(f) else default
    except (TypeError, ValueError):
        return default


@dataclass
class Settings:
    # --- recognition -------------------------------------------------------
    engine: str = "auto"                 # auto | qwen3 | sensevoice | paraformer
    language: str = "auto"               # auto | zh | en | ja | ko | yue
    use_itn: bool = True                 # inverse text normalisation / punctuation
    threads: int = 0                     # 0 = auto
    vad_enabled: bool = True
    vad_threshold: float = 0.5
    max_segment_seconds: float = 25.0
    min_segment_seconds: float = 0.30

    # --- recording ---------------------------------------------------------
    sample_rate: int = 16000
    input_device: str = ""               # empty = system default
    max_record_seconds: int = 7200
    silence_guard_db: float = -60.0

    # --- output ------------------------------------------------------------
    export_encoding: str = "utf-8-sig"   # utf-8-sig | utf-8 | gb18030
    include_timestamps: bool = False
    auto_copy: bool = False
    last_export_dir: str = ""
    recent_files: list[str] = field(default_factory=list)

    # --- shell integration -------------------------------------------------
    auto_shortcut: bool = True
    shortcut_check_each_start: bool = True
    shortcut_created: bool = False
    first_run_done: bool = False

    # --- misc --------------------------------------------------------------
    theme: str = "dark"
    model_dir: str = ""
    log_level: str = "INFO"

    def clamp(self) -> None:
        """Silently repair out-of-range *and ill-typed* values.

        Settings can come from a hand-edited JSON file or a programmatic
        ``update()``; a single non-numeric field must never crash startup, so
        every numeric coercion goes through a guarded helper.
        """
        self.threads = max(0, min(16, _as_int(self.threads, 0)))
        sr = _as_int(self.sample_rate, 16000)
        self.sample_rate = sr if sr in (8000, 16000, 32000, 44100, 48000) else 16000
        self.max_record_seconds = max(5, min(12 * 3600, _as_int(self.max_record_seconds, 7200)))
        self.vad_threshold = max(0.05, min(0.95, _as_float(self.vad_threshold, 0.5)))
        self.max_segment_seconds = max(5.0, min(120.0, _as_float(self.max_segment_seconds, 25.0)))
        self.min_segment_seconds = max(0.05, min(5.0, _as_float(self.min_segment_seconds, 0.30)))
        self.silence_guard_db = max(-100.0, min(0.0, _as_float(self.silence_guard_db, -60.0)))
        if self.export_encoding not in ("utf-8-sig", "utf-8", "gb18030"):
            self.export_encoding = "utf-8-sig"
        if self.engine not in VALID_ENGINES:
            self.engine = "auto"
        if self.language not in VALID_LANGUAGES:
            self.language = "auto"
        if self.theme not in ("dark", "light"):
            self.theme = "dark"
        recent = self.recent_files if isinstance(self.recent_files, list) else []
        seen: set[str] = set()
        cleaned: list[str] = []
        for item in recent:
            if not isinstance(item, str) or not item.strip():
                continue
            key = _recent_key(item)
            if key in seen:
                continue
            seen.add(key)
            cleaned.append(item)
            if len(cleaned) >= 20:
                break
        self.recent_files = cleaned

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _recent_key(path: str) -> str:
    """Windows paths are case-insensitive; share one key for all de-duplication."""
    return path.replace("\\", "/").lower()


_LOCK = threading.Lock()


class SettingsStore:
    def __init__(self, path: Path | None = None):
        self.path = Path(path) if path else settings_file()
        self._settings = Settings()
        self._load_error: str | None = None

    @property
    def data(self) -> Settings:
        return self._settings

    @property
    def load_error(self) -> str | None:
        return self._load_error

    def load(self) -> Settings:
        with _LOCK:
            self._load_error = None
            if not self.path.is_file():
                self._settings = Settings()
                return self._settings
            try:
                raw = json.loads(self.path.read_text(encoding="utf-8"))
                if not isinstance(raw, dict):
                    raise ValueError("settings root must be an object")
                allowed = {f.name for f in fields(Settings)}
                merged = Settings(**{k: v for k, v in raw.items() if k in allowed})
                merged.clamp()
                self._settings = merged
            except Exception as exc:
                self._load_error = f"{type(exc).__name__}: {exc}"
                try:
                    bad = self.path.with_suffix(self.path.suffix + ".bad")
                    self.path.replace(bad)
                except OSError:
                    pass
                self._settings = Settings()
            return self._settings

    def save(self, settings: Settings | None = None) -> None:
        s = copy.deepcopy(settings or self._settings)
        s.clamp()
        with _LOCK:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(prefix="settings-", suffix=".tmp", dir=str(self.path.parent))
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    json.dump(s.as_dict(), f, ensure_ascii=False, indent=2)
                    f.flush()
                    os.fsync(f.fileno())
                os.replace(tmp, self.path)
            except Exception as exc:
                try:
                    os.unlink(tmp)
                except OSError:
                    pass
                raise ConfigError("设置保存失败", detail=str(exc), cause=exc) from exc
            self._settings = s

    def update(self, **kwargs: Any) -> Settings:
        s = copy.deepcopy(self._settings)
        for k, v in kwargs.items():
            if hasattr(s, k):
                setattr(s, k, v)
        self.save(s)
        return self._settings

    def add_recent(self, path: str) -> None:
        if not isinstance(path, str) or not path.strip():
            return
        # Windows paths are case-insensitive; normalise for de-duplication so
        # D:\A.wav and d:\a.wav are not stored as two separate recent entries.
        wanted = _recent_key(path)
        items = [p for p in self._settings.recent_files
                 if isinstance(p, str) and _recent_key(p) != wanted]
        items.insert(0, path)
        self.update(recent_files=items[:20])

    def reset(self) -> Settings:
        """Restore defaults, persist them, and return the live settings.

        ``save()`` intentionally returns None, so the previous
        ``save(...) or self._settings`` relied on a truthiness accident.  Use
        an explicit sequence so the behaviour is obvious and type-correct.
        """
        self.save(Settings())
        return self._settings


_STORE: SettingsStore | None = None


def get_store() -> SettingsStore:
    global _STORE
    if _STORE is None:
        _STORE = SettingsStore()
        _STORE.load()
    return _STORE

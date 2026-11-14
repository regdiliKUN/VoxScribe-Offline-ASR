"""Crash-safe JSON settings.

Every write is atomic (temp file + os.replace). A corrupt or partially written
file is quarantined as ``settings.json.bad`` and defaults are restored, so a
single bad shutdown can never brick the application.
"""
from __future__ import annotations

import copy
import json
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
        """Silently repair out-of-range values (e.g. hand-edited JSON)."""
        self.threads = max(0, min(16, int(self.threads or 0)))
        self.sample_rate = 16000 if self.sample_rate not in (8000, 16000, 32000, 44100, 48000) else self.sample_rate
        self.max_record_seconds = max(5, min(12 * 3600, int(self.max_record_seconds)))
        self.vad_threshold = max(0.05, min(0.95, float(self.vad_threshold)))
        self.max_segment_seconds = max(5.0, min(120.0, float(self.max_segment_seconds)))
        self.min_segment_seconds = max(0.05, min(5.0, float(self.min_segment_seconds)))
        self.silence_guard_db = max(-100.0, min(0.0, float(self.silence_guard_db)))
        if self.export_encoding not in ("utf-8-sig", "utf-8", "gb18030"):
            self.export_encoding = "utf-8-sig"
        if self.engine not in VALID_ENGINES:
            self.engine = "auto"
        if self.language not in VALID_LANGUAGES:
            self.language = "auto"
        if self.theme not in ("dark", "light"):
            self.theme = "dark"
        self.recent_files = [str(x) for x in self.recent_files][:20]

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


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
        items = [p for p in self._settings.recent_files if p != path]
        items.insert(0, path)
        self.update(recent_files=items[:20])

    def reset(self) -> Settings:
        return self.save(Settings()) or self._settings


_STORE: SettingsStore | None = None


def get_store() -> SettingsStore:
    global _STORE
    if _STORE is None:
        _STORE = SettingsStore()
        _STORE.load()
    return _STORE

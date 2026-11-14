"""Path resolution that works both from source and from a PyInstaller bundle.

The shipped layout (portable build) is::

    VoxScribe/
        VoxScribe.exe
        models/<engine>/*.onnx    (external, so Qwen3 fits)
        _internal/ffmpeg.exe     (PyInstaller data file)
        _internal/...            (PyInstaller runtime)

A one-file build embeds the same files in ``sys._MEIPASS``.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def meipass() -> Path | None:
    p = getattr(sys, "_MEIPASS", None)
    return Path(p) if p else None


def package_dir() -> Path:
    return Path(__file__).resolve().parent.parent


def source_root() -> Path:
    """Repository root when running from source."""
    return package_dir().parent.parent


def exe_path() -> Path:
    return Path(sys.executable).resolve()


def app_dir() -> Path:
    """Directory containing the EXE (portable build) or the repo root."""
    return exe_path().parent if is_frozen() else source_root()


def user_data_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    p = Path(base) / "VoxScribe"
    p.mkdir(parents=True, exist_ok=True)
    return p


def documents_dir() -> Path:
    base = os.environ.get("USERPROFILE") or os.path.expanduser("~")
    p = Path(base) / "Documents"
    return p if p.is_dir() else Path(base)


def _candidate_model_dirs() -> list[Path]:
    env = os.environ.get("VOXSCRIBE_MODELS")
    out: list[Path] = []
    if env:
        out.append(Path(env))
    out.append(app_dir() / "models")
    mp = meipass()
    if mp:
        out.append(mp / "models")
    out.append(user_data_dir() / "models")
    out.append(source_root() / "models")
    # de-duplicate, preserve order
    seen: set[str] = set()
    uniq: list[Path] = []
    for p in out:
        key = str(p).lower()
        if key not in seen:
            seen.add(key)
            uniq.append(p)
    return uniq


def models_dir(create: bool = False) -> Path:
    """Return the first existing models directory, or the preferred location."""
    candidates = _candidate_model_dirs()
    for p in candidates:
        if p.is_dir() and any(p.iterdir()):
            return p
    preferred = candidates[0]
    if create:
        preferred.mkdir(parents=True, exist_ok=True)
    return preferred


def find_model_file(relative: str) -> Path | None:
    """Find a model asset relative to any of the model roots."""
    rel = Path(relative)
    for root in _candidate_model_dirs():
        p = root / rel
        if p.is_file():
            return p
    return None


def resource_path(relative: str) -> Path:
    """Resolve a bundled resource (icon, VAD model, ffmpeg ...)."""
    mp = meipass()
    if mp and (mp / relative).exists():
        return mp / relative
    p = app_dir() / relative
    if p.exists():
        return p
    return package_dir() / "resources" / relative


def ffmpeg_path() -> str | None:
    """Prefer the bundled ffmpeg.exe, fall back to a system installation.

    Older builds could contain ``ffmpeg.EXE`` (uppercase suffix).  The lookup
    is therefore case-insensitive on every filesystem, not just Windows.
    """
    import shutil

    roots = []
    mp = meipass()
    if mp:
        roots.append(mp)
    # PyInstaller 6 onedir keeps datas in _internal/; on some versions
    # sys._MEIPASS points at the EXE directory instead, so probe it explicitly.
    roots.extend([app_dir() / "_internal", app_dir(),
                  package_dir() / "resources"])
    for root in roots:
        direct = root / "ffmpeg.exe"
        if direct.is_file():
            return str(direct)
        try:
            for child in root.iterdir():
                if child.is_file() and child.name.lower() == "ffmpeg.exe":
                    return str(child)
        except OSError:
            continue
    return shutil.which("ffmpeg")


def icon_path() -> Path | None:
    for name in ("icon.ico", "app.ico"):
        p = resource_path(name)
        if p.is_file():
            return p
    return None


def log_file() -> Path:
    return user_data_dir() / "voxscribe.log"


def settings_file() -> Path:
    return user_data_dir() / "settings.json"


def history_file() -> Path:
    return user_data_dir() / "history.sqlite3"


def default_export_dir() -> Path:
    return documents_dir()

"""Central logging with a rotating file and an uncaught-exception hook."""
from __future__ import annotations

import logging
import logging.handlers
import os
import sys
import traceback
from pathlib import Path

from .paths import log_file

_CONFIGURED = False
_FMT = "%(asctime)s [%(levelname)-7s] %(name)s: %(message)s"


def setup_logging(level: str = "INFO", console: bool = True) -> Path:
    global _CONFIGURED
    path = log_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    root = logging.getLogger()
    if _CONFIGURED:
        root.setLevel(getattr(logging, level.upper(), logging.INFO))
        return path

    root.setLevel(getattr(logging, level.upper(), logging.INFO))
    formatter = logging.Formatter(_FMT, datefmt="%Y-%m-%d %H:%M:%S")

    file_handler = logging.handlers.RotatingFileHandler(
        str(path), maxBytes=2 * 1024 * 1024, backupCount=4, encoding="utf-8")
    file_handler.setFormatter(formatter)
    file_handler.setLevel(logging.DEBUG)
    root.addHandler(file_handler)

    if console:
        stream = logging.StreamHandler(sys.stderr)
        stream.setFormatter(formatter)
        stream.setLevel(logging.WARNING)
        root.addHandler(stream)

    for noisy in ("vosk", "sherpa_onnx", "onnxruntime", "urllib3", "comtypes"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    _CONFIGURED = True
    return path


def install_excepthook() -> None:
    """Log unhandled exceptions instead of silently losing them in a GUI build."""
    def _hook(exc_type, exc_value, exc_tb):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_tb)
            return
        logging.getLogger("voxscribe").critical(
            "Unhandled exception:\n%s",
            "".join(traceback.format_exception(exc_type, exc_value, exc_tb)),
        )
        sys.__excepthook__(exc_type, exc_value, exc_tb)

    sys.excepthook = _hook


def log_environment() -> None:
    log = logging.getLogger("voxscribe.env")
    try:
        import platform
        log.info("VoxScribe start | python=%s | platform=%s | frozen=%s | exe=%s",
                 platform.python_version(), platform.platform(),
                 getattr(sys, "frozen", False), sys.executable)
    except Exception as exc:  # pragma: no cover
        log.warning("environment logging failed: %s", exc)

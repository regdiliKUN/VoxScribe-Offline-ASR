"""Logging configuration contracts (iteration round 51)."""
from __future__ import annotations

import logging
import logging.handlers

from voxscribe.core import logging_conf


def test_reconfigure_syncs_console_handler_level(monkeypatch, tmp_path):
    """Changing the log level must update already-installed console handlers."""
    # Isolate: reset the module flag and root handlers for this test only.
    monkeypatch.setattr(logging_conf, "_CONFIGURED", False)
    monkeypatch.setattr(logging_conf, "log_file", lambda: tmp_path / "v.log")
    root = logging.getLogger()
    saved_handlers = list(root.handlers)
    saved_level = root.level
    try:
        for h in saved_handlers:
            root.removeHandler(h)
        logging_conf.setup_logging("WARNING", console=True)
        stream_handlers = [h for h in root.handlers
                           if isinstance(h, logging.StreamHandler)
                           and not isinstance(h, logging.handlers.RotatingFileHandler)]
        assert stream_handlers and stream_handlers[0].level == logging.WARNING

        logging_conf.setup_logging("DEBUG", console=True)
        assert root.level == logging.DEBUG
        assert stream_handlers[0].level == logging.DEBUG
    finally:
        for h in list(root.handlers):
            root.removeHandler(h)
        for h in saved_handlers:
            root.addHandler(h)
        root.setLevel(saved_level)


def test_console_can_be_enabled_after_initial_disable(monkeypatch, tmp_path):
    """Round 72: console=False then console=True used to stay silent forever."""
    monkeypatch.setattr(logging_conf, "_CONFIGURED", False)
    monkeypatch.setattr(logging_conf, "log_file", lambda: tmp_path / "v.log")
    root = logging.getLogger()
    saved_handlers = list(root.handlers)
    saved_level = root.level
    try:
        for h in saved_handlers:
            root.removeHandler(h)
        logging_conf.setup_logging("INFO", console=False)
        logging_conf.setup_logging("DEBUG", console=True)
        assert any(isinstance(h, logging.StreamHandler) and not isinstance(
            h, logging.handlers.RotatingFileHandler) for h in root.handlers)
    finally:
        for h in list(root.handlers):
            root.removeHandler(h)
        for h in saved_handlers:
            root.addHandler(h)
        root.setLevel(saved_level)

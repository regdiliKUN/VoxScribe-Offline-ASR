"""Application entry point.

Two modes:
* GUI (default) - PySide6 desktop window.
* CLI (``--cli``) - headless transcription / self-test / shortcut creation.
  The CLI exists primarily so the packaged EXE can be regression-tested
  without any GUI automation.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path

from . import __version__
from .core import export
from .core.errors import ShortcutError, VoxScribeError
from .core.paths import exe_path, ffmpeg_path, is_frozen, log_file
from .core.transcriber import TranscriptionPipeline

log = logging.getLogger("voxscribe.main")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="VoxScribe", description="VoxScribe 离线语音转文字")
    p.add_argument("--version", action="store_true", help="打印版本并退出")
    p.add_argument("--cli", action="store_true", help="无界面模式")
    p.add_argument("--input", "-i", help="待识别的音频文件")
    p.add_argument("--out", "-o", help="导出文件路径（后缀决定格式）")
    p.add_argument("--engine", default="auto",
                    help="auto | qwen3 | sensevoice | paraformer")
    p.add_argument("--format", default=None, choices=list(export.SUPPORTED_FORMATS))
    p.add_argument("--encoding", default=None, choices=list(export.ENCODINGS))
    p.add_argument("--timestamps", action="store_true", help="导出时包含时间戳")
    p.add_argument("--no-vad", action="store_true", help="关闭 VAD 分段")
    p.add_argument("--create-shortcut", action="store_true", help="创建/修复桌面快捷方式")
    p.add_argument("--force-shortcut", action="store_true", help="强制重建快捷方式")
    p.add_argument("--desktop", default=None,
                   help="测试用：指定快捷方式输出目录（默认真实桌面）")
    p.add_argument("--target", default=None,
                   help="测试用：指定快捷方式目标（默认当前 EXE）")
    p.add_argument("--selftest", action="store_true", help="输出运行环境自检 JSON")
    p.add_argument("--verify-models", action="store_true",
                   help="对全部模型文件做 SHA-256 完整校验（较慢）")
    p.add_argument("--log-level", default="INFO")
    p.add_argument("--no-gui-shortcut", action="store_true",
                    help="GUI 启动时不自动创建快捷方式")
    return p


def _json(obj: dict) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=2)


def selftest(full_hash: bool = False) -> int:
    from .core import shortcut
    from .core.integrity import verify_full, verify_quick
    from .engines.base import SPECS
    from .engines.manager import EngineManager

    mgr = EngineManager()
    issues = verify_full() if full_hash else verify_quick()
    info = {
        "model_integrity": "ok" if not issues else [f"{i.path}: {i.problem}" for i in issues],
        "version": __version__,
        "frozen": is_frozen(),
        "executable": str(exe_path()),
        "executable_dir": str(exe_path().parent),
        "python": sys.version.split()[0],
        "ffmpeg": ffmpeg_path(),
        "desktop": str(shortcut.get_desktop_dir()),
        "log_file": str(log_file()),
        "engines": {
            s.key: {"available": not s.missing_files(),
                    "missing": s.missing_files()}
            for s in SPECS
        },
        "available_engines": mgr.available_keys(),
    }
    print(_json(info))
    if not info["available_engines"]:
        return 3
    return 1 if issues else 0


def do_shortcut(force: bool, desktop: str | None = None,
                target: str | None = None) -> int:
    from .core.shortcut import create_shortcut
    try:
        r = create_shortcut(exe=target, desktop=desktop, force=force)
        print(_json({"ok": True, "created": r.created, "path": str(r.path),
                     "target": str(r.target), "method": r.method}))
        return 0
    except ShortcutError as exc:
        print(_json({"ok": False, "code": exc.code, "message": str(exc),
                     "detail": exc.detail}))
        return 2


def do_transcribe(args) -> int:
    from .core.config import get_store
    from .engines.manager import EngineManager

    if not args.input:
        print(_json({"ok": False, "message": "缺少 --input"}))
        return 2
    src = Path(args.input)
    if not src.is_file():
        print(_json({"ok": False, "message": f"找不到音频文件: {src}"}))
        return 2

    cfg = get_store().data
    manager = EngineManager(threads=cfg.threads, language=cfg.language,
                            use_itn=cfg.use_itn)
    pipeline = TranscriptionPipeline.from_settings(cfg, manager=manager)
    pipeline.engine = args.engine
    if args.no_vad:
        pipeline.use_vad = False

    result = pipeline.transcribe_file(src)
    out_path = None
    if args.out:
        out_path = export.export_result(
            result, args.out, fmt=args.format,
            encoding=args.encoding or cfg.export_encoding,
            include_timestamps=args.timestamps or cfg.include_timestamps,
        )
    print(_json({
        "ok": True, "text": result.text, "engine": result.engine,
        "duration": result.duration, "segments": len(result.segments),
        "warnings": result.warnings,
        "output": str(out_path) if out_path else None,
    }))
    return 0


def run_cli(args) -> int:
    if args.selftest or args.verify_models:
        return selftest(full_hash=args.verify_models)
    if args.create_shortcut:
        return do_shortcut(args.force_shortcut, args.desktop, args.target)
    return do_transcribe(args)


def run_gui(args) -> int:
    from PySide6.QtWidgets import QApplication

    from .core.config import get_store
    from .core.logging_conf import install_excepthook, log_environment
    from .core.shortcut import create_shortcut
    from .ui.app import MainWindow

    install_excepthook()
    log_environment()
    cfg_store = get_store()
    cfg = cfg_store.data

    created_shortcut_now = False
    if not args.no_gui_shortcut and cfg.auto_shortcut and is_frozen():
        if cfg.shortcut_check_each_start or not cfg.shortcut_created:
            try:
                r = create_shortcut()
                if r.created:
                    created_shortcut_now = True
                    log.info("Desktop shortcut ready: %s", r.path)
                cfg_store.update(shortcut_created=True)
            except Exception as exc:
                log.warning("Shortcut creation skipped: %s", exc)

    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("VoxScribe")
    app.setApplicationVersion(__version__)
    win = MainWindow()
    win.show()
    if created_shortcut_now:
        from PySide6.QtWidgets import QMessageBox
        QMessageBox.information(
            win, "桌面快捷方式已创建",
            "已在你的桌面创建 VoxScribe 快捷方式，以后可直接从桌面启动。\n\n"
            "右键该快捷方式 → 选择「打开文件所在位置」可直达程序所在目录。")
    cfg_store.update(first_run_done=True)
    return app.exec()


def _hide_console_window() -> None:
    """Console subsystem is required for headless CLI output; hide it for GUI."""
    if os.name != "nt":
        return
    try:
        import ctypes
        hwnd = ctypes.windll.kernel32.GetConsoleWindow()
        if hwnd:
            ctypes.windll.user32.ShowWindow(hwnd, 0)  # SW_HIDE
    except Exception:
        pass


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.version:
        print(f"VoxScribe {__version__}")
        return 0
    # A windowed EXE has no usable stdout, which breaks CLI regression tests.
    # We therefore build with a console subsystem and hide it only in GUI mode.
    if not args.cli:
        _hide_console_window()
    else:
        # Frozen Windows binaries default to the OEM/ANSI code page when stdout
        # is a pipe, which garbles Chinese JSON output (files are still UTF-8).
        for stream in (sys.stdout, sys.stderr):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except (AttributeError, ValueError, OSError):
                pass

    from .core.logging_conf import setup_logging
    setup_logging(args.log_level, console=args.cli)

    try:
        return run_cli(args) if args.cli else run_gui(args)
    except VoxScribeError as exc:
        log.error("%s | %s", exc.code, exc.detail)
        print(_json({"ok": False, "code": exc.code,
                     "message": str(exc), "detail": exc.detail}))
        return 2
    except KeyboardInterrupt:
        return 130
    except Exception as exc:
        logging.getLogger("voxscribe.main").exception("Fatal error: %s", exc)
        print(_json({"ok": False, "code": "VOX_FATAL",
                     "message": str(exc)}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

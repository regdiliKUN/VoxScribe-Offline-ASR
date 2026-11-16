"""Headless CLI tests (iteration round 9 and later rounds)."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from voxscribe import __version__

ROOT = Path(__file__).resolve().parent.parent


def run_cli(*args, exe=None):
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT / "src")
    cmd = [exe or sys.executable, "-m", "voxscribe.main", "--cli", *args]
    p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                       env=env, cwd=str(ROOT), timeout=180)
    return p


def test_version():
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT / "src")
    p = subprocess.run([sys.executable, "-m", "voxscribe.main", "--version"],
                       capture_output=True, text=True, env=env, cwd=str(ROOT))
    assert f"VoxScribe {__version__}" in p.stdout


def test_version_is_single_source_of_truth():
    """CLI --version and --selftest must both report the package __version__."""
    import re
    assert re.fullmatch(r"\d+\.\d+\.\d+", __version__), __version__
    v = subprocess.run([sys.executable, "-m", "voxscribe.main", "--version"],
                       capture_output=True, text=True,
                       env={**os.environ, "PYTHONPATH": str(ROOT / "src")},
                       cwd=str(ROOT))
    assert v.stdout.strip() == f"VoxScribe {__version__}"
    data = json.loads(run_cli("--selftest").stdout)
    assert data["version"] == __version__


def test_selftest_reports_engines():
    p = run_cli("--selftest")
    data = json.loads(p.stdout)
    assert data["version"] == __version__
    assert data["available_engines"]
    assert p.returncode == 0


def test_transcribe_and_export_txt(fixtures, tmp_path, models_root):
    if models_root is None:
        pytest.skip("models not installed")
    out = tmp_path / "结果.txt"
    p = run_cli("-i", str(fixtures / "zh_01_daily.wav"),
                "--engine", "sensevoice", "-o", str(out))
    data = json.loads(p.stdout)
    assert data["ok"] and "天气" in data["text"]
    assert out.is_file() and "天气" in out.read_text(encoding="utf-8-sig")


def test_transcribe_export_srt(fixtures, tmp_path, models_root):
    if models_root is None:
        pytest.skip("models not installed")
    out = tmp_path / "result.srt"
    p = run_cli("-i", str(fixtures / "zh_01_daily.wav"),
                "--engine", "paraformer", "-o", str(out))
    assert p.returncode == 0
    assert "-->" in out.read_text(encoding="utf-8")


def test_invalid_engine_reports_json_error(fixtures):
    """A mistyped engine must fail loudly, not silently fall back to another."""
    p = run_cli("-i", str(fixtures / "zh_01_daily.wav"), "--engine", "qwen")
    data = json.loads(p.stdout)
    assert p.returncode == 2 and data["ok"] is False
    assert data["code"] == "VOX_ENGINE"
    assert "qwen3" in data["valid_engines"]


def test_missing_input_is_reported_not_crash(tmp_path):
    p = run_cli("-i", str(tmp_path / "missing.wav"))
    data = json.loads(p.stdout)
    assert data["ok"] is False and p.returncode == 2


def test_export_failure_preserves_recognized_text(fixtures, tmp_path, models_root):
    """A bad export path must not discard text from a successful recognition."""
    if models_root is None:
        pytest.skip("models not installed")
    # An existing directory cannot be the target of os.replace.
    p = run_cli("-i", str(fixtures / "zh_01_daily.wav"),
                "--engine", "sensevoice", "-o", str(tmp_path))
    data = json.loads(p.stdout)
    assert p.returncode == 2 and data["ok"] is False
    assert data["code"] == "VOX_EXPORT"
    assert "天气" in data["text"]          # recognition result retained
    assert "export_error" in data


def test_all_engines_failed_returns_error_code(fixtures, tmp_settings, monkeypatch, capsys):
    """Round 73: a run with zero successful segments is not ok=true."""
    import argparse
    from voxscribe import main as main_mod
    from voxscribe.core.transcriber import TranscriptResult

    def fake_transcribe(self, *a, **kw):
        return TranscriptResult(text="", segments=[],
                                warnings=["第 1 段识别失败：EngineError"],
                                duration=1.0, failed_segments=1)

    monkeypatch.setattr(
        "voxscribe.core.transcriber.TranscriptionPipeline.transcribe_file",
        fake_transcribe)
    args = argparse.Namespace(input=str(fixtures / "zh_01_daily.wav"), out=None,
                              engine="auto", format=None, encoding=None,
                              timestamps=False, no_vad=False)
    rc = main_mod.do_transcribe(args)
    data = json.loads(capsys.readouterr().out)
    assert rc == 2 and data["ok"] is False
    assert data["code"] == "VOX_ENGINE"


def test_conflicting_cli_actions_are_rejected():
    """Round 78: the old if-chain silently skipped the second action."""
    p = run_cli("--selftest", "--create-shortcut")
    data = json.loads(p.stdout)
    assert p.returncode == 2 and data["ok"] is False
    assert data["code"] == "VOX_ARGS"


def test_gui_startup_error_is_not_cli_json(monkeypatch, capsys):
    """Round 77: GUI mode has no stdout; JSON went to a hidden console."""
    from voxscribe import main as main_mod
    from voxscribe.core.errors import VoxScribeError

    def boom(_args):
        raise VoxScribeError("启动失败")

    monkeypatch.setattr(main_mod, "_hide_console_window", lambda: None)
    monkeypatch.setattr(main_mod, "run_gui", boom)
    rc = main_mod.main([])
    out = capsys.readouterr().out
    assert rc == 2
    assert "VOX_FATAL" not in out and "启动失败" not in out


def test_cli_shortcut_on_temp_desktop(tmp_path):
    """--create-shortcut is fully testable without touching the real desktop."""
    fake = tmp_path / "VoxScribe.exe"
    fake.write_bytes(b"MZ")
    desk = tmp_path / "desktop"
    desk.mkdir()
    p = run_cli("--create-shortcut", "--desktop", str(desk), "--target", str(fake))
    data = json.loads(p.stdout)
    from voxscribe.core.shortcut import verify_shortcut
    assert data["ok"] and data["created"]
    lnk = desk / "VoxScribe.lnk"
    assert verify_shortcut(lnk, fake)[0]
    assert data["target"] == str(fake)

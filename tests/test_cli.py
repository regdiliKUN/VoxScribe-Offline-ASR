"""Headless CLI tests (iteration round 9 and later rounds)."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

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
    assert "VoxScribe 1.0.0" in p.stdout


def test_selftest_reports_engines():
    p = run_cli("--selftest")
    data = json.loads(p.stdout)
    assert data["version"] == "1.0.0"
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


def test_missing_input_is_reported_not_crash(tmp_path):
    p = run_cli("-i", str(tmp_path / "missing.wav"))
    data = json.loads(p.stdout)
    assert data["ok"] is False and p.returncode == 2


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

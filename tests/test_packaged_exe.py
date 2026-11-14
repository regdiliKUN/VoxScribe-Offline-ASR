"""End-to-end tests against the *packaged* EXE (no Python environment needed).

Skipped automatically when dist/standalone/VoxScribe-Standalone.exe is absent,
so the suite also works right after a fresh clone.
"""
from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
EXE = ROOT / "dist" / "standalone" / "VoxScribe-Standalone.exe"
FIXTURES = ROOT / "tests" / "fixtures"

pytestmark = pytest.mark.skipif(not EXE.is_file(), reason="run scripts/build.py first")


def run(*args, timeout=180, clean=True):
    env = os.environ.copy()
    if clean:
        env.pop("PYTHONPATH", None)
        env.pop("PYTHONHOME", None)
        env.pop("VOXSCRIBE_MODELS", None)
    return subprocess.run([str(EXE), *args], capture_output=True,
                          text=True, encoding="utf-8", errors="replace",
                          env=env, cwd=str(ROOT), timeout=timeout)


def test_version_works_without_python_env():
    p = run("--version")
    assert p.returncode == 0
    assert "VoxScribe" in p.stdout


def test_selftest_frozen_and_models_ok():
    p = run("--cli", "--selftest")
    data = json.loads(p.stdout)
    assert data["frozen"] is True
    assert data["model_integrity"] == "ok"
    assert "sensevoice" in data["available_engines"]
    assert Path(data["executable"]).resolve() == EXE.resolve()


def test_transcribe_and_export_utf8(tmp_path):
    out = tmp_path / "输出 结果.txt"
    p = run("--cli", "-i", str(FIXTURES / "zh_01_daily.wav"),
            "--engine", "sensevoice", "-o", str(out))
    assert p.returncode == 0, p.stdout + p.stderr
    data = json.loads(p.stdout)
    assert "天气" in data["text"], f"CLI Chinese output garbled: {data['text']!r}"
    assert "公园" in data["text"]
    assert out.is_file()
    text = out.read_text(encoding="utf-8-sig")
    assert "今天天气很好" in text


def test_mp3_import_without_external_ffmpeg(tmp_path):
    out = tmp_path / "mp3.txt"
    p = run("--cli", "-i", str(FIXTURES / "sample.mp3"),
            "--engine", "paraformer", "-o", str(out))
    assert p.returncode == 0
    assert "天气" in json.loads(p.stdout)["text"]


def test_unavailable_engine_falls_back():
    p = run("--cli", "-i", str(FIXTURES / "zh_01_daily.wav"), "--engine", "qwen3")
    data = json.loads(p.stdout)
    assert data["ok"]
    assert data["engine"] in ("sensevoice", "paraformer")
    assert "天气" in data["text"]


def test_srt_export_from_exe(tmp_path):
    out = tmp_path / "out.srt"
    p = run("--cli", "-i", str(FIXTURES / "zh_01_daily.wav"),
            "--engine", "sensevoice", "-o", str(out))
    assert p.returncode == 0
    text = out.read_text(encoding="utf-8")
    assert "-->" in text and "天气" in text


def test_shortcut_target_is_the_exe_itself(tmp_path):
    """Explorer's 'Open file location' resolves the .lnk target's parent dir."""
    from voxscribe.core.shortcut import verify_shortcut
    desk = tmp_path / "桌面"
    desk.mkdir()
    p = run("--cli", "--create-shortcut", "--desktop", str(desk), "--target", str(EXE))
    data = json.loads(p.stdout)
    assert data["ok"] and data["created"]
    lnk = desk / "VoxScribe.lnk"
    ok, why = verify_shortcut(lnk, EXE)
    assert ok, why
    # "打开文件所在位置" => the folder containing the EXE must exist
    assert EXE.parent.is_dir()


def test_verify_models_full_hash():
    p = run("--cli", "--verify-models", timeout=300)
    data = json.loads(p.stdout)
    assert data["model_integrity"] == "ok"
    assert p.returncode == 0


def test_cold_start_performance():
    t0 = time.perf_counter()
    p = run("--cli", "--selftest")
    elapsed = time.perf_counter() - t0
    assert p.returncode == 0
    assert elapsed < 60, f"cold start too slow: {elapsed:.1f}s"

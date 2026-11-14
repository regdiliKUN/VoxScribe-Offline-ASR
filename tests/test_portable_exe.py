"""End-to-end tests against the portable build (iteration round 19).

The portable bundle ships every engine, including the 0.9 GB Qwen3 decoder, so
this module proves the 'maximum accuracy' distribution really works with no
Python environment and no network access.
"""
from __future__ import annotations

import json
import os
import subprocess
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "dist" / "portable" / "VoxScribe"
EXE = APP / "VoxScribe.exe"
ZIP = ROOT / "dist" / "VoxScribe-Portable-win64.zip"
FIXTURES = ROOT / "tests" / "fixtures"

pytestmark = pytest.mark.skipif(
    not EXE.is_file(), reason="run scripts/build.py --mode portable first")


def run(*args, timeout=180):
    env = os.environ.copy()
    for key in ("PYTHONPATH", "PYTHONHOME", "VOXSCRIBE_MODELS"):
        env.pop(key, None)
    return subprocess.run([str(EXE), *args], capture_output=True,
                          text=True, encoding="utf-8", errors="replace",
                          env=env, cwd=str(ROOT), timeout=timeout)


def test_portable_layout_has_exactly_one_ffmpeg():
    assert (APP / "models" / "manifest.json").is_file()
    assert (APP / "使用说明.txt").is_file()
    bundled = [p for p in APP.rglob("*")
               if p.is_file() and p.name.lower() == "ffmpeg.exe"]
    assert len(bundled) == 1, f"expected one bundled ffmpeg, found {bundled}"
    assert bundled[0].name == "ffmpeg.exe", \
        f"ffmpeg filename is not canonical: {bundled[0].name}"
    assert bundled[0].parent.name == "_internal"


def test_selftest_reports_all_three_engines():
    p = run("--cli", "--selftest")
    assert p.returncode == 0, p.stdout + p.stderr
    data = json.loads(p.stdout)
    assert data["frozen"] is True
    assert data["model_integrity"] == "ok"
    assert data["available_engines"] == ["qwen3", "sensevoice", "paraformer"]
    assert Path(data["executable"]).resolve() == EXE.resolve()
    assert Path(data["ffmpeg"]).is_file()


def test_qwen3_transcribes_chinese_correctly(tmp_path):
    out = tmp_path / "qwen3.txt"
    p = run("--cli", "-i", str(FIXTURES / "zh_01_daily.wav"),
            "--engine", "qwen3", "-o", str(out), timeout=300)
    assert p.returncode == 0, p.stdout + p.stderr
    data = json.loads(p.stdout)
    assert data["ok"] and data["engine"] == "qwen3"
    assert "天气" in data["text"] and "公园" in data["text"]
    assert "今天天气很好" in out.read_text(encoding="utf-8-sig")


def test_auto_mode_prefers_the_accuracy_engine():
    p = run("--cli", "-i", str(FIXTURES / "zh_01_daily.wav"), timeout=300)
    assert p.returncode == 0, p.stdout + p.stderr
    data = json.loads(p.stdout)
    assert data["ok"] and data["engine"] == "qwen3"
    assert "天气" in data["text"]


def test_verify_models_full_sha256():
    p = run("--cli", "--verify-models", timeout=420)
    assert p.returncode == 0, p.stdout + p.stderr
    assert json.loads(p.stdout)["model_integrity"] == "ok"


def test_srt_export_and_shortcut_target(tmp_path):
    out = tmp_path / "result.srt"
    p = run("--cli", "-i", str(FIXTURES / "zh_01_daily.wav"),
            "-o", str(out), timeout=300)
    assert p.returncode == 0, p.stdout + p.stderr
    text = out.read_text(encoding="utf-8")
    assert "-->" in text and "天气" in text

    from voxscribe.core.shortcut import verify_shortcut
    desk = tmp_path / "桌面"
    desk.mkdir()
    p = run("--cli", "--create-shortcut", "--desktop", str(desk),
            "--target", str(EXE))
    assert p.returncode == 0, p.stdout + p.stderr
    assert json.loads(p.stdout)["created"] is True
    ok, why = verify_shortcut(desk / "VoxScribe.lnk", EXE)
    assert ok, why
    assert EXE.parent.is_dir()   # "打开文件所在位置" resolves here


def test_zip_archive_is_self_contained():
    if not ZIP.is_file():
        pytest.skip("portable ZIP not built yet")
    with zipfile.ZipFile(ZIP) as z:
        names = set(z.namelist())
        assert "VoxScribe/VoxScribe.exe" in names
        assert "VoxScribe/models/manifest.json" in names
        assert "VoxScribe/使用说明.txt" in names
        ffmpeg_entries = sorted(n for n in names
                                if n.lower().endswith("/ffmpeg.exe"))
        assert len(ffmpeg_entries) == 1, f"duplicate/missing ffmpeg: {ffmpeg_entries}"
        assert ffmpeg_entries[0] == "VoxScribe/_internal/ffmpeg.exe", \
            "ffmpeg.exe must use the canonical lowercase name"
        manifest = json.loads(z.read("VoxScribe/models/manifest.json"))
        assert len(manifest["files"]) == 12
        assert any(k.startswith("qwen3/decoder") for k in manifest["files"])
        assert all(n.startswith("VoxScribe/") for n in names)

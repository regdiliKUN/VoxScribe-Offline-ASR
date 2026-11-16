"""Model integrity tests (iteration round 12 and later rounds)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from voxscribe.core import integrity
from voxscribe.engines.manager import EngineManager


@pytest.fixture
def fake_models(tmp_path, monkeypatch):
    root = tmp_path / "models"
    root.mkdir()
    f = root / "fake.bin"
    f.write_bytes(b"A" * 1000)
    import hashlib
    (root / "manifest.json").write_text(json.dumps({
        "files": {"fake.bin": {"size": 1000, "sha256": hashlib.sha256(b"A" * 1000).hexdigest()}}
    }), encoding="utf-8")

    monkeypatch.setattr(integrity, "models_dir", lambda: root)
    monkeypatch.setattr(integrity, "find_model_file",
                        lambda rel: (root / rel) if (root / rel).is_file() else None)
    return root, f


def test_quick_verify_passes_on_intact_file(fake_models):
    assert integrity.verify_quick() == []


def test_full_verify_passes_on_intact_file(fake_models):
    assert integrity.verify_full() == []


def test_quick_verify_detects_truncation(fake_models):
    _root, f = fake_models
    f.write_bytes(b"A" * 900)
    issues = integrity.verify_quick()
    assert len(issues) == 1 and "大小不符" in issues[0].problem


def test_full_verify_detects_same_size_corruption(fake_models):
    _root, f = fake_models
    f.write_bytes(b"B" * 1000)
    issues = integrity.verify_full()
    assert len(issues) == 1 and "SHA-256" in issues[0].problem


def test_quick_verify_detects_missing_file(fake_models):
    root, f = fake_models
    f.unlink()
    assert integrity.verify_quick()[0].problem == "文件缺失"


def test_build_manifest_creates_hashes(tmp_path):
    root = tmp_path / "m"
    root.mkdir()
    (root / "a.bin").write_bytes(b"hello")
    data = integrity.build_manifest(root)
    assert data["files"]["a.bin"]["size"] == 5
    assert len(data["files"]["a.bin"]["sha256"]) == 64
    assert (root / "manifest.json").is_file()


def test_build_manifest_excludes_transient_files(tmp_path):
    """Interrupted-download leftovers must not be treated as model assets."""
    root = tmp_path / "m"
    (root / "_downloads").mkdir(parents=True)
    (root / "real.onnx").write_bytes(b"model")
    (root / "partial.onnx.part").write_bytes(b"half")
    (root / "scratch.tmp").write_bytes(b"x")
    (root / "_downloads" / "cached.bin").write_bytes(b"cache")
    data = integrity.build_manifest(root)
    assert set(data["files"]) == {"real.onnx"}


def test_build_manifest_custom_skip_pattern(tmp_path):
    root = tmp_path / "m"
    root.mkdir()
    (root / "keep.bin").write_bytes(b"1")
    (root / "drop.bin").write_bytes(b"2")
    data = integrity.build_manifest(root, skip_patterns=("drop.*",))
    assert set(data["files"]) == {"keep.bin"}


def test_verify_full_reads_manifest_once(monkeypatch, fake_models):
    calls = {"n": 0}
    real = integrity.load_manifest

    def counted():
        calls["n"] += 1
        return real()

    monkeypatch.setattr(integrity, "load_manifest", counted)
    integrity.verify_full()
    assert calls["n"] == 1


def test_corrupt_manifest_structure_is_tolerated(tmp_path, monkeypatch):
    """A malformed 'files' section must not crash quick/full verification."""
    root = tmp_path / "models"
    root.mkdir()
    (root / "fake.bin").write_bytes(b"x")
    (root / "manifest.json").write_text(
        json.dumps({"files": ["not", "a", "mapping"]}), encoding="utf-8")
    monkeypatch.setattr(integrity, "models_dir", lambda: root)
    monkeypatch.setattr(integrity, "find_model_file",
                        lambda rel: (root / rel) if (root / rel).is_file() else None)
    assert integrity.load_manifest() == {}
    assert integrity.verify_quick() == []
    assert integrity.verify_full() == []


def test_engine_excluded_when_model_truncated(monkeypatch):
    """A truncated model must be removed from the failover chain."""
    import voxscribe.engines.base as base

    def fake_issues(self):
        return (["sensevoice/model.int8.onnx 大小不符"]
                if self.key == "sensevoice" else [])

    monkeypatch.setattr(base.EngineSpec, "integrity_issues", fake_issues)
    m = EngineManager()
    assert "sensevoice" not in m.available_keys()
    assert "损坏" in m.missing_summary()


def test_selftest_engine_availability_matches_integrity(monkeypatch, capsys):
    """A truncated model must be reported unavailable consistently in JSON."""
    import voxscribe.engines.base as base
    from voxscribe import main as main_mod

    def broken(self):
        return (["size mismatch"] if self.key == "sensevoice" else [])

    monkeypatch.setattr(base.EngineSpec, "integrity_issues", broken)
    code = main_mod.selftest()
    data = json.loads(capsys.readouterr().out)
    assert data["engines"]["sensevoice"]["available"] is False
    assert data["engines"]["sensevoice"]["integrity_issues"] == ["size mismatch"]
    assert "sensevoice" not in data["available_engines"]


def test_manifest_infinite_size_does_not_crash_quick_verify(fake_models):
    """Round 64: a JSON 1e999 used to raise OverflowError at startup."""
    root, _f = fake_models
    (root / "manifest.json").write_text(json.dumps({
        "files": {"fake.bin": {"size": float("inf"), "sha256": "x"}}
    }), encoding="utf-8")
    assert integrity.verify_quick() == []


def test_quick_verify_tolerates_stat_permission_error(monkeypatch):
    """Round 69: TOCTOU/stat failures must become issues, not exceptions."""
    class Vanished:
        def stat(self):
            raise PermissionError("file locked")

    monkeypatch.setattr(integrity, "find_model_file", lambda rel: Vanished())
    issues = integrity.verify_quick({"a.bin": {"size": 10}})
    assert issues and issues[0].path == "a.bin"
    assert "无法读取文件大小" in issues[0].problem


def test_selftest_reports_integrity():
    import subprocess
    import sys
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent
    import os
    env = os.environ.copy()
    env["PYTHONPATH"] = str(root / "src")
    p = subprocess.run([sys.executable, "-m", "voxscribe.main", "--cli", "--selftest"],
                       capture_output=True, text=True, env=env, cwd=str(root))
    data = json.loads(p.stdout)
    assert "model_integrity" in data
    assert p.returncode == 0

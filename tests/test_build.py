"""Build-script and path-resolution contracts (iteration rounds 19-20)."""
from __future__ import annotations

from pathlib import Path

import build as build_script


def test_generated_specs_compile(tmp_path):
    for mode in ("standalone", "portable"):
        source = build_script.spec_source(
            mode, tmp_path / "ffmpeg.exe", tmp_path / "icon.ico")
        compile(source, f"{mode}.spec", "exec")
        assert "collect_all" in source
        assert "ffmpeg.exe" in source


def test_archive_existing_output_preserves_files(tmp_path):
    """Rebuilding must never bulk-delete a previous portable bundle."""
    out = tmp_path / "dist" / "VoxScribe"
    (out / "models").mkdir(parents=True)
    (out / "models" / "keep.txt").write_text("user data", encoding="utf-8")
    build_script._archive_existing_output(out)
    assert not out.exists()
    backups = list((tmp_path / "dist").glob("VoxScribe_previous_*"))
    assert len(backups) == 1
    assert (backups[0] / "models" / "keep.txt").read_text(encoding="utf-8") == "user data"


def test_archive_is_noop_when_output_absent(tmp_path):
    build_script._archive_existing_output(tmp_path / "missing")
    assert not list(tmp_path.glob("missing*"))


def _patch_frozen_paths(monkeypatch, tmp_path):
    from voxscribe.core import paths

    monkeypatch.setattr(paths, "is_frozen", lambda: True)
    monkeypatch.setattr(paths, "meipass", lambda: None)
    monkeypatch.setattr(paths, "app_dir", lambda: tmp_path)
    monkeypatch.setattr(paths, "package_dir", lambda: tmp_path / "no_such_pkg")
    return paths


def test_ffmpeg_path_prefers_internal_bundle(monkeypatch, tmp_path):
    """Portable builds keep ffmpeg in _internal/; resolve it without meipass."""
    paths = _patch_frozen_paths(monkeypatch, tmp_path)
    internal = tmp_path / "_internal"
    internal.mkdir()
    (internal / "ffmpeg.exe").write_bytes(b"bundled")
    (tmp_path / "ffmpeg.exe").write_bytes(b"legacy root copy")
    assert Path(paths.ffmpeg_path()) == internal / "ffmpeg.exe"


def test_ffmpeg_path_tolerates_uppercase_suffix(monkeypatch, tmp_path):
    """Older archives shipped ffmpeg.EXE; lookup must still find it."""
    paths = _patch_frozen_paths(monkeypatch, tmp_path)
    internal = tmp_path / "_internal"
    internal.mkdir()
    (internal / "ffmpeg.EXE").write_bytes(b"bundled")
    found = paths.ffmpeg_path()
    assert found and Path(found).name.lower() == "ffmpeg.exe"
    assert Path(found).is_file()


def test_ensure_ffmpeg_normalises_filename(monkeypatch, tmp_path):
    """The bundled binary must be named ffmpeg.exe regardless of upstream."""
    fake_source = tmp_path / "imageio" / "ffmpeg-win.EXE"
    fake_source.parent.mkdir()
    fake_source.write_bytes(b"fake ffmpeg payload")
    monkeypatch.setattr(build_script, "find_ffmpeg", lambda: fake_source)
    monkeypatch.setattr(build_script, "BUILD", tmp_path / "_build")
    canonical = build_script.ensure_ffmpeg()
    assert canonical.name == "ffmpeg.exe"
    assert canonical.read_bytes() == b"fake ffmpeg payload"
    # A second call must be idempotent (no rewrite, no duplicate).
    assert build_script.ensure_ffmpeg() == canonical

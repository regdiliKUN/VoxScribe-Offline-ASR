"""Build-script and path-resolution contracts (iteration rounds 19-20)."""
from __future__ import annotations

from pathlib import Path

import build as build_script
import download_models as download_script


def test_find_model_file_rejects_absolute_and_traversal():
    import build as _b  # noqa: F401  (ensures scripts path usable)
    from voxscribe.core.paths import find_model_file
    from pathlib import Path
    assert find_model_file(str(Path("C:/Windows/system.ini"))) is None
    assert find_model_file("../outside/model.onnx") is None
    assert find_model_file("/etc/passwd") is None


def test_extract_skips_non_regular_members(monkeypatch, tmp_path):
    """A symlink entry matching a wanted name must not abort model install."""
    import io
    import tarfile

    models = tmp_path / "models"
    models.mkdir()
    monkeypatch.setattr(download_script, "MODELS", models)
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:bz2") as tf:
        good = tarfile.TarInfo("paraformer/tokens.txt")
        data = b"token1\ntoken2\n"
        good.size = len(data)
        tf.addfile(good, io.BytesIO(data))
        link = tarfile.TarInfo("paraformer/model.int8.onnx")
        link.type = tarfile.SYMTYPE
        link.linkname = "../../evil"
        tf.addfile(link)
    archive = tmp_path / "a.tar.bz2"
    archive.write_bytes(buf.getvalue())
    mapping = {"paraformer/tokens.txt": "paraformer/tokens.txt",
               "paraformer/model.int8.onnx": "paraformer/model.int8.onnx"}
    download_script.extract(archive, mapping)
    assert (models / "paraformer" / "tokens.txt").read_bytes() == data
    assert not (models / "paraformer" / "model.int8.onnx").exists()


def test_resume_rejects_misaligned_content_range():
    """Round 81: a 206 starting at byte 0 must not be appended to a .part."""
    class Response:
        def __init__(self, header):
            self.headers = {"Content-Range": header}

    assert download_script.resume_is_aligned(Response("bytes 100-199/200"), 100)
    assert not download_script.resume_is_aligned(Response("bytes 0-99/200"), 100)
    assert download_script.resume_is_aligned(Response(""), 100)


def test_build_fails_fast_without_manifest(monkeypatch, tmp_path):
    """Round 79: warning-then-crash wasted a full PyInstaller pass."""
    import sys
    import pytest

    called = []
    monkeypatch.setattr(build_script, "MODELS", tmp_path)
    monkeypatch.setattr(build_script, "build_standalone", lambda: called.append(1))
    monkeypatch.setattr(sys, "argv", ["build.py", "--mode", "standalone"])
    with pytest.raises(SystemExit, match="manifest.json"):
        build_script.main()
    assert not called


def test_download_rejects_conflicting_selection_flags(monkeypatch):
    """Round 78: --all --light silently ignored the second choice."""
    import sys

    monkeypatch.setattr(sys, "argv", ["download_models.py", "--all", "--light"])
    assert download_script.main() == 2


def test_resume_request_header_is_rfc_compliant():
    """A malformed Range header corrupts resumed model downloads."""
    headers, mode = download_script.resume_request(0)
    assert headers == {} and mode == "wb"
    headers, mode = download_script.resume_request(4096)
    assert headers == {"Range": "bytes=4096-"}, mode
    assert mode == "ab"
    # Regression: the old code produced 'bytes-4096=' which servers ignore.
    assert "=" in headers["Range"] and headers["Range"].endswith("-")


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

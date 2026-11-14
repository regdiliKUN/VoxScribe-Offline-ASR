"""Export layer tests (iteration round 4 and later rounds)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from voxscribe.core import export
from voxscribe.core.errors import ExportError
from voxscribe.core.transcriber import TranscriptResult, TranscriptSegment


@pytest.fixture
def result():
    return TranscriptResult(
        segments=[TranscriptSegment(0.0, 2.5, "今天天气很好。"),
                  TranscriptSegment(3.0, 6.125, "我们一起去公园。")],
        text="今天天气很好。我们一起去公园。",
        engine="sensevoice", source="录音.wav", duration=6.125,
        audio_path="C:/音频/录音.wav", warnings=["测试告警"],
    )


def test_render_txt_plain_and_header(result):
    out = export.render_txt(result)
    assert "今天天气很好" in out and "识别引擎" in out
    assert "00:00:00.000" not in out


def test_render_txt_with_timestamps(result):
    out = export.render_txt(result, include_timestamps=True)
    assert "[00:00:00.000 --> 00:00:02.500]" in out
    assert "[00:00:03.000 --> 00:00:06.125]" in out


def test_render_srt_is_well_formed(result):
    out = export.render_srt(result)
    lines = out.strip().split("\n")
    assert lines[0] == "1"
    assert lines[1] == "00:00:00,000 --> 00:00:02,500"
    assert "2\n00:00:03,000 --> 00:00:06,125" in out


def test_timestamp_rollover():
    assert export.format_timestamp(59.9996, srt=True) == "00:01:00,000"


def test_render_json_roundtrip(result):
    data = json.loads(export.render_json(result))
    assert data["engine"] == "sensevoice"
    assert len(data["segments"]) == 2


def test_render_md_contains_warnings(result):
    out = export.render_md(result)
    assert "## 提示" in out and "测试告警" in out


def test_export_all_formats(tmp_path, result):
    for fmt in export.SUPPORTED_FORMATS:
        p = export.export_result(result, tmp_path / f"out.{fmt}")
        assert p.is_file() and p.stat().st_size > 0


def test_export_is_atomic_no_tmp_left(tmp_path, result):
    export.export_result(result, tmp_path / "out.txt")
    assert not list(tmp_path.glob("voxscribe-export-*.tmp"))


def test_utf8_bom_and_gb18030(tmp_path, result):
    p = export.export_result(result, tmp_path / "bom.txt", encoding="utf-8-sig")
    assert p.read_bytes().startswith(b"\xef\xbb\xbf")
    p2 = export.export_result(result, tmp_path / "gb.txt", encoding="gb18030")
    assert "今天" in p2.read_text(encoding="gb18030")


def test_non_ascii_path(tmp_path, result):
    p = export.export_result(result, tmp_path / "中文 目录" / "结果 文件.txt")
    assert p.is_file()


def test_sanitize_filename():
    assert export.sanitize_filename('a/b:c*d?.wav') == "a_b_c_d_.wav"
    assert export.sanitize_filename("CON.wav").startswith("_")
    assert export.sanitize_filename("") == "transcript"
    assert len(export.sanitize_filename("x" * 300)) <= 120


def test_default_filename(result):
    name = export.default_filename(result, "srt")
    assert name.endswith(".srt") and "转写" in name


def test_unsupported_format_raises(tmp_path, result):
    with pytest.raises(ExportError):
        export.export_result(result, tmp_path / "out.pdf")


def test_empty_result_srt():
    r = TranscriptResult(text="", duration=3.0)
    assert export.render_srt(r) == ""


def test_io_failure_wrapped_as_export_error(tmp_path, result, monkeypatch):
    def boom(*_a, **_kw):
        raise OSError("disk full")
    monkeypatch.setattr(export.os, "replace", boom)
    with pytest.raises(ExportError):
        export.export_result(result, tmp_path / "out.txt")
    assert not list(tmp_path.glob("voxscribe-export-*.tmp"))

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


def test_export_result_adds_suffix_when_path_has_none(result, tmp_path):
    out = export.export_result(result, tmp_path / "转写结果")
    assert out.name == "转写结果.txt" and out.is_file()
    out2 = export.export_result(result, tmp_path / "末尾点.", fmt="md")
    assert out2.name == "末尾点.md" and out2.is_file()
    # An existing directory is a caller error, not a missing suffix: it must
    # fail rather than being silently rewritten into a sibling .txt file.
    with pytest.raises(ExportError):
        export.export_result(result, tmp_path)


def test_render_md_preserves_markdown_like_text(result):
    """Recognition text with #/*/| must survive as plain text, not be rendered."""
    r = TranscriptResult(text="# 标题\n* 列表 | 表格 <tag>", source="a|b.md",
                         duration=1.0)
    md = export.render_md(r)
    assert "```text\n# 标题\n* 列表 | 表格 <tag>\n```" in md
    assert "a\\|b\\.md" not in md  # source uses inline escaping, not code block
    assert "a\\|b.md" in md
    assert "&lt;tag&gt;" not in md  # body kept verbatim inside code fence


def test_render_srt_normalizes_overlapping_timestamps():
    """Overlapping/inverted ASR segments must produce a monotonic SRT track."""
    import re
    r = TranscriptResult(
        segments=[TranscriptSegment(0.0, 2.0, "第一句"),
                  TranscriptSegment(1.5, 1.4, "第二句"),
                  TranscriptSegment(1.4, 3.0, "第三句")],
        text="第一句第二句第三句", duration=3.0)
    srt = export.render_srt(r)
    times = re.findall(r"(\d\d:\d\d:\d\d,\d\d\d) --> (\d\d:\d\d:\d\d,\d\d\d)", srt)

    def ms(t):
        h, m, rest = t.split(":")
        s, milli = rest.split(",")
        return int(h) * 3600000 + int(m) * 60000 + int(s) * 1000 + int(milli)

    ranges = [(ms(a), ms(b)) for a, b in times]
    assert all(b > a for a, b in ranges)          # positive duration
    assert all(ranges[i][0] >= ranges[i - 1][1]
               for i in range(1, len(ranges)))    # no overlap


def test_format_timestamp_nonfinite_values():
    import math
    assert export.format_timestamp(float("nan")) == "00:00:00.000"
    assert export.format_timestamp(float("inf"), srt=True) == "00:00:00,000"
    assert export.format_timestamp(float("-inf")) == "00:00:00.000"
    assert export.format_timestamp(None) == "00:00:00.000"
    assert math.isfinite(0.0)


def test_sanitize_filename_length_cap_with_long_suffix():
    """Truncation must never exceed max_length, even with an oversized suffix."""
    r = export.sanitize_filename("name.averyverylongsuffix", max_length=8)
    assert len(r) <= 8
    r2 = export.sanitize_filename("报告." + "x" * 50, max_length=10)
    assert len(r2) <= 10
    # trailing dot/space must be removed after truncation
    assert not export.sanitize_filename("abc.defg.", max_length=6).endswith((" ", "."))


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


def test_format_timestamp_huge_finite_value():
    """Round 66: 1e308 seconds overflowed when converted to milliseconds."""
    assert export.format_timestamp(1e308) == "2777:46:40.000"


def test_render_srt_normalizes_nonfinite_segment():
    """Round 67: NaN ranges produced zero-length subtitle rows."""
    r = TranscriptResult(
        segments=[TranscriptSegment(0.0, 1.0, "第一句"),
                  TranscriptSegment(float("nan"), float("inf"), "第二句"),
                  TranscriptSegment(2.0, 3.0, "第三句")],
        text="第一句第二句第三句", duration=3.0)
    srt = export.render_srt(r)
    for line in srt.splitlines():
        if "-->" in line:
            left, right = line.split(" --> ")
            assert left != right


def test_io_failure_wrapped_as_export_error(tmp_path, result, monkeypatch):
    def boom(*_a, **_kw):
        raise OSError("disk full")
    monkeypatch.setattr(export.os, "replace", boom)
    with pytest.raises(ExportError):
        export.export_result(result, tmp_path / "out.txt")
    assert not list(tmp_path.glob("voxscribe-export-*.tmp"))

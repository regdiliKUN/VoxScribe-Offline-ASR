"""Export transcripts to TXT / SRT / JSON / Markdown.

All writes are atomic, all encodings are validated, and filenames derived from
audio names are sanitised so a weird source name can never create an invalid
path or overwrite a system-reserved device name.
"""
from __future__ import annotations

import json
import logging
import math
import os
import re
import tempfile
from datetime import datetime
from pathlib import Path

from .errors import ExportError
from .transcriber import TranscriptResult

log = logging.getLogger("voxscribe.export")

SUPPORTED_FORMATS = ("txt", "srt", "json", "md")
ENCODINGS = ("utf-8-sig", "utf-8", "gb18030")
_INVALID_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_RESERVED = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)),
             *(f"LPT{i}" for i in range(1, 10))}
# 10 million seconds is already beyond any plausible transcript; clamping
# before the float->ms multiplication prevents OverflowError at ~1e308.
_MAX_TIMESTAMP_SECONDS = 10_000_000.0


def _finite_seconds(value) -> float:
    """Coerce a timestamp to a non-negative finite float."""
    try:
        f = float(value)
    except (TypeError, ValueError, OverflowError):
        return 0.0
    if not math.isfinite(f):
        return 0.0
    return min(max(f, 0.0), _MAX_TIMESTAMP_SECONDS)


def sanitize_filename(name: str, *, max_length: int = 120) -> str:
    name = _INVALID_CHARS.sub("_", str(name or "")).strip(" .")
    if not name:
        name = "transcript"
    stem = Path(name).stem
    if stem.upper() in _RESERVED:
        name = "_" + name
    if len(name) > max_length:
        suffix = Path(name).suffix
        # A suffix longer than the whole budget must be dropped entirely;
        # otherwise ``name[:max_length - len(suffix)]`` uses a negative index
        # and returns a name far longer than max_length.
        keep = max_length - len(suffix)
        name = name[:keep] + suffix if keep > 0 else name[:max_length]
        # Truncation can leave a trailing dot/space, which Windows trims
        # silently (and which breaks some tools); strip it defensively.
        name = name.rstrip(" .") or "transcript"
    return name


def default_filename(result: TranscriptResult, fmt: str = "txt") -> str:
    base = Path(result.audio_path or result.source or "transcript").stem
    base = sanitize_filename(base)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return f"{base}-转写-{stamp}.{fmt}"


def format_timestamp(seconds: float, *, srt: bool = False) -> str:
    """Convert seconds to a timestamp, doing all rounding in integer ms.

    Rounding in float seconds first produces invalid values such as
    ``00:00:60,000`` at 59.9996 s; integer-ms arithmetic carries correctly
    into seconds/minutes/hours.
    """
    # A corrupt history row or a hand-built result may carry NaN/Inf or a
    # huge finite number whose ms conversion overflows; one bad timestamp
    # must never abort an entire export.
    value = _finite_seconds(seconds)
    total_ms = int(round(value * 1000))
    h, rem = divmod(total_ms, 3_600_000)
    m, rem = divmod(rem, 60_000)
    s, ms = divmod(rem, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}" if srt else f"{h:02d}:{m:02d}:{s:02d}.{ms:03d}"


def render_txt(result: TranscriptResult, *, include_timestamps: bool = False,
               include_header: bool = True) -> str:
    lines: list[str] = []
    if include_header:
        lines += [
            f"来源：{result.source or '录音'}",
            f"识别引擎：{result.engine or '-'}",
            f"时长：{format_timestamp(result.duration)}",
            f"生成时间：{result.created_at}",
            "-" * 40,
        ]
    if include_timestamps and result.segments:
        for seg in result.segments:
            lines.append(f"[{format_timestamp(seg.start)} --> {format_timestamp(seg.end)}] {seg.text}")
    else:
        lines.append(result.text)
    return "\n".join(lines).strip() + "\n"


def render_srt(result: TranscriptResult) -> str:
    segs = result.segments
    if not segs:
        if not result.text.strip():
            return ""
        segs_eff = [(0.0, max(1.0, result.duration), result.text)]
    else:
        segs_eff = [(s.start, s.end, s.text) for s in segs]
    out = []
    # ASR segmentation can occasionally yield overlapping or inverted ranges
    # (e.g. 1.5-1.4).  Normalise to a monotonic, non-overlapping sequence so
    # media players do not skip or freeze on the subtitle track.
    cursor = 0.0
    for i, (start, end, text) in enumerate(segs_eff, 1):
        # Reuse the same finite-value guard as format_timestamp: max(nan, x)
        # returns nan and would emit a zero-length subtitle line.
        start = max(_finite_seconds(start), cursor)
        end = max(_finite_seconds(end), start + 0.2)
        cursor = end
        out.append(str(i))
        out.append(f"{format_timestamp(start, srt=True)} --> {format_timestamp(end, srt=True)}")
        out.append(text.strip())
        out.append("")
    return "\n".join(out)


def _md_inline(text: str) -> str:
    """Escape characters that would break an inline Markdown line."""
    return (str(text).replace("\\", "\\\\").replace("|", "\\|")
            .replace("<", "&lt;").replace(">", "&gt;"))


def _md_block(text: str) -> str:
    """Wrap plain text in a fenced code block so its Markdown-like symbols
    (headings, lists, tables) are preserved verbatim instead of being rendered.
    """
    body = str(text)
    fence = "```"
    while fence in body:
        fence += "`"
    return f"{fence}text\n{body}\n{fence}"


def render_md(result: TranscriptResult, *, include_timestamps: bool = False) -> str:
    lines = [
        "# 语音转写结果", "",
        f"- **来源**：{_md_inline(result.source or '录音')}",
        f"- **识别引擎**：{result.engine or '-'}",
        f"- **时长**：{format_timestamp(result.duration)}",
        f"- **生成时间**：{result.created_at}",
        "", "## 正文", "",
    ]
    if include_timestamps and result.segments:
        for seg in result.segments:
            lines.append(f"**[{format_timestamp(seg.start)}]**")
            lines.append(_md_block(seg.text))
            lines.append("")
    else:
        lines.append(_md_block(result.text))
    if result.warnings:
        lines += ["", "## 提示", ""] + [f"- {_md_inline(w)}" for w in result.warnings]
    return "\n".join(lines).strip() + "\n"


def render_json(result: TranscriptResult) -> str:
    return json.dumps(result.as_dict(), ensure_ascii=False, indent=2) + "\n"


def atomic_write_text(path: str | Path, content: str, encoding: str = "utf-8-sig") -> Path:
    p = Path(path)
    if encoding not in ENCODINGS:
        raise ExportError("不支持的导出编码", detail=encoding)
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix="voxscribe-export-", suffix=".tmp",
                                   dir=str(p.parent))
        try:
            with os.fdopen(fd, "w", encoding=encoding, errors="replace", newline="\n") as f:
                f.write(content)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, p)
        except Exception:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
    except ExportError:
        raise
    except OSError as exc:
        raise ExportError("导出失败，请检查目标路径是否可写或磁盘空间是否充足",
                          detail=f"{type(exc).__name__}: {exc}", cause=exc) from exc
    return p


def export_result(result: TranscriptResult, path: str | Path, *, fmt: str | None = None,
                  encoding: str = "utf-8-sig", include_timestamps: bool = False,
                  include_header: bool = True) -> Path:
    """Export a transcript; format inferred from the file suffix when omitted."""
    p = Path(path)
    suffix = p.suffix.lstrip(".").lower()
    fmt = (fmt or suffix or "txt").lower()
    if fmt not in SUPPORTED_FORMATS:
        raise ExportError(f"不支持的导出格式：{fmt}", detail=f"supported={SUPPORTED_FORMATS}")
    # A path without a usable suffix (e.g. "out" or "out.") would otherwise
    # produce a file with no extension, which Windows treats as an unknown
    # type and which cannot be reopened by double-clicking.  But never rewrite
    # a path that is already an existing directory: that is a caller error and
    # must surface as an export failure (so the CLI can preserve the text).
    if not suffix and not p.is_dir():
        p = p.with_name(p.name.rstrip(".") + "." + fmt)
    if fmt == "txt":
        content = render_txt(result, include_timestamps=include_timestamps,
                             include_header=include_header)
    elif fmt == "srt":
        content = render_srt(result)
    elif fmt == "md":
        content = render_md(result, include_timestamps=include_timestamps)
    else:
        content = render_json(result)
    if fmt == "json":
        encoding = "utf-8"
    out = atomic_write_text(p, content, encoding)
    log.info("Exported %s (%s bytes, %s)", out, out.stat().st_size, fmt)
    return out

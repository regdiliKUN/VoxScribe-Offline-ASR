"""Transcription pipeline: audio -> VAD segments -> engine -> structured result.

Reliability rules:
* one bad segment never aborts the whole file;
* cancellation is checked between segments and honoured promptly;
* empty / silent input returns an explicit, empty result rather than garbage;
* every fallback and skipped segment is recorded in ``warnings``.
"""
from __future__ import annotations

import json
import logging
import re
import threading
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable

import numpy as np

from ..engines.manager import EngineManager
from .audio import AudioData, load_audio, segment_audio
from .errors import AudioError, EngineError, VoxScribeError

log = logging.getLogger("voxscribe.transcriber")

ProgressCallback = Callable[[str, int, int, str], None]


class TranscriptionCancelled(VoxScribeError):
    user_message = "转写已取消。"
    code = "VOX_CANCELLED"


@dataclass
class TranscriptSegment:
    start: float
    end: float
    text: str
    engine: str = ""

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass
class TranscriptResult:
    segments: list[TranscriptSegment] = field(default_factory=list)
    text: str = ""
    engine: str = ""
    source: str = ""
    duration: float = 0.0
    created_at: str = ""
    warnings: list[str] = field(default_factory=list)
    audio_path: str = ""

    def __post_init__(self):
        if not self.created_at:
            self.created_at = datetime.now().astimezone().isoformat(timespec="seconds")

    @property
    def is_empty(self) -> bool:
        return not self.text.strip()

    def as_dict(self) -> dict:
        return {
            **{k: v for k, v in asdict(self).items() if k != "segments"},
            "segments": [s.as_dict() for s in self.segments],
        }

    def to_json(self, *, indent: int = 2) -> str:
        return json.dumps(self.as_dict(), ensure_ascii=False, indent=indent)


_LATIN = re.compile(r"^[A-Za-z0-9\s.,!?'\"-]+$")


def join_texts(texts: list[str]) -> str:
    """Join chunks naturally: no space between CJK, one space between Latin words."""
    out = ""
    for t in texts:
        t = t.strip()
        if not t:
            continue
        if not out:
            out = t
        elif _LATIN.match(out) and _LATIN.match(t):
            out = out + " " + t
        else:
            out = out + t
    return out.strip()


class TranscriptionPipeline:
    def __init__(self, manager: EngineManager | None = None, *,
                 engine: str = "auto", use_vad: bool = True,
                 max_segment_seconds: float = 25.0,
                 min_segment_seconds: float = 0.30,
                 vad_threshold: float = 0.5):
        self.manager = manager or EngineManager()
        self.engine = engine
        self.use_vad = use_vad
        self.max_segment_seconds = max_segment_seconds
        self.min_segment_seconds = min_segment_seconds
        self.vad_threshold = vad_threshold

    @classmethod
    def from_settings(cls, settings, manager: EngineManager | None = None):
        return cls(
            manager=manager,
            engine=settings.engine,
            use_vad=settings.vad_enabled,
            max_segment_seconds=settings.max_segment_seconds,
            min_segment_seconds=settings.min_segment_seconds,
            vad_threshold=settings.vad_threshold,
        )

    def transcribe_file(self, path: str | Path, *,
                        progress: ProgressCallback | None = None,
                        cancel: threading.Event | None = None) -> TranscriptResult:
        if cancel and cancel.is_set():
            raise TranscriptionCancelled()
        _emit(progress, "load", 0, 1, "正在读取音频…")
        data = load_audio(path)
        return self.transcribe_audio(data, source=Path(path).name,
                                     audio_path=str(path), progress=progress, cancel=cancel)

    def transcribe_audio(self, data: AudioData, *, source: str = "microphone",
                         audio_path: str = "",
                         progress: ProgressCallback | None = None,
                         cancel: threading.Event | None = None) -> TranscriptResult:
        started = time.perf_counter()
        warnings: list[str] = []
        if data.duration <= 0 or data.samples.size == 0:
            return TranscriptResult(source=source, audio_path=audio_path,
                                    warnings=["音频为空，未进行识别。"])

        if data.is_silent:
            warnings.append("未检测到有效语音（音频接近静音）。")
            log.info("Nearly silent input (rms=%s); skipping recognition", data.rms)
            _emit(progress, "done", 1, 1, "未检测到语音")
            return TranscriptResult(source=source, audio_path=audio_path,
                                    duration=data.duration, warnings=warnings)

        _emit(progress, "segment", 0, 1, "正在分析语音段落…")
        try:
            segs = segment_audio(
                data.samples, use_vad=self.use_vad,
                max_segment_seconds=self.max_segment_seconds,
                min_segment_seconds=self.min_segment_seconds,
                vad_threshold=self.vad_threshold,
            )
        except Exception as exc:
            log.warning("VAD failed (%s); using single chunk", exc)
            warnings.append("语音分段失败，已按整段识别。")
            segs = segment_audio(data.samples, use_vad=False)

        from .audio import AudioSegment
        if len(segs) > 2000:
            warnings.append(f"片段过多（{len(segs)}），已合并为单段以保证稳定性。")
            segs = [AudioSegment(0.0, data.duration, data.samples)]

        results: list[TranscriptSegment] = []
        used_engines: list[str] = []
        total = len(segs)
        for i, seg in enumerate(segs):
            if cancel and cancel.is_set():
                raise TranscriptionCancelled()
            _emit(progress, "decode", i, total,
                  f"正在识别 {i + 1}/{total} 段（{seg.start:.1f}s–{seg.end:.1f}s）…")
            try:
                text, used, attempts = self.manager.transcribe(
                    seg.samples, self.engine, sample_rate=data.sample_rate,
                    allow_fallback=True)
                used_engines.append(used)
                failed = [a for a in attempts if not a.ok]
                if failed:
                    msg = f"第 {i + 1} 段：{failed[0].key} 引擎失败，已切换到 {used}。"
                    if msg not in warnings:
                        warnings.append(msg)
                if text.strip():
                    results.append(TranscriptSegment(
                        round(seg.start, 3), round(seg.end, 3), text.strip(), used))
            except EngineError as exc:
                warnings.append(f"第 {i + 1} 段识别失败：{exc}")
                log.error("Segment %s failed: %s", i + 1, exc.detail)
            except Exception as exc:  # never let one segment kill the whole job
                warnings.append(f"第 {i + 1} 段出现未预期错误，已跳过。")
                log.exception("Unexpected error in segment %s: %s", i + 1, exc)

        engine = max(set(used_engines), key=used_engines.count) if used_engines else ""
        text = join_texts([s.text for s in results])
        if not text:
            warnings.append("未能识别出文字，请尝试更换引擎或检查录音质量。")
        elapsed = time.perf_counter() - started
        log.info("Transcription done: %s segments, %.2fs audio, %.2fs wall, engine=%s",
                 len(results), data.duration, elapsed, engine)
        _emit(progress, "done", total, total, "识别完成")
        return TranscriptResult(
            segments=results, text=text, engine=engine, source=source,
            duration=round(data.duration, 3), warnings=warnings,
            audio_path=audio_path,
        )


def _emit(cb: ProgressCallback | None, stage: str, cur: int, total: int, msg: str) -> None:
    if cb is None:
        return
    try:
        cb(stage, cur, total, msg)
    except Exception as exc:
        log.warning("Progress callback raised: %s", exc)

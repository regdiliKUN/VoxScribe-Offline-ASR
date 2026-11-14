"""Transcription pipeline tests (iteration round 3 and later rounds)."""
from __future__ import annotations

import json
import threading

import numpy as np
import pytest

from voxscribe.core import audio
from voxscribe.core.errors import AudioError
from voxscribe.core.transcriber import (
    TranscriptionCancelled, TranscriptionPipeline, TranscriptResult,
    TranscriptSegment, join_texts,
)


def test_join_texts_cjk_and_latin():
    assert join_texts(["今天天气", "很好。"]) == "今天天气很好。"
    assert join_texts(["Hello", "world"]) == "Hello world"
    assert join_texts(["", "  ", "abc "]) == "abc"


def test_result_json_roundtrip():
    r = TranscriptResult(text="测试", engine="sensevoice", duration=1.5,
                         segments=[TranscriptSegment(0, 1, "测试")])
    assert json.loads(r.to_json())["text"] == "测试"
    assert r.as_dict()["segments"][0]["start"] == 0


def test_short_file_transcription(fixtures, models_root):
    if models_root is None:
        pytest.skip("models not installed")
    p = TranscriptionPipeline(engine="sensevoice")
    r = p.transcribe_file(fixtures / "zh_01_daily.wav")
    assert "天气" in r.text and "公园" in r.text
    assert r.engine == "sensevoice"
    assert r.duration > 1.0
    assert r.segments


def test_progress_callback_is_called(fixtures, models_root):
    if models_root is None:
        pytest.skip("models not installed")
    events = []
    p = TranscriptionPipeline(engine="paraformer")
    p.transcribe_file(fixtures / "zh_01_daily.wav",
                      progress=lambda *e: events.append(e))
    stages = {e[0] for e in events}
    assert {"load", "segment", "decode", "done"} <= stages


def test_cancel_before_start_raises(fixtures):
    ev = threading.Event()
    ev.set()
    with pytest.raises(TranscriptionCancelled):
        TranscriptionPipeline().transcribe_file(fixtures / "zh_01_daily.wav", cancel=ev)


def test_silent_audio_returns_explicit_empty(fixtures, models_root):
    if models_root is None:
        pytest.skip("models not installed")
    r = TranscriptionPipeline().transcribe_file(fixtures / "hard_silence.wav")
    assert r.is_empty
    assert any("静音" in w for w in r.warnings)


def test_long_audio_segmentation_and_coverage(fixtures, models_root):
    if models_root is None:
        pytest.skip("models not installed")
    p = TranscriptionPipeline(engine="paraformer", max_segment_seconds=20.0)
    r = p.transcribe_file(fixtures / "long_60s.wav")
    assert len(r.segments) >= 2
    assert r.segments[-1].end > 50
    assert "天气" in r.text and "会议纪要" in r.text


def test_corrupt_file_propagates_audio_error(tmp_path):
    bad = tmp_path / "bad.mp3"
    bad.write_bytes(b"garbage" * 100)
    with pytest.raises(AudioError):
        TranscriptionPipeline().transcribe_file(bad)


def test_single_bad_segment_does_not_abort(fixtures, models_root, monkeypatch):
    """A transient engine failure on one segment must not lose the others."""
    if models_root is None:
        pytest.skip("models not installed")
    from voxscribe.engines.manager import EngineManager
    from voxscribe.core.errors import EngineError
    mgr = EngineManager(threads=2)
    original = mgr.transcribe
    calls = {"n": 0}

    def flaky(x, requested="auto", **kw):
        calls["n"] += 1
        if calls["n"] == 1:
            raise EngineError("simulated transient failure")
        return original(x, requested, **kw)

    monkeypatch.setattr(mgr, "transcribe", flaky)
    p = TranscriptionPipeline(manager=mgr, engine="paraformer", use_vad=True,
                              max_segment_seconds=12.0)
    # force >=2 segments with a synthetic long input
    a = audio.load_audio(fixtures / "long_60s.wav")
    r = p.transcribe_audio(a)
    assert r.text, "other segments should still produce text"
    assert any("失败" in w for w in r.warnings)

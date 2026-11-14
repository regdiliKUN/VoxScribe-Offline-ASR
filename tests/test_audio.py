"""Audio layer regression tests (iteration round 1 and later rounds)."""
from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from voxscribe.core import audio
from voxscribe.core.errors import AudioError


def test_load_wav_is_16k_mono(fixtures):
    a = audio.load_audio(fixtures / "zh_01_daily.wav")
    assert a.sample_rate == 16000
    assert a.samples.ndim == 1
    assert a.duration > 1.0
    assert np.isfinite(a.samples).all()
    assert a.peak <= 1.0


def test_load_mp3_natively_without_ffmpeg(fixtures, monkeypatch):
    """MP3 should decode through libsndfile even when ffmpeg is unavailable."""
    monkeypatch.setattr(audio, "ffmpeg_path", lambda: None)
    a = audio.load_audio(fixtures / "sample.mp3")
    assert a.sample_rate == 16000
    assert a.duration > 1.0
    assert a.rms > 0.001


def test_stereo_44100_is_downmixed_and_resampled(fixtures):
    a = audio.load_audio(fixtures / "hard_stereo441.wav")
    assert a.sample_rate == 16000
    assert a.samples.ndim == 1
    assert 2.0 < a.duration < 6.0


def test_telephone_8k_is_upsampled(fixtures):
    a = audio.load_audio(fixtures / "hard_telephone8k.wav")
    assert a.sample_rate == 16000
    assert a.duration > 2.0


def test_empty_and_corrupt_files_raise_typed_error(tmp_path):
    empty = tmp_path / "empty.wav"
    empty.write_bytes(b"")
    with pytest.raises(AudioError):
        audio.load_audio(empty)
    corrupt = tmp_path / "corrupt.mp3"
    corrupt.write_bytes(b"not an audio file" * 100)
    with pytest.raises(AudioError):
        audio.load_audio(corrupt)


def test_missing_file_raises_typed_error(tmp_path):
    with pytest.raises(AudioError):
        audio.load_audio(tmp_path / "nope.wav")


def test_non_ascii_path_and_spaces(tmp_path, fixtures):
    target = tmp_path / "中文 目录" / "录音 文件.wav"
    target.parent.mkdir(parents=True, exist_ok=True)
    x = np.sin(np.linspace(0, 1000, 16000), dtype="float32") * 0.2
    sf.write(target, x, 16000, subtype="PCM_16")
    a = audio.load_audio(target)
    assert a.duration == pytest.approx(1.0, abs=0.02)


def test_normalize_repairs_nan_and_overscale():
    x = np.array([0.0, np.nan, np.inf, 50000.0, -50000.0], dtype="float32")
    y = audio.normalize(x, 16000)
    assert np.isfinite(y).all()
    assert y.max() <= 1.0 and y.min() >= -1.0


def test_write_wav_is_atomic(tmp_path):
    x = np.zeros(16000, dtype="float32")
    p = tmp_path / "out.wav"
    audio.write_wav(p, x, 16000)
    assert p.is_file()
    assert not list(tmp_path.glob("voxscribe-*.wav"))
    a = audio.load_audio(p)
    assert a.duration == pytest.approx(1.0, abs=0.01)


def test_energy_vad_finds_speech(fixtures):
    a = audio.load_audio(fixtures / "zh_01_daily.wav")
    segs = audio.energy_vad_segments(a.samples)
    assert segs, "expected at least one voiced segment"
    assert all(0 <= s < e <= len(a.samples) for s, e in segs)


def test_segment_audio_long_coverage(fixtures):
    a = audio.load_audio(fixtures / "long_60s.wav")
    segs = audio.segment_audio(a.samples, use_vad=True, max_segment_seconds=25.0)
    assert len(segs) >= 2
    assert all(s.duration > 0 for s in segs)
    assert segs[-1].end == pytest.approx(a.duration, abs=0.01)
    assert all(s.duration <= 25.01 for s in segs)


def test_segment_short_audio_single_chunk(fixtures):
    a = audio.load_audio(fixtures / "zh_01_daily.wav")
    segs = audio.segment_audio(a.samples, use_vad=True, max_segment_seconds=25.0)
    assert len(segs) == 1
    assert segs[0].start == 0.0


def test_device_enumeration_never_raises():
    devices = audio.list_input_devices()
    assert isinstance(devices, list)

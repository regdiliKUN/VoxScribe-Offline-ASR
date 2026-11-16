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


def test_silero_vad_is_actually_available_when_model_present():
    """Silero VAD must not silently fall back to energy VAD on API changes."""
    from voxscribe.core.paths import find_model_file
    if find_model_file("vad/silero_vad.onnx") is None:
        pytest.skip("VAD model not installed")
    sr = 16000
    # Speech-like modulated tone; the point is that the neural VAD runs at all.
    t = np.arange(sr) / sr
    x = (0.3 * np.sin(2 * np.pi * 200 * t) *
         (0.5 + 0.5 * np.sin(2 * np.pi * 3 * t))).astype("float32")
    result = audio.silero_vad_segments(x)
    assert result is not None          # None means it errored out and bailed
    assert isinstance(result, list)


def test_silero_vad_cache_is_thread_safe():
    from concurrent.futures import ThreadPoolExecutor
    from voxscribe.core.paths import find_model_file
    if find_model_file("vad/silero_vad.onnx") is None:
        pytest.skip("VAD model not installed")
    audio._SILERO_CACHE.clear()
    with ThreadPoolExecutor(max_workers=6) as ex:
        results = list(ex.map(lambda _: audio._get_silero_vad(0.5, 20.0), range(6)))
    assert len({id(v) for v in results}) == 1   # one shared instance
    assert len(audio._SILERO_CACHE) == 1


def test_silero_vad_model_is_cached():
    from voxscribe.core.paths import find_model_file
    if find_model_file("vad/silero_vad.onnx") is None:
        pytest.skip("VAD model not installed")
    audio._SILERO_CACHE.clear()
    v1 = audio._get_silero_vad(0.5, 20.0)
    v2 = audio._get_silero_vad(0.5, 20.0)
    assert v1 is v2
    assert len(audio._SILERO_CACHE) == 1


def test_load_audio_wraps_stat_permission_error(tmp_path, monkeypatch):
    """A stat() failure (TOCTOU/permission) must surface as a typed AudioError."""
    f = tmp_path / "gone.wav"
    f.write_bytes(b"RIFFxxxx")

    def boom(self, *a, **kw):
        raise PermissionError("access denied")

    monkeypatch.setattr(Path, "stat", boom)
    with pytest.raises(AudioError):
        audio.load_audio(f)


def test_resample_decimation_suppresses_aliasing():
    """A 20 kHz tone must not fold into the speech band on 44.1k->16k decimation."""
    sr = 44100
    t = np.arange(sr) / sr
    hf = (0.5 * np.sin(2 * np.pi * 20000 * t)).astype("float32")
    y = audio.resample(hf, sr, 16000)
    # With anti-aliasing the folded high-frequency energy is damped by several
    # times versus the source tone (~0.354 rms); plain interpolation leaves it
    # nearly intact.
    src_rms = float(np.sqrt(np.mean(hf ** 2)))
    out_rms = float(np.sqrt(np.mean(y ** 2)))
    assert out_rms < src_rms * 0.35
    assert len(y) == 16000


def test_resample_upsampling_and_identity():
    x = np.sin(np.arange(160) / 10).astype("float32")
    assert np.array_equal(audio.resample(x, 16000, 16000), x)
    up = audio.resample(x, 8000, 16000)
    assert len(up) == 320 and np.isfinite(up).all()


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


def test_normalize_keeps_hot_float_audio_audible():
    """Round 65: peak 10 used to be divided by 32768 and become silence."""
    x = np.array([0.0, 10.0, -10.0, 5.0], dtype="float32")
    y = audio.normalize(x, 16000)
    assert float(np.max(np.abs(y))) > 0.9


def test_segment_audio_absorbs_short_middle_piece(monkeypatch):
    """Round 68: short VAD hits must not create holes in the timeline."""
    x = np.zeros(3 * 16000, dtype="float32")
    monkeypatch.setattr(audio, "silero_vad_segments",
                        lambda *a, **kw: [(0, 8000), (20000, 24000), (40000, 48000)])
    segs = audio.segment_audio(x, use_vad=True, max_segment_seconds=25.0,
                               min_segment_seconds=0.30)
    assert any(s.start <= 1.25 < s.end for s in segs)


def test_device_enumeration_never_raises():
    devices = audio.list_input_devices()
    assert isinstance(devices, list)

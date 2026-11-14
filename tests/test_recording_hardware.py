"""Real-hardware smoke test: record from the actual default microphone.

Skipped automatically on machines without an input device. This complements
the deterministic fake-stream tests in test_recorder.py.
"""
from __future__ import annotations

import time

import pytest

from voxscribe.core import audio


def test_real_microphone_roundtrip(tmp_path):
    devices = audio.list_input_devices()
    if not devices:
        pytest.skip("no input device on this machine")

    r = audio.Recorder(sample_rate=16000, max_seconds=30)
    try:
        r.start()
    except Exception as exc:
        pytest.skip(f"microphone unavailable: {exc}")
    deadline = time.monotonic() + 1.5
    while time.monotonic() < deadline and r.recording:
        time.sleep(0.05)
    data = r.stop()

    assert data.sample_rate == 16000
    assert 1.0 <= data.duration <= 5.0, f"unexpected duration {data.duration}"
    assert data.samples.ndim == 1
    assert data.samples.size >= 16000

    wav = audio.write_wav(tmp_path / "mic 录音.wav", data.samples)
    loaded = audio.load_audio(wav)
    assert loaded.duration == pytest.approx(data.duration, abs=0.02)
    assert wav.stat().st_size > 44

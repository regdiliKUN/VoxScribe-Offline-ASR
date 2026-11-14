"""Recorder behaviour tests with a deterministic fake PortAudio stream."""
from __future__ import annotations

import numpy as np
import pytest
import sounddevice as sd

from voxscribe.core import audio
from voxscribe.core.errors import RecordingError


class FakeStream:
    instances = []

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.callback = kwargs["callback"]
        self.started = False
        self.stopped = False
        self.closed = False
        FakeStream.instances.append(self)

    def start(self):
        self.started = True

    def stop(self):
        self.stopped = True

    def close(self):
        self.closed = True

    def feed(self, n=1024, value=0.1, status=None):
        block = np.full((n, 1), value, dtype="float32")
        self.callback(block, n, None, status)


@pytest.fixture
def fake_sd(monkeypatch):
    FakeStream.instances.clear()
    monkeypatch.setattr(sd, "InputStream", FakeStream)
    return FakeStream


def test_record_and_stop_returns_audio(fake_sd):
    levels = []
    r = audio.Recorder(on_level=levels.append)
    r.start()
    stream = fake_sd.instances[0]
    assert stream.started
    for _ in range(16):
        stream.feed()
    a = r.stop()
    assert a.sample_rate == 16000
    assert a.duration > 0.9
    assert a.peak > 0
    assert levels and max(levels) > 0
    assert stream.stopped and stream.closed
    assert not r.recording


def test_stop_on_empty_recording_raises(fake_sd):
    r = audio.Recorder()
    r.start()
    with pytest.raises(RecordingError):
        r.stop()


def test_double_start_raises(fake_sd):
    r = audio.Recorder()
    r.start()
    with pytest.raises(RecordingError):
        r.start()
    fake_sd.instances[0].feed()
    r.stop()


def test_cancel_discards_audio(fake_sd):
    r = audio.Recorder()
    r.start()
    fake_sd.instances[0].feed()
    r.cancel()
    assert not r.recording
    with pytest.raises(RecordingError):
        r.stop()


def test_max_duration_stops_stream_cleanly(fake_sd):
    """Reaching the cap must not raise an arbitrary exception in the callback."""
    r = audio.Recorder(max_seconds=1)
    r.start()
    stream = fake_sd.instances[0]
    with pytest.raises(sd.CallbackStop):
        for _ in range(20):
            stream.feed()
    assert r.limit_reached
    a = r.stop()
    assert a.duration <= 1.1


def test_status_is_reported_once(fake_sd):
    errors = []
    r = audio.Recorder(on_error=errors.append)
    r.start()
    stream = fake_sd.instances[0]
    stream.feed(status="input overflow")
    stream.feed(status="input overflow")
    stream.feed(status="input overflow")
    assert len(errors) == 1
    r.stop()


def test_start_failure_is_wrapped(monkeypatch):
    def boom(**_kw):
        raise OSError("device busy")
    monkeypatch.setattr(sd, "InputStream", boom)
    with pytest.raises(RecordingError):
        audio.Recorder().start()

"""Engine layer tests (iteration round 2 and later rounds)."""
from __future__ import annotations

import numpy as np
import pytest

from voxscribe.core import audio
from voxscribe.core.errors import EngineError, ModelError
from voxscribe.engines.base import SPECS, SPECS_BY_KEY, clean_text
from voxscribe.engines.manager import EngineManager


@pytest.fixture(scope="module")
def manager():
    return EngineManager(threads=4)


def test_specs_are_well_formed():
    assert [s.key for s in SPECS] == ["qwen3", "sensevoice", "paraformer"]
    assert all(s.files for s in SPECS)
    assert len(SPECS_BY_KEY) == len(SPECS)


def test_clean_text_removes_sensevoice_tags():
    assert clean_text("<|zh|><|NEUTRAL|><|Speech|><|woitn|>今天天气很好。") == "今天天气很好。"
    assert clean_text("  \ufeffabc\u200b ") == "abc"


def test_available_engines(models_root, manager):
    if models_root is None:
        pytest.skip("models not installed")
    assert "sensevoice" in manager.available_keys()
    assert manager.resolve("auto").key in manager.available_keys()


def test_resolve_unknown_engine_falls_back(models_root, manager):
    if models_root is None:
        pytest.skip("models not installed")
    assert manager.resolve("does-not-exist").key in manager.available_keys()


@pytest.mark.parametrize("key", ["qwen3", "sensevoice", "paraformer"])
def test_engine_recognises_chinese(fixtures, models_root, manager, key):
    if models_root is None or key not in manager.available_keys():
        pytest.skip(f"engine {key} not installed")
    a = audio.load_audio(fixtures / "zh_01_daily.wav")
    text, used, attempts = manager.transcribe(a.samples, key, allow_fallback=False)
    assert used == key
    assert "天气" in text and "公园" in text
    assert attempts[-1].ok


def test_engine_handles_silence_without_crash(fixtures, models_root, manager):
    if models_root is None:
        pytest.skip("models not installed")
    a = audio.load_audio(fixtures / "hard_silence.wav")
    text, used, _ = manager.transcribe(a.samples, "auto", allow_fallback=False)
    assert isinstance(text, str)
    assert len(text) < 30, f"unexpected hallucination on silence: {text!r}"


def test_missing_models_raise_model_error(monkeypatch):
    import voxscribe.engines.base as base
    monkeypatch.setattr(base, "find_model_file", lambda _rel: None)
    m = EngineManager()
    assert m.available_keys() == []
    with pytest.raises(ModelError):
        m.resolve("auto")


def test_failover_when_primary_engine_fails(fixtures, models_root, monkeypatch):
    if models_root is None:
        pytest.skip("models not installed")
    m = EngineManager(threads=2)
    a = audio.load_audio(fixtures / "zh_01_daily.wav")
    primary = m._get(SPECS_BY_KEY["qwen3"])

    def broken(_x, _sr=16000):
        raise EngineError("simulated primary failure")

    monkeypatch.setattr(primary, "transcribe", broken)
    text, used, attempts = m.transcribe(a.samples, "qwen3", allow_fallback=True)
    assert used != "qwen3"
    assert "天气" in text
    assert attempts[0].ok is False and attempts[-1].ok is True

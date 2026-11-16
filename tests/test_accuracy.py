"""Recognition accuracy regression tests (iteration round 19+)."""
from __future__ import annotations

import pytest

from evaluate import cer, evaluate, normalize
from voxscribe.core import audio
from voxscribe.engines.manager import EngineManager


def test_cer_helper():
    assert cer("今天天气很好", "今天天气很好") == 0.0
    assert cer("今天天气很好", "今天天汽很好") == pytest.approx(1 / 6)
    assert normalize("<|zh|><|NEUTRAL|>今天，天气很好！") == "今天天气很好"


def test_evaluate_marks_engine_failures_as_full_miss(monkeypatch):
    """A crashed engine must score CER 1.0, not a flattering string similarity."""
    import evaluate as ev

    def boom(self, *a, **kw):
        raise RuntimeError("engine down")

    monkeypatch.setattr(ev.EngineManager, "transcribe", boom)
    result = ev.evaluate("auto", ids={"zh_01_daily"})
    assert result["samples"] >= 1
    row = next(r for r in result["rows"] if r["id"] == "zh_01_daily")
    assert row["failed"] is True
    assert row["cer"] == 1.0
    assert row["engine"] == "none"


def test_evaluate_rtf_excludes_failed_samples(monkeypatch):
    """Round 80: instant failures must not produce a flattering near-zero RTF."""
    import evaluate as ev

    def boom(self, *a, **kw):
        raise RuntimeError("engine down")

    monkeypatch.setattr(ev.EngineManager, "transcribe", boom)
    result = ev.evaluate("auto", ids={"zh_01_daily"})
    assert result["rtf"] == 0.0
    assert result["failed_samples"] >= 1


def test_evaluate_counts_missing_audio_as_full_miss(monkeypatch, tmp_path):
    """Round 82: silently skipping fixtures inflated accuracy claims."""
    import json
    import evaluate as ev

    (tmp_path / "manifest.json").write_text(json.dumps([
        {"id": "missing_01", "wav": "nope.wav", "text": "今天天气很好"}
    ], ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(ev, "FIXTURES", tmp_path)
    result = ev.evaluate("auto")
    assert result["samples"] == 1
    assert result["missing_samples"] == 1
    assert result["failed_samples"] == 1
    assert result["rows"][0]["cer"] == 1.0


def test_cer_digit_normalisation():
    assert cer("二零二六年", "2026年") == 0.0


@pytest.mark.parametrize("key", ["qwen3", "sensevoice", "paraformer"])
def test_clean_chinese_cer_below_threshold(fixtures, models_root, key):
    if models_root is None:
        pytest.skip("models not installed")
    mgr = EngineManager(threads=4)
    if key not in mgr.available_keys():
        pytest.skip(f"{key} not installed")
    a = audio.load_audio(fixtures / "zh_01_daily.wav")
    text, used, _ = mgr.transcribe(a.samples, key, allow_fallback=False)
    assert cer("今天天气很好，我们一起去公园散步吧。", text) <= 0.15, (used, text)


@pytest.mark.parametrize("key", ["qwen3", "sensevoice", "paraformer"])
def test_hard_noise_cer_below_threshold(fixtures, models_root, key):
    if models_root is None:
        pytest.skip("models not installed")
    mgr = EngineManager(threads=4)
    if key not in mgr.available_keys():
        pytest.skip(f"{key} not installed")
    a = audio.load_audio(fixtures / "hard_noise_snr0.wav")
    text, _used, _ = mgr.transcribe(a.samples, key, allow_fallback=False)
    assert cer("人工智能技术正在深刻改变我们的工作方式。", text) <= 0.30, text


def test_english_sample_accuracy(fixtures, models_root):
    if models_root is None:
        pytest.skip("models not installed")
    mgr = EngineManager(threads=4)
    a = audio.load_audio(fixtures / "en_01.wav")
    text, _used, _ = mgr.transcribe(a.samples, "sensevoice", allow_fallback=True)
    assert cer("The quick brown fox jumps over the lazy dog.", text) <= 0.25, text


def test_silence_does_not_hallucinate(fixtures, models_root):
    if models_root is None:
        pytest.skip("models not installed")
    mgr = EngineManager(threads=4)
    a = audio.load_audio(fixtures / "hard_silence.wav")
    text, _used, _ = mgr.transcribe(a.samples, "auto", allow_fallback=False)
    assert len(text.strip()) < 20, text


def test_evaluate_script_aggregate(models_root):
    if models_root is None:
        pytest.skip("models not installed")
    result = evaluate("paraformer", ids={"zh_01_daily", "zh_03_tech", "en_01"})
    assert result["samples"] == 3
    assert result["cer"] <= 0.15
    assert result["rtf"] < 1.0

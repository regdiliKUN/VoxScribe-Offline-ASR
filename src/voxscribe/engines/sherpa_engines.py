"""Concrete sherpa-onnx backends (Qwen3-ASR / SenseVoice / Paraformer)."""
from __future__ import annotations

import logging

from .base import BaseEngine, EngineSpec

log = logging.getLogger("voxscribe.engine.sherpa")


class SherpaEngine(BaseEngine):
    """All three engines share the sherpa-onnx runtime but use different model graphs."""

    def _create_recognizer(self):
        import sherpa_onnx

        spec: EngineSpec = self.spec
        nt = self.threads
        if spec.kind == "qwen3":
            d = spec.resolve("qwen3/conv_frontend.onnx").parent
            return sherpa_onnx.OfflineRecognizer.from_qwen3_asr(
                conv_frontend=str(d / "conv_frontend.onnx"),
                encoder=str(d / "encoder.int8.onnx"),
                decoder=str(d / "decoder.int8.onnx"),
                tokenizer=str(d / "tokenizer"),
                num_threads=nt,
                max_new_tokens=256,
            )
        if spec.kind == "sense_voice":
            return sherpa_onnx.OfflineRecognizer.from_sense_voice(
                model=str(spec.resolve("sensevoice/model.int8.onnx")),
                tokens=str(spec.resolve("sensevoice/tokens.txt")),
                use_itn=bool(self.use_itn),
                language="" if self.language == "auto" else self.language,
                num_threads=nt,
            )
        if spec.kind == "paraformer":
            return sherpa_onnx.OfflineRecognizer.from_paraformer(
                paraformer=str(spec.resolve("paraformer/model.int8.onnx")),
                tokens=str(spec.resolve("paraformer/tokens.txt")),
                num_threads=nt,
            )
        raise ValueError(f"unknown engine kind: {spec.kind}")


def create_engine(spec: EngineSpec, *, threads: int = 0, language: str = "auto",
                  use_itn: bool = True) -> SherpaEngine:
    return SherpaEngine(spec, threads=threads, language=language, use_itn=use_itn)

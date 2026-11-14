"""Engine contracts and model specifications."""
from __future__ import annotations

import logging
import threading
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from ..core.errors import EngineError, ModelError
from ..core.paths import find_model_file

log = logging.getLogger("voxscribe.engine")


@dataclass(frozen=True)
class EngineSpec:
    key: str
    display: str
    kind: str                     # qwen3 | sense_voice | paraformer
    files: tuple[str, ...]
    summary: str = ""
    languages: str = ""
    relative_speed: str = ""

    def missing_files(self) -> list[str]:
        return [f for f in self.files if find_model_file(f) is None]

    def integrity_issues(self) -> list[str]:
        """Detect truncated model files using the shipped manifest."""
        from ..core.integrity import load_manifest
        manifest = load_manifest()
        problems = []
        if not manifest:
            return problems
        for f in self.files:
            meta = manifest.get(f)
            if not meta:
                continue
            p = find_model_file(f)
            if p is None:
                continue
            expected = int(meta.get("size", 0))
            if expected and p.stat().st_size != expected:
                problems.append(f"{f} 大小不符（可能被截断）")
        return problems

    def resolve(self, relative: str) -> Path:
        p = find_model_file(relative)
        if p is None:
            raise ModelError(f"模型文件缺失：{relative}", detail=self.key)
        return p


SPECS: tuple[EngineSpec, ...] = (
    EngineSpec(
        key="qwen3",
        display="Qwen3-ASR 0.6B · 极致精度",
        kind="qwen3",
        files=(
            "qwen3/conv_frontend.onnx",
            "qwen3/encoder.int8.onnx",
            "qwen3/decoder.int8.onnx",
            "qwen3/tokenizer/vocab.json",
            "qwen3/tokenizer/merges.txt",
            "qwen3/tokenizer/tokenizer_config.json",
        ),
        summary="2026 年新一代多语种/22 种中文方言模型；实测 39 样本 CER 0.0000，静音不幻听。",
        languages="中/英/日/韩/粤 + 中文方言",
        relative_speed="≈8× 实时",
    ),
    EngineSpec(
        key="sensevoice",
        display="SenseVoice-Small · 均衡快速",
        kind="sense_voice",
        files=("sensevoice/model.int8.onnx", "sensevoice/tokens.txt"),
        summary="非自回归多语种模型，自带标点、ITN、语种与情感标签；体积与速度最均衡。",
        languages="中/英/日/韩/粤",
        relative_speed="≈47× 实时",
    ),
    EngineSpec(
        key="paraformer",
        display="Paraformer-small · 轻量极速",
        kind="paraformer",
        files=("paraformer/model.int8.onnx", "paraformer/tokens.txt"),
        summary="仅 79 MB 的中文专用模型，CPU 上最快，适合低配机器与批量长音频。",
        languages="普通话 / 简单英文",
        relative_speed="≈125× 实时",
    ),
)

SPECS_BY_KEY = {s.key: s for s in SPECS}


class BaseEngine(ABC):
    """A lazily loaded, thread-safe offline recogniser."""

    def __init__(self, spec: EngineSpec, *, threads: int = 0,
                 language: str = "auto", use_itn: bool = True):
        self.spec = spec
        self.threads = threads or min(4, max(1, (__import__("os").cpu_count() or 4)))
        self.language = language
        self.use_itn = use_itn
        self._lock = threading.Lock()
        self._recognizer = None
        self._healthy = True

    @property
    def key(self) -> str:
        return self.spec.key

    @property
    def available(self) -> bool:
        return not self.spec.missing_files()

    @property
    def healthy(self) -> bool:
        return self._healthy

    def mark_unhealthy(self, reason: str = "") -> None:
        self._healthy = False
        log.error("Engine %s marked unhealthy: %s", self.key, reason)

    @abstractmethod
    def _create_recognizer(self):  # pragma: no cover - abstract
        ...

    def load(self) -> None:
        with self._lock:
            if self._recognizer is not None:
                return
            missing = self.spec.missing_files()
            if missing:
                raise ModelError(
                    "识别模型缺失，请重新安装完整版或检查 models 目录",
                    detail=f"{self.key}: missing {missing}")
            broken = self.spec.integrity_issues()
            if broken:
                raise ModelError(
                    "识别模型文件不完整，请重新下载安装包",
                    detail=f"{self.key}: {broken}")
            try:
                self._recognizer = self._create_recognizer()
                log.info("Engine %s loaded (threads=%s)", self.key, self.threads)
            except ModelError:
                raise
            except Exception as exc:
                self._healthy = False
                raise EngineError(
                    f"{self.spec.display} 加载失败",
                    detail=f"{type(exc).__name__}: {exc}", cause=exc) from exc

    def unload(self) -> None:
        with self._lock:
            self._recognizer = None

    def transcribe(self, x: np.ndarray, sample_rate: int = 16000) -> str:
        """Recognise one 16 kHz mono chunk; never returns None."""
        if x is None or getattr(x, "size", 0) == 0:
            return ""
        self.load()
        arr = np.ascontiguousarray(x, dtype="float32")
        try:
            import sherpa_onnx
            stream = self._recognizer.create_stream()
            stream.accept_waveform(int(sample_rate), arr)
            self._recognizer.decode_stream(stream)
            return clean_text(stream.result.text)
        except Exception as exc:
            self.mark_unhealthy(str(exc))
            raise EngineError("语音识别失败", detail=f"{self.key}: {exc}", cause=exc) from exc


_TAG_RE = None


def clean_text(text: str) -> str:
    """Strip SenseVoice control tags and collapse exotic whitespace."""
    global _TAG_RE
    if _TAG_RE is None:
        import re
        _TAG_RE = re.compile(r"<\|[^|]*\|>")
    import re
    text = _TAG_RE.sub("", text or "")
    text = re.sub(r"[\u200b\ufeff]", "", text)
    return text.strip()

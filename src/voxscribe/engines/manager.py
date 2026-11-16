"""Engine registry, availability probing and automatic failover.

Failover is intentional: a corrupt model, an ONNX runtime problem or an OOM on
one backend must never make the whole application unusable. Every failure is
logged with its technical detail and surfaced as a short user-facing note.
"""
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass

import numpy as np

from ..core.errors import EngineError, ModelError
from .base import SPECS, SPECS_BY_KEY, BaseEngine, EngineSpec
from .sherpa_engines import create_engine

log = logging.getLogger("voxscribe.engine.manager")


@dataclass
class EngineAttempt:
    key: str
    ok: bool
    error: str = ""


class EngineManager:
    def __init__(self, *, threads: int = 0, language: str = "auto", use_itn: bool = True):
        self.threads = threads
        self.language = language
        self.use_itn = use_itn
        self._engines: dict[str, BaseEngine] = {}
        # Two GUI/CLI threads can request the same engine on first use; without
        # a lock each one loads a full ONNX model and one copy leaks.
        self._lock = threading.RLock()
        # Availability probing stats every model file (including the 721 MB
        # Qwen3 decoder) and parses the manifest.  A manager instance is bound
        # to one app session, so cache the result lazily and allow explicit
        # invalidation when models are changed at runtime.
        self._available_cache: list[EngineSpec] | None = None

    def invalidate(self) -> None:
        """Drop cached availability and loaded engines after model changes.

        Loaded engines can be marked unhealthy from a previous failure; if a
        model is repaired on disk, keeping those instances would make the
        engine stay broken.  Clearing both caches forces a clean re-probe and
        a fresh recogniser on the next transcription.
        """
        with self._lock:
            self._available_cache = None
            self._engines.clear()

    def _get(self, spec: EngineSpec) -> BaseEngine:
        with self._lock:
            if spec.key not in self._engines:
                self._engines[spec.key] = create_engine(
                    spec, threads=self.threads, language=self.language, use_itn=self.use_itn)
            return self._engines[spec.key]

    def available_specs(self) -> list[EngineSpec]:
        with self._lock:
            if self._available_cache is not None:
                return list(self._available_cache)
            out = []
            for s in SPECS:
                if s.missing_files() or s.integrity_issues():
                    continue
                out.append(s)
            self._available_cache = list(out)
            return out

    def available_keys(self) -> list[str]:
        return [s.key for s in self.available_specs()]

    def missing_summary(self) -> str:
        parts = []
        for s in SPECS:
            missing = s.missing_files()
            broken = s.integrity_issues()
            if missing:
                parts.append(f"{s.key}({len(missing)} 个文件缺失)")
            elif broken:
                parts.append(f"{s.key}(文件损坏：{broken[0]})")
        return "；".join(parts)

    def resolve(self, requested: str) -> EngineSpec:
        """Map 'auto' / explicit key to an actually available engine."""
        available = self.available_keys()
        if not available:
            raise ModelError(
                "未找到任何识别模型，请重新下载完整安装包",
                detail=self.missing_summary())
        if requested in ("auto", "", None):
            return SPECS_BY_KEY[available[0]]
        if requested in SPECS_BY_KEY and requested in available:
            return SPECS_BY_KEY[requested]
        log.warning("Requested engine %s unavailable (%s); falling back to %s",
                    requested, self.missing_summary(), available[0])
        return SPECS_BY_KEY[available[0]]

    def ordered_specs(self, requested: str) -> list[EngineSpec]:
        primary = self.resolve(requested)
        rest = [s for s in self.available_specs() if s.key != primary.key]
        specs = [primary, *rest]
        # `healthy` used to be recorded but never consulted: a failed engine
        # stayed first and was retried on every job.  Stable sort demotes it
        # while preserving the configured priority among healthy engines.
        return sorted(specs, key=lambda s: not getattr(
            self._engines.get(s.key), "healthy", True))

    def transcribe(self, x: np.ndarray, requested: str = "auto", *,
                   sample_rate: int = 16000, allow_fallback: bool = True) -> tuple[str, str, list[EngineAttempt]]:
        """Return (text, engine_key_used, attempts)."""
        specs = self.ordered_specs(requested)
        if not allow_fallback:
            specs = specs[:1]
        attempts: list[EngineAttempt] = []
        last_error = ""
        for spec in specs:
            eng = self._get(spec)
            try:
                text = eng.transcribe(x, sample_rate)
                # An engine that returns nothing on a non-silent chunk is a soft failure.
                if not text and float(np.sqrt(np.mean(np.asarray(x) ** 2))) > 0.004:
                    raise EngineError("识别结果为空")
                attempts.append(EngineAttempt(spec.key, True))
                return text, spec.key, attempts
            except Exception as exc:
                last_error = f"{type(exc).__name__}: {exc}"
                attempts.append(EngineAttempt(spec.key, False, last_error))
                log.warning("Engine %s failed: %s", spec.key, last_error)
                eng.unload()
                continue
        raise EngineError(
            "所有识别引擎均失败，请查看日志或切换引擎重试",
            detail=last_error)

    def warm(self, key: str = "auto") -> str | None:
        """Pre-load an engine so the first transcription is not delayed."""
        try:
            spec = self.resolve(key)
            self._get(spec).load()
            return spec.key
        except Exception as exc:
            log.warning("Warm-up failed: %s", exc)
            return None

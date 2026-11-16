"""Audio input: import, normalise, record and segment.

Design goals
------------
* Everything that reaches an ASR engine is **16 kHz mono float32** in [-1, 1].
* Corrupt / silent / absurdly long / non-ASCII-path files never crash the app;
  they raise a typed :class:`AudioError` with a user-facing message.
* ffmpeg is optional for WAV/FLAC/OGG (libsndfile handles them) and mandatory
  for MP3/M4A/video containers; a bundled ffmpeg.exe is used when available.
"""
from __future__ import annotations

import logging
import math
import os
import subprocess
import tempfile
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterator

import numpy as np

from .errors import AudioError, RecordingError, UnsupportedFormatError
from .paths import ffmpeg_path, find_model_file

log = logging.getLogger("voxscribe.audio")

TARGET_SR = 16000
MAX_AUDIO_SECONDS = 6 * 3600
SUPPORTED_SUFFIXES = {
    ".wav", ".flac", ".ogg", ".oga", ".mp3", ".m4a", ".aac", ".wma",
    ".opus", ".aiff", ".aif", ".mp4", ".mkv", ".mov", ".avi", ".webm",
    ".ts", ".flv", ".wmv", ".mpeg", ".mpg", ".3gp", ".caf",
}
# libsndfile >= 1.2 decodes MP3 and Opus natively; avoiding an ffmpeg process
# for the most common compressed formats cuts import latency and removes a
# hard dependency for users who only ever use .wav/.mp3/.flac.
LIBSNDFILE_SUFFIXES = {".wav", ".flac", ".ogg", ".oga", ".aiff", ".aif",
                       ".caf", ".mp3", ".opus"}


@dataclass
class AudioData:
    samples: np.ndarray
    sample_rate: int
    source: str = ""

    @property
    def duration(self) -> float:
        return len(self.samples) / self.sample_rate

    @property
    def peak(self) -> float:
        return float(np.max(np.abs(self.samples))) if self.samples.size else 0.0

    @property
    def rms(self) -> float:
        return float(np.sqrt(np.mean(self.samples ** 2))) if self.samples.size else 0.0

    @property
    def is_silent(self) -> bool:
        return self.rms < 1e-4


@dataclass
class AudioSegment:
    start: float
    end: float
    samples: np.ndarray

    @property
    def duration(self) -> float:
        return self.end - self.start


def resample(x: np.ndarray, src_sr: int, dst_sr: int = TARGET_SR) -> np.ndarray:
    """Linear resampling with anti-aliasing on decimation; no SciPy needed.

    Plain linear interpolation when down-sampling folds frequencies above the
    new Nyquist limit back into the speech band (e.g. 44.1 kHz -> 16 kHz folds
    20 kHz to ~2.4 kHz).  A short moving-average FIR applied before decimation
    suppresses that aliasing while keeping the frozen build dependency-free.
    """
    if src_sr == dst_sr or x.size == 0:
        return np.ascontiguousarray(x, dtype="float32")
    x = np.asarray(x, dtype="float32")
    if src_sr > dst_sr:
        # Kernel width ~= decimation factor gives a low-pass corner near the
        # destination Nyquist frequency.
        width = max(2, int(round(src_sr / dst_sr)))
        if x.size >= width:
            kernel = np.ones(width, dtype="float32") / width
            x = np.convolve(x, kernel, mode="same")
    n = max(1, int(round(len(x) * dst_sr / src_sr)))
    return np.ascontiguousarray(
        np.interp(np.linspace(0, len(x) - 1, n), np.arange(len(x)), x),
        dtype="float32",
    )


def normalize(x: np.ndarray, sr: int) -> np.ndarray:
    """Downmix to mono, resample to 16 kHz, clamp, and validate."""
    x = np.asarray(x, dtype="float32")
    if x.ndim == 2:
        x = x.mean(axis=1)
    if x.ndim != 1:
        raise AudioError("音频通道数异常", detail=f"ndim={x.ndim}")
    if x.size == 0:
        raise AudioError("音频文件为空")
    if not np.all(np.isfinite(x)):
        x = np.nan_to_num(x, nan=0.0, posinf=0.0, neginf=0.0)
        log.warning("Non-finite samples repaired")
    if sr != TARGET_SR:
        x = resample(x, sr, TARGET_SR)
    # Scale only by what the data actually needs.  The old `peak > 8` rule
    # mistook legitimately hot float audio (e.g. peak 10) for int16 samples
    # read as float, dividing it by 32768 and turning speech into silence.
    peak = float(np.max(np.abs(x)))
    if peak > 32768.0:
        # Clearly int16-scale values supplied through a float reader.
        x = x / 32768.0
    elif peak > 1.0:
        # Ordinary over-driven float audio: peak-normalise, never silence it.
        x = x / peak
    if float(np.max(np.abs(x))) > 1.0:
        x = np.clip(x, -1.0, 1.0)
    return np.ascontiguousarray(x, dtype="float32")


def _run_ffmpeg(args: list[str], timeout: int = 180) -> subprocess.CompletedProcess:
    exe = ffmpeg_path()
    if not exe:
        raise UnsupportedFormatError(
            "缺少音频解码组件（ffmpeg），无法读取该格式",
            detail="ffmpeg not found in bundle nor PATH")
    creation = 0
    if os.name == "nt":
        creation = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        return subprocess.run(
            [exe, "-hide_banner", "-nostdin", "-loglevel", "error", *args],
            capture_output=True, timeout=timeout, creationflags=creation,
        )
    except subprocess.TimeoutExpired as exc:
        raise AudioError("音频解码超时，文件可能过大或已损坏", detail=str(exc)) from exc
    except OSError as exc:
        raise UnsupportedFormatError("无法启动音频解码组件", detail=str(exc)) from exc


def convert_to_wav(src: str | Path, dst: str | Path | None = None, *,
                   timeout: int = 180) -> Path:
    """Decode any supported container into a 16 kHz mono PCM WAV."""
    src = Path(src)
    if not src.is_file():
        raise AudioError("找不到音频文件", detail=str(src))
    if dst is None:
        fd, tmp = tempfile.mkstemp(prefix="voxscribe-", suffix=".wav")
        os.close(fd)
        dst = Path(tmp)
    dst = Path(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    proc = _run_ffmpeg([
        "-y", "-i", str(src), "-vn", "-map", "0:a:0",
        "-ac", "1", "-ar", str(TARGET_SR), "-c:a", "pcm_s16le",
        "-f", "wav", str(dst),
    ], timeout=timeout)
    if proc.returncode != 0 or not dst.is_file() or dst.stat().st_size <= 44:
        try:
            dst.unlink(missing_ok=True)
        except OSError:
            pass
        err = proc.stderr.decode("utf-8", "replace")[:600]
        raise UnsupportedFormatError(
            "无法解码该音频文件，请确认文件未损坏",
            detail=f"ffmpeg rc={proc.returncode}: {err}")
    return dst


def load_audio(path: str | Path, *, allow_convert: bool = True) -> AudioData:
    """Load an audio file as 16 kHz mono float32, with layered fallbacks."""
    import soundfile as sf

    p = Path(path)
    # A file can vanish or lose read permission between is_file() and stat()
    # (TOCTOU); keep every audio-path failure typed so the UI never surfaces a
    # raw traceback instead of a friendly message.
    try:
        if not p.is_file():
            raise AudioError("找不到音频文件", detail=str(p))
        if p.stat().st_size == 0:
            raise AudioError("音频文件为空（0 字节）")
    except AudioError:
        raise
    except OSError as exc:
        raise AudioError("无法访问音频文件（可能被移动或无读取权限）",
                         detail=f"{type(exc).__name__}: {exc}", cause=exc) from exc
    suffix = p.suffix.lower()

    temp_wav: Path | None = None
    try:
        if suffix in LIBSNDFILE_SUFFIXES:
            try:
                x, sr = sf.read(str(p), dtype="float32", always_2d=False)
                data = normalize(x, sr)
                _validate_duration(len(data) / TARGET_SR)
                return AudioData(data, TARGET_SR, str(p))
            except AudioError:
                raise
            except Exception as exc:
                log.info("libsndfile failed for %s (%s); falling back to ffmpeg", p, exc)
        if not allow_convert:
            raise UnsupportedFormatError("该文件格式需要解码组件", detail=suffix)
        temp_wav = convert_to_wav(p)
        x, sr = sf.read(str(temp_wav), dtype="float32", always_2d=False)
        data = normalize(x, sr)
        _validate_duration(len(data) / TARGET_SR)
        return AudioData(data, TARGET_SR, str(p))
    except (AudioError, UnsupportedFormatError):
        raise
    except Exception as exc:
        raise AudioError("音频读取失败", detail=f"{type(exc).__name__}: {exc}", cause=exc) from exc
    finally:
        if temp_wav:
            try:
                temp_wav.unlink(missing_ok=True)
            except OSError:
                pass


def _validate_duration(seconds: float) -> None:
    if seconds <= 0:
        raise AudioError("音频时长为 0")
    if seconds > MAX_AUDIO_SECONDS:
        raise AudioError(
            f"音频过长（{seconds / 3600:.1f} 小时），单次最多支持 {MAX_AUDIO_SECONDS / 3600:.0f} 小时",
            detail=f"seconds={seconds}")


def write_wav(path: str | Path, x: np.ndarray, sr: int = TARGET_SR) -> Path:
    """Atomic WAV writer (temp file + replace) so a crash never leaves a stub."""
    import soundfile as sf

    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix="voxscribe-", suffix=".wav", dir=str(p.parent))
    os.close(fd)
    try:
        sf.write(tmp, np.asarray(x, dtype="float32"), sr, subtype="PCM_16")
        os.replace(tmp, p)
    except Exception as exc:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise AudioError("录音保存失败", detail=str(exc), cause=exc) from exc
    return p


# --------------------------------------------------------------------------- #
# Recording
# --------------------------------------------------------------------------- #
def list_input_devices() -> list[dict]:
    """Enumerate microphones; never raises if PortAudio is unavailable."""
    try:
        import sounddevice as sd
        devices = []
        for i, d in enumerate(sd.query_devices()):
            if int(d.get("max_input_channels", 0)) > 0:
                devices.append({
                    "index": i,
                    "name": str(d.get("name", f"Device {i}")),
                    "channels": int(d.get("max_input_channels", 1)),
                    "sample_rate": float(d.get("default_samplerate", TARGET_SR)),
                })
        return devices
    except Exception as exc:
        log.warning("Device enumeration failed: %s", exc)
        return []


class Recorder:
    """Thread-safe microphone recorder with level metering and hard limits."""

    def __init__(self, sample_rate: int = TARGET_SR, device: str | int | None = None,
                 max_seconds: int = 7200,
                 on_level: Callable[[float], None] | None = None,
                 on_error: Callable[[Exception], None] | None = None):
        self.sample_rate = int(sample_rate)
        self.device = device
        self.max_seconds = int(max_seconds)
        self.on_level = on_level
        self.on_error = on_error
        self._chunks: list[np.ndarray] = []
        # O(1) running total of appended samples.  Recomputing with
        # ``sum(len(c) for c in self._chunks)`` on every audio callback turns a
        # 2-hour recording (~110k blocks) into O(n^2) work inside the PortAudio
        # thread, which can starve the callback and drop frames.
        self._total_samples: int = 0
        self._lock = threading.Lock()
        self._stream = None
        self._started_at = 0.0
        self._level = 0.0
        self._error: Exception | None = None
        self._recording = False
        self._limit_reached = False
        self._status_reported = False

    @property
    def recording(self) -> bool:
        return self._recording

    @property
    def duration(self) -> float:
        return (time.monotonic() - self._started_at) if self._recording else self._file_duration()

    def _file_duration(self) -> float:
        with self._lock:
            n = self._total_samples
        return n / self.sample_rate

    @property
    def level(self) -> float:
        return self._level

    @property
    def error(self) -> Exception | None:
        return self._error

    @property
    def limit_reached(self) -> bool:
        return self._limit_reached

    def _callback(self, indata, frames, time_info, status):  # noqa: ANN001
        if status and not self._status_reported:
            self._status_reported = True
            self._error = RuntimeError(str(status))
            if self.on_error:
                try:
                    self.on_error(self._error)
                except Exception:
                    pass
        x = np.asarray(indata, dtype="float32")
        if x.ndim == 2:
            x = x.mean(axis=1)
        x = np.ascontiguousarray(x, dtype="float32")
        with self._lock:
            self._chunks.append(x.copy())
            self._total_samples += len(x)
            total = self._total_samples
        rms = float(np.sqrt(np.mean(x ** 2))) if x.size else 0.0
        self._level = min(1.0, rms * 4.0)
        if self.on_level:
            try:
                self.on_level(self._level)
            except Exception:
                pass
        if total / self.sample_rate >= self.max_seconds:
            # Never raise an arbitrary exception inside a PortAudio callback:
            # it is swallowed by the audio thread and the stream keeps running.
            # CallbackStop is the documented way to end the stream cleanly.
            self._limit_reached = True
            import sounddevice as sd
            raise sd.CallbackStop()

    def start(self) -> None:
        if self._recording:
            raise RecordingError("已经在录音中")
        import sounddevice as sd
        self._chunks = []
        self._total_samples = 0
        self._error = None
        self._level = 0.0
        self._limit_reached = False
        self._status_reported = False
        dev = None
        if self.device not in (None, ""):
            try:
                dev = int(self.device)
            except (TypeError, ValueError):
                dev = self.device
        try:
            self._stream = sd.InputStream(
                samplerate=self.sample_rate, channels=1, dtype="float32",
                device=dev, blocksize=1024, callback=self._callback,
            )
            self._stream.start()
        except Exception as exc:
            self._stream = None
            raise RecordingError(
                "无法启动录音，请检查麦克风连接与系统录音权限",
                detail=f"{type(exc).__name__}: {exc}", cause=exc) from exc
        self._started_at = time.monotonic()
        self._recording = True
        log.info("Recording started (device=%s, sr=%s)", dev, self.sample_rate)

    def stop(self) -> AudioData:
        """Stop and return recorded audio; always releases the stream."""
        if not self._recording and not self._chunks:
            raise RecordingError("没有可保存的录音")
        stream, self._stream = self._stream, None
        self._recording = False
        try:
            if stream is not None:
                stream.stop()
                stream.close()
        except Exception as exc:
            log.warning("Closing stream failed: %s", exc)
        with self._lock:
            x = np.concatenate(self._chunks) if self._chunks else np.zeros(0, dtype="float32")
            self._chunks = []
            self._total_samples = 0
        if x.size == 0:
            raise RecordingError("录音为空，请确认麦克风有输入")
        if self._limit_reached:
            log.warning("Recording reached the %ss limit", self.max_seconds)
        if x.size / self.sample_rate > self.max_seconds:
            x = x[: int(self.max_seconds * self.sample_rate)]
            log.warning("Recording truncated to %ss", self.max_seconds)
        return AudioData(normalize(x, self.sample_rate), TARGET_SR, "microphone")

    def cancel(self) -> None:
        stream, self._stream = self._stream, None
        self._recording = False
        try:
            if stream is not None:
                stream.stop()
                stream.close()
        except Exception:
            pass
        with self._lock:
            self._chunks = []
            self._total_samples = 0


# --------------------------------------------------------------------------- #
# Voice activity detection / segmentation
# --------------------------------------------------------------------------- #
def energy_vad_segments(x: np.ndarray, *, frame_ms: int = 20,
                        min_speech: float = 0.25, min_silence: float = 0.35,
                        threshold: float = 0.5) -> list[tuple[int, int]]:
    """Adaptive energy VAD with hysteresis. Returns (start_sample, end_sample)."""
    sr = TARGET_SR
    hop = max(1, int(sr * frame_ms / 1000))
    if x.size < hop:
        return []
    n = len(x) // hop
    frames = x[: n * hop].reshape(n, hop)
    rms = np.sqrt(np.mean(frames ** 2, axis=1))
    # noise floor = 10th percentile, plus a relative adaptive threshold
    floor = float(np.percentile(rms, 10))
    peak = float(np.percentile(rms, 90))
    hi = max(floor * 3.0, (floor + peak) * (0.25 + 0.35 * threshold), 1e-4)
    lo = hi * 0.6
    active = rms > hi

    # hysteresis: start on hi, keep going until below lo
    voiced = np.zeros(n, dtype=bool)
    inside = False
    for i, v in enumerate(active):
        if not inside and v:
            inside = True
        elif inside and rms[i] < lo:
            inside = False
        voiced[i] = inside

    min_on = max(1, int(min_speech * 1000 / frame_ms))
    min_off = max(1, int(min_silence * 1000 / frame_ms))
    segments: list[tuple[int, int]] = []
    i = 0
    while i < n:
        if not voiced[i]:
            i += 1
            continue
        start = i
        last = i
        gap = 0
        while i < n:
            if voiced[i]:
                last = i
                gap = 0
            else:
                gap += 1
                if gap >= min_off:
                    break
            i += 1
        end = min(n, last + 1)
        if end - start >= min_on:
            segments.append((start * hop, end * hop))
        i = max(i, last + 1)
    return segments


_SILERO_CACHE: dict[tuple[float, float], object] = {}
_SILERO_LOCK = threading.Lock()


def _get_silero_vad(threshold: float, max_speech_duration: float):
    """Create (once) and cache a Silero VAD model keyed by its parameters.

    Guarded by a lock: two transcription threads hitting the cache cold at the
    same time must not both load the ONNX VAD model and leak one instance.
    """
    key = (round(float(threshold), 3), round(float(max_speech_duration), 3))
    with _SILERO_LOCK:
        cached = _SILERO_CACHE.get(key)
        if cached is not None:
            return cached
        model = find_model_file("vad/silero_vad.onnx")
        if model is None:
            return None
        import sherpa_onnx
        cfg = sherpa_onnx.VadModelConfig(
            silero_vad=sherpa_onnx.SileroVadModelConfig(
                model=str(model), threshold=float(threshold),
                min_silence_duration=0.35, min_speech_duration=0.25,
                window_size=512, max_speech_duration=float(max_speech_duration),
            ),
            sample_rate=TARGET_SR, num_threads=1,
        )
        vad = sherpa_onnx.VadModel.create(cfg)
        _SILERO_CACHE[key] = vad
        return vad


def silero_vad_segments(x: np.ndarray, threshold: float = 0.5,
                        max_speech_duration: float = 20.0) -> list[tuple[int, int]] | None:
    """Neural VAD via the bundled silero_vad.onnx. Returns None if unavailable."""
    try:
        vad = _get_silero_vad(threshold, max_speech_duration)
        if vad is None:
            return None
        # window_size is a method in current sherpa-onnx (was an attribute in
        # older releases); calling it is required, otherwise int(method) raised
        # and this whole neural VAD silently fell back to energy VAD forever.
        win_attr = vad.window_size
        win = int(win_attr() if callable(win_attr) else win_attr)
        n = len(x) // win
        flags = []
        for i in range(n):
            chunk = np.ascontiguousarray(x[i * win:(i + 1) * win], dtype="float32")
            flags.append(bool(vad.is_speech(chunk)))
        if not any(flags):
            return []
        segments = []
        i = 0
        while i < n:
            if not flags[i]:
                i += 1
                continue
            start = i
            while i < n and flags[i]:
                i += 1
            segments.append((start * win, min(len(x), i * win)))
        return segments
    except Exception as exc:
        log.warning("Silero VAD unavailable (%s); using energy VAD", exc)
        return None


def segment_audio(x: np.ndarray, *, use_vad: bool = True,
                  max_segment_seconds: float = 25.0,
                  min_segment_seconds: float = 0.30,
                  vad_threshold: float = 0.5) -> list[AudioSegment]:
    """Split audio into engine-friendly chunks with timestamps."""
    x = np.ascontiguousarray(x, dtype="float32")
    total = len(x) / TARGET_SR
    if total <= 0:
        return []
    if not use_vad or total <= max_segment_seconds:
        return [AudioSegment(0.0, total, x)]

    bounds = silero_vad_segments(x, threshold=vad_threshold,
                                 max_speech_duration=max_segment_seconds)
    if bounds is None:
        bounds = energy_vad_segments(x, threshold=vad_threshold)
    if not bounds:
        # No speech detected: still try once so quiet-but-valid audio is not lost.
        return [AudioSegment(0.0, total, x)]

    max_len = int(max_segment_seconds * TARGET_SR)
    min_len = int(min_segment_seconds * TARGET_SR)
    merged: list[list[int]] = []
    for start, end in bounds:
        if merged and start - merged[-1][1] < int(0.25 * TARGET_SR):
            merged[-1][1] = end
        else:
            merged.append([start, end])
    # Split over-long merged regions into <= max_segment_seconds pieces.
    pieces: list[list[int]] = []
    for start, end in merged:
        while end - start > max_len:
            pieces.append([start, start + max_len])
            start += max_len
        pieces.append([start, end])

    # Short VAD pieces carry real speech.  Dropping them silently created
    # holes in the middle of the timeline (the old tail fix only covered the
    # end).  Absorb them into a neighbour instead, keeping max_len bounded.
    kept: list[list[int]] = []
    for start, end in pieces:
        if end - start >= min_len:
            kept.append([start, end])
        elif kept and start - kept[-1][0] <= max_len:
            kept[-1][1] = end
        else:
            kept.append([start, end])
    if len(kept) > 1 and kept[0][1] - kept[0][0] < min_len:
        kept[1][0] = kept[0][0]
        kept.pop(0)
    if not kept:
        kept = [[0, len(x)]]
    out: list[AudioSegment] = []
    for start, end in kept:
        out.append(AudioSegment(start / TARGET_SR, end / TARGET_SR,
                                np.ascontiguousarray(x[start:end])))
    # Guarantee full coverage of the timeline (no gap swallowing trailing audio).
    if out[-1].end < total - 0.05:
        tail_start = min(len(x), int(out[-1].end * TARGET_SR))
        out.append(AudioSegment(tail_start / TARGET_SR, total,
                                np.ascontiguousarray(x[tail_start:])))
    return out


def iter_audio_segments(x: np.ndarray, **kwargs) -> Iterator[AudioSegment]:
    yield from segment_audio(x, **kwargs)

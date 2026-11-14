"""Download and assemble the offline ASR model bundle.

Run once to build `models/` from the official upstream releases::

    python scripts/download_models.py --all
    python scripts/download_models.py --light          # SenseVoice + Paraformer only
    python scripts/download_models.py --verify         # SHA-256 check of existing files

Sources (all Apache-2.0 / MIT licensed upstream artefacts):
  * k2-fsa/sherpa-onnx release "asr-models"
  * alphacephei.com Vosk models (not used by default, kept for reference)

The script is idempotent, resumes interrupted downloads, and writes
``models/manifest.json`` containing sizes and SHA-256 hashes that the app
uses to detect truncated files.
"""
from __future__ import annotations

import argparse
import hashlib
import shutil
import sys
import tarfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

MODELS = ROOT / "models"
CACHE = MODELS / "_downloads"
RELEASE = "https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models"

# archive filename -> (url, {member path: destination relative path})
SOURCES = {
    "sensevoice": (
        f"{RELEASE}/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-int8-2024-07-17.tar.bz2",
        {
            "sherpa-onnx-sense-voice-zh-en-ja-ko-yue-int8-2024-07-17/model.int8.onnx":
                "sensevoice/model.int8.onnx",
            "sherpa-onnx-sense-voice-zh-en-ja-ko-yue-int8-2024-07-17/tokens.txt":
                "sensevoice/tokens.txt",
            "sherpa-onnx-sense-voice-zh-en-ja-ko-yue-int8-2024-07-17/LICENSE":
                "sensevoice/LICENSE",
        },
    ),
    "paraformer": (
        f"{RELEASE}/sherpa-onnx-paraformer-zh-small-2024-03-09.tar.bz2",
        {
            "sherpa-onnx-paraformer-zh-small-2024-03-09/model.int8.onnx":
                "paraformer/model.int8.onnx",
            "sherpa-onnx-paraformer-zh-small-2024-03-09/tokens.txt":
                "paraformer/tokens.txt",
        },
    ),
    "qwen3": (
        f"{RELEASE}/sherpa-onnx-qwen3-asr-0.6B-int8-2026-03-25.tar.bz2",
        {
            "sherpa-onnx-qwen3-asr-0.6B-int8-2026-03-25/conv_frontend.onnx":
                "qwen3/conv_frontend.onnx",
            "sherpa-onnx-qwen3-asr-0.6B-int8-2026-03-25/encoder.int8.onnx":
                "qwen3/encoder.int8.onnx",
            "sherpa-onnx-qwen3-asr-0.6B-int8-2026-03-25/decoder.int8.onnx":
                "qwen3/decoder.int8.onnx",
            "sherpa-onnx-qwen3-asr-0.6B-int8-2026-03-25/tokenizer/vocab.json":
                "qwen3/tokenizer/vocab.json",
            "sherpa-onnx-qwen3-asr-0.6B-int8-2026-03-25/tokenizer/merges.txt":
                "qwen3/tokenizer/merges.txt",
            "sherpa-onnx-qwen3-asr-0.6B-int8-2026-03-25/tokenizer/tokenizer_config.json":
                "qwen3/tokenizer/tokenizer_config.json",
        },
    ),
}

VAD_URL = f"{RELEASE}/silero_vad.onnx"
VAD_DEST = "vad/silero_vad.onnx"


def download(url: str, dest: Path, *, retries: int = 3) -> Path:
    import requests
    if dest.is_file() and dest.stat().st_size > 1024:
        print(f"  cached: {dest.name} ({dest.stat().st_size / 1048576:.0f} MB)")
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    last = None
    for attempt in range(1, retries + 1):
        try:
            with requests.get(url, stream=True, timeout=(20, 120)) as r:
                r.raise_for_status()
                tmp = dest.with_suffix(dest.suffix + ".part")
                mode = "ab" if tmp.exists() else "wb"
                headers = {"Range": f"bytes-{tmp.stat().st_size}="} if mode == "ab" else {}
                if headers:
                    r.close()
                    r2 = requests.get(url, stream=True, headers=headers, timeout=(20, 120))
                    r = r2
                done = tmp.stat().st_size if mode == "ab" else 0
                total = int(r.headers.get("Content-Length", 0)) + done
                with open(tmp, mode) as f:
                    for chunk in r.iter_content(1024 * 1024):
                        if chunk:
                            f.write(chunk)
                            done += len(chunk)
                            if total:
                                print(f"\r  {dest.name}: {done / 1048576:.0f}/{total / 1048576:.0f} MB",
                                      end="", flush=True)
                print()
                tmp.replace(dest)
                return dest
        except Exception as exc:
            last = exc
            print(f"  attempt {attempt} failed: {exc}")
            time.sleep(2 * attempt)
    raise RuntimeError(f"download failed: {url}: {last}")


def extract(archive: Path, mapping: dict[str, str]) -> None:
    wanted = set(mapping)
    found = set()
    with tarfile.open(archive, "r:bz2") as tf:
        for member in tf:
            if member.name in wanted:
                dst = MODELS / mapping[member.name]
                dst.parent.mkdir(parents=True, exist_ok=True)
                with tf.extractfile(member) as src, open(dst, "wb") as out:
                    shutil.copyfileobj(src, out, length=1024 * 1024)
                print(f"  -> {dst.relative_to(MODELS)} ({dst.stat().st_size / 1048576:.1f} MB)")
                found.add(member.name)
    missing = wanted - found
    if missing:
        raise RuntimeError(f"archive {archive.name} missing members: {sorted(missing)}")


def build_manifest() -> None:
    from voxscribe.core.integrity import build_manifest as _build
    data = _build(MODELS)
    print(f"manifest.json written with {len(data['files'])} entries")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--all", action="store_true", help="下载全部引擎（含 Qwen3，约 1.2 GB）")
    ap.add_argument("--light", action="store_true", help="仅下载 SenseVoice + Paraformer（约 310 MB）")
    ap.add_argument("--only", nargs="*", choices=list(SOURCES), help="下载指定引擎")
    ap.add_argument("--verify", action="store_true", help="只做完整性校验")
    args = ap.parse_args()

    if args.verify:
        from voxscribe.core.integrity import verify_full
        issues = verify_full()
        if issues:
            for i in issues:
                print(f"FAIL {i.path}: {i.problem}")
            return 1
        print("All model files verified (SHA-256 OK)")
        return 0

    keys = list(args.only) if args.only else (list(SOURCES) if args.all else list(SOURCES)[:2])
    if not keys:
        keys = list(SOURCES)[:2]
    CACHE.mkdir(parents=True, exist_ok=True)

    if not (MODELS / VAD_DEST).is_file():
        print("Downloading silero VAD…")
        vad_tmp = CACHE / "silero_vad.onnx"
        download(VAD_URL, vad_tmp)
        (MODELS / "vad").mkdir(parents=True, exist_ok=True)
        shutil.copy2(vad_tmp, MODELS / VAD_DEST)

    for key in keys:
        url, mapping = SOURCES[key]
        targets = [MODELS / p for p in mapping.values()]
        if all(p.is_file() and p.stat().st_size > 0 for p in targets):
            print(f"{key}: already present, skipped")
            continue
        print(f"Downloading {key} …")
        archive = CACHE / url.rsplit("/", 1)[-1]
        download(url, archive)
        extract(archive, mapping)
    build_manifest()
    print("Done. Model bundle is ready at", MODELS)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

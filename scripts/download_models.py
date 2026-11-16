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
import re
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


def resume_request(part_size: int) -> tuple[dict[str, str], str]:
    """Return (headers, file_mode) for a resumable download.

    HTTP Range uses ``bytes=<start>-`` (RFC 9110).  A malformed header is
    silently ignored by servers, which then send the whole file; appending
    that to an existing .part corrupts the model.  With nothing to resume,
    download from scratch in ``wb`` mode.
    """
    if part_size > 0:
        return {"Range": f"bytes={part_size}-"}, "ab"
    return {}, "wb"


def resume_is_aligned(response, part_size: int) -> bool:
    """A 206 response must actually start where our .part file ends.

    Some proxies reply 206 with ``Content-Range: bytes 0-...``; appending
    that body duplicates the whole file and silently corrupts the model.
    """
    if part_size <= 0:
        return True
    header = response.headers.get("Content-Range", "")
    match = re.match(r"bytes\s+(\d+)-", header)
    return match is None or int(match.group(1)) == part_size


def download(url: str, dest: Path, *, retries: int = 3) -> Path:
    import requests
    if dest.is_file() and dest.stat().st_size > 1024:
        print(f"  cached: {dest.name} ({dest.stat().st_size / 1048576:.0f} MB)")
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    last = None
    for attempt in range(1, retries + 1):
        try:
            part_size = tmp.stat().st_size if tmp.is_file() else 0
            headers, mode = resume_request(part_size)
            with requests.get(url, stream=True, headers=headers,
                              timeout=(20, 120)) as r:
                r.raise_for_status()
                # Only append when the server honoured the Range request.
                # A 200 (full body) means we must overwrite the .part file.
                if mode == "ab" and (
                        r.status_code != 206 or not resume_is_aligned(r, part_size)):
                    mode = "wb"
                    part_size = 0
                done = part_size
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
            if member.name not in wanted:
                continue
            # Only regular files can be copied.  A symlink/dir entry matching a
            # wanted name makes extractfile() raise (or follow an arbitrary
            # link target), aborting the whole model install.
            if not member.isfile():
                # Treat as handled so the final "missing members" check does
                # not fail on a normal archive that carries metadata entries.
                found.add(member.name)
                continue
            dst = (MODELS / mapping[member.name]).resolve()
            # Defence in depth: never write outside the models directory even
            # if a mapping entry is later edited to an absolute/traversal path.
            if MODELS.resolve() not in dst.parents:
                raise RuntimeError(f"unsafe extraction target: {dst}")
            dst.parent.mkdir(parents=True, exist_ok=True)
            src = tf.extractfile(member)
            if src is None:
                continue
            with src, open(dst, "wb") as out:
                shutil.copyfileobj(src, out, length=1024 * 1024)
            print(f"  -> {dst.relative_to(MODELS.resolve())} "
                  f"({dst.stat().st_size / 1048576:.1f} MB)")
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
    if sum(map(bool, (args.all, args.light, args.only is not None, args.verify))) > 1:
        print("ERROR: --all / --light / --only / --verify are mutually exclusive")
        return 2

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

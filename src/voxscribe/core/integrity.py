"""Model integrity: fast size checks at runtime, full SHA-256 on demand.

A truncated 800 MB ONNX file is the most common cause of an unexplained ASR
startup crash after a partial download. We ship a manifest with sizes/hashes;
startup verifies sizes (milliseconds), and `--verify-models` verifies hashes.
"""
from __future__ import annotations

import fnmatch
import hashlib
import json
import logging
import math
import os
from dataclasses import dataclass
from pathlib import Path

from .paths import find_model_file, models_dir

log = logging.getLogger("voxscribe.integrity")
MANIFEST_NAME = "manifest.json"
CHUNK = 1024 * 1024


def _as_int(value, default: int = 0) -> int:
    """Size metadata from a hand-edited manifest must not crash verification.

    A JSON ``1e999`` parses to ``inf``; int(inf) raises OverflowError and
    would abort startup/self-test instead of reporting an integrity issue.
    """
    try:
        f = float(value)
        return int(f) if math.isfinite(f) else default
    except (TypeError, ValueError, OverflowError):
        return default


@dataclass
class IntegrityIssue:
    path: str
    problem: str


def manifest_path() -> Path:
    return models_dir() / MANIFEST_NAME


def load_manifest() -> dict:
    p = manifest_path()
    if not p.is_file():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return {}
        files = data.get("files", {})
        # A hand-corrupted manifest may declare "files" as a list/str; treat
        # any non-mapping value as "no integrity data" instead of letting
        # downstream .items()/.get() calls blow up.
        return files if isinstance(files, dict) else {}
    except Exception as exc:
        log.warning("Cannot read model manifest: %s", exc)
        return {}


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            block = f.read(CHUNK)
            if not block:
                break
            h.update(block)
    return h.hexdigest()


def verify_quick(manifest: dict | None = None) -> list[IntegrityIssue]:
    """Check existence + exact byte size for every manifest entry (fast).

    ``manifest`` can be supplied by callers (e.g. verify_full) that already
    loaded it, avoiding a second disk read and a race between two reads.
    """
    issues: list[IntegrityIssue] = []
    entries = load_manifest() if manifest is None else manifest
    for rel, meta in entries.items():
        p = find_model_file(rel)
        if p is None:
            issues.append(IntegrityIssue(rel, "文件缺失"))
            continue
        if not isinstance(meta, dict):
            continue
        expected = _as_int(meta.get("size", 0), 0)
        try:
            actual = p.stat().st_size  # single stat, reuse in message
        except OSError as exc:
            # TOCTOU: the file may vanish or lose permission between
            # find_model_file() and stat(); report an issue, never crash.
            issues.append(IntegrityIssue(rel, f"无法读取文件大小：{exc}"))
            continue
        if expected and actual != expected:
            issues.append(IntegrityIssue(
                rel, f"大小不符：{actual} != {expected}（文件可能被截断）"))
    return issues


def verify_full() -> list[IntegrityIssue]:
    manifest = load_manifest()
    issues = verify_quick(manifest)
    quick_bad = {i.path for i in issues}
    for rel, meta in manifest.items():
        if not isinstance(meta, dict):
            continue
        if rel in quick_bad or not meta.get("sha256"):
            continue
        p = find_model_file(rel)
        if p and sha256(p) != meta["sha256"]:
            issues.append(IntegrityIssue(rel, "SHA-256 校验失败"))
    return issues


# Transient files left behind by interrupted downloads or by our own atomic
# writers must never become manifest entries: doing so would make a freshly
# generated manifest report "corruption" for files that are not real models.
DEFAULT_SKIP_PATTERNS = (
    "*.part", "*.tmp", "*.bad", "_downloads/*", "*/_downloads/*",
)


def build_manifest(models_root: Path, *, skip_patterns=DEFAULT_SKIP_PATTERNS) -> dict:
    """Generate sizes + SHA-256 for all model assets in a directory tree.

    ``skip_patterns`` are fnmatch globs applied to both the file name and its
    POSIX-style relative path, so transient download artifacts are excluded.
    """
    files: dict[str, dict] = {}
    for p in sorted(models_root.rglob("*")):
        if not p.is_file() or p.name == MANIFEST_NAME:
            continue
        rel = p.relative_to(models_root).as_posix()
        if any(fnmatch.fnmatch(rel, pat) or fnmatch.fnmatch(p.name, pat)
               for pat in skip_patterns):
            continue
        files[rel] = {"size": p.stat().st_size, "sha256": sha256(p)}
    data = {
        "generator": "VoxScribe scripts/download_models.py",
        "files": files,
    }
    (models_root / MANIFEST_NAME).write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return data


def summary() -> str:
    issues = verify_quick()
    if not issues:
        return "模型完整性检查通过"
    return "；".join(f"{i.path}: {i.problem}" for i in issues[:5])

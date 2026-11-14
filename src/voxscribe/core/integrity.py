"""Model integrity: fast size checks at runtime, full SHA-256 on demand.

A truncated 800 MB ONNX file is the most common cause of an unexplained ASR
startup crash after a partial download. We ship a manifest with sizes/hashes;
startup verifies sizes (milliseconds), and `--verify-models` verifies hashes.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path

from .paths import find_model_file, models_dir

log = logging.getLogger("voxscribe.integrity")
MANIFEST_NAME = "manifest.json"
CHUNK = 1024 * 1024


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
        return data.get("files", {}) if isinstance(data, dict) else {}
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


def verify_quick() -> list[IntegrityIssue]:
    """Check existence + exact byte size for every manifest entry (fast)."""
    issues: list[IntegrityIssue] = []
    for rel, meta in load_manifest().items():
        p = find_model_file(rel)
        if p is None:
            issues.append(IntegrityIssue(rel, "文件缺失"))
            continue
        expected = int(meta.get("size", 0))
        if expected and p.stat().st_size != expected:
            issues.append(IntegrityIssue(
                rel, f"大小不符：{p.stat().st_size} != {expected}（文件可能被截断）"))
    return issues


def verify_full() -> list[IntegrityIssue]:
    issues = verify_quick()
    quick_bad = {i.path for i in issues}
    for rel, meta in load_manifest().items():
        if rel in quick_bad or not meta.get("sha256"):
            continue
        p = find_model_file(rel)
        if p and sha256(p) != meta["sha256"]:
            issues.append(IntegrityIssue(rel, "SHA-256 校验失败"))
    return issues


def build_manifest(models_root: Path, *, skip_patterns=("*.onnx", "*.txt", "*.json", "LICENSE")) -> dict:
    """Generate sizes + SHA-256 for all model assets in a directory tree."""
    files: dict[str, dict] = {}
    for p in sorted(models_root.rglob("*")):
        if not p.is_file() or p.name == MANIFEST_NAME:
            continue
        rel = p.relative_to(models_root).as_posix()
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

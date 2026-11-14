"""Shared pytest fixtures."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

FIXTURES = Path(__file__).resolve().parent / "fixtures"


@pytest.fixture(scope="session")
def fixtures() -> Path:
    return FIXTURES


@pytest.fixture(scope="session")
def manifest() -> dict:
    data = json.loads((FIXTURES / "manifest.json").read_text(encoding="utf-8"))
    return {m["id"]: m for m in data}


@pytest.fixture(scope="session")
def models_root() -> Path | None:
    """Prefer the repo models dir; allow an external one via env var."""
    import os
    env = os.environ.get("VOXSCRIBE_MODELS")
    if env and Path(env).is_dir():
        return Path(env)
    p = ROOT / "models"
    return p if p.is_dir() and (p / "sensevoice" / "model.int8.onnx").is_file() else None


@pytest.fixture
def tmp_settings(tmp_path, monkeypatch):
    from voxscribe.core.config import SettingsStore
    store = SettingsStore(tmp_path / "settings.json")
    store.load()
    monkeypatch.setattr("voxscribe.core.config._STORE", store)
    return store

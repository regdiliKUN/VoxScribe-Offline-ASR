"""Config and history tests (iteration round 6 and later rounds)."""
from __future__ import annotations

import json
import sqlite3

import pytest

from voxscribe.core.config import Settings, SettingsStore
from voxscribe.core.history import HistoryDB
from voxscribe.core.transcriber import TranscriptResult, TranscriptSegment


def test_default_settings_are_sane():
    s = Settings()
    assert s.engine == "auto" and s.sample_rate == 16000
    assert s.export_encoding == "utf-8-sig"
    assert s.max_record_seconds == 7200


def test_save_and_reload(tmp_path):
    p = tmp_path / "settings.json"
    a = SettingsStore(p)
    a.update(engine="paraformer", threads=3, include_timestamps=True)
    b = SettingsStore(p)
    b.load()
    assert b.data.engine == "paraformer"
    assert b.data.threads == 3 and b.data.include_timestamps


def test_atomic_save_leaves_no_temp(tmp_path):
    store = SettingsStore(tmp_path / "settings.json")
    store.load()
    store.save()
    assert not list(tmp_path.glob("settings-*.tmp"))


def test_corrupt_settings_are_quarantined_and_reset(tmp_path):
    p = tmp_path / "settings.json"
    p.write_text("{not valid json", encoding="utf-8")
    store = SettingsStore(p)
    s = store.load()
    assert s.engine == "auto"
    assert store.load_error
    assert p.with_suffix(".json.bad").is_file()


def test_unknown_keys_and_out_of_range_values_are_clamped(tmp_path):
    p = tmp_path / "settings.json"
    p.write_text(json.dumps({
        "engine": "nonsense", "threads": 999, "vad_threshold": 99,
        "export_encoding": "latin1", "unknown_future_key": 42,
    }), encoding="utf-8")
    s = SettingsStore(p).load()
    assert s.engine == "auto" and s.threads == 16
    assert s.vad_threshold == 0.95
    assert s.export_encoding == "utf-8-sig"


def test_recent_files_deduplicated_and_bounded(tmp_path):
    store = SettingsStore(tmp_path / "settings.json")
    store.load()
    for i in range(30):
        store.add_recent(f"f{i}.wav")
    store.add_recent("f0.wav")
    assert len(store.data.recent_files) == 20
    assert store.data.recent_files[0] == "f0.wav"


def _sample_result():
    return TranscriptResult(
        text="今天天气很好。", engine="sensevoice", source="录音.wav",
        duration=3.5, audio_path="C:/a.wav", warnings=["w"],
        segments=[TranscriptSegment(0, 3.5, "今天天气很好。")],
    )


def test_history_add_get_list_search_delete(tmp_path):
    db = HistoryDB(tmp_path / "h.sqlite3")
    rid = db.add(_sample_result())
    assert rid > 0 and db.count() == 1
    row = db.get(rid)
    assert row["text"] == "今天天气很好。"
    assert len(row["segments"]) == 1 and row["warnings"] == ["w"]
    assert db.list()[0]["id"] == rid
    assert db.search("天气")[0]["id"] == rid
    assert db.delete(rid) and db.count() == 0


def test_history_clear_and_pagination(tmp_path):
    db = HistoryDB(tmp_path / "h.sqlite3")
    for _ in range(5):
        db.add(_sample_result())
    assert len(db.list(limit=3)) == 3
    assert len(db.list(limit=3, offset=3)) == 2
    db.clear()
    assert db.count() == 0


def test_history_rebuilds_corrupt_database(tmp_path):
    p = tmp_path / "h.sqlite3"
    p.write_bytes(b"this is not a sqlite database" * 20)
    db = HistoryDB(p)
    assert db.count() == 0
    assert db.add(_sample_result()) > 0
    assert p.with_suffix(".sqlite3.bad").is_file()


def test_history_handles_unicode_and_quotes(tmp_path):
    db = HistoryDB(tmp_path / "h.sqlite3")
    r = _sample_result()
    r.text = "他说：'今天天气很好'，\"对吧\"？"
    rid = db.add(r)
    assert db.get(rid)["text"] == r.text


def test_engine_choices_match_registered_specs():
    """Round 20: the settings allow-list must not drift from the engine registry."""
    from voxscribe.core.config import VALID_ENGINES
    from voxscribe.engines.base import SPECS

    assert VALID_ENGINES[0] == "auto"
    assert tuple(VALID_ENGINES[1:]) == tuple(s.key for s in SPECS)


def test_qwen3_setting_survives_save_and_reload(tmp_path):
    """Round 20: Qwen3 used to be clamped back to 'auto' on every save."""
    p = tmp_path / "settings.json"
    SettingsStore(p).update(engine="qwen3")
    assert SettingsStore(p).load().engine == "qwen3"
    # Retired research candidates are rejected rather than silently leaking.
    p.write_text(json.dumps({"engine": "firered"}), encoding="utf-8")
    assert SettingsStore(p).load().engine == "auto"
    p.write_text(json.dumps({"engine": "vosk"}), encoding="utf-8")
    assert SettingsStore(p).load().engine == "auto"

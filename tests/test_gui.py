"""GUI smoke tests using Qt's offscreen platform."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from PySide6.QtWidgets import QApplication

from voxscribe.core.config import SettingsStore
from voxscribe.core.history import HistoryDB
from voxscribe.core.transcriber import TranscriptResult, TranscriptSegment
from voxscribe.ui.app import HistoryDialog, MainWindow, SettingsDialog
from voxscribe.ui.styles import stylesheet


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def win(qapp, tmp_settings):
    w = MainWindow()
    yield w
    w.close()


def test_main_window_constructs(win):
    assert win.windowTitle().startswith("VoxScribe")
    assert win.record_btn and win.transcribe_btn and win.text
    assert win.engine_combo.count() >= 2


def test_engine_combo_contains_auto_and_specs(win):
    keys = [win.engine_combo.itemData(i) for i in range(win.engine_combo.count())]
    assert "auto" in keys and "sensevoice" in keys


def test_set_valid_source_enables_transcribe(win, fixtures, monkeypatch):
    monkeypatch.setattr(win, "_show_error", lambda *a: None)
    win._set_source(str(fixtures / "zh_01_daily.wav"))
    assert win.transcribe_btn.isEnabled()
    assert "zh_01_daily.wav" in win.source_label.text()


def test_unsupported_format_is_rejected(win, tmp_path, monkeypatch):
    errors = []
    monkeypatch.setattr(win, "_show_error", lambda m, d="": errors.append(m))
    bad = tmp_path / "note.docx"
    bad.write_text("x")
    win._set_source(str(bad))
    assert errors and "不支持" in errors[0]
    assert not win.transcribe_btn.isEnabled()


def test_recording_write_failure_is_reported(win, monkeypatch):
    """Round 76: a full disk must show a message instead of escaping a Qt slot."""
    import numpy as np
    from types import SimpleNamespace
    from voxscribe.core.errors import AudioError

    class FakeRecorder:
        recording = False
        limit_reached = False

        def stop(self):
            return SimpleNamespace(samples=np.zeros(160, dtype="float32"), duration=0.01)

    win.recorder = FakeRecorder()
    errors = []
    monkeypatch.setattr(win, "_show_error", lambda m, d="": errors.append(m))

    def boom(*_a, **_kw):
        raise AudioError("disk full")

    monkeypatch.setattr("voxscribe.ui.app.audio.write_wav", boom)
    win._stop_record()
    assert errors and "录音保存失败" in errors[0]
    assert win.record_path in (None, "")


def test_render_result_with_and_without_timestamps(win):
    win.result = TranscriptResult(
        text="今天天气很好。我们一起去公园。",
        segments=[TranscriptSegment(0, 2.5, "今天天气很好。"),
                  TranscriptSegment(3, 6, "我们一起去公园。")],
        engine="sensevoice")
    win.ts_check.setChecked(False)
    win._render_result()
    assert win.text.toPlainText() == win.result.text
    win.ts_check.setChecked(True)
    assert "[00:00:00.000 --> 00:00:02.500]" in win.text.toPlainText()


def test_copy_text_puts_content_on_clipboard(win, qapp):
    win.text.setPlainText("复制测试内容")
    win.copy_text(silent=True)
    assert qapp.clipboard().text() == "复制测试内容"


def test_settings_dialog_saves(qapp, tmp_settings, monkeypatch):
    monkeypatch.setattr("voxscribe.ui.app.get_store", lambda: tmp_settings)
    from voxscribe.engines.manager import EngineManager
    dlg = SettingsDialog(tmp_settings, EngineManager())
    dlg.engine.setCurrentIndex(dlg.engine.findData("paraformer"))
    dlg.theme.setCurrentIndex(dlg.theme.findData("light"))
    dlg.accept()
    assert tmp_settings.data.engine == "paraformer"
    assert tmp_settings.data.theme == "light"


def test_history_dialog_lists_records(qapp, tmp_path):
    db = HistoryDB(tmp_path / "h.db")
    db.add(TranscriptResult(text="历史测试", engine="paraformer"))
    dlg = HistoryDialog(db)
    assert dlg.list.count() == 1
    dlg.list.setCurrentRow(0)
    dlg._show_selected()
    assert "历史测试" in dlg.detail.toPlainText()


def test_themes_differ_and_are_nonempty():
    assert stylesheet("dark") != stylesheet("light")
    assert "QPushButton#Primary" in stylesheet("dark")

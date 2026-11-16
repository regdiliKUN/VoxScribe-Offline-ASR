"""PySide6 desktop UI for VoxScribe."""
from __future__ import annotations

import logging
import os
import threading
import time
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, QThread, QTimer, Signal
from PySide6.QtGui import QAction, QIcon
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog,
    QFormLayout, QFrame, QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
    QMainWindow, QMenu, QMessageBox, QPlainTextEdit, QProgressBar, QPushButton,
    QSplitter, QVBoxLayout, QWidget,
)

from .. import __version__
from ..core import audio, export
from ..core.config import get_store
from ..core.errors import VoxScribeError
from ..core.history import HistoryDB
from ..core.paths import default_export_dir, icon_path, log_file, user_data_dir
from ..core.transcriber import (
    TranscriptionCancelled, TranscriptionPipeline, TranscriptResult,
)
from ..engines.base import SPECS
from ..engines.manager import EngineManager
from .styles import stylesheet

log = logging.getLogger("voxscribe.ui")

AUDIO_FILTER = ("音频/视频文件 (*.wav *.mp3 *.m4a *.flac *.ogg *.opus *.aac *.wma "
                "*.aiff *.mp4 *.mkv *.mov *.avi *.webm *.ts *.flv);;所有文件 (*.*)")


class TranscribeWorker(QThread):
    progress = Signal(str, int, int, str)
    succeeded = Signal(object)
    failed = Signal(str, str)
    cancelled = Signal()

    def __init__(self, pipeline: TranscriptionPipeline, path: str | None = None,
                 data: audio.AudioData | None = None, parent=None):
        super().__init__(parent)
        self.pipeline = pipeline
        self.path = path
        self.data = data
        self._cancel = threading.Event()

    def cancel(self):
        self._cancel.set()

    def run(self):
        try:
            if self.path:
                result = self.pipeline.transcribe_file(
                    self.path, progress=self._emit, cancel=self._cancel)
            else:
                result = self.pipeline.transcribe_audio(
                    self.data, progress=self._emit, cancel=self._cancel)
            self.succeeded.emit(result)
        except TranscriptionCancelled:
            self.cancelled.emit()
        except VoxScribeError as exc:
            self.failed.emit(str(exc), exc.detail)
        except Exception as exc:
            log.exception("Worker crashed")
            self.failed.emit("转写过程中出现未预期错误", f"{type(exc).__name__}: {exc}")

    def _emit(self, stage, cur, total, msg):
        self.progress.emit(stage, cur, total, msg)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.store = get_store()
        self.settings = self.store.data
        self.manager = EngineManager(
            threads=self.settings.threads, language=self.settings.language,
            use_itn=self.settings.use_itn)
        self.history = HistoryDB()
        self.recorder: audio.Recorder | None = None
        self.record_path: Path | None = None
        self.worker: TranscribeWorker | None = None
        self.result: TranscriptResult | None = None
        self.current_audio: str = ""

        self.setWindowTitle(f"VoxScribe {__version__} · 离线语音转文字")
        self.resize(1120, 720)
        self.setMinimumSize(900, 600)
        ico = icon_path()
        if ico:
            self.setWindowIcon(QIcon(str(ico)))
        self.setStyleSheet(stylesheet(self.settings.theme))
        self.setAcceptDrops(True)
        self._build_ui()
        self._refresh_status()

        self.ui_timer = QTimer(self)
        self.ui_timer.setInterval(80)
        self.ui_timer.timeout.connect(self._tick)
        self.ui_timer.start()

    # ------------------------------------------------------------------ UI
    def _build_ui(self):
        root = QWidget()
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(16, 14, 16, 10)
        outer.setSpacing(12)

        header = QHBoxLayout()
        titles = QVBoxLayout()
        t = QLabel("VoxScribe")
        t.setObjectName("Title")
        st = QLabel("100% 本地离线识别 · 音频不上传云端 · 支持录音/导入/导出")
        st.setObjectName("Subtitle")
        titles.addWidget(t)
        titles.addWidget(st)
        header.addLayout(titles)
        header.addStretch(1)
        self.engine_combo = QComboBox()
        self.engine_combo.setMinimumWidth(250)
        self._fill_engine_combo()
        self.engine_combo.currentIndexChanged.connect(self._on_engine_changed)
        header.addWidget(QLabel("识别引擎"))
        header.addWidget(self.engine_combo)
        outer.addLayout(header)

        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(self._build_left())
        splitter.addWidget(self._build_right())
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([340, 760])
        outer.addWidget(splitter, 1)

        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setVisible(False)
        outer.addWidget(self.progress)

        self.status = self.statusBar()
        self.status_label = QLabel("就绪")
        self.status.addWidget(self.status_label)
        self.status.addPermanentWidget(QLabel(f"日志：{log_file()}"))

        menu = self.menuBar().addMenu("文件")
        act_import = QAction("导入音频…", self)
        act_import.triggered.connect(self.import_audio)
        menu.addAction(act_import)
        act_folder = QAction("打开导出目录", self)
        act_folder.triggered.connect(self.open_export_folder)
        menu.addAction(act_folder)
        menu.addSeparator()
        act_exit = QAction("退出", self)
        act_exit.triggered.connect(self.close)
        menu.addAction(act_exit)
        menu2 = self.menuBar().addMenu("工具")
        for text, fn in (("历史记录", self.show_history), ("设置", self.show_settings),
                         ("创建/修复桌面快捷方式", self.recreate_shortcut),
                         ("关于", self.show_about)):
            a = QAction(text, self)
            a.triggered.connect(fn)
            menu2.addAction(a)

    def _card(self) -> tuple[QFrame, QVBoxLayout]:
        f = QFrame()
        f.setObjectName("Card")
        v = QVBoxLayout(f)
        v.setContentsMargins(16, 16, 16, 16)
        v.setSpacing(12)
        return f, v

    def _build_left(self) -> QWidget:
        card, v = self._card()
        v.addWidget(QLabel("① 获取音频"))

        self.device_combo = QComboBox()
        self.device_combo.addItem("系统默认设备", "")
        for d in audio.list_input_devices():
            self.device_combo.addItem(f"{d['name']}", str(d["index"]))
        v.addWidget(QLabel("麦克风"))
        v.addWidget(self.device_combo)

        self.timer_label = QLabel("00:00.0")
        self.timer_label.setObjectName("Timer")
        self.timer_label.setAlignment(Qt.AlignCenter)
        v.addWidget(self.timer_label)

        self.level = QProgressBar()
        self.level.setObjectName("Level")
        self.level.setRange(0, 100)
        self.level.setValue(0)
        self.level.setFormat("输入电平")
        v.addWidget(self.level)

        self.record_btn = QPushButton("●  开始录音")
        self.record_btn.setObjectName("Record")
        self.record_btn.setMinimumHeight(44)
        self.record_btn.clicked.connect(self.toggle_record)
        v.addWidget(self.record_btn)

        imp = QPushButton("导入音频文件…")
        imp.clicked.connect(self.import_audio)
        v.addWidget(imp)

        self.source_label = QLabel("尚未选择音频（也可把文件拖到窗口）")
        self.source_label.setObjectName("Hint")
        self.source_label.setWordWrap(True)
        v.addWidget(self.source_label)

        self.transcribe_btn = QPushButton("开始转写")
        self.transcribe_btn.setObjectName("Primary")
        self.transcribe_btn.setMinimumHeight(44)
        self.transcribe_btn.clicked.connect(self.start_transcription)
        self.transcribe_btn.setEnabled(False)
        v.addWidget(self.transcribe_btn)

        self.cancel_btn = QPushButton("取消")
        self.cancel_btn.clicked.connect(self.cancel_transcription)
        self.cancel_btn.setVisible(False)
        v.addWidget(self.cancel_btn)
        v.addStretch(1)
        return card

    def _build_right(self) -> QWidget:
        card, v = self._card()
        head = QHBoxLayout()
        head.addWidget(QLabel("② 识别结果"))
        self.ts_check = QCheckBox("显示时间戳")
        self.ts_check.setChecked(self.settings.include_timestamps)
        self.ts_check.stateChanged.connect(self._render_result)
        head.addStretch(1)
        head.addWidget(self.ts_check)
        v.addLayout(head)

        self.text = QPlainTextEdit()
        self.text.setPlaceholderText("识别结果会显示在这里。可全选复制，或导出为 TXT / SRT / JSON / Markdown。")
        self.text.setReadOnly(False)
        v.addWidget(self.text, 1)

        self.warnings_label = QLabel("")
        self.warnings_label.setObjectName("Hint")
        self.warnings_label.setWordWrap(True)
        v.addWidget(self.warnings_label)

        actions = QHBoxLayout()
        self.copy_btn = QPushButton("复制全文")
        self.copy_btn.clicked.connect(self.copy_text)
        actions.addWidget(self.copy_btn)
        self.export_btn = QPushButton("导出 ▾")
        self.export_btn.setObjectName("Primary")
        self.export_btn.clicked.connect(self.show_export_menu)
        actions.addWidget(self.export_btn)
        hist = QPushButton("历史")
        hist.clicked.connect(self.show_history)
        actions.addWidget(hist)
        sett = QPushButton("设置")
        sett.clicked.connect(self.show_settings)
        actions.addWidget(sett)
        clear = QPushButton("清空")
        clear.clicked.connect(self.clear_result)
        actions.addWidget(clear)
        actions.addStretch(1)
        v.addLayout(actions)
        return card

    def _fill_engine_combo(self):
        self.engine_combo.blockSignals(True)
        self.engine_combo.clear()
        self.engine_combo.addItem("自动（精度优先，失败自动降级）", "auto")
        available = self.manager.available_keys()
        for s in SPECS:
            suffix = "" if s.key in available else "（未安装）"
            self.engine_combo.addItem(s.display + suffix, s.key)
        idx = self.engine_combo.findData(self.settings.engine)
        self.engine_combo.setCurrentIndex(max(0, idx))
        self.engine_combo.blockSignals(False)

    # -------------------------------------------------------------- events
    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        urls = event.mimeData().urls()
        if urls:
            self._set_source(urls[0].toLocalFile())

    def _on_engine_changed(self):
        key = self.engine_combo.currentData()
        if key:
            self.store.update(engine=key)
            self.settings = self.store.data
            self._refresh_status()

    def _set_source(self, path: str):
        if not path or not Path(path).is_file():
            self._show_error("找不到该文件", path)
            return
        suffix = Path(path).suffix.lower()
        if suffix not in audio.SUPPORTED_SUFFIXES:
            self._show_error("不支持的文件格式", f"{suffix or '无后缀'}；{path}")
            return
        self.current_audio = path
        self.source_label.setText(f"当前文件：{Path(path).name}")
        self.transcribe_btn.setEnabled(True)
        self.store.add_recent(path)
        self.status_label.setText(f"已选择：{Path(path).name}")

    def import_audio(self):
        start = self.store.data.last_export_dir or str(default_export_dir())
        path, _ = QFileDialog.getOpenFileName(self, "选择音频文件", start, AUDIO_FILTER)
        if path:
            self._set_source(path)

    def toggle_record(self):
        if self.recorder and self.recorder.recording:
            self._stop_record()
        else:
            self._start_record()

    def _start_record(self):
        if self.worker and self.worker.isRunning():
            QMessageBox.information(self, "正在转写", "请等待当前转写完成或点击取消。")
            return
        try:
            dev = self.device_combo.currentData()
            self.recorder = audio.Recorder(
                sample_rate=16000, device=dev or None,
                max_seconds=self.settings.max_record_seconds,
                on_error=lambda e: log.warning("录音状态：%s", e))
            self.recorder.start()
        except VoxScribeError as exc:
            self._show_error(str(exc), exc.detail)
            self.recorder = None
            return
        self.record_btn.setText("■  停止录音")
        self.record_btn.setObjectName("Danger")
        self.record_btn.setStyleSheet(stylesheet(self.settings.theme))
        self.transcribe_btn.setEnabled(False)
        self.status_label.setText("正在录音…")

    def _stop_record(self):
        if not self.recorder:
            return
        try:
            data = self.recorder.stop()
        except VoxScribeError as exc:
            self._show_error(str(exc), exc.detail)
            return
        finally:
            self.record_btn.setText("●  开始录音")
            self.record_btn.setObjectName("Record")
            self.record_btn.setStyleSheet(stylesheet(self.settings.theme))
            limit = self.recorder.limit_reached
            self.recorder = None
        if limit:
            QMessageBox.information(self, "录音已达上限",
                                    "已达到最大录音时长，后续音频未保存。")
        rec_dir = user_data_dir() / "recordings"
        rec_dir.mkdir(parents=True, exist_ok=True)
        p = rec_dir / f"录音-{datetime.now():%Y%m%d-%H%M%S}.wav"
        try:
            audio.write_wav(p, data.samples)
        except (VoxScribeError, OSError) as exc:
            # A full/read-only disk must not escape a Qt slot as a raw
            # traceback; tell the user and keep the recording in memory.
            self._show_error("录音保存失败，请检查磁盘空间或保存目录权限。", str(exc))
            return
        self.record_path = p
        self._set_source(str(p))
        log.info("Recording saved: %s (%.2fs)", p, data.duration)
        self.start_transcription()

    def _tick(self):
        if self.recorder and self.recorder.recording:
            d = self.recorder.duration
            self.timer_label.setText(f"{int(d // 60):02d}:{d % 60:04.1f}")
            self.level.setValue(int(self.recorder.level * 100))

    # ---------------------------------------------------------- transcribe
    def _new_manager(self) -> EngineManager:
        s = self.store.data
        return EngineManager(threads=s.threads, language=s.language, use_itn=s.use_itn)

    def start_transcription(self):
        if self.worker and self.worker.isRunning():
            return
        if not self.current_audio:
            QMessageBox.information(self, "提示", "请先录音或导入音频文件。")
            return
        self.manager = self._new_manager()
        s = self.store.data
        pipeline = TranscriptionPipeline.from_settings(s, manager=self.manager)
        pipeline.engine = s.engine
        self.worker = TranscribeWorker(pipeline, path=self.current_audio)
        self.worker.progress.connect(self._on_progress)
        self.worker.succeeded.connect(self._on_success)
        self.worker.failed.connect(self._on_failure)
        self.worker.cancelled.connect(self._on_cancelled)
        self.progress.setVisible(True)
        self.progress.setValue(0)
        self.cancel_btn.setVisible(True)
        self.transcribe_btn.setEnabled(False)
        self.record_btn.setEnabled(False)
        self.worker.start()

    def _on_progress(self, stage, cur, total, msg):
        if stage == "done":
            self.progress.setValue(100)
        elif total:
            self.progress.setValue(min(99, int(cur * 100 / max(total, 1))))
        self.status_label.setText(msg)

    def _on_success(self, result: TranscriptResult):
        self.result = result
        try:
            self.history.add(result)
        except Exception as exc:
            log.warning("History write failed: %s", exc)
        self._render_result()
        self.warnings_label.setText("；".join(result.warnings))
        self.status_label.setText(
            f"完成 · 引擎 {result.engine} · {len(result.segments)} 段 · "
            f"时长 {result.duration:.1f}s")
        if self.store.data.auto_copy and result.text:
            self.copy_text(silent=True)
        self._finish_busy()

    def _on_failure(self, msg, detail):
        self._show_error(msg, detail)
        self.status_label.setText("转写失败")
        self._finish_busy()

    def _on_cancelled(self):
        self.status_label.setText("已取消")
        self._finish_busy()

    def _finish_busy(self):
        self.progress.setVisible(False)
        self.cancel_btn.setVisible(False)
        self.transcribe_btn.setEnabled(bool(self.current_audio))
        self.record_btn.setEnabled(True)

    def cancel_transcription(self):
        if self.worker:
            self.worker.cancel()
            self.status_label.setText("正在取消…")

    def _render_result(self):
        if not self.result:
            return
        if self.ts_check.isChecked() and self.result.segments:
            lines = [f"[{export.format_timestamp(s.start)} --> {export.format_timestamp(s.end)}] {s.text}"
                     for s in self.result.segments]
            self.text.setPlainText("\n".join(lines))
        else:
            self.text.setPlainText(self.result.text)

    def clear_result(self):
        self.result = None
        self.text.clear()
        self.warnings_label.clear()
        self.status_label.setText("已清空")

    # -------------------------------------------------------------- output
    def copy_text(self, silent: bool = False):
        text = self.text.toPlainText()
        if not text.strip():
            if not silent:
                QMessageBox.information(self, "提示", "当前没有可复制的文字。")
            return
        QApplication.clipboard().setText(text)
        self.status_label.setText("已复制到剪贴板")

    def show_export_menu(self):
        if not self.result or self.result.is_empty:
            QMessageBox.information(self, "提示", "请先完成一次识别。")
            return
        m = QMenu(self)
        for label, fmt in (("纯文本 (.txt)", "txt"), ("字幕 (.srt)", "srt"),
                           ("结构化数据 (.json)", "json"), ("Markdown (.md)", "md")):
            a = QAction(label, self)
            a.triggered.connect(lambda _checked=False, f=fmt: self.export_as(f))
            m.addAction(a)
        m.exec(self.export_btn.mapToGlobal(self.export_btn.rect().bottomLeft()))

    def export_as(self, fmt: str):
        if not self.result:
            return
        s = self.store.data
        start_dir = s.last_export_dir or str(default_export_dir())
        default = str(Path(start_dir) / export.default_filename(self.result, fmt))
        filters = {"txt": "文本文件 (*.txt)", "srt": "字幕文件 (*.srt)",
                   "json": "JSON (*.json)", "md": "Markdown (*.md)"}
        path, _ = QFileDialog.getSaveFileName(self, "导出识别结果", default, filters[fmt])
        if not path:
            return
        if not path.lower().endswith("." + fmt):
            path += "." + fmt
        try:
            out = export.export_result(
                self.result, path, fmt=fmt, encoding=s.export_encoding,
                include_timestamps=self.ts_check.isChecked())
            self.store.update(last_export_dir=str(Path(path).parent))
        except VoxScribeError as exc:
            self._show_error(str(exc), exc.detail)
            return
        self.status_label.setText(f"已导出：{out}")
        box = QMessageBox(self)
        box.setWindowTitle("导出成功")
        box.setText(f"已保存到：\n{out}")
        box.setIcon(QMessageBox.Information)
        open_btn = box.addButton("打开文件所在位置", QMessageBox.ActionRole)
        box.addButton("确定", QMessageBox.AcceptRole)
        box.exec()
        if box.clickedButton() == open_btn:
            self._reveal(out)

    def _reveal(self, path: Path):
        try:
            os.startfile(str(Path(path).parent))  # noqa: S606 - Windows shell reveal
        except Exception as exc:
            log.warning("Cannot open folder: %s", exc)

    def open_export_folder(self):
        self._reveal(Path(self.store.data.last_export_dir or default_export_dir()))

    # -------------------------------------------------------------- dialogs
    def show_history(self):
        dlg = HistoryDialog(self.history, self)
        dlg.exec()

    def show_settings(self):
        dlg = SettingsDialog(self.store, self.manager, self)
        if dlg.exec() == QDialog.Accepted:
            self.settings = self.store.data
            self.setStyleSheet(stylesheet(self.settings.theme))
            self.manager = self._new_manager()
            self._fill_engine_combo()
            self._refresh_status()

    def show_about(self):
        QMessageBox.about(
            self, "关于 VoxScribe",
            f"<h3>VoxScribe {__version__}</h3>"
            "<p>100% 本地离线语音转文字，音频与文本都不会上传。</p>"
            "<p>引擎：Qwen3-ASR 0.6B / SenseVoice-Small / Paraformer-small（sherpa-onnx）</p>"
            "<p>支持录音、导入音视频、复制、TXT/SRT/JSON/Markdown 导出、桌面快捷方式。</p>"
            f"<p>日志：{log_file()}</p>")

    def recreate_shortcut(self):
        from ..core.shortcut import create_shortcut
        try:
            r = create_shortcut(force=True)
            QMessageBox.information(self, "快捷方式",
                                    f"已创建桌面快捷方式：\n{r.path}\n目标：{r.target}")
        except VoxScribeError as exc:
            self._show_error(str(exc), exc.detail)

    def _refresh_status(self):
        keys = self.manager.available_keys()
        missing = self.manager.missing_summary()
        if keys:
            self.status_label.setText(
                f"可用引擎：{', '.join(keys)}"
                + (f" ｜ 未安装：{missing}" if missing else ""))
        else:
            self.status_label.setText("⚠ 未找到识别模型，请检查 models 目录")

    def _show_error(self, msg: str, detail: str = ""):
        log.error("UI error: %s | %s", msg, detail)
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Critical)
        box.setWindowTitle("VoxScribe")
        box.setText(msg)
        if detail:
            box.setDetailedText(detail)
        box.exec()

    def closeEvent(self, event):
        if self.worker and self.worker.isRunning():
            self.worker.cancel()
            self.worker.wait(3000)
        if self.recorder and self.recorder.recording:
            self.recorder.cancel()
        self.ui_timer.stop()
        super().closeEvent(event)


class SettingsDialog(QDialog):
    def __init__(self, store, manager: EngineManager, parent=None):
        super().__init__(parent)
        self.store = store
        self.manager = manager
        s = store.data
        self.setWindowTitle("设置")
        self.setMinimumWidth(460)
        self.setStyleSheet(stylesheet(s.theme))
        form = QFormLayout(self)
        form.setSpacing(10)

        self.engine = QComboBox()
        self.engine.addItem("自动（精度优先，失败自动降级）", "auto")
        for spec in SPECS:
            self.engine.addItem(spec.display, spec.key)
        self.engine.setCurrentIndex(max(0, self.engine.findData(s.engine)))
        form.addRow("识别引擎", self.engine)

        self.language = QComboBox()
        for k, label in (("auto", "自动"), ("zh", "中文"), ("en", "English"),
                         ("ja", "日本語"), ("ko", "한국어"), ("yue", "粤语")):
            self.language.addItem(label, k)
        self.language.setCurrentIndex(max(0, self.language.findData(s.language)))
        form.addRow("识别语言", self.language)

        self.theme = QComboBox()
        self.theme.addItem("深色", "dark")
        self.theme.addItem("浅色", "light")
        self.theme.setCurrentIndex(max(0, self.theme.findData(s.theme)))
        form.addRow("界面主题", self.theme)

        self.encoding = QComboBox()
        for k in export.ENCODINGS:
            self.encoding.addItem(k, k)
        self.encoding.setCurrentIndex(max(0, self.encoding.findData(s.export_encoding)))
        form.addRow("导出编码", self.encoding)

        self.vad = QCheckBox("长音频自动分段（推荐）")
        self.vad.setChecked(s.vad_enabled)
        form.addRow("", self.vad)
        self.itn = QCheckBox("数字/标点智能规整（ITN）")
        self.itn.setChecked(s.use_itn)
        form.addRow("", self.itn)
        self.timestamps = QCheckBox("默认显示时间戳")
        self.timestamps.setChecked(s.include_timestamps)
        form.addRow("", self.timestamps)
        self.auto_copy = QCheckBox("识别完成后自动复制")
        self.auto_copy.setChecked(s.auto_copy)
        form.addRow("", self.auto_copy)
        self.shortcut = QCheckBox("启动时检查并创建桌面快捷方式")
        self.shortcut.setChecked(s.auto_shortcut)
        form.addRow("", self.shortcut)

        note = QLabel("修改后点击「保存」生效；模型文件位于程序目录下的 models 文件夹。")
        note.setObjectName("Hint")
        note.setWordWrap(True)
        form.addRow(note)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def accept(self):
        self.store.update(
            engine=self.engine.currentData(), language=self.language.currentData(),
            theme=self.theme.currentData(), export_encoding=self.encoding.currentData(),
            vad_enabled=self.vad.isChecked(), use_itn=self.itn.isChecked(),
            include_timestamps=self.timestamps.isChecked(),
            auto_copy=self.auto_copy.isChecked(), auto_shortcut=self.shortcut.isChecked(),
        )
        super().accept()


class HistoryDialog(QDialog):
    def __init__(self, db: HistoryDB, parent=None):
        super().__init__(parent)
        self.db = db
        self.setWindowTitle("历史记录")
        self.resize(720, 480)
        self.setStyleSheet(stylesheet(get_store().data.theme))
        v = QVBoxLayout(self)
        row = QHBoxLayout()
        self.list = QListWidget()
        self.detail = QPlainTextEdit()
        self.detail.setReadOnly(True)
        row.addWidget(self.list, 1)
        row.addWidget(self.detail, 2)
        v.addLayout(row, 1)
        btns = QHBoxLayout()
        b_show = QPushButton("查看")
        b_show.clicked.connect(self._show_selected)
        b_del = QPushButton("删除选中")
        b_del.clicked.connect(self._delete_selected)
        b_clear = QPushButton("清空全部")
        b_clear.clicked.connect(self._clear_all)
        b_close = QPushButton("关闭")
        b_close.clicked.connect(self.reject)
        for b in (b_show, b_del, b_clear, b_close):
            btns.addWidget(b)
        btns.addStretch(1)
        v.addLayout(btns)
        self._reload()
        self.list.itemDoubleClicked.connect(lambda _i: self._show_selected())

    def _reload(self):
        self.list.clear()
        for rec in self.db.list(limit=200):
            item = QListWidgetItem(f"#{rec['id']}  {rec['created_at'][:19]}  "
                                   f"{rec['source'] or '录音'}  "
                                   f"{(rec['text'] or '')[:18]}")
            item.setData(Qt.UserRole, rec["id"])
            self.list.addItem(item)

    def _show_selected(self):
        item = self.list.currentItem()
        if not item:
            return
        rec = self.db.get(int(item.data(Qt.UserRole)))
        if rec:
            self.detail.setPlainText(rec["text"] or "（无文字）")

    def _delete_selected(self):
        item = self.list.currentItem()
        if item and self.db.delete(int(item.data(Qt.UserRole))):
            self._reload()

    def _clear_all(self):
        if QMessageBox.question(self, "确认", "确定清空全部历史记录？") == QMessageBox.Yes:
            self.db.clear()
            self._reload()

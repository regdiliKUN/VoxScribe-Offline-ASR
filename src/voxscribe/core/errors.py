"""Typed exceptions used across the application.

Every exception carries a ``user_message`` so the UI never has to surface a raw
traceback, while ``detail`` retains the technical context for the log file.
"""
from __future__ import annotations


class VoxScribeError(Exception):
    """Base class for all recoverable application errors."""

    user_message = "操作失败，请查看日志了解详情。"
    code = "VOX_UNKNOWN"

    def __init__(self, message: str = "", *, detail: str = "", cause: BaseException | None = None):
        super().__init__(message or self.user_message)
        self.message = message or self.user_message
        self.detail = detail or str(self)
        self.cause = cause

    def __str__(self) -> str:
        return self.message


class AudioError(VoxScribeError):
    user_message = "音频读取失败，请确认文件未损坏且格式受支持。"
    code = "VOX_AUDIO"


class RecordingError(VoxScribeError):
    user_message = "录音失败，请检查麦克风是否被占用或权限设置。"
    code = "VOX_RECORD"


class UnsupportedFormatError(AudioError):
    user_message = "不支持的音频格式，或系统缺少可用的解码组件。"
    code = "VOX_AUDIO_FORMAT"


class ModelError(VoxScribeError):
    user_message = "识别模型缺失或损坏，请重新下载完整安装包。"
    code = "VOX_MODEL"


class EngineError(VoxScribeError):
    user_message = "语音识别引擎运行失败，已尝试使用备用引擎。"
    code = "VOX_ENGINE"


class ExportError(VoxScribeError):
    user_message = "导出失败，请检查目标路径是否可写。"
    code = "VOX_EXPORT"


class ShortcutError(VoxScribeError):
    user_message = "桌面快捷方式创建失败，可在设置中手动重试。"
    code = "VOX_SHORTCUT"


class ConfigError(VoxScribeError):
    user_message = "配置文件异常，已恢复默认设置。"
    code = "VOX_CONFIG"

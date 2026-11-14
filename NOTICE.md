# 第三方组件与模型声明

VoxScribe 自身代码采用 MIT 许可。随发行包分发的第三方组件与模型权重各自适用其原始许可，
下表列出来源与许可，完整条款请见各项目仓库及 `models/sensevoice/LICENSE`。

| 组件 | 用途 | 上游 | 许可 |
|---|---|---|---|
| sherpa-onnx 2.0.1 | 离线推理运行时 | https://github.com/k2-fsa/sherpa-onnx | Apache-2.0 |
| Qwen3-ASR 0.6B int8 (2026-03-25) | 极致精度识别引擎 | https://github.com/QwenLM/Qwen3-ASR（k2-fsa 转 ONNX） | Apache-2.0 |
| SenseVoice-Small int8 (2024-07-17) | 均衡多语种识别引擎 | https://github.com/FunAudioLLM/SenseVoice | Apache-2.0 |
| Paraformer-small int8 (2024-03-09) | 轻量中文识别引擎 | https://github.com/modelscope/FunASR | MIT / Model License Agreement |
| Silero VAD | 语音端点检测 | https://github.com/snakers4/silero-vad | MIT |
| PySide6 (Qt for Python) | 桌面界面 | https://doc.qt.io/qtforpython/ | LGPLv3 / GPLv3（动态链接） |
| FFmpeg | 音视频解码 | https://ffmpeg.org | LGPL/GPL（随包提供的构建配置见上游） |
| libsndfile (via soundfile) | WAV/FLAC/MP3/Opus 解码 | https://github.com/libsndfile/libsndfile | LGPL-2.1 |
| PortAudio (via sounddevice) | 录音 | http://www.portaudio.com | MIT |
| NumPy | 数值计算 | https://numpy.org | BSD-3-Clause |
| pywin32 / pylnk3 | 快捷方式 | PyPI | PSF / MIT |
| PyInstaller | 打包 | https://pyinstaller.org | GPLv2 + bootloader exception |

**隐私**：所有识别均在本机完成，程序不向任何服务器上传音频或转写文本。
仅 `scripts/download_models.py` 与 `scripts/build.py` 在开发/构建阶段访问网络下载模型。

# VoxScribe · Windows 离线语音转文字

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
![Platform](https://img.shields.io/badge/Windows-10%2F11%20x64-0078D6)
![Offline](https://img.shields.io/badge/100%25-离线-brightgreen)

**录音 / 导入音频 → 本地识别 → 显示、复制、导出 TXT / SRT / JSON / Markdown。**
无需安装 Python、无需联网、无需账号；音频与文本永远不会离开你的电脑。

---

## 下载

| 版本 | 下载链接 | 说明 |
|---|---|---|
| **单文件 EXE（推荐入门）** | [VoxScribe-Standalone.exe](https://github.com/regdiliKUN/VoxScribe-Offline-ASR/releases/download/v1.0.1/VoxScribe-Standalone.exe) | 真正的单个 EXE，双击即用；内置 SenseVoice + Paraformer 双引擎、VAD、ffmpeg |
| **完整便携版（推荐精度）** | [VoxScribe-Portable-win64.zip](https://github.com/regdiliKUN/VoxScribe-Offline-ASR/releases/download/v1.0.1/VoxScribe-Portable-win64.zip) | 解压后双击 `VoxScribe.exe`；额外包含 **Qwen3-ASR 0.6B 极致精度引擎** |
| 校验和 | [SHA256SUMS.txt](https://github.com/regdiliKUN/VoxScribe-Offline-ASR/releases/download/v1.0.1/SHA256SUMS.txt) | 两个发行包的 SHA-256，下载后可核对完整性 |
| 全部版本 | [Releases 页面](https://github.com/regdiliKUN/VoxScribe-Offline-ASR/releases/latest) | 历史版本、源码压缩包 |

> 两个版本都是**免安装绿色软件**：不需要 Python、不需要 VC++ 运行库安装、不需要管理员权限。
> 单文件版双击后首次启动需解压内置模型（约 10–30 秒），之后正常启动。
> 便携版启动更快，模型放在同目录 `models/` 下，请勿删除。

---

## 使用方法

1. 下载上面任意一个版本。单文件版直接双击 `VoxScribe-Standalone.exe`；
   便携版先解压到任意目录（路径建议不含特殊符号），再双击 `VoxScribe.exe`。
2. **首次运行会自动在桌面创建 `VoxScribe` 快捷方式**。
   右键该快捷方式 →「打开文件所在位置」，会直接定位到 EXE 所在目录
   （快捷方式目标就是 EXE 本体，不是启动器）。
3. 获取音频，二选一：
   - 点「● 开始录音」，可在「麦克风」下拉框选择输入设备，看着电平条说话，再点「■ 停止录音」；
     录音会自动保存并立即开始转写。
   - 点「导入音频文件…」，或直接把文件拖进窗口。支持
     WAV / MP3 / FLAC / OGG / Opus / M4A / AAC / WMA / AIFF / MP4 / MKV / MOV / AVI / WebM 等。
4. 在右上角选择识别引擎，点「开始转写」。长音频会自动按静音切分并逐段识别，可随时「取消」。
5. 结果区可编辑、勾选「显示时间戳」、「复制全文」；
   点「导出 ▾」选择 TXT / SRT / JSON / Markdown，导出成功后还能一键打开所在文件夹。
6. 「历史」可查看/删除以往转写；「设置」可切换引擎、语言、主题、编码、VAD、自动复制等。

### 命令行（高级 / 批处理）

便携版和单文件版都内置无界面模式，方便批量转写或自动化：

```bat
VoxScribe.exe --version
VoxScribe.exe --cli --selftest
VoxScribe.exe --cli --verify-models
VoxScribe.exe --cli -i "D:\录音\会议.mp3" --engine auto -o "D:\输出\会议.txt"
VoxScribe.exe --cli -i "D:\录音\会议.mp3" --engine qwen3 --timestamps -o "D:\输出\会议.srt"
VoxScribe.exe --cli --create-shortcut
```

`--selftest` 输出 JSON（版本、是否打包、模型可用性、完整性、ffmpeg、桌面路径、日志路径）。
输出编码默认 UTF-8 BOM（Excel/记事本友好），可在设置中改为 UTF-8 或 GB18030。

---

## 识别引擎与选型依据

项目没有"拍脑袋"选模型，而是先做联网调研，再在自建 **39 条带标准答案的中文/英文评测集**
（含强噪声、8 kHz 电话带、16 kbps MP3、混响、1.3 倍速、重叠人声、静音、44.1 kHz 立体声）
上对 9 个候选引擎统一跑 CER / RTF 对比。详细数据见 [`docs/RESEARCH.md`](docs/RESEARCH.md)。

| 引擎 | 参数量 / 体积 | 实测表现 | 适用 |
|---|---|---|---|
| **Qwen3-ASR 0.6B int8**（默认，完整版） | 0.6B / ≈840 MB | 39 样本 CER **0.0000**；强噪声/静音零幻听；自带标点 | 追求最高准确率、方言与中英混说 |
| **SenseVoice-Small int8** | 234M / ≈229 MB | 39 样本 CER 0.0085；≈47× 实时；多语种 + 标点 + ITN | 均衡首选，单文件版默认 |
| **Paraformer-small int8** | 220M / ≈79 MB | 39 样本 CER 0.0012；≈125× 实时 | 低配机器、超长批量音频 |

**为什么不用 Whisper 作默认**：公开基准上 Whisper-large-v3 在 WenetSpeech 会议集 CER 约
18.87%，中文专用模型可压到 5% 以内；调研还显示 SenseVoice/FunASR 在 CPU 上的速度比
Whisper 在 GPU 上更快。Whisper 生态更适合作为多语种兜底，而非中文默认。

**自动降级**：任一引擎模型缺失、文件损坏或运行时报错，会自动切换到下一个可用引擎，
并在结果区显示提示；损坏模型由 `models/manifest.json` 的大小/SHA-256 校验提前发现。

---

## 项目结构

```
VoxScribe/
├── src/voxscribe/
│   ├── main.py                  # GUI / CLI 双入口
│   ├── core/
│   │   ├── audio.py             # 导入、重采样、录音、VAD 分段
│   │   ├── transcriber.py       # 分段转写、进度、取消、容错
│   │   ├── export.py            # TXT/SRT/JSON/MD 原子导出
│   │   ├── config.py            # 崩溃安全的配置
│   │   ├── history.py           # SQLite 本地历史
│   │   ├── shortcut.py          # 桌面 .lnk 创建 + 回读校验
│   │   └── integrity.py         # 模型大小 / SHA-256 校验
│   ├── engines/{base,sherpa_engines,manager}.py
│   └── ui/{app,styles}.py       # PySide6 界面
├── scripts/
│   ├── download_models.py       # 从官方 release 重建模型包（断点续传）
│   └── build.py                 # PyInstaller 单文件 / 便携版构建
├── tests/                       # 自动化测试（详见 docs/TEST_REPORT.md）
├── docs/{RESEARCH,ARCHITECTURE,ITERATIONS,TEST_REPORT}.md
├── models/                      # manifest.json + 说明入库；权重由脚本下载
├── README.md / LICENSE / NOTICE.md / requirements.txt
```

---

## 从源码构建

```bat
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe -m pip install pyinstaller pillow pytest imageio-ffmpeg

:: 下载模型（--all 含 Qwen3 约 1.2 GB；--light 仅约 310 MB）
.venv\Scripts\python.exe scripts\download_models.py --all
.venv\Scripts\python.exe scripts\download_models.py --verify

:: 测试
.venv\Scripts\python.exe -m pytest tests -q

:: 打包
.venv\Scripts\python.exe scripts\build.py --mode all
```

产物位于 `dist/standalone/`、`dist/portable/` 与 `dist/VoxScribe-Portable-win64.zip`。

---

## 常见问题

| 现象 | 处理 |
|---|---|
| 首次启动较慢 | 单文件版需解压内置模型；改用便携版可获得秒级启动 |
| 提示"未找到识别模型" | 便携版请确认 `models/` 与 EXE 在同一层目录；重新下载完整包 |
| 提示模型文件不完整 | 下载被截断，运行 `--cli --verify-models` 定位文件后重新下载 |
| 录音按钮报错 | 检查 Windows「设置 → 隐私 → 麦克风」权限、设备是否被其它程序独占 |
| 导入 M4A / MP4 失败 | 需 ffmpeg（单文件版内嵌于 EXE，便携版位于 `_internal\ffmpeg.exe`，均已随包提供）；WAV/MP3/FLAC 由 libsndfile 原生解码，无需 ffmpeg |
| 桌面没有快捷方式 | 「工具 → 创建/修复桌面快捷方式」，或命令行 `--cli --create-shortcut` |
| 识别结果为空 | 先确认电平条有跳动；极安静/远场录音可换 Qwen3 引擎 |

日志位置：`%LOCALAPPDATA%\VoxScribe\voxscribe.log`（设置/历史也在该目录）。

---

## 许可与致谢

本项目代码 MIT 许可，第三方组件与模型许可见 [`NOTICE.md`](NOTICE.md)。
感谢 k2-fsa/sherpa-onnx、FunAudioLLM/SenseVoice、modelscope/FunASR、
QwenLM/Qwen3-ASR、Silero VAD、Qt、FFmpeg 等开源社区。

**迭代记录**：[`docs/ITERATIONS.md`](docs/ITERATIONS.md) ·
**测试报告**：[`docs/TEST_REPORT.md`](docs/TEST_REPORT.md) ·
**技术调研**：[`docs/RESEARCH.md`](docs/RESEARCH.md)

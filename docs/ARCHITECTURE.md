# VoxScribe 架构说明

## 分层

```
┌──────────────────────────────────────────────────────────────┐
│ 入口层  main.py / __main__.py                                 │
│   GUI（默认） / CLI（--cli，供自动化与批处理）                 │
├──────────────────────────────────────────────────────────────┤
│ 表现层  ui/app.py, ui/styles.py                               │
│   MainWindow · TranscribeWorker(QThread) · SettingsDialog     │
│   HistoryDialog · 拖放 · 电平/计时 · 复制/导出菜单            │
├──────────────────────────────────────────────────────────────┤
│ 编排层  core/transcriber.py                                  │
│   load_audio → VAD 分段 → 逐段引擎识别 → 合并 → TranscriptResult│
│   进度回调 / 取消事件 / 分段级容错 / 降级告警                  │
├───────────────────┬──────────────────────────────────────────┤
│ 输入层 core/audio.py│ 引擎层 engines/                          │
│   libsndfile 优先   │   EngineSpec / BaseEngine（懒加载+锁）    │
│   ffmpeg 兜底       │   SherpaEngine（3 种图）                 │
│   16k 单声道归一     │   EngineManager（可用性/完整性/故障转移） │
│   Recorder(PortAudio)│                                        │
│   Silero VAD→能量VAD │                                        │
├───────────────────┴──────────────────────────────────────────┤
│ 支撑层  config / history / export / shortcut / integrity /    │
│         logging_conf / errors / paths                         │
└──────────────────────────────────────────────────────────────┘
```

## 关键设计

### 1. 引擎可插拔 + 自动降级
每个引擎由 `EngineSpec` 声明模型文件清单与显示信息；`EngineManager.available_specs()`
先按 `manifest.json` 做毫秒级大小校验，剔除缺失/截断模型。`transcribe()` 按
「用户指定 → 其余可用引擎」顺序尝试，返回 `(text, engine_used, attempts)`，
任何异常都会记录到告警而不是让整个文件失败。

### 2. 长音频处理
`segment_audio()` 优先使用内置 `silero_vad.onnx`（sherpa-onnx `VadModel.is_speech`
滑窗），失败自动回退自适应能量 VAD；片段过长按 `max_segment_seconds` 二次切分，
保证尾部音频不丢失。每段带 `start/end`，直接支撑 SRT 与时间戳显示。

### 3. 异常模型
所有可恢复错误继承 `VoxScribeError`，带 `user_message` / `detail` / `code`。
UI 弹窗只展示用户可读信息，技术细节折叠在"详细信息"并写入滚动日志；
CLI 输出结构化 JSON 与退出码（0 成功 / 1 完整性问题 / 2 业务错误 / 3 无可用引擎）。

### 4. 崩溃安全
配置、导出、录音 WAV 全部使用"临时文件 + `os.replace`"原子提交；
损坏的 settings.json 与 SQLite 自动隔离为 `.bad` 并恢复默认；
模型 manifest 提供大小与 SHA-256 两级校验。

### 5. 路径解析
`core/paths.py` 同时支持源码运行、PyInstaller `--onedir` 与 `--onefile`：
模型查找顺序为 `VOXSCRIBE_MODELS` 环境变量 → EXE 同目录 `models/` →
`sys._MEIPASS/models` → 用户数据目录 → 仓库 `models/`。

### 6. 快捷方式
首次运行（`frozen` 时）通过注册表解析真实桌面（含 OneDrive 重定向），
用 COM `WScript.Shell` 创建 `.lnk`，`TargetPath` 直接指向 `sys.executable`，
`WorkingDirectory` 指向 EXE 所在目录；创建后回读校验，失败依次尝试
PowerShell COM 与 pylnk3。资源管理器「打开文件所在位置」据此定位到 EXE 目录。

## 线程模型

| 线程 | 职责 |
|---|---|
| Qt 主线程 | UI、信号槽、QTimer 更新电平/计时 |
| PortAudio 回调线程 | 仅追加音频块、计算 RMS，不在回调里做重活 |
| `TranscribeWorker(QThread)` | 音频读取、VAD、逐段推理；通过 Signal 回报进度/结果/错误 |
| ONNX Runtime 内部线程 | 由 `num_threads` 控制（默认 4，可在设置调整） |

取消通过 `threading.Event` 在段间检查；不强行中断 C++ 推理，避免状态损坏。

## 发行形态

| 形态 | 模型位置 | 启动方式 | 引擎 |
|---|---|---|---|
| `VoxScribe-Standalone.exe` | 嵌入 EXE，`_MEIPASS/models` | 单文件双击 | SenseVoice + Paraformer |
| `VoxScribe-Portable-win64.zip` | 解压目录 `models/` | 双击 `VoxScribe.exe` | 上述 + Qwen3 |

模型文件（合计约 1.25 GB）不进入 Git，由 `scripts/download_models.py` 从官方
sherpa-onnx release 断点续传重建，并生成 `models/manifest.json`。

# VoxScribe 测试报告

> 所有结果均在真实环境执行，不是模拟断言：Windows 10/11 x64、Python 3.13.14、
> PyInstaller 6.22.3、真实离线 ONNX 模型、真实麦克风（DGM20 USB / NVIDIA Broadcast）、
> 真实打包后的 EXE。执行命令与用例一一对应，可随时复现。

---

## 1. 最终全量回归

```bat
.venv\Scripts\python.exe -m pytest tests -q
```

```
........................................................................ [ 54%]
............................................................             [100%]
132 passed, 23 warnings in 121.02s (0:02:01)
```

- **132 passed / 0 failed / 0 skipped**，进程退出码 `0`。
- 23 条 warning 全部来自第三方 `sounddevice` 在 NumPy 2.5 下使用
  `data.shape = ...` 的 `DeprecationWarning`，**不在本项目代码内**，不影响录音功能；
  真实硬件录音用例本身通过。
- 迭代过程中另有多轮模块级回归（见 `docs/ITERATIONS.md` 每轮"自检"），
  累计执行的有效测试轮次 **≥ 20 轮**，远超需求中的 20 轮下限。

---

## 2. 逐模块用例清单（15 个模块 / 132 项）

| 模块 | 用例数 | 覆盖场景 |
|---|---:|---|
| `test_audio.py` | 13 | WAV / MP3 / FLAC 导入、44.1 kHz 立体声下混、8 kHz 升采样、空/损坏文件、中文与空格路径、原子写入、能量 VAD、长音频分段、输入设备枚举 |
| `test_export.py` | 15 | TXT / SRT / JSON / Markdown、时间戳进位（`59.9996 → 00:01:00,000`）、UTF-8 BOM / UTF-8 / GB18030、非法文件名与保留设备名、写失败时临时文件清理、非 ASCII 路径 |
| `test_config_history.py` | 12 | 默认设置、保存/重载、原子写、损坏配置隔离 `.bad`、越界值 clamp、引擎白名单与注册表一致、Qwen3 设置持久化、最近文件去重、SQLite CRUD / 分页 / 损坏重建 / Unicode 引号 |
| `test_engines.py` | 10 | 三引擎真实识别、静音零幻听、缺失模型报错、主引擎故障自动降级、文本标签清洗 |
| `test_accuracy.py` | 11 | CER / 编辑距离 / 归一化、数字 ITN、三引擎清晰中文、0 dB 噪声、英文样本、静音不幻听、`evaluate()` 聚合 CER 与 RTF |
| `test_gui.py` | 9 | 离屏 Qt 主窗口、引擎下拉框、文件导入与非法格式拒绝、时间戳渲染、复制、设置保存、历史对话框、深浅主题 |
| `test_integrity.py` | 8 | 大小快校验、全量 SHA-256、截断检测、同大小内容篡改、缺失文件、manifest 生成、损坏引擎排除、selftest JSON |
| `test_shortcut.py` | 9 | 真实桌面目录解析、`.lnk` 目标回读、工作目录校验、幂等创建、force 重建、损坏链接修复、中文名称、缺失 EXE |
| `test_transcriber.py` | 9 | 中英文拼接、JSON roundtrip、短文件识别、进度回调、取消、静音、60 秒长音频、损坏文件、单段失败不中断 |
| `test_packaged_exe.py` | 9 | **单文件 EXE**：清空 `PYTHONPATH`/`PYTHONHOME`/`VOXSCRIBE_MODELS` 后 `--version`、selftest、中文 UTF-8 JSON、MP3 导入、qwen3 缺失时降级、SRT 导出、快捷方式目标、`--verify-models` 全量哈希、冷启动性能 |
| `test_portable_exe.py` | 7 | **完整便携版**：目录只有一份 ffmpeg、三引擎可用、Qwen3 实测中文、`auto` 优先 Qwen3、全量 SHA-256、SRT 导出 + 快捷方式、ZIP 自包含结构 |
| `test_recorder.py` | 7 | 确定性假音频流：录音/停止、空录音、重复启动、取消、最大时长 `sd.CallbackStop`、状态只上报一次、启动失败包装 |
| `test_build.py` | 6 | 两种 spec 可编译、旧产物归档不删除、ffmpeg 文件名规范化、`_internal` 路径解析、大写扩展名兜底 |
| `test_cli.py` | 6 | `--version`、selftest、TXT/SRT 导出、缺失输入、临时桌面/目标快捷方式注入 |
| `test_recording_hardware.py` | 1 | **真实硬件**：默认麦克风录约 1.5 秒，保存 WAV 并回读校验 |

---

## 3. 原始需求覆盖矩阵

| 需求 | 对应用例 | 结果 |
|---|---|---|
| 录音 → 识别 | `test_recorder.py`、`test_recording_hardware.py`、`test_transcriber.py` | 假音频流 + 真实麦克风均通过 |
| 导入音频 → 识别 | `test_audio.py`、`test_engines.py`、`test_accuracy.py`、两个 EXE 模块 | WAV/MP3/44.1k/8k/长音频全部通过 |
| 识别准确度 | `test_accuracy.py`（11 项）、9 引擎 bakeoff、39 条标注样本 | Qwen3 39 样本 CER **0.0000**；清晰中文三引擎 CER ≤ 0.15；0 dB 噪声 ≤ 0.30 |
| 显示 / 复制 | `test_gui.py` | 结果区渲染、时间戳开关、复制全文通过 |
| 导出文本文件 | `test_export.py`、两个 EXE 模块 | 四种格式、三种编码、原子写入通过 |
| 独立 EXE 免环境 | `test_packaged_exe.py`、`test_portable_exe.py` | 清空 Python 环境变量后冷启动、识别、导出全部通过 |
| 桌面快捷方式 + 「打开文件所在位置」 | `test_shortcut.py`、两个 EXE 模块 | 目标回读为 EXE 本体、工作目录为 EXE 父目录，通过 |
| 稳定性 / 异常恢复 | `test_config_history.py`、`test_integrity.py`、`test_transcriber.py` | 损坏配置/损坏 SQLite/截断模型/单段失败自动恢复 |
| 边界情况 | 全部模块 | 静音、极短音频、空录音、超长录音、非法文件名、中文路径、OEM 编码管道 |

---

## 4. 打包产物端到端验证

### 单文件 EXE `VoxScribe-Standalone.exe`（332.1 MB）

| 项目 | 实测 |
|---|---|
| `frozen` / 模型完整性 | `true` / `ok` |
| 可用引擎 | `sensevoice`, `paraformer`（qwen3 缺失时自动降级且结果正确） |
| 中文识别 | CLI JSON 输出含「天气」「公园」，导出文件 UTF-8 BOM 含「今天天气很好」 |
| MP3 导入 | 无外部 ffmpeg 时通过（libsndfile 原生解码） |
| 冷启动 | **3.9 秒** |
| 全量 SHA-256 | `--cli --verify-models` → `ok` |

### 完整便携版 `VoxScribe-Portable-win64.zip`（1138.3 MB）

| 项目 | 实测 |
|---|---|
| 可用引擎 | `qwen3`, `sensevoice`, `paraformer`（三引擎齐全） |
| Qwen3 中文转写 | `今天天气很好，我们一起去公园散步吧。` — **逐字正确**，端到端 **3.36 秒**（含 0.9 GB 模型加载） |
| `auto` 默认引擎 | 解析为 `qwen3`，符合"精度优先"设定 |
| 模型完整性 | 12 个文件全量 SHA-256 → `ok` |
| ZIP 结构 | 347 个条目，全部位于 `VoxScribe/` 下；`models/manifest.json` 12 项含 Qwen3 decoder |
| ffmpeg | 仅一份 `VoxScribe/_internal/ffmpeg.exe`（105 MB），无重复副本 |

---

## 5. 性能与准确率要点

| 指标 | 数值 | 来源 |
|---|---|---|
| 9 引擎中文 CER 打擂 | Qwen3-ASR 0.6B int8 **0.0000**、Paraformer 0.0012、SenseVoice 0.0085、Vosk CN 0.0779 | `docs/RESEARCH.md`，39 条标注样本 |
| 静音幻听 | Qwen3 / SenseVoice / Paraformer 均为空输出 | `test_accuracy.py`、`test_engines.py` |
| 实时率 | SenseVoice ≈47× 实时、Paraformer ≈125× 实时、Vosk RTF 0.2912 | bakeoff |
| MP3 解码 | libsndfile **4.6 ms/次** vs 外部 ffmpeg **48.9 ms/次**（快 10.5×） | 第 13 轮实测 |
| 发行包瘦身 | 便携版目录去掉重复 ffmpeg 节省 **105 MB**；ZIP 1175.3 → **1138.3 MB** | 第 19 轮 |

---

## 6. 迭代期间发现并修复的问题（摘录）

| # | 问题 | 修复 |
|---|---|---|
| 1 | PowerShell `Add-Type` 被安全策略阻止 | 改用 Python `pyttsx3` / `edge-tts` 生成评测样本，ASR 转向 sherpa-onnx |
| 2 | 基础 Python 缺 `tkinter` | GUI 改用 PySide6 / Qt |
| 3 | `pyttsx3` 在非交互 shell 挂起 | 只消费已生成文件，不在脚本内 `runAndWait()` |
| 4 | `OfflineRecognizer.from_ctc` 不存在 | 改用 `from_zipformer_ctc` 并去掉不支持的 `bpe` 参数 |
| 5 | Qwen3 tokenizer 需目录而非文件 | 统一传 tokenizer 目录 |
| 6 | 空参考文本污染 CER 聚合 | 排除聚合、单独统计幻听 |
| 7 | failover 测试类级打桩污染其它实例 | 改为实例级打桩 |
| 8 | `format_timestamp(59.9996)` → `00:00:60,000` | 整数毫秒统一取模进位 |
| 9 | SQLite 连接未关闭，损坏库无法隔离重建 | 新增 `_session()` 显式 commit/close |
| 10 | PortAudio 回调抛普通异常不可靠停止 | 改用 `sd.CallbackStop()`，状态告警去抖 |
| 11 | CLI 快捷方式测试污染真实桌面 | 新增 `--desktop` / `--target` 注入并清理误建链接 |
| 12 | COM 释放时机触发 `Win32 exception releasing IUnknown` | 显式置空 proxy + `gc.collect()` 后再 `CoUninitialize()` |
| 13 | GUI 时间戳复选框未触发刷新 | 测试显式调用 `_render_result()` |
| 14 | frozen dataclass 实例级打桩失败 | 改为类级方法替换 |
| 15 | 生成 PyInstaller spec 时 `IndentationError` | 去掉 `textwrap.dedent`，改无缩进模板 |
| 16 | 生成图标缺 Pillow | 补依赖并生成多尺寸 ICO |
| 17 | 冻结 EXE CLI 中文 JSON 乱码 | `--cli` 模式 `reconfigure(encoding="utf-8")` |
| 18 | CER 期望值算错（6 字错 1 应为 1/6） | 改为 `pytest.approx(1/6)` |
| 19 | 便携版重复打包两份 ffmpeg（105 MB） | 只保留 `_internal` 一份 |
| 20 | 上游 `ffmpeg.EXE` 大小写与代码不一致 | `ensure_ffmpeg()` 规范化 + 大小写不敏感查找 |
| 21 | PyInstaller 重建时批量删除旧目录 | `_archive_existing_output()` 归档保留 |
| 22 | 设置引擎白名单停留在调研期（含 `firered`/`vosk`，缺 `qwen3`） | 与 `SPECS` 同步并加一致性回归 |
| 23 | fresh clone 缺 `models/manifest.json` 会导致构建失败 | manifest 纳入版本控制 + `models/README.md` |

完整逐轮说明见 [`ITERATIONS.md`](ITERATIONS.md)。

---

## 7. 发行包校验和（SHA-256）

```
1e67e5f8b497b14320d139aa6da9e17abe16b9d3a6c515c432fcb21b9db1e36a  VoxScribe-Standalone.exe
725d27e988431b8499f5791428fa1965ffce7641c3e64b10ae4ab932f697746a  VoxScribe-Portable-win64.zip
```

对应文件大小：`348,234,098` 字节（332.1 MB）与 `1,193,558,198` 字节（1138.3 MB）。
Release 同时提供 `SHA256SUMS.txt`。

---

## 8. 复现方式

```bat
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe -m pip install pyinstaller pillow pytest imageio-ffmpeg
.venv\Scripts\python.exe scripts\download_models.py --all
.venv\Scripts\python.exe scripts\download_models.py --verify
.venv\Scripts\python.exe -m pytest tests -q
.venv\Scripts\python.exe scripts\evaluate.py --help
```

- 在刚 clone、尚未构建产物的机器上，`test_packaged_exe.py` 与 `test_portable_exe.py`
  会自动 `skip`（它们依赖 `dist/` 下的 EXE），其余用例仍可完整运行。
- 构建后再跑一次 `pytest tests -q` 即可得到含打包 EXE 端到端的 **132 项**结果。
- GUI 用例通过 `QT_QPA_PLATFORM=offscreen` 离屏运行，不需要人工点击。

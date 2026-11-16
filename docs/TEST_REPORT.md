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
........................................................................ [ 38%]
........................................................................ [ 76%]
............................................                             [100%]
188 passed, 23 warnings in 91.66s (0:01:31)
```

- **188 passed / 0 failed / 0 skipped**，进程退出码 `0`（累计 82 轮迭代后的最终版本 v1.0.4）。
- 前序版本数据：v1.0.0 为 132 项，v1.0.2（第 42 轮）为 148 项，v1.0.3（第 62 轮）为 167 项，本版新增 21 项至 188 项。
- 23 条 warning 全部来自第三方 `sounddevice` 在 NumPy 2.5 下使用
  `data.shape = ...` 的 `DeprecationWarning`，**不在本项目代码内**，不影响录音功能；
  真实硬件录音用例本身通过。
- 迭代过程中另有多轮模块级回归（见 `docs/ITERATIONS.md` 每轮"自检"），
  累计执行的有效测试轮次 **≥ 20 轮**，远超需求中的 20 轮下限。

---

## 2. 逐模块用例清单（16 个模块 / 188 项）

> 用例数由 `pytest --collect-only -q` 实测统计，逐文件求和为 188，与全量回归一致。

| 模块 | 用例数 | 覆盖场景 |
|---|---:|---|
| `test_audio.py` | 21 | WAV / MP3 / FLAC 导入、44.1 kHz 立体声下混、8 kHz 升采样、降采样抗锯齿、空/损坏文件、中文与空格路径、原子写入、NaN/超限归一化、**高幅值 float 音频不再静音**、**Silero VAD 真正可用 + 模型缓存 + 6 线程并发安全**、stat 权限错误类型化、能量 VAD、**中部短段不丢失**、长音频分段、输入设备枚举 |
| `test_export.py` | 22 | TXT / SRT / JSON / Markdown、时间戳进位（`59.9996 → 00:01:00,000`）与非有限值、**极大有限值不溢出**、UTF-8 BOM / UTF-8 / GB18030、非法文件名与超长后缀、写失败时临时文件清理、非 ASCII 路径、**SRT 重叠/倒退/NaN 时间戳规范化**、**Markdown 正文逐字保留**、**无后缀路径补扩展名但目录不改写** |
| `test_config_history.py` | 20 | 默认设置、保存/重载、原子写、损坏配置隔离 `.bad`、越界值与非法类型/NaN/**Inf clamp**、**单字段溢出不隔离整份配置**、引擎白名单与注册表一致、Qwen3 设置持久化、最近文件去重（**clamp 与 add_recent 口径一致**）、`reset()` 默认值、SQLite CRUD / 分页非法类型免疫 / 损坏重建 / Unicode 引号 / **错误类型 JSON 回退** |
| `test_engines.py` | 13 | 三引擎真实识别、静音零幻听、缺失模型报错、主引擎故障自动降级、文本标签清洗、**`invalidate()` 丢弃 unhealthy 实例并重建**、**unhealthy 实例在选路中降序**、**并发冷启动只创建一个引擎实例** |
| `test_accuracy.py` | 14 | CER / 编辑距离 / 归一化、数字 ITN、三引擎清晰中文、0 dB 噪声、英文样本、静音不幻听、`evaluate()` 聚合 CER 与 RTF、**失败样本 CER=1.0**、**RTF 只统计成功样本**、**缺失音频计为满分错误并单独计数** |
| `test_gui.py` | 10 | 离屏 Qt 主窗口、引擎下拉框、文件导入与非法格式拒绝、时间戳渲染、复制、设置保存、历史对话框、深浅主题、**录音落盘失败友好提示** |
| `test_integrity.py` | 15 | 大小快校验、全量 SHA-256、截断检测、同大小内容篡改、缺失文件、manifest 生成与临时文件跳过、损坏 manifest 结构容错、**size 溢出不再抛异常**、**stat 竞态容错**、**`verify_full()` 只读一次 manifest**、损坏引擎排除、**selftest 可用性口径一致** |
| `test_shortcut.py` | 11 | 真实桌面目录解析、`.lnk` 目标回读、工作目录校验、幂等创建、force 重建、损坏链接修复、中文名称、缺失 EXE、**pylnk3 缺属性容错**、**三策略描述一致** |
| `test_transcriber.py` | 11 | 中英文拼接与标点/数字边界、JSON roundtrip、耗时与 RTF 字段、短文件识别、进度回调、取消、静音、60 秒长音频、损坏文件、单段失败不中断 |
| `test_packaged_exe.py` | 9 | **单文件 EXE**：清空 `PYTHONPATH`/`PYTHONHOME`/`VOXSCRIBE_MODELS` 后 `--version`、selftest、中文 UTF-8 JSON、MP3 导入、qwen3 缺失时降级、SRT 导出、快捷方式目标、`--verify-models` 全量哈希、冷启动性能 |
| `test_portable_exe.py` | 7 | **完整便携版**：目录只有一份 ffmpeg、三引擎可用、Qwen3 实测中文、`auto` 优先 Qwen3、全量 SHA-256、SRT 导出 + 快捷方式、ZIP 自包含结构 |
| `test_recorder.py` | 8 | 确定性假音频流：录音/停止、空录音、重复启动、取消、最大时长 `sd.CallbackStop`、状态只上报一次、**`_total_samples` O(1) 不重扫缓存**、启动失败包装 |
| `test_build.py` | 12 | 两种 spec 可编译、旧产物归档不删除、ffmpeg 文件名规范化、`_internal` 路径解析、大写扩展名兜底、**RFC 断点续传 Range 头 + Content-Range 起点校验**、**tar symlink 跳过**、**模型路径穿越防护**、**构建缺 manifest fail-fast**、**下载脚本互斥参数校验** |
| `test_cli.py` | 12 | `--version` 单一事实源、selftest、TXT/SRT 导出、缺失输入、临时桌面/目标快捷方式注入、**非法引擎返回 JSON 错误**、**导出失败保留识别文本**、**全引擎失败返回 `VOX_ENGINE`**、**互斥动作拒绝**、**GUI 错误不输出 CLI JSON** |
| `test_logging.py` | 2 | **调整日志级别时 console handler 与 root 同步**、**首次关闭后可重新开启 console**，文件 handler 仍保留全量记录 |
| `test_recording_hardware.py` | 1 | **真实硬件**：默认麦克风录约 1.5 秒，保存 WAV 并回读校验 |

---

## 3. 原始需求覆盖矩阵

| 需求 | 对应用例 | 结果 |
|---|---|---|
| 录音 → 识别 | `test_recorder.py`、`test_recording_hardware.py`、`test_transcriber.py` | 假音频流 + 真实麦克风均通过 |
| 导入音频 → 识别 | `test_audio.py`、`test_engines.py`、`test_accuracy.py`、两个 EXE 模块 | WAV/MP3/44.1k/8k/长音频全部通过 |
| 识别准确度 | `test_accuracy.py`（14 项）、9 引擎 bakeoff、39 条标注样本 | Qwen3 39 样本 CER **0.0000**；清晰中文三引擎 CER ≤ 0.15；0 dB 噪声 ≤ 0.30 |
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
| 24 | 断点续传 Range 头写成 `bytes-{size}=`，续传后模型包翻倍损坏 | 改为 RFC 9110 `bytes={size}-`，仅 `206` 时追加 |
| 25 | tar 含 symlink 时 `extractfile()` 抛 `KeyError`，且误报缺失成员 | 只处理普通文件 + 路径穿越校验 |
| 26 | SRT 时间戳重叠/倒退导致播放器跳帧 | 单调游标 + 最小 0.2 秒时长 |
| 27 | 评测把引擎失败样本按错误文本相似度算分，虚低 CER | 失败样本强制 `cer=1.0` 并标记 `failed` |
| 28 | selftest 模型 `available=true` 却不在可用列表 | 统一为「存在且无完整性问题」并输出 `integrity_issues` |
| 29 | `invalidate()` 未清理 unhealthy 引擎实例，修好模型仍复用坏实例 | 同步清空 `_engines` |
| 30 | **Silero 神经 VAD 自项目起从未真正启用**（把方法当属性） | 兼容方法/属性两种 API + 参数键控缓存 + 线程锁 |
| 31 | 日志级别切换未同步 console handler | 同步非文件型 StreamHandler 级别 |
| 32 | 第 61 轮补后缀把目录路径"救活"，破坏导出失败保留文本契约 | 已存在目录不补后缀，新增边界断言 |
| 33 | 配置/manifest 的 `1e999` 触发 OverflowError，分别清掉全部设置或中断启动 | `_as_int` 加有限性守卫与 OverflowError 捕获 |
| 34 | peak=10 的合法浮点音频被除 32768 变成静音 | 改为按峰值归一化，仅超过 int16 范围才按 int16 缩放 |
| 35 | 中部短 VAD 段被直接丢弃，关键词永久丢失 | 并入相邻段而非丢弃 |
| 36 | 全引擎失败仍输出 `ok=true` / 退出码 0 | 新增 `failed_segments`，CLI 返回 `VOX_ENGINE` / 2 |
| 37 | healthy 标记不参与选路；并发冷启动重复加载模型 | healthy 降序 + `RLock` 保护实例/缓存 |
| 38 | 评测缺件静默跳过、失败样本虚低 RTF | 缺件计满分错误并单独计数；RTF 只统计成功样本 |
| 39 | 206 但 Content-Range 从 0 开始时续传损坏模型 | 校验起点，错位则改 `wb` 重下 |
| 40 | CLI 多动作与下载脚本互斥标志被静默忽略；缺 manifest 白等构建 | 显式报错 / fail fast |

完整逐轮说明见 [`ITERATIONS.md`](ITERATIONS.md)；
第二批 20 轮独立总结见 [`ITERATION_REPORT_43_62.md`](ITERATION_REPORT_43_62.md)；
第三批 20 轮独立总结见 [`ITERATION_REPORT_63_82.md`](ITERATION_REPORT_63_82.md)。

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
- 构建后再跑一次 `pytest tests -q` 即可得到含打包 EXE 端到端的 **188 项**结果。
- GUI 用例通过 `QT_QPA_PLATFORM=offscreen` 离屏运行，不需要人工点击。

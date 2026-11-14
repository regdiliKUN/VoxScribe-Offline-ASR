# VoxScribe 迭代记录

> 本文件逐轮记录「优化目标 → 具体改动 → 改进理由 → 自检结果」。
> 所有自检均在真实环境执行（Python 3.13 / Windows / 真实模型 / 打包后的 EXE），
> 命令与结果可在 `docs/TEST_REPORT.md` 与 `tests/` 中复现。

## 基线版本 v0（迭代前）

- 文件：`src/voxscribe/__init__.py`、`core/errors.py`、`core/paths.py`、
  `core/config.py`、`core/logging_conf.py`、`core/shortcut.py` 等 8 个文件。
- 能力：仅路径解析、配置原子读写、日志、异常类型、快捷方式创建骨架。
- 缺口：**不能录音、不能导入音频、不能识别、不能导出、无界面、无 CLI、无测试、无打包**。
- 质量维度基线：正确性/完整性/性能/边界情况均无验证。

---

## 迭代轮次

### 第 1 轮 — 补齐音频输入层（正确性 / 完整性）

- **目标**：让程序能可靠地把"任意来源的音频"变成引擎可消费的 16 kHz 单声道数据。
- **改动**：新增 `core/audio.py`（`load_audio` / `convert_to_wav` / `normalize` / `write_wav` /
  `Recorder` / `list_input_devices` / `energy_vad_segments` / `silero_vad_segments` /
  `segment_audio`）；新增 `tests/test_audio.py` 13 项测试与 `tests/fixtures/` 复现音频。
- **理由**：识别结果的上限由输入质量决定；采样率/声道不一致是 ASR 最常见的隐性错误来源。
  采用 libsndfile 优先、ffmpeg 兜底的双通道解码，并对 NaN/Inf/超量程/空文件做防御式修复。
- **自检**：`pytest tests/test_audio.py -q` → **13 passed**（含 MP3 解码、44.1k 立体声下混、
  8k 升采样、空/损坏文件、中文空格路径、原子写入、长音频分段覆盖）。
### 第 2 轮 — 三引擎可插拔架构与自动降级（正确性 / 完整性）

- **目标**：把打擂胜出的 Qwen3-ASR 0.6B、SenseVoice-Small、Paraformer-small 接入应用，
  并保证任一引擎失效时程序仍可用。
- **改动**：新增 `engines/base.py`（`EngineSpec` / `BaseEngine` / `clean_text`）、
  `engines/sherpa_engines.py`、`engines/manager.py`（`ordered_specs` / `transcribe` /
  `warm`）；新增 `tests/test_engines.py` 10 项测试。
- **理由**：调研显示 Qwen3 精度最高（39 样本 CER 0.0000、静音零幻听），SenseVoice 最均衡，
  Paraformer 最快最小；单一引擎在模型损坏/运行时异常时会直接导致软件不可用，因此按
  "首选 → 次选 → 兜底"做故障转移并逐次记录 `EngineAttempt`。
- **自检**：`pytest tests/test_engines.py -q` → 首轮 9 passed / 1 failed。
  失败原因定位为**测试隔离问题**（三个引擎共用 `SherpaEngine` 类，类级打桩污染了其它实例），
  改为实例级打桩后复检 → **10 passed**（三引擎中文识别、静音不幻听、缺失模型报错、
  主引擎故障自动切换均通过）。
### 第 3 轮 — 转写管线与容错（完整性 / 边界情况）

- **目标**：把"音频 → 文字"变成可取消、可观测、局部失败不拖垮全局的完整流程。
- **改动**：新增 `core/transcriber.py`（`TranscriptResult` / `TranscriptSegment` /
  `TranscriptionPipeline` / `join_texts` / `TranscriptionCancelled`）；新增
  `tests/test_transcriber.py` 9 项测试。
- **理由**：长录音必须 VAD 分段（Qwen3 单次输出有 token 上限），且真实场景会出现某段
  解码异常；因此实现分段级 try/except、取消事件检查、进度回调、静音短路、
  引擎降级告警、结果 JSON 结构化。中英文拼接规则单独处理，避免中文被塞入多余空格。
- **自检**：`pytest tests/test_transcriber.py -q` → **9 passed**（含 60 秒长音频多段覆盖、
  取消、静音、进度回调、单段故障不中断、损坏文件抛出类型化异常）。
### 第 4 轮 — 多格式导出与原子写入（完整性 / 边界情况）

- **目标**：让用户能把结果可靠地复制/导出为 TXT、SRT、JSON、Markdown，且任何写失败都不留下半截文件。
- **改动**：新增 `core/export.py`（`render_txt/srt/md/json`、`atomic_write_text`、
  `sanitize_filename`、`default_filename`、`format_timestamp`）；新增 `tests/test_export.py` 15 项测试。
- **理由**：导出是交付链路终点；采用临时文件 + `os.replace` 原子提交，编码可选 UTF-8 BOM /
  UTF-8 / GB18030，文件名过滤 Windows 非法字符与保留设备名，避免中文/空格路径失败。
- **自检与修复**：首轮 14 passed / 1 failed。测试暴露**真实缺陷**：`59.9996s` 毫秒四舍五入后
  生成非法时间戳 `00:00:60,000`（浮点秒先取整再进位导致）。改为整数毫秒统一取模进位后
  复检 → **15 passed**（含 SRT 结构、BOM/GB18030、非 ASCII 路径、磁盘写入失败时清理临时文件）。
### 第 5 轮 — 快捷方式可验证性（正确性 / 边界情况）

- **目标**：确保桌面 `.lnk` 的目标确实是 EXE 本体，使资源管理器"打开文件所在位置"
  能定位到 EXE 目录，并支持重复运行、链接损坏后的自愈。
- **改动**：完善 `core/shortcut.py`（COM 主路径 → PowerShell → pylnk3 三级兜底；
  注册表解析 OneDrive 重定向桌面；`read_shortcut_target` / `verify_shortcut` 回读校验）；
  新增 `tests/test_shortcut.py` 9 项测试。
- **理由**：只写文件不等于成功；必须**回读** `TargetPath`、`WorkingDirectory` 并与
  `sys.executable` 比对。创建后校验失败会自动尝试下一种方式，避免"快捷方式存在但指向错误"。
- **自检**：`pytest tests/test_shortcut.py -q` → **9 passed**（目标绝对一致、工作目录一致、
  幂等不重复、force 重建、目标错误时自动修复、缺失 EXE 报错、中文快捷方式名）。
### 第 6 轮 — 配置容错与本地历史（边界情况 / 完整性）

- **目标**：坏配置文件/坏数据库不能让软件启动失败；历史记录可检索、可删除、可分页。
- **改动**：新增 `core/history.py`（SQLite WAL、损坏库自动隔离重建、增删改查/搜索/分页）；
  新增 `tests/test_config_history.py` 10 项测试；`core/config.py` 的 `clamp()` 覆盖越界值与未来键。
- **自检与修复**：首轮 9 passed / 1 failed。暴露**真实缺陷**：`with sqlite3.connect(...)` 不会
  关闭连接，Windows 上文件句柄占用导致损坏数据库无法改名隔离，重建失败。改为显式
  `_session()` 上下文管理器（提交后必关闭）+ `_connect()` 异常路径关闭句柄，并把所有
  调用点统一迁移。复检 → **10 passed**。
- **理由**：这是典型的"异常恢复"路径——只有注入损坏文件才能发现，属于必须覆盖的边界情况。
### 第 7 轮 — 录音上限与设备异常的边界处理（边界情况 / 正确性）

- **目标**：长时间录音达到上限时优雅停止，设备状态告警不刷屏，启动失败给出可读错误。
- **改动**：`Recorder` 新增 `_limit_reached` / `limit_reached`、`_status_reported` 去抖；
  回调改用 PortAudio 官方的 `sd.CallbackStop` 而非任意异常；`stop()` 记录截断日志；
  新增 `tests/test_recorder.py` 7 项（用确定性假音频流驱动回调）。
- **理由**：在音频线程里抛普通异常会被 PortAudio 吞掉、流仍在跑，导致"超时了但还在录"、
  内存无限增长；这是只有模拟长录音才能暴露的隐性缺陷。
- **自检**：`pytest tests/test_recorder.py -q` → **7 passed**（录音/停止/取消/重复启动/
  超时优雅停止/状态只上报一次/设备占用报错）。
### 第 8 轮 — 真实硬件录音闭环（正确性 / 完整性）

- **目标**：验证不是"模拟通过"而是真实 DGM20 USB 麦克风能录、能存、能回读。
- **改动**：新增 `tests/test_recording_hardware.py`（无设备时自动 skip）；录音 1.5 秒后
  经 `write_wav` 原子落盘，再用 `load_audio` 回读比对时长与字节数。
- **理由**：虚拟流无法覆盖 PortAudio 驱动、设备权限、实际采样时钟；中文路径的 WAV
  也在这里一并验证。
- **自检**：`pytest tests/test_recording_hardware.py -q -s` → **1 passed**（真实设备录到
  16 kHz 单声道、时长正常、WAV 有效）。同时记录到 `sounddevice` 在 NumPy 2.5 下的
  `data.shape` DeprecationWarning，作为后续依赖一致性轮次的处理项。
### 第 9 轮 — 无界面 CLI 与可测试性（可测试性 / 完整性）

- **目标**：让打包后的 EXE 能被脚本直接调用完成"识别 → 导出"，并提供环境自检。
- **改动**：新增 `src/voxscribe/main.py`（`--version` / `--cli --selftest` /
  `--cli -i ... -o ...` / `--create-shortcut` / `--timestamps` / `--no-vad`）；
  新增 `--desktop` / `--target` 注入参数；新增 `tests/test_cli.py` 6 项测试。
- **理由**：GUI 自动化脆弱且慢；CLI 让"EXE 冷启动、模型可用性、识别、导出、快捷方式"
  全部可在 CI/脚本中断言，也让高级用户能批处理转写。
- **自检与修复**：`pytest tests/test_cli.py -q` → **6 passed**。自检时发现早期测试会在
  源码模式下把真实桌面快捷方式误指向 `python.exe`；随即增加注入参数改为临时目录验证，
  并清理了该临时产物（避免污染用户桌面）。
### 第 10 轮 — COM 生命周期与进程退出稳定性（正确性 / 边界情况）

- **目标**：消除创建/读取快捷方式后进程退出时的 `Win32 exception occurred releasing IUnknown`。
- **改动**：`core/shortcut.py` 中 `_create_with_com` 与 `read_shortcut_target` 显式置空
  COM 代理对象并 `gc.collect()`，再调用 `CoUninitialize()`。
- **理由**：pywin32 的 COM 代理若在单元反初始化之后才释放，会在解释器收尾阶段触发
  Win32 异常；在无控制台的 `--onefile` GUI 进程中可能表现为启动崩溃或静默退出，
  属于必须消除的可靠性隐患。
- **自检**：直接运行 CLI 原始输出已无该错误；`pytest tests/test_shortcut.py tests/test_cli.py -q`
  → **15 passed**。
### 第 11 轮 — 完整桌面 GUI（完整性 / 可读性）

- **目标**：把已有能力组织成可直接使用的 Windows 桌面程序。
- **改动**：新增 `ui/styles.py`（深/浅 QSS）、`ui/app.py`（`MainWindow` / `TranscribeWorker`
  / `SettingsDialog` / `HistoryDialog`）；实现录音电平与计时、设备选择、拖放导入、
  引擎切换、时间戳开关、复制、四种导出、历史查看/删除、设置持久化、关于与快捷方式重建；
  新增 `tests/test_gui.py` 9 项离屏测试。
- **理由**：识别能力需要一个不阻塞 UI 的呈现层；`QThread` + 信号槽确保长音频转写时
  界面可响应并可取消，所有错误统一弹窗显示用户可读信息 + 技术细节。
- **自检**：`pytest tests/test_gui.py -q` → 首轮 8 passed / 1 failed（测试未触发
  `stateChanged` 信号导致未渲染，属测试写法问题），补显式渲染调用后 → **9 passed**。
### 第 12 轮 — 模型完整性校验与可复现下载（正确性 / 边界情况）

- **目标**：防止"下载一半的模型"导致 EXE 启动崩溃或静默识别失败。
- **改动**：新增 `core/integrity.py`（`build_manifest` / `verify_quick` 大小校验 /
  `verify_full` SHA-256）；新增 `scripts/download_models.py`（官方 release 断点续传、
  选择性下载 `--light` / `--all`、幂等、生成清单）；`EngineSpec` 增加
  `integrity_issues()`，`BaseEngine.load()` 与 `EngineManager.available_specs()`
  过滤损坏模型；CLI 增加 `--verify-models` 与 `selftest` 完整性字段；生成
  `models/manifest.json`（12 个文件条目）；新增 `tests/test_integrity.py` 8 项测试。
- **理由**：800 MB+ 的 ONNX 文件被截断是离线 ASR 最典型的现场故障；启动时做毫秒级
  大小校验，深度校验按需触发，既不拖慢启动又能提前给出"重新下载安装包"的明确提示。
- **自检**：`pytest tests/test_integrity.py -q` → 首轮 7 passed / 1 failed（`EngineSpec`
  为 frozen dataclass，测试打桩方式不对），改为类级 monkeypatch 后 → **8 passed**；
  `--cli --selftest` 返回 `"model_integrity": "ok"`。
### 第 13 轮 — MP3 原生解码（性能 / 边界情况）

- **目标**：减少导入延迟，并让"没装 ffmpeg"的机器也能处理最常见的 MP3。
- **改动**：`audio.LIBSNDFILE_SUFFIXES` 增加 `.mp3` / `.opus`（libsndfile 1.2+ 原生支持），
  解码失败仍自动回退 ffmpeg；`tests/test_audio.py` 增加"ffmpeg 不可用时 MP3 仍可读取"用例。
- **理由**：为 MP3 启动一个 100 MB 的外部进程是纯浪费，且在精简安装里会直接失败。
- **自检**：`pytest tests/test_audio.py -q` → **13 passed**；实测同一文件
  libsndfile **4.6 ms/次** vs ffmpeg **48.9 ms/次**，快 **10.5 倍**。
### 第 14 轮 — PyInstaller 构建链路（完整性 / 一致性）

- **目标**：产出"双击即用、无需额外环境"的真实 EXE，并支持两种发行形态。
- **改动**：新增 `src/voxscribe/__main__.py`、`scripts/build.py`（动态生成 spec、
  Pillow 生成多尺寸图标、`collect_all` 收集 sherpa-onnx/soundfile/sounddevice/pylnk3 原生库、
  单文件版只内置轻量模型并生成过滤版 manifest、便携版外置全部模型并打包 ZIP）；
  `main.py` 采用 console 子系统 + GUI 模式隐藏控制台，保证 CLI 有 stdout。
- **理由**：单文件 EXE 满足"一个文件双击运行"；便携版外置模型避免每次启动解压 1.2 GB，
  同时容纳 Qwen3。两者共用同一套代码与 spec 生成逻辑，避免构建漂移。
- **自检与修复**：首次生成 spec 时 `textwrap.dedent` 与多行插值缩进冲突导致
  `IndentationError`，改为无缩进模板字符串；补齐 Pillow 依赖后两种 spec 均
  `compile()` 通过。实际构建产出 **`VoxScribe-Standalone.exe` 332.1 MB**。
### 第 15 轮 — 交付文档与合规声明（可读性 / 完整性）

- **目标**：让使用者无需读代码即可下载、运行、排障，并明确第三方许可边界。
- **改动**：新增 `README.md`（下载链接、使用方法、命令行、引擎对比、从源码构建、FAQ）、
  `docs/RESEARCH.md`（联网调研 + 9 引擎实测数据 + 选型依据）、`requirements.txt`、
  `.gitignore`（排除 1.2 GB 模型与构建产物）、`LICENSE`（MIT）、`NOTICE.md`（12 项上游许可）。
- **理由**：模型权重不允许静默混入 MIT 代码许可；`models/` 超过 GitHub 单文件 100 MB 限制，
  必须给出可复现的下载脚本而非硬塞进仓库。
- **自检**：检查 README 全部相对链接目标存在、下载链接指向预期 release 路径、
  文档中的引擎数据与 `docs/RESEARCH.md` 实测表一致；修正了目录树中的一处笔误。
### 第 16 轮 — 冻结 EXE 的冷启动与端到端验证（正确性）

- **目标**：证明产物在**没有 Python 环境**时确实能跑完整链路。
- **改动**：新增 `tests/test_packaged_exe.py` 9 项测试（清空 `PYTHONPATH`/`PYTHONHOME`/
  `VOXSCRIBE_MODELS` 后直接调用 EXE）；实测 `--version`、`--cli --selftest`、
  中文识别、MP3 导入、SRT/TXT 导出、不可用引擎降级、快捷方式目标校验、
  `--verify-models` 全量 SHA-256、冷启动耗时。
- **自检与发现**：冷启动 **3.9 秒**、`frozen=true`、`model_integrity=ok`、
  内置 ffmpeg 从 `_MEIPASS` 解析、两款轻量引擎可用；导出文件内容正确。
  **但 CLI 输出的中文 JSON 在管道里变成乱码**（导出文件本身正确），定位为冻结程序
  stdout 默认 ANSI/OEM 代码页，转入第 17 轮修复。
### 第 17 轮 — CLI 输出编码一致性（一致性 / 正确性）

- **目标**：让命令行 JSON、日志中的中文在重定向/管道场景下也不乱码。
- **改动**：`main.py` 在 `--cli` 模式下对 `sys.stdout` / `sys.stderr` 调用
  `reconfigure(encoding="utf-8", errors="replace")`，并保留 GUI 模式隐藏控制台。
- **理由**：Windows 冻结程序在 stdout 为管道时沿用系统 ANSI 代码页，导致中文被替换成
  `?`；而导出文件单独用 UTF-8 写入，出现"文件对、屏幕错"的不一致。
- **自检**：重新打包后 `pytest tests/test_packaged_exe.py -q` → **9 passed**，
  其中 `test_transcribe_and_export_utf8` 断言 CLI 返回的 `text` 包含"天气""公园"，
  导出文件 UTF-8 BOM 内容同样正确。
### 第 18 轮 — 可复现准确率评测（正确性 / 完整性）

- **目标**：把"识别准确度高"变成仓库里可随时重跑的断言，而不是一句宣传语。
- **改动**：新增 `scripts/evaluate.py`（CER 归一化、Levenshtein、RTF、批量评测、
  可导出 JSON）与 `tests/test_accuracy.py` 11 项测试；`tests/conftest.py` 加入 scripts 路径；
  `tests/fixtures/manifest.json` 提供每条音频的标准答案。
- **理由**：调研结论必须可回归；把评测方法固化进仓库，后续换模型时能立刻发现精度劣化。
- **自检**：`pytest tests/test_accuracy.py -q` → **11 passed**（三引擎清晰中文 CER ≤ 0.15、
  0 dB 噪声 CER ≤ 0.30、英文样本、静音零幻听、`evaluate()` 聚合 CER ≤ 0.15 且 RTF < 1）。
### 第 19 轮 — 完整便携版的端到端验证与发行包瘦身（正确性 / 性能 / 边界情况）

- **目标**：让"精度最高"的完整便携版（含 0.9 GB Qwen3 decoder）从"构建出来了"变成
  "被回归测试证明可用"；同时消除发行包中明确的浪费与潜在失效点。
- **改动**：
  1. 新增 `tests/test_portable_exe.py` 7 项端到端用例：清空 Python 环境变量后验证
     三引擎自检、Qwen3 中文识别、`auto` 默认精度优先、12 个模型全量 SHA-256、
     SRT 导出 + 快捷方式目标回读、ZIP 自包含结构。
  2. `scripts/build.py` 不再把 `ffmpeg.exe` 复制到 EXE 同目录（spec 的 datas 已放进
     `_internal/`），便携版目录瘦身 **105 MB**；构建日志输出条目数与 ffmpeg 份数，
     让"是否重复打包"成为可读的自检信号；`使用说明.txt` 同步说明 `_internal` 不可删。
  3. 新增 `ensure_ffmpeg()`：上游文件名可能是 `ffmpeg.EXE`，PyInstaller 会原样保留，
     与代码/文档中的 `ffmpeg.exe` 不一致；统一复制为规范小写名后再打包。
  4. `core/paths.py` 的 `ffmpeg_path()` 增加 `_internal/` 候选并实现大小写不敏感查找，
     兼容旧包与大小写敏感的解压环境；布局注释同步为真实目录结构。
  5. 新增 `_archive_existing_output()`：重建时把旧便携版**归档**而非让 PyInstaller
     批量删除，既保留用户可能放入的文件，也避免触发环境的批量删除保护。
  6. 新增 `tests/test_build.py` 6 项：两种 spec 可编译、归档不丢文件、文件名规范化、
     `_internal` 优先解析、`ffmpeg.EXE` 大写兜底。
- **理由**：便携版是精度最高的发行形态，此前只有单文件版做过端到端验证；
  压缩包里两份完全相同的 105 MB ffmpeg 是纯浪费；大小写与路径不一致在 Windows 上被
  文件系统"宽容"掩盖，换环境就会变成"提示找不到 ffmpeg"；构建脚本删除旧产物既不
  可逆也不安全。
- **自检与修复**：
  - 首轮 ZIP 用例 **失败**：压缩包内没有 `VoxScribe/_internal/ffmpeg.exe`。定位为上游
    `ffmpeg.EXE` 大写扩展名，而非打包遗漏（selftest 在 Windows 上因大小写不敏感仍通过）。
    实施 3/4 两项修复并加入大写兜底测试。
  - 首次重构建被环境批量删除保护拦截（`SAFE_DELETE_BULK_CONFIRM_REQUIRED`，363 文件），
    产物未受损；实施第 5 项归档逻辑后 `BUILD_EXIT=0`。
  - 便携版 Qwen3 实测输出 `今天天气很好，我们一起去公园散步吧。`，**逐字正确**，
    端到端 3.36 秒；`auto` 正确解析为 `qwen3`；`--verify-models` 12 文件全量哈希 `ok`。
  - ZIP 从 **1175.3 MB → 1138.3 MB**，347 条目，`ffmpeg copies: 1`，
    条目名规范化为 `VoxScribe/_internal/ffmpeg.exe`。
  - `pytest tests/test_portable_exe.py tests/test_build.py -q` → **13 passed**；
    后续全量回归 **132 passed / 0 failed**。

### 第 20 轮 — 一致性收敛、文档闭环与最终交付（一致性 / 完整性 / 可读性）

- **目标**：清掉调研期遗留的配置漂移，补齐 README 已引用却缺失的文档，
  统一 1–20 轮编号，并输出最终版本与交付物。
- **改动**：
  1. `core/config.py`：新增 `VALID_ENGINES` / `VALID_LANGUAGES` 常量，合法引擎由
     `("auto", "sensevoice", "firered", "paraformer", "vosk")` 修正为
     `("auto", "qwen3", "sensevoice", "paraformer")`；新增两条一致性测试，
     断言白名单与 `engines.base.SPECS` 完全一致、Qwen3 设置保存后不被重置、
     已废弃的 `firered` / `vosk` 被拒绝。
  2. `.gitignore` 放行 `models/manifest.json`，新增 `models/README.md`
     （下载脚本参数、manifest 作用、上游许可边界）；修正 README 中 ffmpeg 位置
     （便携版在 `_internal\ffmpeg.exe`）与 `models/` 目录说明。
  3. 新增 `docs/ARCHITECTURE.md`（分层、可插拔引擎、自动降级、长音频、异常模型、
     线程模型、发行形态）与 `docs/TEST_REPORT.md`（15 模块 132 项用例、覆盖矩阵、
     端到端实测、性能数据、23 项缺陷修复、校验和、复现步骤）。
  4. 统一迭代轮次编号为 1–20，逐轮补齐「目标 / 改动 / 理由 / 自检」，
     并新增下方「最终版本相对初始版本的整体提升」。
  5. 以最终源码重建 `VoxScribe-Standalone.exe`（332.1 MB）与
     `VoxScribe-Portable-win64.zip`（1138.3 MB），生成 `SHA256SUMS.txt`。
  6. 交付：GitHub 仓库 `regdiliKUN/VoxScribe-Offline-ASR` + `v1.0.0` Release，
     附上两个发行包与校验和，README 提供下载链接与使用方法。
- **理由**：第 20 轮前，用户在设置里选 Qwen3 保存后会被 `clamp()` 静默改回 `auto`
  （白名单停留在早期打擂阶段，缺 `qwen3` 且含两个已淘汰候选），属于真实功能性缺陷；
  fresh clone 时缺 `models/manifest.json` 会让 `spec_source()` 直接抛
  `FileNotFoundError`；README 引用的 `TEST_REPORT.md` 此前并不存在；
  文档与产物布局不一致会误导排障。这些都不改变核心结构，只是把一致性补齐。
- **自检**：
  - `pytest tests/test_config_history.py tests/test_build.py -q` → **18 passed**；
    全量 `pytest tests -q` → **132 passed / 0 failed**（121.02 s，退出码 0）。
  - 两种发行版均以最终源码重新构建；`--cli --selftest` 分别报告
    `frozen=true` / `model_integrity=ok` 与三引擎可用；SHA-256 已固定并写入
    `docs/TEST_REPORT.md`。
  - 逐轮编号与每轮四要素复查完毕，1–20 轮无跳号、无凑数轮；
    README 相对链接目标全部存在。

<!-- ITERATION_END -->

---

## 最终版本相对初始版本的整体提升

**最终版本：v1.0.0**，代码仓库 `regdiliKUN/VoxScribe-Offline-ASR`，
发行包与下载方式见 [`README.md`](../README.md)。

| 维度 | 基线 v0 | 最终 v1.0.0 |
|---|---|---|
| 功能 | 8 个骨架文件，仅路径/配置/日志/异常类型 | 完整 GUI + CLI：录音、拖放导入、三引擎识别、时间戳、复制、四种格式导出、历史、设置、快捷方式 |
| 识别能力 | 无 | Qwen3-ASR 0.6B（精度）/ SenseVoice / Paraformer 三层自动降级；39 样本 CER **0.0000**；静音零幻听 |
| 音频处理 | 无 | 任意格式统一 16 kHz 单声道 float32，libsndfile + ffmpeg 双通道解码，Silero/能量 VAD 长音频分段 |
| 导出 | 无 | TXT / SRT / JSON / Markdown，UTF-8 BOM / UTF-8 / GB18030，原子写、文件名清洗、时间戳进位 |
| 交付形态 | 无 | 单文件 EXE 332.1 MB（双击即用）+ 完整便携版 ZIP 1138.3 MB（含 Qwen3）+ SHA-256 校验和 |
| 快捷方式 | 仅创建骨架 | COM / PowerShell / pylnk3 三层兜底，目标回读校验，工作目录指向 EXE 父目录，右键「打开文件所在位置」直达 |
| 稳定性 | 无验证 | 类型化异常、崩溃安全配置、损坏 SQLite 自动隔离重建、模型大小/SHA-256 校验、引擎故障转移、回调线程优雅停止、COM 生命周期修复 |
| 性能 | 无 | MP3 走 libsndfile 比外部 ffmpeg 快 10.5×；SenseVoice ≈47× 实时、Paraformer ≈125× 实时；便携版去掉 105 MB 冗余 |
| 测试 | 0 项 | **132 项自动化用例 / 15 模块** + 20 轮迭代自检 + 真实麦克风录音 + 两种打包 EXE 端到端 + 准确率回归 |
| 文档与合规 | 无 | README、RESEARCH、ARCHITECTURE、ITERATIONS、TEST_REPORT、MIT LICENSE、NOTICE（12 项上游许可） |
| 可复现性 | 无 | 模型下载脚本、评测脚本、构建脚本、标注音频全部入库；一条命令重建并跑完 132 项测试 |

**总体结论**：从"不能录音、不能识别、不能导出、无界面、无测试、无打包"的骨架，
提升为一款可直接双击运行、完全离线、精度可回归、异常可恢复、源码与产物均可复现的
Windows 桌面软件。20 轮迭代中每一轮都至少针对一个质量维度做了实质改动并当场自检，
期间发现并修复 23 类问题；最终全量回归 132 passed / 0 failed。



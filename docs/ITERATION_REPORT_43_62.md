# VoxScribe 深度质量迭代报告（第 43–62 轮）

> 本报告是「不少于 20 轮迭代完善」任务的第二批独立交付物。
> 逐轮的完整「目标 → 改动 → 理由 → 自检」记录见 [`ITERATIONS.md`](ITERATIONS.md) 第 43–62 轮。
> 版本：v1.0.2 → **v1.0.3（源码）**；基线与最终均在真实 Python 3.13 / Windows / 真实模型环境验证。

## 一、任务要求与执行情况

| 要求 | 执行 |
|---|---|
| 累计不少于 20 轮 | 完成 **20 轮**（第 43–62 轮），项目累计 62 轮 |
| 每轮明确目标 / 改动 / 理由 / 自检 | 逐轮四要素齐全，均当场跑测试自检 |
| 每轮至少一个质量维度实质提升 | 覆盖正确性、完整性、可读性、性能、边界情况、一致性六维度 |
| 找不到优化点时说明原因并深层改进 | 本批每轮均找到可验证的实质改进点，无需降级处理 |
| 保持核心需求与结构稳定，不凑数 | 20 轮均为真实缺陷修复或可验证增强，无 cosmetic 凑数改动 |
| 输出最终版本 + 迭代记录 + 整体提升 | 最终 v1.0.3 源码；本报告 + ITERATIONS.md；见第四节 |

## 二、基线

- 上一批交付：**148 passed / 0 failed**（v1.0.2，源码 131 + 打包/硬件 17）。
- 本批起点：v1.0.2 源码，工作树包含第 23–42 轮全部改动。

## 三、逐轮改动摘要

| 轮 | 维度 | 改动摘要 | 自检结果 |
|---|---|---|---|
| 43 | 正确性/完整性 | 修复断点续传 Range 头 `bytes-{size}=` → RFC 9110 `bytes={size}-`，仅 `206` 响应追加 | 7 passed |
| 44 | 边界/正确性 | tar 解压跳过 symlink/目录等非普通成员，路径 `resolve()` 防穿越；首轮误报缺失成员后修复 | 8 passed |
| 45 | 正确性/边界 | SRT 时间戳用单调游标规范化，消除重叠与倒退，最小段长 0.2 秒 | 18 passed |
| 46 | 正确性/完整性 | 评测脚本把引擎失败样本强制 `cer=1.0` 并标记 `failed`，不再用错误文本相似度虚低 CER | 1 passed |
| 47 | 边界/正确性 | `HistoryDB.list/search` 引入 `_safe_int()`，limit/offset 对 `"bad"`/`None`/NaN 免疫 | 16 passed |
| 48 | 一致性/边界 | CLI `--engine` 用 `VALID_ENGINES` 校验，非法值输出 `VOX_ENGINE` JSON 且退出码 2 | 9 passed |
| 49 | 一致性/完整性 | selftest 模型可用性统一为「存在且无完整性问题」，新增 `integrity_issues` 字段 | 12 passed |
| 50 | 一致性/正确性 | `EngineManager.invalidate()` 同步清空 `_engines`，避免修复模型后仍复用 unhealthy 实例 | 11 passed |
| 51 | 一致性/正确性 | 新建 `test_logging.py`，日志级别切换同步 console handler（排除 RotatingFileHandler） | 1 passed |
| 52 | 边界/正确性 | `load_audio()` 的 `stat()` 失败包装为 `AudioError`，不再向 GUI 抛裸 `OSError` | 16 passed |
| 53 | 可读性/正确性 | Markdown 正文与时间戳用动态围栏代码块逐字保留，来源/警告字段转义 | 19 passed |
| 54 | 性能/完整性 | `TranscriptResult.as_dict()` 用 `fields()` 直接构造，去掉双重深拷贝；首轮漏导入 `fields` 后修复 | 11 passed |
| 55 | 正确性/性能 | **【重大】修复 Silero 神经 VAD 从未真正启用**：`window_size` 方法/属性双兼容 + 按参数键控模型缓存，5 次调用 71.8→13.1 ms | 30 passed |
| 56 | 正确性/边界 | VAD 缓存加 `_SILERO_LOCK`，6 线程并发冷启动只创建一个模型实例 | 19 passed |
| 57 | 边界/正确性 | `find_model_file()` 拒绝绝对路径与 `..` 穿越，受限在模型根目录内 | 9 passed |
| 58 | 一致性/可读性 | 抽出 `SHORTCUT_DESCRIPTION` 常量，COM / PowerShell / pylnk3 三策略悬停提示统一 | 11 passed |
| 59 | 性能/一致性 | `verify_quick(manifest=None)` 接受外部清单，`verify_full()` 只读一次 manifest，消除读取竞态 | 13 passed |
| 60 | 一致性/边界 | 最近文件按 Windows 大小写不敏感去重，忽略空白/非字符串路径 | 17 passed |
| 61 | 一致性/边界 | 无后缀导出路径按格式补扩展名；**已存在目录不改写**，避免掩盖错误用法 | 20 passed |
| 62 | 一致性/完整性 | 版本升至 1.0.3；全量回归捕获第 61 轮跨轮回归（目录路径被"救活"破坏第 35 轮契约），当场修复并加断言 | 29 + 167 passed |

过程透明：第 44、54、62 轮出现「首轮自检失败 → 定位根因 → 修复 → 复检通过」；
第 62 轮的全量回归还捕获到第 61 轮引入的跨轮回归并当场修复，均已如实记录于 ITERATIONS.md。

## 四、最终版本相对初始版本的整体提升

| 维度 | 初始（基线 v1.0.2） | 最终（v1.0.3 源码） |
|---|---|---|
| 正确性 | 断点续传损坏模型、神经 VAD 从未启用、SRT 时间戳倒退、selftest 口径矛盾、评测失败样本虚低分 | 全部修复；长音频分段恢复设计中的神经 VAD 能力；167 passed / 0 failed |
| 完整性 | tar symlink 中断安装、stat 失败裸异常、引擎实例失效不彻底 | 安全跳过非普通成员；音频链路全类型化异常；缓存失效彻底 |
| 可读性 | Markdown 正文被渲染器解释、三策略快捷方式提示语言不一 | 正文逐字保留；用户可见描述统一且常量化 |
| 性能 | VAD 每次重建、manifest 双读、`as_dict` 双重深拷贝 | VAD 缓存 71.8→13.1 ms；manifest 单次读取；序列化无冗余拷贝 |
| 边界情况 | 绝对路径/目录穿越、分页非法类型、CLI 引擎拼写静默降级、无后缀导出 | 全部有确定回退或明确错误；目录边界不误判 |
| 一致性 | selftest 与可用列表矛盾、Windows 路径重复、导出目录边界破坏既有契约 | 各口径统一；跨轮回归由全量回归拦截并锁定测试 |
| 测试 | 148 passed / 0 failed（15 个模块） | **167 passed / 0 failed**（16 个模块，源码 150 + 打包/硬件 17），净增 19 项 |

## 五、复现命令

```bat
cd I:\workbuddyAI\2026-11-15-04-52-58\VoxScribe
set PY=I:\workbuddyAI\2026-11-15-04-52-58\.venv\Scripts\python.exe
set QT_QPA_PLATFORM=offscreen
%PY% -m pytest tests -q
%PY% -m pytest tests --collect-only -q
```

## 六、已知项（未改，如实记录）

- `sounddevice` 在 NumPy 2.5 下产生 `data.shape` 的 `DeprecationWarning`（23 条）。该警告来自第三方库内部，
  属无害弃用提示，冻结包运行正常，未通过抑制警告的方式掩盖；待上游 sounddevice 更新后自然消失。
- `dist/` 中的 EXE/ZIP 仍为 v1.0.1（已发布产物），本轮为源码迭代交付，未重新打包上传；
  README 下载链接保持指向真实存在的 v1.0.1 Release。
- 模块数为 16（由 `pytest --collect-only -q` 实测）：前序文档中的「17 模块」为统计笔误，本批已更正。

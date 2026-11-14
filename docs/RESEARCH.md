# 离线 ASR 选型调研与实测对比

> 调研时间：2026-11-15。目标：在保证"独立 EXE / 完全离线 / CPU 可跑"的前提下，
> 选准确率最高且稳定可维护的方案。所有结论以**本地自建评测集实测**为准，公开资料仅作交叉验证。

## 1. 联网调研结论

| 来源 | 关键结论 |
|---|---|
| [腾讯云开发者社区《中文语音识别该用谁？6 个开源模型 + 2 个配套工具》](https://cloud.tencent.com/developer/article/2642961) | 统一基准下 FireRedASR2 / Qwen3-ASR / Fun-ASR 普通话平均 CER 2.89%–4.16%；Paraformer-zh AISHELL-1 CER 1.95%，SenseVoice-Small ≈3.0%，Whisper-large-v3 AISHELL-1 5.14% / WenetSpeech meeting **18.87%**。SenseVoice-Small 处理 10 秒音频约 70 ms，CPU ≈17× 实时，q8 量化约 250 MB。端侧部署覆盖最广的是 sherpa-onnx。 |
| [《中文语音识别选型 2026：FunASR 凭什么排在 Whisper 前面？》](https://baijiahao.baidu.com/s?id=1873332432438787197) | 中文生产环境不建议默认 Whisper；FunASR 全家桶的 VAD / 标点 / 热词配套最完整；SenseVoice q8 ≈250 MB、CPU ≈17× 实时；**FunASR 内嵌 ModelScope SDK 在纯内网可能联网校验卡住**，应选 sherpa-onnx / llama.cpp 这类不带网络请求的运行时。 |
| GitHub 仓库活跃度（`gh api`） | `k2-fsa/sherpa-onnx` 15.9k stars、Apache-2.0、持续提交；`modelscope/FunASR` 21.0k、MIT；`SYSTRAN/faster-whisper` 26.8k、MIT；`alphacep/vosk-api` 15.3k、Apache-2.0；`ggml-org/whisper.cpp` 55.2k、MIT。 |
| [Buzz](https://github.com/chidiwilliams/buzz) / CapsWriter-Offline | 成熟桌面 ASR 应用普遍采用「可插拔后端 + 本地历史 + 统一设置 + 工作线程转写」结构，本项目借鉴该工程分层。 |

**工程决策**：
1. 选 `sherpa-onnx` 作为统一离线运行时（纯 ONNX、无云端校验、Windows 原生、Apache-2.0、
   支持 SenseVoice / Paraformer / Qwen3-ASR / FireRedASR2 / Zipformer 等多种图）。
2. 不选 FunASR Python SDK（依赖重、可能联网校验、打包体积与稳定性差）。
3. 不把 Whisper 作为中文默认（公开 CER 明显劣势），但保留其生态作为背景参考。

## 2. 候选模型清单（k2-fsa/sherpa-onnx `asr-models` release）

| 模型 | 压缩包 | 展开后 int8 权重 | 备注 |
|---|---|---|---|
| SenseVoice-zh-en-ja-ko-yue-int8 **2024-07-17** | 155 MB | 229 MB | 标准多语种版 |
| SenseVoice 2025-09-09 int8 | 158 MB | 227 MB | **粤语微调**（WSYue-ASR），非普通话通用版 |
| Paraformer-zh-small 2024-03-09 | 74 MB | 79 MB | 轻量中文 |
| Paraformer-zh 2023-03-28 | 987 MB | 214 MB int8 | 标准普通话 large |
| Paraformer-zh-int8 2025-10-07 | 217 MB | 228 MB | **四川话微调**（WenetSpeech-Chuan） |
| Zipformer-CTC-zh-int8 2025-07-03 | 287 MB | 351 MB | AISHELL WER 1.74 / WenetSpeech meeting 7.75 |
| FireRedASR2-CTC-int8 2026-02-25 | 496 MB | 740 MB | SOTA 系统的 CTC 分支 |
| **Qwen3-ASR-0.6B-int8 2026-03-25** | 837 MB | 839 MB | 22 种方言、多语种、LLM 解码 |
| Vosk-small-cn 0.22 | 42 MB | 66 MB | 传统 Kaldi 轻量基线 |

> 重要发现：**"版本号更新"不等于"普通话更准"**——2025 版 SenseVoice 是粤语微调、
> 2025 版 Paraformer 是四川话微调。只看日期选型会踩坑，必须实测。

## 3. 自建评测集与方法

- **27 条干净样本**：Edge 神经 TTS（3 种中文音色 + 英文音色、语速 ±25%）、
  Windows SAPI 本地中文音色，全部带精确参考文本。
- **13 条高难度样本**：SNR 5/0/-5 dB 加性噪声、调制噪声、300–3400 Hz 电话带 + 8 kHz、
  16 kbps MP3 往返、混响、1.3 倍速、重叠人声、DC 偏移削波、44.1 kHz 非平衡立体声、
  纯静音、0.1 秒极短音频；另有一条 60 秒长音频用于分段测试。
- **指标**：字符错误率 CER（NFKC 归一化、去标点、大小写统一、数字规范化后 Levenshtein）、
  实时因子 RTF（解码耗时 / 音频时长）、模型加载耗时、静音幻听次数。
- **统一输入**：所有音频先归一化为 16 kHz 单声道 float32，保证对比公平。

## 4. 实测结果（39 条样本 / 9 个引擎）

| 引擎 | CER(all) | CER(中文核心) | 高难度子集 CER | RTF | 加载(s) | 静音幻听 |
|---|---:|---:|---:|---:|---:|---:|
| **qwen3-asr-0.6b-2026** | **0.0000** | **0.0000** | **0.0000** | 0.127 | 2.25 | **0** |
| paraformer-small-2024 | 0.0012 | 0.0016 | 0.0000 | **0.0079** | 1.25 | 1 |
| paraformer-large-2023 | 0.0012 | 0.0016 | 0.0000 | 0.0165 | 2.78 | 1 |
| sensevoice-2025-yue | 0.0060 | 0.0016 | 0.0000 | 0.0215 | 1.73 | 1 |
| fireredasr2-ctc-2026 | 0.0072 | 0.0064 | 0.0096 | 0.149 | 1.00 | 2 |
| sensevoice-2024 | 0.0085 | 0.0016 | 0.0000 | 0.0212 | 1.98 | 2 |
| paraformer-chuan-2025 | 0.0772 | 0.0016 | 0.0000 | 0.0158 | 2.29 | 2 |
| zipformer-ctc-2025 | 0.1802 | 0.0016 | 0.0000 | 0.0253 | 4.31 | 0 |
| vosk-cn-small | 0.2721 | 0.0779 | 0.1675 | 0.2912 | 0.37 | 0 |

补充说明：
- `CER(all)` 的主要差异来自**英文样本与 ITN 规整**。例如 SenseVoice 把"百分之十五"
  写成 `15%`，在我们的字符级归一化下被计为差异，属于文本规整而非听错；中文核心集上各
  sherpa-onnx 引擎几乎都是 0.0016（仅一处"地/的"之差）。
- Zipformer-CTC / Vosk 在英文上输出 `<unk>` 或中文乱码，故 `CER(all)` 高；Vosk 在
  中文与高难度噪声上也明显落后，且 RTF 最高，因此**不纳入发行版**。
- Qwen3-ASR 全部高难度样本逐字正确，且静音/极短音频输出为空（不幻听），是唯一在
  鲁棒性上无短板的模型。

## 5. 最终架构决策

| 决策 | 理由 |
|---|---|
| 默认 `auto` → Qwen3（存在时） | 实测精度与鲁棒性第一；CPU 上仍有 ≈8× 实时，可接受 |
| 保留 SenseVoice 作为均衡引擎 | 229 MB、≈47× 实时、自带标点与 ITN、多语种；单文件版默认 |
| 保留 Paraformer-small 作为轻量引擎 | 79 MB、≈125× 实时，低配机器与长音频批处理 |
| 不打包 FireRedASR2 / Zipformer-CTC | 体积 740 MB / 351 MB，实测未优于 Qwen3，增加发行包负担 |
| 三层自动降级 | 模型缺失、截断、运行时异常时自动切换，避免单点故障 |
| VAD 分段（Silero，失败回退能量 VAD） | Qwen3 单次输出有 token 上限，长音频必须切段；同时给出 SRT 时间戳 |

## 6. 可复现

评测脚本与原始数据保存在开发工作区；仓库内保留等价的精简评测集
（`tests/fixtures/`）与准确率回归测试（`tests/test_accuracy.py`），
运行 `pytest tests/test_accuracy.py -q` 即可复核主要结论。

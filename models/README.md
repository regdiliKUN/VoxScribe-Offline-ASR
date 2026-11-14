# 离线模型目录

本目录**只把 `manifest.json` 纳入版本控制**。模型权重体积较大（完整包约 1.2 GB），
不进 Git 仓库：请从 GitHub Release 直接下载打包好的 EXE / ZIP，或用脚本重建本目录。

## 从源码构建时重建模型

```bat
.venv\Scripts\python.exe scripts\download_models.py --all
.venv\Scripts\python.exe scripts\download_models.py --verify
```

- `--all`：SenseVoice + Paraformer + Qwen3-ASR + Silero VAD（约 1.2 GB）
- `--light`：仅轻量引擎（约 310 MB），用于构建单文件 EXE
- `--only <key>`：只下载指定引擎
- `--verify`：按 `manifest.json` 做 SHA-256 全量校验

下载源为 `k2-fsa/sherpa-onnx` 官方 release 与 Silero VAD 官方仓库，
脚本支持断点续传、tar.bz2 抽取，完成后重新生成 `manifest.json`。

## manifest.json 的作用

记录每个模型/资源文件的 `size` 与 `sha256`：

- 启动时 `verify_quick()` 按文件大小做毫秒级快速校验，提前发现被截断的下载；
- `--cli --verify-models` 做 SHA-256 深度校验；
- 引擎管理器会**排除**大小或哈希不符的模型，自动降级到可用引擎，
  避免损坏的 ONNX 权重直接让 ONNX Runtime 崩溃。

## 许可

各模型遵循各自的上游许可（Apache-2.0 / MIT / 模型专用许可等），
详见仓库根目录 [`NOTICE.md`](../NOTICE.md)。模型权重不随 MIT 代码许可一并再授权。

> 已发行的两个版本都自带所需模型，**终端用户无需执行本目录的任何操作**。

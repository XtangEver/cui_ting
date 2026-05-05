# CLAUDE.md

本文件为 Claude Code (claude.ai/code) 在此仓库中工作时提供指导。

## 项目概述

cui_ting 是一个视频转录与智能摘要工具，支持从 Bilibili/YouTube 下载音频，使用 Whisper（MLX，适配 Apple Silicon）进行转录，并通过 LLM 生成结构化文本摘要。

## 命令

```bash
# 激活环境并运行
conda activate cui_ting && python cli.py

# 安装依赖
pip install -r requirements.txt
```

## 架构

项目采用流水线架构：

```
cli.py → VideoSummarizer.process() → AudioDownloader → Transcriber → LLMProcessor → TextProcessor
```

**核心模块：**
- `cli.py` — 入口文件。读取 `input_data.json` 并批量处理任务。
- `core/summarizer.py` — 主编排器。协调流水线：下载 → 转录 → 精炼。处理断点续传逻辑（检查已有文件）。
- `core/downloader.py` — 使用 yt-dlp 下载音频。处理 Bilibili/YouTube cookies、多分段视频及 FFmpeg 合并。
- `core/transcriber.py` — MLX Whisper 转录，支持 Metal GPU 加速。
- `core/llm_processor.py` — LLM API 调用，用于文本精炼/去噪。
- `core/text_processor.py` — 文本分块与结果合并。
- `core/config.py` — 配置管理，从 config.yaml 和 .env 加载。

**配置文件：**
- `config.yaml` — 模型名称白名单、Whisper 路径、分块设置、输入输出路径
- `.env` — 模型敏感信息（API Key、Base URL、模型名称）
- `input_data.json` — 批量任务列表（文件夹名 → 视频URL）

## 关键模式

- **断点续传**：重新运行时，工具会检查已有文件：
  - `source*.mp3` → 跳过下载
  - `*_raw.md` → 跳过转录
  - `*_refined.md` → 跳过 LLM 处理
- **目录结构**：输出支持扁平或嵌套形式（`output_dir/video_id/`）。代码会同时搜索两种位置。
- **Cookie 管理**：`cookie/` 目录下按平台存放 cookies，根据 URL 自动选择。
- **模型配置**：模型通过环境变量统一配置（格式：`{NAME}_API_KEY` / `{NAME}_BASE_URL` / `{NAME}_MODEL`），config.yaml 中仅声明启用的模型名称列表。

## 数据流

1. 从 URL 提取视频 ID
2. 下载音频到输出目录
3. 转录为 `source_raw.md`
4. 将文本分块，每块通过 LLM 处理
5. 合并结果为 `source_refined.md`

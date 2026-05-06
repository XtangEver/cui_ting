# CLAUDE.md

本文件为 Claude Code (claude.ai/code) 在此仓库中工作时提供指导。

## 项目概述

cui_ting 是一个视频转录与智能摘要工具，支持从 Bilibili/YouTube 下载音频，使用 Whisper（MLX，适配 Apple Silicon）进行转录，并通过 LLM 生成结构化文本摘要。提供 CLI 批量处理和 Web 前端两种使用方式。

## 命令

```bash
# CLI 批量处理
conda activate cui_ting && python cli.py

# Web 前端（局域网访问）
conda activate cui_ting && uvicorn web.app:app --host 0.0.0.0 --port 8000

# 安装依赖
pip install -r requirements.txt
```

## 架构

项目采用流水线架构：

```
CLI: cli.py → VideoSummarizer.process() → AudioDownloader → Transcriber → LLMProcessor → TextProcessor
Web: 浏览器 → FastAPI API → 任务队列 → VideoSummarizer.process() → SQLite 存储
```

**核心模块：**
- `cli.py` — CLI 入口，读取 `input_data.json` 批量处理任务。
- `core/summarizer.py` — 主编排器。协调流水线：下载 → 转录 → 精炼。处理断点续传逻辑。
- `core/downloader.py` — 使用 yt-dlp 下载音频。处理 Bilibili/YouTube cookies、多分段视频及 FFmpeg 合并。
- `core/transcriber.py` — MLX Whisper 转录，Metal GPU 加速。
- `core/llm_processor.py` — LLM API 调用，文本精炼/去噪（OpenAI 兼容格式）。
- `core/text_processor.py` — 文本分块与结果合并。
- `core/config.py` — 配置管理，从 config.yaml + .env 加载。

**Web 模块：**
- `web/app.py` — FastAPI 应用入口，API 路由 + 后台 worker 线程。
- `web/database.py` — SQLAlchemy ORM，Task 模型 + CRUD 操作。
- `web/static/` — 前端文件（HTML + CSS + JS），marked.js 渲染 Markdown。

**配置文件：**
- `config.yaml` — 模型名称白名单、Whisper 路径、分块设置、输入输出路径。
- `.env` — 模型敏感信息（API Key、Base URL、模型名称），不提交到 Git。
- `input_data.json` — CLI 批量任务列表（文件夹名 → 视频URL）。

## 关键模式

- **模型配置**：环境变量统一管理（`{NAME}_API_KEY` / `{NAME}_BASE_URL` / `{NAME}_MODEL`），config.yaml 仅声明启用的模型名称列表。新增模型只需 .env + config.yaml 两个文件。
- **断点续传**：重新运行时检查已有文件：`source*.mp3` 跳过下载、`*_raw.md` 跳过转录、`*_refined.md` 跳过 LLM 处理。
- **Web 异步任务**：单 worker 线程 + queue.Queue 顺序执行，避免 Metal GPU 资源冲突。前端每 3 秒轮询状态。
- **Cookie 管理**：`cookie/` 目录下按平台存放，根据 URL 自动选择。

## 数据流

**CLI 模式：**
1. 从 URL 提取视频 ID
2. 下载音频到输出目录
3. 转录为 `source_raw.md`
4. 将文本分块，每块通过 LLM 处理
5. 合并结果为 `source_refined.md`

**Web 模式：**
1. 浏览器提交 B站链接 → POST /api/tasks
2. 创建 SQLite 任务记录 → 入队
3. Worker 线程调用 VideoSummarizer.process() → 更新状态
4. 前端轮询任务状态 → 完成后展示 Markdown 渲染结果

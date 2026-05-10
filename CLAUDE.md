# CLAUDE.md

本文件为 Claude Code (claude.ai/code) 在此仓库中工作时提供指导。

## 项目概述

cui_ting 是一个视频转录与智能摘要工具，支持从 Bilibili/YouTube 下载音频，使用 Whisper（MLX，适配 Apple Silicon）进行转录，并通过 LLM 生成结构化文本摘要。提供 CLI 批量处理和 Web 前端两种使用方式。

## 命令

```bash
# Web 前端 + 外网隧道（一键启动，推荐）
bash start.sh

# 仅启动 Web 前端（局域网访问）
conda activate cui_ting && uvicorn web.app:app --host 0.0.0.0 --port 8000

# CLI 批量处理
conda activate cui_ting && python cli.py

# 停止所有服务
bash stop.sh

# 安装依赖
pip install -r requirements.txt
```

## 架构

项目采用流水线架构：

```
CLI: cli.py → VideoSummarizer.process() → AudioDownloader → Transcriber → LLMProcessor → TextProcessor
Web: 浏览器 → FastAPI API → 任务队列 → VideoSummarizer.process() → SQLite 存储
     └─ SSE 实时推送流水线进度（stage_update / log / complete / task_error）
```

**核心模块：**
- `cli.py` — CLI 入口，读取 `input_data.json` 批量处理任务。
- `core/summarizer.py` — 主编排器。协调流水线：下载 → 转录 → 精炼。支持 `progress_callback` 参数向 Web 层推送进度（含 stage_update、progress、log 事件）。处理断点续传逻辑。
- `core/downloader.py` — 使用 yt-dlp 下载音频。处理 Bilibili/YouTube cookies、多分段视频及 FFmpeg 合并。支持 `progress_callback` 报告下载百分比。
- `core/subtitle_downloader.py` — 平台字幕下载，VTT 解析。字幕优先于 Whisper 转录。
- `core/transcriber.py` — MLX Whisper 转录，Metal GPU 加速。单次阻塞调用，无进度回调。
- `core/llm_processor.py` — LLM API 调用，文本精炼/去噪（OpenAI 兼容格式）。自动过滤 `<think/thinking>` 标签内容，检测提示词泄露。
- `core/text_processor.py` — 文本分块与结果合并。
- `core/timestamp_utils.py` — 时间戳工具。
- `core/config.py` — 配置管理，从 config.yaml + .env 加载。

**Web 模块：**
- `web/app.py` — FastAPI 应用入口。API 路由 + SSE 实时进度 + 后台单 worker 线程。使用 `loop.call_soon_threadsafe` 桥接同步线程到 asyncio 事件循环。队列跟踪（`_queue_order`）提供排队位置。含认证（Cookie session）。
- `web/database.py` — SQLAlchemy ORM，Task 模型（UUID 主键、状态机、raw/refined 文本、tags、model、enable_refine）+ CRUD 操作。含 SQLite 迁移逻辑（`ALTER TABLE` 添加新列）。
- `web/static/index.html` — 两页 SPA（任务列表 + 结果详情），path-based 路由。含标签输入、高级选项（模型选择、精炼开关）、导出工具栏、TOC 侧栏。
- `web/static/style.css` — Indigo 主题 + GitHub 风格 Markdown，移动端适配（安全区域、防 iOS 缩放、44px 触控目标）。
- `web/static/app.js` — SSE EventSource 集成、流水线进度条（含动画指示器）、日志展示、GitHub 风格 Markdown 渲染（marked.js GFM）、TOC 目录、导出/复制、标签管理、模型选择、分块长文档渲染。

**部署脚本：**
- `start.sh` — 一键启动 uvicorn + SSH 隧道（serveo.net，通过 FlClash 代理 127.0.0.1:7890）。
- `stop.sh` — 停止所有服务进程。

**配置文件：**
- `config.yaml` — 模型名称白名单、Whisper 路径、分块设置、输入输出路径。
- `.env` — 模型敏感信息（API Key、Base URL、模型名称），不提交到 Git。
- `input_data.json` — CLI 批量任务列表（文件夹名 → 视频URL）。

## 关键模式

- **模型配置**：环境变量统一管理（`{NAME}_API_KEY` / `{NAME}_BASE_URL` / `{NAME}_MODEL`），config.yaml 仅声明启用的模型名称列表。新增模型只需 .env + config.yaml 两个文件。
- **断点续传**：重新运行时检查已有文件：`source*.mp3` 跳过下载、`*_raw.md` 跳过转录、`*_refined.md` 跳过 LLM 处理。
- **Web 异步任务**：单 worker 线程 + queue.Queue 顺序执行，`_queue_order` 列表跟踪排队位置。避免 Metal GPU 资源冲突。
- **SSE 实时进度**：worker 线程通过 `progress_callback` 回调触发 SSE 事件，事件类型：`stage_update`（流水线阶段变更）、`progress`（进度百分比+详情，含下载/转录/精炼各阶段）、`log`（关键日志）、`complete`（完成）、`task_error`（失败）。前端通过 EventSource 接收。Whisper 转录阶段使用 indeterminate 动画进度条（MLX Whisper 无进度回调）。
- **思考内容过滤**：`LLMProcessor._call_llm()` 使用 `re.DOTALL` 正则自动剥离 `<think/thinking>` 标签。同时检测提示词泄露（log warning）。
- **任务标签**：Task.tags 字段存储 JSON 数组字符串，前端解析为 tag chip 显示，支持按标签筛选。
- **外网访问**：通过 SSH 隧道连接 serveo.net，经由 FlClash 代理（SOCKS5/HTTP，127.0.0.1:7890）绕过 TUN 设备。每次启动生成随机 URL。
- **Cookie 管理**：`cookie/` 目录下按平台存放，根据 URL 自动选择。
- **前端路由**：两页 SPA，`/` 为任务列表，`/result/{task_id}` 为结果详情。服务端对未知路径回退 index.html。

## 数据流

**CLI 模式：**
1. 从 URL 提取视频 ID
2. 下载音频到输出目录
3. 字幕优先获取文本，无字幕时 fallback 到 Whisper 转录为 `source_raw.md`
4. 将文本分块，每块通过 LLM 处理
5. 合并结果为 `source_refined.md`

**Web 模式：**
1. 浏览器提交 B站链接 → POST /api/tasks
2. 创建 SQLite 任务记录 → 入队
3. Worker 线程调用 VideoSummarizer.process(progress_callback) → 更新状态
4. SSE 实时推送流水线进度（下载 → 转录 → 精炼）和关键日志
5. 前端 EventSource 接收事件 → 更新进度指示器和日志
6. 完成后前端展示 Markdown 渲染结果

## Web API

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/` | 前端页面（任务列表） |
| GET | `/result/{task_id}` | 前端页面（结果详情） |
| POST | `/api/auth/login` | 登录（Cookie session） |
| GET | `/api/auth/check` | 检查登录状态 |
| POST | `/api/auth/logout` | 退出登录 |
| POST | `/api/tasks` | 提交任务 `{"url": "...", "tags": "", "model": "", "enable_refine": true}` |
| GET | `/api/tasks` | 任务列表（含 `queue_position`、`tags`、`model`） |
| GET | `/api/tasks/{id}` | 任务详情（含 raw/refined 文本） |
| PATCH | `/api/tasks/{id}` | 更新任务（`TaskUpdateRequest`: `title` 和/或 `tags`） |
| DELETE | `/api/tasks/{id}` | 删除任务 |
| GET | `/api/tasks/{id}/stream` | SSE 实时事件流 |
| GET | `/api/models` | 可用模型列表（`name` + `display_name`） |

## 环境要求

- Python >= 3.10
- Apple Silicon Mac（MLX Whisper 依赖）
- FFmpeg（`brew install ffmpeg`）
- FlClash 或其他代理（外网隧道需要，监听 127.0.0.1:7890）
- ssh、nc（系统自带）

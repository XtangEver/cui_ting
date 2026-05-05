# Web 前端设计规格

## 概述

为 cui_ting 视频转录工具添加 Web 前端，支持用户通过浏览器提交 B站视频链接，异步执行转录+LLM精炼流程，在线预览结果并持久化存储。

## 技术栈

- **后端**: FastAPI（Python 异步框架）
- **前端**: 单页 HTML + 原生 JS + CSS
- **数据库**: SQLite + SQLAlchemy ORM
- **Markdown 渲染**: marked.js（CDN 引入）

## 架构

```
浏览器 ──HTTP──→ FastAPI 后端 ──调用──→ core/ 现有模块
   │                  │
   │                  ├── SQLite (任务状态 + 结果存储)
   │                  │
   │                  └── 单线程任务队列 (顺序执行转录任务)
   │
   └── 轮询任务状态 / 获取结果
```

### 核心流程

1. 用户在页面输入 B站链接，点击提交
2. FastAPI 创建任务记录（status=pending），立即返回任务 ID
3. 后台 worker 线程从队列中取任务，调用 `VideoSummarizer.process()` 执行转录+精炼
4. 前端每隔 3 秒轮询任务状态（pending → processing → completed/failed）
5. 完成后前端展示 refined 文本（Markdown 渲染）

## 文件结构

```
web/
├── app.py              # FastAPI 应用入口（从项目根目录启动 uvicorn）
├── database.py         # SQLite ORM 模型 & 数据库操作
├── static/
│   ├── index.html      # 单页面
│   ├── style.css       # 样式
│   └── app.js          # 前端逻辑
```

## 数据库模型

**表 `tasks`：**

| 字段 | 类型 | 说明 |
|------|------|------|
| id | TEXT (UUID) | 主键 |
| url | TEXT | B站视频链接 |
| video_id | TEXT | BV号（用于展示和去重） |
| title | TEXT | 显示标题，默认使用 video_id |
| status | TEXT | pending / processing / completed / failed |
| raw_text | TEXT | 原始转录文本（多分段合并） |
| refined_text | TEXT | LLM 精炼后的文本（多分段合并） |
| error_message | TEXT | 失败时的错误信息 |
| created_at | DATETIME | 创建时间 |
| updated_at | DATETIME | 最后更新时间 |

## API 端点

### GET `/`
返回 `static/index.html` 页面。

### POST `/api/tasks`
提交新任务。

请求体：
```json
{"url": "https://www.bilibili.com/video/BV1xxxxxx"}
```

响应：
```json
{
  "id": "uuid-string",
  "url": "https://www.bilibili.com/video/BV1xxxxxx",
  "video_id": "BV1xxxxxx",
  "title": "BV1xxxxxx",
  "status": "pending",
  "created_at": "2026-05-05T10:00:00"
}
```

### GET `/api/tasks`
获取所有任务列表（按 created_at 倒序）。

响应：
```json
[
  {
    "id": "uuid-string",
    "url": "...",
    "video_id": "BV1xxxxxx",
    "title": "BV1xxxxxx",
    "status": "completed",
    "created_at": "2026-05-05T10:00:00",
    "updated_at": "2026-05-05T10:05:00"
  }
]
```

列表接口不返回 raw_text / refined_text，避免大量数据传输。

### GET `/api/tasks/{id}`
获取单个任务详情，包含 raw_text 和 refined_text。

响应：
```json
{
  "id": "uuid-string",
  "url": "...",
  "video_id": "BV1xxxxxx",
  "title": "BV1xxxxxx",
  "status": "completed",
  "raw_text": "原始转录文本...",
  "refined_text": "精炼后文本...",
  "error_message": null,
  "created_at": "...",
  "updated_at": "..."
}
```

### DELETE `/api/tasks/{id}`
删除任务及其关联的输出文件。

响应：`204 No Content`

## 前端页面

单页面布局，从上到下：

1. **标题栏**: 视频转录工具
2. **输入区**: B站链接文本框 + 提交按钮
3. **任务列表**: 按 created_at 倒序展示所有任务，显示状态图标、标题、时间、操作按钮
4. **结果预览区**: 点击"查看结果"后展示 Markdown 渲染的 refined 文本

**状态图标**: ⏳等待中 / 🔄处理中 / 🟢已完成 / ❌失败

**交互**:
- 提交后输入框清空，新任务出现在列表顶部
- 处理中自动轮询更新状态（每 3 秒），完成后变为绿色并停止轮询
- 点击"查看结果"展开 Markdown 渲染文本
- 支持删除任务

## 后台任务执行

### 并发模型：单 worker 顺序执行

- 使用 `queue.Queue` + 单个后台 worker 线程
- 所有任务入队，worker 逐个消费执行
- 原因：MLX Whisper 占用 Metal GPU，并发转录会导致资源冲突；LLM API 调用也无需并发
- Web API（提交、查询、删除）不受影响，FastAPI 主线程正常响应

### 任务执行流程

1. 任务入队后 status=pending
2. worker 取到任务，status=processing
3. 调用 `VideoSummarizer.process(url=url, output_dir=output_dir)`
   - output_dir = `{config.output_dir}/{task_id}/`
   - 使用 config.yaml 中配置的 cookies_file
4. 成功后：
   - 遍历返回的 `results` 列表，读取每个 result 的 `refined_file` 和 `raw_file`
   - 多分段结果用 `\n\n---\n\n` 分隔符合并
   - 合并后的文本存入 refined_text / raw_text 字段
   - video_id 从 process() 返回值获取，存入 video_id 字段
   - title 默认使用 video_id
5. 失败时：error_message 写入异常信息，status=failed

### Cookie 配置

Web 后端直接使用 `config.yaml` 中的 `cookies_file` 配置，传入 `VideoSummarizer` 构造函数。

### 启动方式

从项目根目录启动：`uvicorn web.app:app --host 0.0.0.0 --port 8000`

确保 `config.yaml` 路径相对于项目根目录正确解析。

## 错误处理

- 提交时验证 URL 格式（必须包含 bilibili.com）
- 任务失败时记录错误信息，前端展示错误详情
- 同一 video_id 允许重复提交（用户可能需要重新处理）

## 新增依赖

```
fastapi>=0.115.0
uvicorn>=0.34.0
sqlalchemy>=2.0.0
```

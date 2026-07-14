# Frontend Redesign & Real-time Logs Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Redesign frontend following `前端参考.html`, add SSE-based real-time pipeline progress, preserve CLI mode, update docs, add production deployment config.

**Architecture:** Backend adds `progress_callback` to `VideoSummarizer.process()`. Worker thread emits events via `loop.call_soon_threadsafe()` to per-task `asyncio.Queue`, consumed by SSE `StreamingResponse`. Frontend is a two-page SPA (task list + result view) with indigo theme.

**Tech Stack:** FastAPI SSE (StreamingResponse), EventSource API, marked.js, asyncio.Queue + threading bridge

---

## Task 1: Add progress_callback to core/summarizer.py

**Files:**
- Modify: `core/summarizer.py`

Add optional `progress_callback` parameter to pipeline methods. CLI mode passes `None` (no change). Web mode passes callback that emits SSE events.

- [ ] **Step 1: Modify `process()` method signature and add callback emissions**

In `core/summarizer.py`, replace the `process()` method (lines 153-188) with:

```python
    def process(self, url: str, model_name: str = None, output_dir: str = None,
                progress_callback=None) -> Dict[str, Any]:
        """Process video: download -> transcribe -> refine."""
        if model_name is None:
            model_name = next(iter(self.app_config.models))

        logger.info("开始处理视频: %s (模型: %s)", url, model_name)

        if progress_callback:
            progress_callback("stage_update", {"stage": "downloading", "status": "active"})

        video_id = AudioDownloader.extract_video_id(url)
        if output_dir is None:
            output_dir = f"output/{video_id}"
        os.makedirs(output_dir, exist_ok=True)

        # Download audio
        existing_audio = self._find_existing_audio_files(output_dir, video_id)
        if existing_audio:
            logger.info("检测到已存在的音频文件，跳过下载: %s", existing_audio)
            if progress_callback:
                progress_callback("log", {"message": "音频已缓存，跳过下载"})
            merged_files = existing_audio
        else:
            _, video_id, merged_files = self.downloader.download_and_merge(url, output_dir=output_dir)

        if progress_callback:
            progress_callback("log", {"message": "下载完成"})
            progress_callback("stage_update", {"stage": "transcribing", "status": "active"})

        # Process each audio segment
        results = []
        for idx, audio_path in enumerate(merged_files, 1):
            result = self._process_part(
                url, audio_path, idx, len(merged_files),
                output_dir, video_id, model_name,
                progress_callback=progress_callback,
            )
            results.append(result)

        if progress_callback:
            progress_callback("stage_update", {"stage": "refining", "status": "done"})

        logger.info("处理完成! 分段数: %d, 输出目录: %s", len(merged_files), output_dir)

        return {
            'video_id': video_id,
            'output_dir': output_dir,
            'results': results
        }
```

- [ ] **Step 2: Modify `_process_part()` to accept and forward callback**

Replace `_process_part()` (lines 128-151) with:

```python
    def _process_part(self, url: str, audio_path: str, idx: int, total: int,
                      output_dir: str, video_id: str, model_name: str,
                      progress_callback=None) -> Dict[str, Any]:
        """Process a single audio segment: transcribe -> [optional] refine."""
        part_basename = os.path.splitext(os.path.basename(audio_path))[0]
        logger.info("处理分段 [%d/%d]: %s", idx, total, part_basename)

        if progress_callback:
            progress_callback("log", {"message": f"正在处理第 {idx}/{total} 部分..."})

        # Stage 1: Acquire timestamped text
        segments = self._acquire_text(url, audio_path, output_dir, video_id, part_basename)

        if progress_callback:
            progress_callback("log", {"message": "转录完成"})
            progress_callback("stage_update", {"stage": "refining", "status": "active"})

        # Stage 2: Refine (optional, controlled by enable_refine)
        refined_file = None
        if self.app_config.enable_refine:
            refined_file = self._refine(
                segments, output_dir, video_id, part_basename, model_name,
                progress_callback=progress_callback,
            )
        else:
            logger.info("  LLM后处理已禁用，跳过精炼步骤")

        return {
            'part_index': idx,
            'audio_path': audio_path,
            'raw_file': os.path.join(output_dir, f"{part_basename}_raw.md"),
            'refined_file': refined_file,
        }
```

- [ ] **Step 3: Modify `_refine()` to emit per-chunk progress**

Replace `_refine()` (lines 97-124) with:

```python
    def _refine(self, segments: list[TimestampedSegment],
                output_dir: str, video_id: str,
                part_basename: str, model_name: str,
                progress_callback=None) -> str:
        """LLM structured refinement."""
        refined_file = os.path.join(output_dir, f"{part_basename}_refined.md")

        found_refined = self._find_file(output_dir, video_id, f"{part_basename}_refined.md")
        if found_refined:
            logger.info("  结构化摘要已存在: %s", found_refined)
            if progress_callback:
                progress_callback("log", {"message": "LLM 结果已缓存，跳过"})
            return found_refined

        chunks = self.text_processor.split_segments(segments)
        logger.info("  文本已分块: %d 块", len(chunks))

        refined_chunks = []
        for i, chunk in enumerate(chunks):
            logger.info("  处理块 %d/%d...", i + 1, len(chunks))
            if progress_callback:
                progress_callback("log", {"message": f"LLM 处理: 第 {i + 1}/{len(chunks)} 块"})
            refined_chunks.append(
                self.llm_processor.structured_refine(chunk, model_name)
            )

        refined_text = self.text_processor.merge_results(refined_chunks)

        with open(refined_file, 'w', encoding='utf-8') as f:
            f.write(f"{REFINED_HEADER}{refined_text}")
        logger.info("  结构化摘要已保存: %s", refined_file)

        if progress_callback:
            progress_callback("log", {"message": "LLM 处理完成"})

        return refined_file
```

- [ ] **Step 4: Verify CLI still works**

Run: `conda run -n cui_ting python -c "from core.summarizer import VideoSummarizer; print('import OK')"`

Expected: `import OK` (no errors)

- [ ] **Step 5: Commit**

```bash
git add core/summarizer.py
git commit -m "feat: add optional progress_callback to VideoSummarizer pipeline"
```

---

## Task 2: Add SSE endpoint and threading bridge to web/app.py

**Files:**
- Modify: `web/app.py` (complete rewrite)

Rewrite `web/app.py` with SSE endpoint, per-task asyncio.Queue, threading bridge (`loop.call_soon_threadsafe`), result page route, and SSE queue pre-creation on task submit.

- [ ] **Step 1: Replace entire `web/app.py`**

Write the following complete file:

```python
import asyncio
import json
import logging
import os
import queue
import re
import shutil
import threading

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from core.config import ConfigManager
from core.summarizer import VideoSummarizer
from web.database import (
    Task, init_db, create_task, get_task, list_tasks,
    update_task, delete_task,
)

logger = logging.getLogger(__name__)

# --- App setup ---

BASE_DIR = os.path.dirname(os.path.dirname(__file__))
STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")

app = FastAPI(title="cui_ting 视频转录工具")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

init_db()

_config_manager = ConfigManager(os.path.join(BASE_DIR, "config.yaml"))
_app_config = _config_manager.get_app_config()

_summarizer = VideoSummarizer(
    config_path=os.path.join(BASE_DIR, "config.yaml"),
    cookies_file=_app_config.cookies_file,
)

_task_queue: queue.Queue = queue.Queue()

# --- SSE infrastructure ---

_event_loop: asyncio.AbstractEventLoop | None = None
_sse_queues: dict[str, asyncio.Queue] = {}


@app.on_event("startup")
async def _capture_loop():
    global _event_loop
    _event_loop = asyncio.get_running_loop()


def _emit_sse(task_id: str, event_type: str, data: dict):
    """Thread-safe SSE event emission from worker thread."""
    q = _sse_queues.get(task_id)
    if q and _event_loop:
        _event_loop.call_soon_threadsafe(
            q.put_nowait, {"type": event_type, "data": data}
        )


# --- Background worker ---


def _worker():
    while True:
        task_id = _task_queue.get()
        try:
            task = get_task(task_id)
            if not task:
                continue
            update_task(task_id, status="processing")

            output_dir = os.path.join(_app_config.output_dir, task_id)
            os.makedirs(output_dir, exist_ok=True)

            def progress_callback(event_type, data):
                _emit_sse(task_id, event_type, data)

            result = _summarizer.process(
                url=task.url,
                output_dir=output_dir,
                progress_callback=progress_callback,
            )

            # Collect results from all parts
            raw_parts = []
            refined_parts = []
            for r in result.get("results", []):
                raw_path = r.get("raw_file")
                if raw_path and os.path.exists(raw_path):
                    with open(raw_path, "r", encoding="utf-8") as f:
                        raw_parts.append(f.read())
                refined_path = r.get("refined_file")
                if refined_path and os.path.exists(refined_path):
                    with open(refined_path, "r", encoding="utf-8") as f:
                        refined_parts.append(f.read())

            raw_text = "\n\n---\n\n".join(raw_parts)
            refined_text = "\n\n---\n\n".join(refined_parts)

            update_task(
                task_id,
                status="completed",
                raw_text=raw_text,
                refined_text=refined_text,
                video_id=result.get("video_id", task.video_id),
                title=result.get("video_id", task.title),
            )

            _emit_sse(task_id, "complete", {"task_id": task_id})

        except Exception as e:
            logger.exception("Task %s failed", task_id)
            update_task(task_id, status="failed", error_message=str(e))
            _emit_sse(task_id, "task_error", {"message": str(e)})
        finally:
            _task_queue.task_done()
            _sse_queues.pop(task_id, None)


threading.Thread(target=_worker, daemon=True).start()


# --- Request / Response schemas ---

class TaskCreateRequest(BaseModel):
    url: str


# --- API routes ---


@app.get("/")
def index():
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))


@app.get("/result/{task_id}")
def result_page(task_id: str):
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))


@app.post("/api/tasks")
def api_create_task(req: TaskCreateRequest):
    if "bilibili.com" not in req.url:
        raise HTTPException(status_code=400, detail="请输入有效的B站链接")

    match = re.search(r"(BV[a-zA-Z0-9]+)", req.url)
    video_id = match.group(1) if match else ""

    task = create_task(url=req.url, video_id=video_id)

    # Pre-create SSE queue before enqueuing
    _sse_queues[task.id] = asyncio.Queue()
    _task_queue.put(task.id)

    return _task_to_dict(task, include_content=False)


@app.get("/api/tasks")
def api_list_tasks():
    tasks = list_tasks()
    return [_task_to_dict(t, include_content=False) for t in tasks]


@app.get("/api/tasks/{task_id}/stream")
async def api_stream_task(task_id: str):
    task = get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")

    # If task already terminal, send final event immediately
    if task.status == "completed":
        async def _done():
            yield 'event: complete\ndata: {"task_id": "%s"}\n\n' % task_id

        return StreamingResponse(_done(), media_type="text/event-stream")

    if task.status == "failed":
        msg = (task.error_message or "").replace('"', '\\"')
        async def _failed():
            yield 'event: task_error\ndata: {"message": "%s"}\n\n' % msg
        return StreamingResponse(_failed(), media_type="text/event-stream")

    # Get or create queue for active task
    q = _sse_queues.get(task_id)
    if not q:
        q = asyncio.Queue()
        _sse_queues[task_id] = q

    async def event_generator():
        try:
            while True:
                event = await asyncio.wait_for(q.get(), timeout=300)
                data_json = json.dumps(event["data"], ensure_ascii=False)
                yield f"event: {event['type']}\ndata: {data_json}\n\n"
                if event["type"] in ("complete", "task_error"):
                    break
        except asyncio.TimeoutError:
            yield 'event: task_error\ndata: {"message": "连接超时"}\n\n'
        finally:
            _sse_queues.pop(task_id, None)

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@app.get("/api/tasks/{task_id}")
def api_get_task(task_id: str):
    task = get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    return _task_to_dict(task, include_content=True)


@app.delete("/api/tasks/{task_id}", status_code=204)
def api_delete_task(task_id: str):
    task = get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")

    output_dir = os.path.join(_app_config.output_dir, task_id)
    if os.path.exists(output_dir):
        shutil.rmtree(output_dir, ignore_errors=True)

    # Close any open SSE connection
    q = _sse_queues.pop(task_id, None)
    if q and _event_loop:
        _event_loop.call_soon_threadsafe(
            q.put_nowait, {"type": "task_error", "data": {"message": "任务已删除"}}
        )

    delete_task(task_id)
    return Response(status_code=204)


def _task_to_dict(task: Task, include_content: bool = False) -> dict:
    d = {
        "id": task.id,
        "url": task.url,
        "video_id": task.video_id,
        "title": task.title,
        "status": task.status,
        "error_message": task.error_message,
        "created_at": task.created_at.isoformat() if task.created_at else None,
        "updated_at": task.updated_at.isoformat() if task.updated_at else None,
    }
    if include_content:
        d["raw_text"] = task.raw_text
        d["refined_text"] = task.refined_text
    return d
```

- [ ] **Step 2: Verify app starts**

Run: `conda run -n cui_ting python -c "from web.app import app; print('app OK')"`

Expected: `app OK`

- [ ] **Step 3: Commit**

```bash
git add web/app.py
git commit -m "feat: add SSE endpoint with threading bridge for real-time progress"
```

---

## Task 3: Rewrite frontend HTML

**Files:**
- Modify: `web/static/index.html` (complete rewrite)

Rewrite as a two-page SPA with task list page and result page, following the reference design structure.

- [ ] **Step 1: Replace entire `web/static/index.html`**

```html
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Transcribe - 智能视频转录</title>
    <link rel="stylesheet" href="/static/style.css">
    <script src="https://cdn.jsdelivr.net/npm/marked/marked.min.js"></script>
</head>
<body>
    <!-- Task List Page -->
    <div id="page-list" class="page">
        <div class="glow"></div>
        <div class="container">
            <header>
                <h1>Transcribe</h1>
                <p class="subtitle">将 B 站智慧转化为文字力量</p>
            </header>

            <div class="input-section">
                <div class="input-wrapper">
                    <input type="text" id="url-input" placeholder="粘贴视频链接或输入 BV 号...">
                </div>
                <button class="primary-btn" id="submit-btn">开始转录</button>
            </div>

            <div class="task-list-wrapper">
                <div class="list-header">
                    <span>近期任务</span>
                    <span id="task-count">0 任务</span>
                </div>
                <div id="task-list"></div>
            </div>
        </div>
        <div id="toast-container"></div>
    </div>

    <!-- Result Page -->
    <div id="page-result" class="page" style="display:none;">
        <div class="glow"></div>
        <div class="container result-container">
            <div class="result-header">
                <button class="back-btn" id="back-btn">&larr; 返回</button>
                <h2 id="result-title">结果</h2>
            </div>
            <div class="result-tabs">
                <button class="result-tab active" data-tab="refined">精炼文本</button>
                <button class="result-tab" data-tab="raw">原始转录</button>
            </div>
            <div id="result-content" class="result-content markdown-body"></div>
        </div>
    </div>

    <script src="/static/app.js"></script>
</body>
</html>
```

- [ ] **Step 2: Commit**

```bash
git add web/static/index.html
git commit -m "feat: rewrite index.html with two-page SPA layout"
```

---

## Task 4: Rewrite frontend CSS

**Files:**
- Modify: `web/static/style.css` (complete rewrite)

Adopt the indigo theme from `前端参考.html` and add styles for pipeline progress, log area, and result page.

- [ ] **Step 1: Replace entire `web/static/style.css`**

```css
:root {
    --bg-color: #f8f9fa;
    --surface-color: #ffffff;
    --primary-color: #5e5ce6;
    --primary-hover: #4a48c6;
    --text-main: #1d1d1f;
    --text-muted: #86868b;
    --border-color: #e5e5e7;
    --input-bg: #f5f5f7;
    --radius-lg: 16px;
    --radius-md: 12px;
    --shadow-sm: 0 2px 8px rgba(0, 0, 0, 0.04);
    --shadow-md: 0 12px 32px rgba(0, 0, 0, 0.08);
    --transition-base: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
    --green: #30d158;
    --red: #ff3b30;
    --orange: #ff9f0a;
}

* {
    margin: 0;
    padding: 0;
    box-sizing: border-box;
    -webkit-font-smoothing: antialiased;
}

body {
    font-family: -apple-system, BlinkMacSystemFont, "SF Pro Text", "Helvetica Neue", sans-serif;
    background-color: var(--bg-color);
    color: var(--text-main);
    line-height: 1.5;
    background-image: radial-gradient(#d1d1d6 0.5px, transparent 0.5px);
    background-size: 24px 24px;
}

/* Decorative glow */
.glow {
    position: fixed;
    width: 400px;
    height: 400px;
    background: radial-gradient(circle, rgba(94, 92, 230, 0.05) 0%, transparent 70%);
    z-index: -1;
    top: -100px;
    right: -100px;
}

/* Page visibility */
.page {
    min-height: 100vh;
    display: flex;
    flex-direction: column;
    align-items: center;
    padding: 60px 20px;
}

/* Main container */
.container {
    width: 100%;
    max-width: 560px;
    background: var(--surface-color);
    padding: 40px;
    border-radius: var(--radius-lg);
    box-shadow: var(--shadow-md);
    border: 1px solid rgba(255, 255, 255, 0.7);
}

header {
    margin-bottom: 32px;
    text-align: center;
}

h1 {
    font-size: 24px;
    font-weight: 600;
    letter-spacing: -0.02em;
    margin-bottom: 8px;
}

.subtitle {
    color: var(--text-muted);
    font-size: 14px;
}

/* Input section */
.input-section {
    display: flex;
    gap: 12px;
    margin-bottom: 32px;
}

.input-wrapper { flex: 1; }

input {
    width: 100%;
    padding: 12px 16px;
    border: 1px solid var(--border-color);
    border-radius: var(--radius-md);
    background: var(--input-bg);
    font-size: 15px;
    transition: var(--transition-base);
    outline: none;
}

input:focus {
    background: #fff;
    border-color: var(--primary-color);
    box-shadow: 0 0 0 4px rgba(94, 92, 230, 0.1);
}

button.primary-btn {
    background: var(--primary-color);
    color: white;
    border: none;
    padding: 0 24px;
    border-radius: var(--radius-md);
    font-weight: 500;
    font-size: 15px;
    cursor: pointer;
    transition: var(--transition-base);
    white-space: nowrap;
}

button.primary-btn:hover {
    background: var(--primary-hover);
    transform: translateY(-1px);
}

button.primary-btn:active { transform: translateY(0); }

button.primary-btn:disabled {
    background: #c7c7cc;
    cursor: not-allowed;
    transform: none;
}

/* Task list */
.list-header {
    font-size: 13px;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    color: var(--text-muted);
    margin-bottom: 12px;
    display: flex;
    justify-content: space-between;
}

.task-item {
    display: flex;
    align-items: flex-start;
    padding: 16px;
    border-bottom: 1px solid var(--input-bg);
    transition: var(--transition-base);
    animation: fadeIn 0.4s ease-out forwards;
}

.task-item:last-child { border-bottom: none; }

.task-item:hover {
    background: var(--input-bg);
    border-radius: var(--radius-md);
}

.task-item.clickable { cursor: pointer; }

.task-item.clickable:hover {
    background: rgba(94, 92, 230, 0.04);
}

.task-info { flex: 1; min-width: 0; }

.task-bv {
    font-weight: 500;
    font-size: 15px;
    display: block;
}

.task-meta {
    font-size: 12px;
    color: var(--text-muted);
    margin-top: 4px;
    display: flex;
    align-items: center;
    gap: 8px;
}

/* Status dots */
.status-dot {
    width: 8px;
    height: 8px;
    border-radius: 50%;
    display: inline-block;
    flex-shrink: 0;
}

.status-dot.pending { background: var(--text-muted); }
.status-dot.processing { background: var(--primary-color); animation: pulse 1.5s infinite; }
.status-dot.completed { background: var(--green); }
.status-dot.failed { background: var(--red); }

@keyframes pulse {
    0% { opacity: 1; transform: scale(1); }
    50% { opacity: 0.4; transform: scale(1.2); }
    100% { opacity: 1; transform: scale(1); }
}

/* Pipeline progress indicator */
.pipeline {
    display: flex;
    align-items: center;
    gap: 4px;
    margin-top: 10px;
    font-size: 11px;
    color: var(--text-muted);
}

.pipeline-stage {
    display: flex;
    align-items: center;
    gap: 4px;
}

.pipeline-dot {
    width: 6px;
    height: 6px;
    border-radius: 50%;
    background: var(--border-color);
    transition: var(--transition-base);
}

.pipeline-dot.active {
    background: var(--primary-color);
    animation: pulse 1.5s infinite;
}

.pipeline-dot.done { background: var(--green); }
.pipeline-dot.failed { background: var(--red); }

.pipeline-arrow {
    color: var(--border-color);
    font-size: 10px;
}

/* Log area */
.log-area {
    margin-top: 8px;
    padding: 8px 12px;
    background: var(--input-bg);
    border-radius: 8px;
    font-size: 12px;
    color: var(--text-muted);
    max-height: 80px;
    overflow-y: auto;
    font-family: "SF Mono", Menlo, monospace;
    line-height: 1.6;
}

.log-area:empty { display: none; }

/* Delete button */
.delete-btn {
    background: none;
    border: none;
    color: var(--text-muted);
    cursor: pointer;
    padding: 8px;
    border-radius: 6px;
    transition: var(--transition-base);
    font-size: 13px;
    flex-shrink: 0;
}

.delete-btn:hover {
    background: #ffe5e5;
    color: var(--red);
}

/* Exit animation */
.exit-animation {
    opacity: 0;
    transform: translateX(20px);
    pointer-events: none;
    transition: all 0.3s ease;
}

@keyframes fadeIn {
    from { opacity: 0; transform: translateY(10px); }
    to { opacity: 1; transform: translateY(0); }
}

/* Toast */
#toast-container {
    position: fixed;
    bottom: 30px;
    left: 50%;
    transform: translateX(-50%);
    z-index: 1000;
}

.toast {
    background: #1d1d1f;
    color: white;
    padding: 10px 20px;
    border-radius: 30px;
    font-size: 14px;
    box-shadow: var(--shadow-md);
    margin-bottom: 10px;
    animation: toastIn 0.3s cubic-bezier(0.18, 0.89, 0.32, 1.28);
    transition: opacity 0.3s;
}

@keyframes toastIn {
    from { transform: translateY(100%); opacity: 0; }
    to { transform: translateY(0); opacity: 1; }
}

/* Error message */
.error-msg {
    margin-top: 6px;
    font-size: 12px;
    color: var(--red);
}

/* Empty state */
.empty-state {
    text-align: center;
    color: var(--text-muted);
    padding: 40px 0;
    font-size: 14px;
}

/* --- Result Page --- */
.result-container {
    max-width: 720px;
}

.result-header {
    display: flex;
    align-items: center;
    gap: 12px;
    margin-bottom: 24px;
}

.back-btn {
    background: var(--input-bg);
    border: none;
    padding: 8px 16px;
    border-radius: 8px;
    font-size: 14px;
    cursor: pointer;
    transition: var(--transition-base);
    color: var(--text-main);
}

.back-btn:hover { background: var(--border-color); }

.result-header h2 {
    font-size: 18px;
    font-weight: 600;
    flex: 1;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
}

.result-tabs {
    display: flex;
    gap: 4px;
    background: var(--input-bg);
    border-radius: 8px;
    padding: 3px;
    margin-bottom: 20px;
}

.result-tab {
    flex: 1;
    padding: 8px;
    border: none;
    border-radius: 6px;
    background: transparent;
    font-size: 14px;
    cursor: pointer;
    transition: var(--transition-base);
    color: var(--text-muted);
}

.result-tab.active {
    background: var(--surface-color);
    box-shadow: 0 1px 2px rgba(0, 0, 0, 0.1);
    color: var(--text-main);
}

.result-content {
    font-size: 15px;
    line-height: 1.8;
    max-height: 70vh;
    overflow-y: auto;
}

/* Markdown body */
.markdown-body h2 {
    font-size: 18px;
    font-weight: 600;
    margin: 24px 0 8px;
    padding-bottom: 6px;
    border-bottom: 1px solid var(--border-color);
}

.markdown-body h3 {
    font-size: 16px;
    font-weight: 600;
    margin: 20px 0 6px;
}

.markdown-body p { margin: 8px 0; }

.markdown-body ul, .markdown-body ol {
    margin: 8px 0;
    padding-left: 24px;
}

.markdown-body li { margin: 4px 0; }

.markdown-body hr {
    border: none;
    border-top: 1px solid var(--border-color);
    margin: 16px 0;
}

.markdown-body blockquote {
    border-left: 3px solid var(--primary-color);
    padding-left: 16px;
    color: var(--text-muted);
    margin: 12px 0;
}

.markdown-body code {
    background: var(--input-bg);
    padding: 2px 6px;
    border-radius: 4px;
    font-size: 13px;
}

.markdown-body pre {
    background: var(--input-bg);
    padding: 16px;
    border-radius: 8px;
    overflow-x: auto;
    margin: 12px 0;
}

.markdown-body pre code {
    background: none;
    padding: 0;
}

/* Responsive */
@media (max-width: 480px) {
    .container { padding: 24px; }
    .page { padding: 30px 16px; }
    .input-section { flex-direction: column; }
    button.primary-btn { padding: 12px; }
    .task-item { padding: 12px 8px; }
    .result-container { padding: 24px; }
}
```

- [ ] **Step 2: Commit**

```bash
git add web/static/style.css
git commit -m "feat: rewrite CSS with indigo theme, pipeline progress, and result page"
```

---

## Task 5: Rewrite frontend JavaScript

**Files:**
- Modify: `web/static/app.js` (complete rewrite)

Complete rewrite with SSE integration, client-side routing (path-based), pipeline progress UI, log display, toast notifications, and result page rendering.

- [ ] **Step 1: Replace entire `web/static/app.js`**

```javascript
// State
const sseConnections = {};
let currentResultTab = 'refined';
let taskDataCache = null;

// Pipeline stage order (only moves forward)
const STAGES = ['downloading', 'transcribing', 'refining'];
const STAGE_LABELS = { downloading: '下载', transcribing: '转录', refining: 'LLM处理' };

// --- Routing ---
function initRouter() {
    const path = window.location.pathname;
    if (path.startsWith('/result/')) {
        const taskId = path.split('/result/')[1].replace(/\/$/, '');
        if (taskId) {
            showResultPage(taskId);
            return;
        }
    }
    showListPage();
}

function showListPage() {
    document.getElementById('page-list').style.display = '';
    document.getElementById('page-result').style.display = 'none';
    document.title = 'Transcribe - 智能视频转录';
    loadTasks();
}

function showResultPage(taskId) {
    document.getElementById('page-list').style.display = 'none';
    document.getElementById('page-result').style.display = '';
    loadResult(taskId);
}

// --- Init ---
document.addEventListener('DOMContentLoaded', () => {
    initRouter();

    // Submit
    document.getElementById('submit-btn').addEventListener('click', handleSubmit);
    document.getElementById('url-input').addEventListener('keypress', (e) => {
        if (e.key === 'Enter') handleSubmit();
    });

    // Back button
    document.getElementById('back-btn').addEventListener('click', () => {
        // Close any SSE for result page
        Object.keys(sseConnections).forEach(closeSSE);
        window.location.href = '/';
    });

    // Result tabs (event delegation)
    document.querySelectorAll('.result-tab').forEach(btn => {
        btn.addEventListener('click', () => {
            currentResultTab = btn.dataset.tab;
            document.querySelectorAll('.result-tab').forEach(b =>
                b.classList.toggle('active', b.dataset.tab === currentResultTab));
            renderResultContent();
        });
    });
});

// --- Submit ---
async function handleSubmit() {
    const input = document.getElementById('url-input');
    const btn = document.getElementById('submit-btn');
    const url = input.value.trim();
    if (!url) {
        showToast('请输入有效链接');
        return;
    }

    btn.disabled = true;
    try {
        const res = await fetch('/api/tasks', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ url }),
        });
        if (!res.ok) {
            const err = await res.json();
            showToast(err.detail || '提交失败');
            return;
        }
        input.value = '';
        showToast('提交成功，正在处理');
        await loadTasks();
    } catch {
        showToast('网络错误');
    } finally {
        btn.disabled = false;
    }
}

// --- Task list ---
async function loadTasks() {
    try {
        const res = await fetch('/api/tasks');
        const tasks = await res.json();
        renderTasks(tasks);

        // Open SSE for active tasks
        tasks.forEach(t => {
            if (t.status === 'pending' || t.status === 'processing') {
                openSSE(t.id);
            } else {
                closeSSE(t.id);
            }
        });
    } catch {
        // ignore
    }
}

function renderTasks(tasks) {
    const list = document.getElementById('task-list');
    const count = document.getElementById('task-count');
    count.textContent = `${tasks.length} 任务`;

    if (tasks.length === 0) {
        list.innerHTML = '<div class="empty-state">暂无任务</div>';
        return;
    }

    list.innerHTML = tasks.map(t => {
        const time = t.created_at ? new Date(t.created_at).toLocaleTimeString('zh-CN', {
            hour: '2-digit', minute: '2-digit'
        }) : '';
        const isClickable = t.status === 'completed';
        const errorHtml = t.status === 'failed' && t.error_message
            ? `<div class="error-msg">${escapeHtml(t.error_message)}</div>` : '';

        return `
            <div class="task-item ${isClickable ? 'clickable' : ''}" data-id="${t.id}"
                 ${isClickable ? `onclick="window.location.href='/result/${t.id}'"` : ''}>
                <div class="task-info">
                    <span class="task-bv">${escapeHtml(t.video_id || t.url)}</span>
                    <div class="task-meta">
                        <span class="status-dot ${t.status}"></span>
                        <span>${statusLabel(t.status)}</span>
                        <span>&middot;</span>
                        <span>${time}</span>
                    </div>
                    <div class="pipeline" id="pipeline-${t.id}" style="display:none">
                        ${STAGES.map(s => `
                            <div class="pipeline-stage">
                                <span class="pipeline-dot" data-stage="${s}"></span>
                                <span>${STAGE_LABELS[s]}</span>
                            </div>
                            ${s !== 'refining' ? '<span class="pipeline-arrow">&rarr;</span>' : ''}
                        `).join('')}
                    </div>
                    <div class="log-area" id="logs-${t.id}"></div>
                    ${errorHtml}
                </div>
                <button class="delete-btn" onclick="event.stopPropagation(); deleteTask('${t.id}', this.closest('.task-item'))">删除</button>
            </div>`;
    }).join('');
}

function statusLabel(status) {
    const map = { pending: '等待中', processing: '处理中', completed: '已完成', failed: '失败' };
    return map[status] || status;
}

// --- SSE ---
function openSSE(taskId) {
    if (sseConnections[taskId]) return;

    const es = new EventSource(`/api/tasks/${taskId}/stream`);
    sseConnections[taskId] = es;

    es.addEventListener('stage_update', (e) => {
        const data = JSON.parse(e.data);
        updatePipeline(taskId, data.stage, data.status);
    });

    es.addEventListener('log', (e) => {
        const data = JSON.parse(e.data);
        appendLog(taskId, data.message);
    });

    es.addEventListener('complete', () => {
        closeSSE(taskId);
        loadTasks();
    });

    es.addEventListener('task_error', (e) => {
        const data = JSON.parse(e.data);
        closeSSE(taskId);
        loadTasks();
        if (data.message) showToast(data.message);
    });
}

function closeSSE(taskId) {
    const es = sseConnections[taskId];
    if (es) {
        es.close();
        delete sseConnections[taskId];
    }
}

function updatePipeline(taskId, stage, status) {
    const pipeline = document.getElementById(`pipeline-${taskId}`);
    if (!pipeline) return;
    pipeline.style.display = 'flex';

    const stageIdx = STAGES.indexOf(stage);
    if (stageIdx < 0) return;

    pipeline.querySelectorAll('.pipeline-dot').forEach((dot, i) => {
        dot.classList.remove('active', 'done', 'failed');
        if (i < stageIdx) dot.classList.add('done');
        else if (i === stageIdx) {
            if (status === 'failed') dot.classList.add('failed');
            else if (status === 'done') dot.classList.add('done');
            else dot.classList.add('active');
        }
    });
}

function appendLog(taskId, message) {
    const logs = document.getElementById(`logs-${taskId}`);
    if (!logs) return;

    const line = document.createElement('div');
    line.textContent = message;
    logs.appendChild(line);

    // Keep last 5 lines
    while (logs.children.length > 5) {
        logs.removeChild(logs.firstChild);
    }
    logs.scrollTop = logs.scrollHeight;
}

// --- Delete ---
async function deleteTask(id, element) {
    if (!confirm('确定删除此任务？')) return;
    closeSSE(id);

    if (element) {
        element.classList.add('exit-animation');
        await new Promise(r => setTimeout(r, 300));
    }

    await fetch(`/api/tasks/${id}`, { method: 'DELETE' });
    showToast('任务已移除');
    await loadTasks();
}

// --- Result page ---
async function loadResult(taskId) {
    const title = document.getElementById('result-title');
    const content = document.getElementById('result-content');

    title.textContent = '加载中...';
    content.innerHTML = '';

    try {
        const res = await fetch(`/api/tasks/${taskId}`);
        if (!res.ok) {
            title.textContent = '任务不存在';
            content.innerHTML = '<p class="empty-state">找不到该任务</p>';
            return;
        }
        taskDataCache = await res.json();
        title.textContent = taskDataCache.video_id || taskDataCache.title || '转录结果';

        // If still processing, open SSE
        if (taskDataCache.status === 'pending' || taskDataCache.status === 'processing') {
            openSSE(taskId);
            // Listen for completion
            const checkDone = setInterval(async () => {
                const r = await fetch(`/api/tasks/${taskId}`);
                const t = await r.json();
                if (t.status === 'completed' || t.status === 'failed') {
                    clearInterval(checkDone);
                    taskDataCache = t;
                    renderResultContent();
                }
            }, 3000);
        }

        renderResultContent();
    } catch {
        title.textContent = '加载失败';
        content.innerHTML = '<p class="empty-state">网络错误</p>';
    }
}

function renderResultContent() {
    if (!taskDataCache) return;
    const content = document.getElementById('result-content');
    const text = currentResultTab === 'refined'
        ? taskDataCache.refined_text
        : taskDataCache.raw_text;

    if (text) {
        content.innerHTML = marked.parse(text);
    } else if (taskDataCache.status === 'failed') {
        content.innerHTML = `<p class="error-msg">${escapeHtml(taskDataCache.error_message || '处理失败')}</p>`;
    } else {
        content.innerHTML = '<p class="empty-state">处理中，请稍候...</p>';
    }
}

// --- Toast ---
function showToast(msg) {
    const container = document.getElementById('toast-container');
    const toast = document.createElement('div');
    toast.className = 'toast';
    toast.textContent = msg;
    container.appendChild(toast);
    setTimeout(() => {
        toast.style.opacity = '0';
        setTimeout(() => toast.remove(), 300);
    }, 2500);
}

// --- Utils ---
function escapeHtml(str) {
    if (!str) return '';
    const d = document.createElement('div');
    d.textContent = str;
    return d.innerHTML;
}
```

- [ ] **Step 2: Commit**

```bash
git add web/static/app.js
git commit -m "feat: rewrite JS with SSE integration, routing, pipeline progress, and result view"
```

---

## Task 6: Update README.md

**Files:**
- Modify: `README.md`

Update README with comprehensive CLI usage, web usage, production deployment instructions, and updated API reference.

- [ ] **Step 1: Replace `README.md`**

Write the complete updated README covering:
- Project intro (unchanged)
- Features (unchanged + real-time progress mention)
- Quick start (env, config, cookies)
- CLI usage section with `input_data.json` format
- Web local dev section with `uvicorn` command
- Production deployment section with Nginx + HTTPS + systemd
- Updated API reference including SSE endpoint
- Configuration table (unchanged)
- Project structure (unchanged)

The README content should preserve all existing accurate content and add new sections for production deployment and the SSE stream endpoint.

Key additions to the API table:
```
| GET | `/api/tasks/{id}/stream` | SSE 实时事件流 |
```

New "生产部署" section with:
- DNS config
- Nginx config (from spec)
- certbot for HTTPS
- systemd service (from spec)
- Deployment steps 1-6

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs: update README with CLI usage, web usage, and production deployment guide"
```

---

## Task 7: Add deployment config files

**Files:**
- Create: `deploy/nginx.conf`
- Create: `deploy/cui_ting.service`

- [ ] **Step 1: Create `deploy/nginx.conf`**

```nginx
server {
    listen 80;
    server_name www.cuiting.com;
    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl http2;
    server_name www.cuiting.com;

    ssl_certificate /etc/letsencrypt/live/www.cuiting.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/www.cuiting.com/privkey.pem;

    location / {
        proxy_pass http://example.com:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    # SSE stream endpoints
    location ~ ^/api/tasks/[^/]+/stream$ {
        proxy_pass http://example.com:8000;
        proxy_buffering off;
        proxy_cache off;
        proxy_set_header Connection '';
        proxy_http_version 1.1;
        chunked_transfer_encoding off;
    }
}
```

- [ ] **Step 2: Create `deploy/cui_ting.service`**

```ini
[Unit]
Description=cui_ting Web App
After=network.target

[Service]
User=www-data
WorkingDirectory=/path/to/cui_ting
ExecStart=/path/to/conda/env/bin/uvicorn web.app:app --host 127.0.0.1 --port 8000
Restart=always
Environment=PATH=/path/to/conda/env/bin:/usr/bin

[Install]
WantedBy=multi-user.target
```

- [ ] **Step 3: Commit**

```bash
mkdir -p deploy
git add deploy/nginx.conf deploy/cui_ting.service
git commit -m "feat: add Nginx and systemd deployment config files"
```

---

## Task 8: Add .superpowers to .gitignore and final verification

**Files:**
- Modify: `.gitignore`

- [ ] **Step 1: Add `.superpowers/` to `.gitignore`**

Append `.superpowers/` to `.gitignore`.

- [ ] **Step 2: Verify CLI mode still works**

Run: `conda run -n cui_ting python -c "from cli import main; print('CLI OK')"`

Expected: `CLI OK`

- [ ] **Step 3: Verify web app starts**

Run: `conda run -n cui_ting python -c "from web.app import app; print('Web OK')"`

Expected: `Web OK`

- [ ] **Step 4: Commit**

```bash
git add .gitignore
git commit -m "chore: add .superpowers/ to gitignore"
```

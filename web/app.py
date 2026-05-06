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
            data = json.dumps({"task_id": task_id}, ensure_ascii=False)
            yield f"event: complete\ndata: {data}\n\n"

        return StreamingResponse(_done(), media_type="text/event-stream")

    if task.status == "failed":
        async def _failed():
            data = json.dumps({"message": task.error_message or ""}, ensure_ascii=False)
            yield f"event: task_error\ndata: {data}\n\n"
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

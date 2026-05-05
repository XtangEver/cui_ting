# web/app.py
import logging
import os
import queue
import re
import shutil
import threading

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, Response
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

# Init DB on startup
init_db()

# Load config once
_config_manager = ConfigManager(os.path.join(BASE_DIR, "config.yaml"))
_app_config = _config_manager.get_app_config()

# Shared VideoSummarizer (single worker processes one task at a time)
_summarizer = VideoSummarizer(
    config_path=os.path.join(BASE_DIR, "config.yaml"),
    cookies_file=_app_config.cookies_file,
)

# Task queue
_task_queue: queue.Queue = queue.Queue()


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

            result = _summarizer.process(url=task.url, output_dir=output_dir)

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

        except Exception as e:
            logger.exception("Task %s failed", task_id)
            update_task(task_id, status="failed", error_message=str(e))
        finally:
            _task_queue.task_done()


threading.Thread(target=_worker, daemon=True).start()


# --- Request / Response schemas ---

class TaskCreateRequest(BaseModel):
    url: str


# --- API routes ---

@app.get("/")
def index():
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))


@app.post("/api/tasks")
def api_create_task(req: TaskCreateRequest):
    if "bilibili.com" not in req.url:
        raise HTTPException(status_code=400, detail="请输入有效的B站链接")

    # Extract BV id
    match = re.search(r"(BV[a-zA-Z0-9]+)", req.url)
    video_id = match.group(1) if match else ""

    task = create_task(url=req.url, video_id=video_id)
    _task_queue.put(task.id)

    return _task_to_dict(task, include_content=False)


@app.get("/api/tasks")
def api_list_tasks():
    tasks = list_tasks()
    return [_task_to_dict(t, include_content=False) for t in tasks]


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

    # Clean up output files
    output_dir = os.path.join(_app_config.output_dir, task_id)
    if os.path.exists(output_dir):
        shutil.rmtree(output_dir, ignore_errors=True)

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

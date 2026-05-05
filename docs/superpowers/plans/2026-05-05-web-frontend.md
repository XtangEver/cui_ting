# Web Frontend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a FastAPI web frontend for the cui_ting video transcription tool with Bilibili URL input, async task processing, online preview of refined text, and SQLite persistence.

**Architecture:** FastAPI serves a single-page HTML/JS frontend and a REST API. A single background worker thread consumes tasks from a queue, calling the existing `VideoSummarizer.process()` pipeline. Results are stored in SQLite and displayed via Markdown rendering in the browser.

**Tech Stack:** FastAPI, SQLAlchemy, SQLite, vanilla JS, marked.js (CDN)

---

## File Structure

| File | Action | Responsibility |
|------|--------|---------------|
| `web/__init__.py` | Create | Package init |
| `web/database.py` | Create | SQLAlchemy models, DB init, CRUD operations |
| `web/app.py` | Create | FastAPI app, API routes, background worker |
| `web/static/index.html` | Create | Single-page HTML structure |
| `web/static/style.css` | Create | Styling |
| `web/static/app.js` | Create | Frontend logic (submit, poll, render) |
| `requirements.txt` | Modify | Add fastapi, uvicorn, sqlalchemy |
| `data/` | Create dir | SQLite database file location |

---

### Task 1: Install dependencies

**Files:**
- Modify: `requirements.txt`

- [ ] **Step 1: Add new dependencies to requirements.txt**

Append to `requirements.txt`:
```
fastapi>=0.115.0
uvicorn[standard]>=0.34.0
sqlalchemy>=2.0.0
```

- [ ] **Step 2: Install in conda environment**

Run: `conda run -n cui_ting pip install fastapi "uvicorn[standard]" sqlalchemy`
Expected: Successfully installed

- [ ] **Step 3: Verify imports work**

Run: `conda run -n cui_ting python -c "import fastapi; import uvicorn; import sqlalchemy; print('OK')"`
Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add requirements.txt
git commit -m "chore: add FastAPI, uvicorn, SQLAlchemy dependencies"
```

---

### Task 2: Create database module

**Files:**
- Create: `web/__init__.py`
- Create: `web/database.py`

- [ ] **Step 1: Create web package**

Create `web/__init__.py` as an empty file.

- [ ] **Step 2: Write database.py with Task model and CRUD functions**

Create `web/database.py`:

```python
# web/database.py
import os
import uuid
from datetime import datetime

from sqlalchemy import create_engine, Column, String, Text, DateTime
from sqlalchemy.orm import declarative_base, sessionmaker

DB_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
os.makedirs(DB_DIR, exist_ok=True)
DB_PATH = os.path.join(DB_DIR, "cui_ting.db")

engine = create_engine(f"sqlite:///{DB_PATH}", connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine)
Base = declarative_base()


class Task(Base):
    __tablename__ = "tasks"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    url = Column(Text, nullable=False)
    video_id = Column(String, default="")
    title = Column(String, default="")
    status = Column(String, default="pending")  # pending/processing/completed/failed
    raw_text = Column(Text, default="")
    refined_text = Column(Text, default="")
    error_message = Column(Text, default="")
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)


def init_db():
    Base.metadata.create_all(engine)


def get_session():
    return SessionLocal()


def create_task(url: str, video_id: str) -> Task:
    session = get_session()
    task = Task(url=url, video_id=video_id, title=video_id, status="pending")
    session.add(task)
    session.commit()
    session.refresh(task)
    session.close()
    return task


def get_task(task_id: str) -> Task | None:
    session = get_session()
    task = session.query(Task).filter(Task.id == task_id).first()
    session.close()
    return task


def list_tasks() -> list[Task]:
    session = get_session()
    tasks = session.query(Task).order_by(Task.created_at.desc()).all()
    session.close()
    return tasks


def update_task(task_id: str, **kwargs) -> Task | None:
    session = get_session()
    task = session.query(Task).filter(Task.id == task_id).first()
    if task:
        for key, value in kwargs.items():
            setattr(task, key, value)
        task.updated_at = datetime.now()
        session.commit()
        session.refresh(task)
    session.close()
    return task


def delete_task(task_id: str) -> bool:
    session = get_session()
    task = session.query(Task).filter(Task.id == task_id).first()
    if task:
        session.delete(task)
        session.commit()
        session.close()
        return True
    session.close()
    return False
```

- [ ] **Step 3: Test database operations**

Run:
```bash
conda run -n cui_ting python -c "
import sys; sys.path.insert(0, '.')
from web.database import init_db, create_task, list_tasks, get_task, delete_task
init_db()
t = create_task('https://www.bilibili.com/video/BV1test', 'BV1test')
print(f'Created: {t.id}, status={t.status}, video_id={t.video_id}')
t2 = get_task(t.id)
print(f'Got: {t2.id}, title={t2.title}')
tasks = list_tasks()
print(f'List count: {len(tasks)}')
delete_task(t.id)
print(f'After delete: {len(list_tasks())}')
print('DB TEST PASSED')
"
```
Expected: `DB TEST PASSED`

- [ ] **Step 4: Commit**

```bash
git add web/__init__.py web/database.py
git commit -m "feat: add SQLite database module with Task model and CRUD"
```

---

### Task 3: Create FastAPI app with API routes and background worker

**Files:**
- Create: `web/app.py`

- [ ] **Step 1: Write web/app.py**

Create `web/app.py`:

```python
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
```

- [ ] **Step 2: Test API starts without errors**

Run:
```bash
conda run -n cui_ting python -c "
import sys; sys.path.insert(0, '.')
from web.app import app
print(f'Routes: {[r.path for r in app.routes if hasattr(r, \"path\")]}')
print('APP INIT OK')
"
```
Expected: `APP INIT OK` with routes listed including `/`, `/api/tasks`, `/api/tasks/{task_id}`

- [ ] **Step 3: Commit**

```bash
git add web/app.py
git commit -m "feat: add FastAPI app with API routes and background worker"
```

---

### Task 4: Create frontend HTML

**Files:**
- Create: `web/static/index.html`

- [ ] **Step 1: Write index.html**

Create `web/static/index.html`:

```html
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>视频转录工具</title>
    <link rel="stylesheet" href="/static/style.css">
    <script src="https://cdn.jsdelivr.net/npm/marked/marked.min.js"></script>
</head>
<body>
    <div class="container">
        <header>
            <h1>视频转录工具</h1>
            <p class="subtitle">输入B站链接，自动转录并生成结构化摘要</p>
        </header>

        <section class="input-section">
            <form id="task-form">
                <input type="text" id="url-input" placeholder="请输入B站视频链接..." required>
                <button type="submit" id="submit-btn">提交</button>
            </form>
        </section>

        <section class="task-list-section">
            <h2>任务列表</h2>
            <div id="task-list"></div>
            <p id="empty-hint" class="empty-hint">暂无任务</p>
        </section>

        <section class="preview-section" id="preview-section" style="display:none;">
            <div class="preview-header">
                <h2 id="preview-title">结果预览</h2>
                <div class="preview-tabs">
                    <button class="tab-btn active" data-tab="refined">精炼文本</button>
                    <button class="tab-btn" data-tab="raw">原始转录</button>
                </div>
                <button class="close-btn" id="close-preview">关闭</button>
            </div>
            <div id="preview-content" class="preview-content markdown-body"></div>
        </section>
    </div>

    <script src="/static/app.js"></script>
</body>
</html>
```

- [ ] **Step 2: Commit**

```bash
git add web/static/index.html
git commit -m "feat: add frontend HTML page"
```

---

### Task 5: Create frontend CSS

**Files:**
- Create: `web/static/style.css`

- [ ] **Step 1: Write style.css**

Create `web/static/style.css`:

```css
* {
    margin: 0;
    padding: 0;
    box-sizing: border-box;
}

body {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
    background: #f5f5f7;
    color: #1d1d1f;
    line-height: 1.6;
}

.container {
    max-width: 800px;
    margin: 0 auto;
    padding: 40px 20px;
}

header {
    text-align: center;
    margin-bottom: 32px;
}

header h1 {
    font-size: 28px;
    font-weight: 600;
    color: #1d1d1f;
}

.subtitle {
    color: #86868b;
    font-size: 15px;
    margin-top: 8px;
}

/* Input section */
.input-section {
    margin-bottom: 32px;
}

#task-form {
    display: flex;
    gap: 12px;
}

#url-input {
    flex: 1;
    padding: 12px 16px;
    border: 1px solid #d2d2d7;
    border-radius: 10px;
    font-size: 15px;
    outline: none;
    transition: border-color 0.2s;
    background: #fff;
}

#url-input:focus {
    border-color: #0071e3;
}

#submit-btn {
    padding: 12px 24px;
    background: #0071e3;
    color: #fff;
    border: none;
    border-radius: 10px;
    font-size: 15px;
    font-weight: 500;
    cursor: pointer;
    transition: background 0.2s;
    white-space: nowrap;
}

#submit-btn:hover {
    background: #0077ed;
}

#submit-btn:disabled {
    background: #c7c7cc;
    cursor: not-allowed;
}

/* Task list */
.task-list-section h2 {
    font-size: 20px;
    font-weight: 600;
    margin-bottom: 16px;
}

.empty-hint {
    text-align: center;
    color: #86868b;
    padding: 40px 0;
}

.task-card {
    background: #fff;
    border-radius: 12px;
    padding: 16px 20px;
    margin-bottom: 12px;
    display: flex;
    align-items: center;
    gap: 16px;
    box-shadow: 0 1px 3px rgba(0,0,0,0.06);
}

.task-status {
    font-size: 20px;
    flex-shrink: 0;
}

.task-info {
    flex: 1;
    min-width: 0;
}

.task-title {
    font-weight: 500;
    font-size: 15px;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
}

.task-meta {
    font-size: 13px;
    color: #86868b;
    margin-top: 2px;
}

.task-actions {
    display: flex;
    gap: 8px;
    flex-shrink: 0;
}

.task-actions button {
    padding: 6px 14px;
    border: 1px solid #d2d2d7;
    border-radius: 8px;
    background: #fff;
    font-size: 13px;
    cursor: pointer;
    transition: all 0.2s;
}

.task-actions button:hover {
    background: #f5f5f7;
}

.task-actions .btn-view {
    border-color: #0071e3;
    color: #0071e3;
}

.task-actions .btn-view:hover {
    background: #0071e3;
    color: #fff;
}

.task-actions .btn-delete {
    color: #ff3b30;
    border-color: #ff3b30;
}

.task-actions .btn-delete:hover {
    background: #ff3b30;
    color: #fff;
}

.status-pending { color: #ff9f0a; }
.status-processing { color: #0071e3; }
.status-completed { color: #30d158; }
.status-failed { color: #ff3b30; }

.task-card.status-processing {
    animation: pulse 2s ease-in-out infinite;
}

@keyframes pulse {
    0%, 100% { opacity: 1; }
    50% { opacity: 0.7; }
}

.task-error {
    margin-top: 8px;
    padding: 8px 12px;
    background: #fff3f3;
    border-radius: 8px;
    color: #ff3b30;
    font-size: 13px;
}

/* Preview */
.preview-section {
    margin-top: 24px;
    background: #fff;
    border-radius: 12px;
    box-shadow: 0 1px 3px rgba(0,0,0,0.06);
    overflow: hidden;
}

.preview-header {
    display: flex;
    align-items: center;
    padding: 16px 20px;
    border-bottom: 1px solid #f0f0f0;
    gap: 16px;
}

.preview-header h2 {
    font-size: 17px;
    font-weight: 600;
    flex: 1;
}

.preview-tabs {
    display: flex;
    gap: 4px;
    background: #f5f5f7;
    border-radius: 8px;
    padding: 3px;
}

.tab-btn {
    padding: 5px 14px;
    border: none;
    border-radius: 6px;
    background: transparent;
    font-size: 13px;
    cursor: pointer;
    transition: all 0.2s;
}

.tab-btn.active {
    background: #fff;
    box-shadow: 0 1px 2px rgba(0,0,0,0.1);
}

.close-btn {
    padding: 6px 12px;
    border: 1px solid #d2d2d7;
    border-radius: 8px;
    background: #fff;
    font-size: 13px;
    cursor: pointer;
}

.close-btn:hover {
    background: #f5f5f7;
}

.preview-content {
    padding: 24px;
    max-height: 600px;
    overflow-y: auto;
    font-size: 15px;
    line-height: 1.8;
}

/* Markdown rendered content */
.markdown-body h2 {
    font-size: 18px;
    font-weight: 600;
    margin: 24px 0 8px;
    padding-bottom: 6px;
    border-bottom: 1px solid #f0f0f0;
}

.markdown-body p {
    margin: 8px 0;
}

.markdown-body hr {
    border: none;
    border-top: 1px solid #e5e5ea;
    margin: 16px 0;
}

/* Responsive */
@media (max-width: 600px) {
    .container {
        padding: 20px 16px;
    }
    #task-form {
        flex-direction: column;
    }
    .task-card {
        flex-wrap: wrap;
    }
    .task-actions {
        width: 100%;
        justify-content: flex-end;
    }
}
```

- [ ] **Step 2: Commit**

```bash
git add web/static/style.css
git commit -m "feat: add frontend CSS styling"
```

---

### Task 6: Create frontend JavaScript

**Files:**
- Create: `web/static/app.js`

- [ ] **Step 1: Write app.js**

Create `web/static/app.js`:

```javascript
// web/static/app.js
const POLL_INTERVAL = 3000;
let currentTaskId = null;
let currentTab = 'refined';
let taskDataCache = {};

const STATUS_MAP = {
    pending: { icon: '⏳', label: '等待中', cls: 'status-pending' },
    processing: { icon: '🔄', label: '处理中', cls: 'status-processing' },
    completed: { icon: '🟢', label: '已完成', cls: 'status-completed' },
    failed: { icon: '❌', label: '失败', cls: 'status-failed' },
};

// --- DOM refs ---
const form = document.getElementById('task-form');
const urlInput = document.getElementById('url-input');
const submitBtn = document.getElementById('submit-btn');
const taskList = document.getElementById('task-list');
const emptyHint = document.getElementById('empty-hint');
const previewSection = document.getElementById('preview-section');
const previewTitle = document.getElementById('preview-title');
const previewContent = document.getElementById('preview-content');
const closePreview = document.getElementById('close-preview');

// --- Init ---
document.addEventListener('DOMContentLoaded', () => {
    loadTasks();
    form.addEventListener('submit', handleSubmit);

    document.querySelectorAll('.tab-btn').forEach(btn => {
        btn.addEventListener('click', () => switchTab(btn.dataset.tab));
    });

    closePreview.addEventListener('click', () => {
        previewSection.style.display = 'none';
        currentTaskId = null;
    });
});

// --- Submit ---
async function handleSubmit(e) {
    e.preventDefault();
    const url = urlInput.value.trim();
    if (!url) return;

    submitBtn.disabled = true;
    try {
        const res = await fetch('/api/tasks', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ url }),
        });
        if (!res.ok) {
            const err = await res.json();
            alert(err.detail || '提交失败');
            return;
        }
        urlInput.value = '';
        await loadTasks();
    } catch (err) {
        alert('网络错误');
    } finally {
        submitBtn.disabled = false;
    }
}

// --- Task list ---
async function loadTasks() {
    const res = await fetch('/api/tasks');
    const tasks = await res.json();
    renderTasks(tasks);
    emptyHint.style.display = tasks.length ? 'none' : 'block';
    pollActiveTasks(tasks);
}

function renderTasks(tasks) {
    taskList.innerHTML = tasks.map(t => {
        const s = STATUS_MAP[t.status] || STATUS_MAP.pending;
        const time = t.created_at ? new Date(t.created_at).toLocaleString('zh-CN') : '';
        const errorHtml = t.status === 'failed' && t.error_message
            ? `<div class="task-error">${escapeHtml(t.error_message)}</div>` : '';
        return `
            <div class="task-card" data-id="${t.id}">
                <span class="task-status ${s.cls}">${s.icon}</span>
                <div class="task-info">
                    <div class="task-title">${escapeHtml(t.title || t.video_id)}</div>
                    <div class="task-meta">${s.label} · ${time}</div>
                    ${errorHtml}
                </div>
                <div class="task-actions">
                    ${t.status === 'completed' ? `<button class="btn-view" onclick="viewResult('${t.id}')">查看</button>` : ''}
                    <button class="btn-delete" onclick="deleteTask('${t.id}')">删除</button>
                </div>
            </div>`;
    }).join('');
}

function pollActiveTasks(tasks) {
    const hasActive = tasks.some(t => t.status === 'pending' || t.status === 'processing');
    if (hasActive) {
        setTimeout(loadTasks, POLL_INTERVAL);
    }
}

// --- View result ---
async function viewResult(id) {
    const res = await fetch(`/api/tasks/${id}`);
    const task = await res.json();
    currentTaskId = id;
    currentTab = 'refined';
    taskDataCache = task;
    previewTitle.textContent = task.title || task.video_id;
    updateActiveTab();
    renderPreview();
    previewSection.style.display = '';
    previewSection.scrollIntoView({ behavior: 'smooth' });
}

function switchTab(tab) {
    currentTab = tab;
    document.querySelectorAll('.tab-btn').forEach(b => b.classList.toggle('active', b.dataset.tab === tab));
    renderPreview();
}

function updateActiveTab() {
    document.querySelectorAll('.tab-btn').forEach(b => b.classList.toggle('active', b.dataset.tab === currentTab));
}

function renderPreview() {
    const text = currentTab === 'refined' ? taskDataCache.refined_text : taskDataCache.raw_text;
    if (text) {
        previewContent.innerHTML = marked.parse(text);
    } else {
        previewContent.innerHTML = '<p style="color:#86868b">暂无内容</p>';
    }
}

// --- Delete ---
async function deleteTask(id) {
    if (!confirm('确定删除此任务？')) return;
    await fetch(`/api/tasks/${id}`, { method: 'DELETE' });
    if (currentTaskId === id) {
        previewSection.style.display = 'none';
        currentTaskId = null;
    }
    await loadTasks();
}

// --- Utils ---
function escapeHtml(str) {
    const d = document.createElement('div');
    d.textContent = str;
    return d.innerHTML;
}
```

- [ ] **Step 2: Commit**

```bash
git add web/static/app.js
git commit -m "feat: add frontend JavaScript with task management and Markdown rendering"
```

---

### Task 7: Integration test — full end-to-end

**Files:**
- No new files

This task tests the full running system. It requires the server to be running.

- [ ] **Step 1: Clean up test database from earlier unit test**

Run:
```bash
rm -f /Users/tangxian/work_dir/cui_ting/data/cui_ting.db
```

- [ ] **Step 2: Start the server in background**

Run:
```bash
conda run -n cui_ting uvicorn web.app:app --host 0.0.0.0 --port 8000 &
sleep 3
curl -s http://localhost:8000/ | head -5
```
Expected: HTML output starting with `<!DOCTYPE html>`

- [ ] **Step 3: Test POST /api/tasks with invalid URL**

Run:
```bash
curl -s -X POST http://localhost:8000/api/tasks \
  -H "Content-Type: application/json" \
  -d '{"url": "https://google.com"}' | python3 -m json.tool
```
Expected: `{"detail": "请输入有效的B站链接"}` with status 400

- [ ] **Step 4: Test POST /api/tasks with valid URL**

Run:
```bash
curl -s -X POST http://localhost:8000/api/tasks \
  -H "Content-Type: application/json" \
  -d '{"url": "https://www.bilibili.com/video/BV1test123"}' | python3 -m json.tool
```
Expected: JSON with `status: "pending"`, `video_id: "BV1test123"`

- [ ] **Step 5: Test GET /api/tasks**

Run:
```bash
curl -s http://localhost:8000/api/tasks | python3 -m json.tool
```
Expected: Array with at least one task, no `refined_text` or `raw_text` fields

- [ ] **Step 6: Test GET /api/tasks/{id} with the ID from step 4**

Run (use actual task ID from step 4 output):
```bash
TASK_ID=$(curl -s http://localhost:8000/api/tasks | python3 -c "import sys,json; print(json.load(sys.stdin)[0]['id'])")
curl -s "http://localhost:8000/api/tasks/$TASK_ID" | python3 -m json.tool
```
Expected: JSON with all fields including `raw_text`, `refined_text`, `error_message`

- [ ] **Step 7: Test DELETE /api/tasks/{id}**

Run:
```bash
curl -s -o /dev/null -w "%{http_code}" -X DELETE "http://localhost:8000/api/tasks/$TASK_ID"
```
Expected: `204`

- [ ] **Step 8: Verify deletion**

Run:
```bash
curl -s http://localhost:8000/api/tasks | python3 -c "import sys,json; d=json.load(sys.stdin); print(f'count={len(d)}')"
```
Expected: `count=0`

- [ ] **Step 9: Stop the server**

Run:
```bash
kill $(lsof -ti:8000) 2>/dev/null; echo "server stopped"
```

- [ ] **Step 10: Commit**

```bash
git add -A
git commit -m "test: integration tests passing for web frontend"
```

---

### Task 8: Manual browser test

**Files:**
- No new files

- [ ] **Step 1: Start server**

Run:
```bash
conda run -n cui_ting uvicorn web.app:app --host 0.0.0.0 --port 8000
```

- [ ] **Step 2: Open browser**

Navigate to `http://localhost:8000`

- [ ] **Step 3: Verify UI renders correctly**

Check: title "视频转录工具" is visible, input box and submit button are present.

- [ ] **Step 4: Submit a Bilibili URL and verify async task flow**

Enter a B站 URL, click submit, verify:
- New task appears in list with ⏳ status
- Status updates to 🔄 processing (auto-poll)
- When complete, status shows 🟢 and "查看" button appears
- Click "查看" shows Markdown-rendered refined text
- Tab switching between "精炼文本" and "原始转录" works
- Delete works with confirmation dialog

- [ ] **Step 5: Stop server**

Ctrl+C in terminal

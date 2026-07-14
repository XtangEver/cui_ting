# Frontend Redesign & Real-time Logs Design

Date: 2026-05-06

## Overview

Redesign the cui_ting web frontend based on the provided visual reference (`前端参考.html`), add real-time pipeline progress and logs via SSE, ensure CLI mode continues to work independently, and support production deployment with domain `www.cuiting.com`.

## Task Summary

1. Preserve `python cli.py` CLI mode
2. Update README.md documentation
3. Frontend redesign following `前端参考.html` visual style
4. Real-time pipeline progress and key logs via SSE
5. Production deployment with `www.cuiting.com` domain (DNS + Nginx + HTTPS)

---

## 1. Frontend Redesign

### Visual Style

Completely adopt `前端参考.html` design language:

- **Color scheme**: Indigo/purple primary (`#5e5ce6`), with CSS custom properties
- **Background**: Subtle grid-dot texture + decorative purple glow element
- **Cards**: Large border-radius (16px), deep shadows, Apple-style transitions (`cubic-bezier`)
- **Animations**: Pulsing status dots, fade-in for new tasks, slide-out for deletions
- **Typography**: Title "Transcribe", subtitle "将 B 站智慧转化为文字力量"
- **Input**: "粘贴视频链接或输入 BV 号..." placeholder, "开始转录" button

### Page Structure

**Page 1: Task List (`/`)**

- Centered single-card layout (max-width 560px)
- Input + "开始转录" button side by side
- Task card list, each card shows:
  - BV ID (extracted from URL)
  - Animated status dot (pending = gray, processing = pulsing purple, completed = green, failed = red)
  - Created time
  - Delete button (with slide-out animation)
- **Pipeline progress indicator** (shown when processing):
  - Stages: 下载 → 转录 → LLM处理
  - Each stage shows: waiting (gray), active (pulsing), done (green check), failed (red X)
  - Current stage highlighted
- **Key log area** (shown when processing):
  - Last 3-5 log lines displayed below the progress indicator
  - Auto-scrolling, latest at bottom
  - Disappears when task completes
- Completed tasks are clickable → navigate to result page
- Toast notifications for actions (submit, delete, errors)

**Page 2: Result View (`/result/{task_id}`)**

- Back button (returns to task list)
- Tab switcher: 精炼文本 / 原始转录
- Markdown rendered content (marked.js from CDN)
- Same indigo visual theme

---

## 2. Real-time Progress via SSE

### Architecture

```
Browser (EventSource) → GET /api/tasks/{id}/stream → StreamingResponse (async)
                                                            ↓
Worker Thread → callback() → loop.call_soon_threadsafe(q.put_nowait, event) → asyncio.Queue → SSE events
```

### New API Endpoint

`GET /api/tasks/{id}/stream` — SSE stream endpoint

Returns `text/event-stream` with events:

| Event Type | Data | Description |
|---|---|---|
| `stage_update` | `{"stage": "downloading", "status": "active"}` | Pipeline stage change |
| `log` | `{"message": "下载进度: 50%", "level": "info"}` | Key log message |
| `complete` | `{"task_id": "..."}` | Task finished successfully |
| `error` | `{"message": "下载失败: ..."}` | Task failed |

### Backend Changes

**`core/summarizer.py`**:

- Add optional `progress_callback(event_type, data)` parameter to `process()` method
- Callback invocations are coarse-grained, placed only in `process()` / `_process_part()` / `_refine()` methods (not threaded into downloader/transcriber/LLM modules):
  - `process()` entry: emit `stage_update("downloading", "active")`, then call downloader
  - After download: emit `log("下载完成")`, `stage_update("transcribing", "active")`
  - Per-part in `_process_part()`: emit `log("正在处理第 N 部分...")`
  - After transcription: emit `log("转录完成")`, `stage_update("refining", "active")`
  - Per-chunk in `_refine()`: emit `log("LLM 处理: 第 N/M 块")`
  - After refinement: emit `log("LLM 处理完成")`
  - On success: emit `complete` event
  - On exception: emit `error` event with message
- CLI mode: `callback=None`, all callback calls guarded by `if callback:` — no behavior change

**`web/app.py`**:

- New SSE endpoint using `StreamingResponse` with `text/event-stream` media type
- Per-task `asyncio.Queue` stored in a dict (`_sse_queues: dict[str, asyncio.Queue]`)
- **Threading bridge**: Worker thread calls `loop.call_soon_threadsafe(queue.put_nowait, event)` to safely push events from the sync worker thread into the async event loop's queue
- Store reference to the running event loop via `asyncio.get_event_loop()` at app startup
- SSE endpoint is an async generator that `await queue.get()` and yields SSE-formatted events
- Auto-cleanup: close connection after `complete` or `error` event, remove queue from dict
- Task status polling endpoint (`GET /api/tasks`) remains for initial page load
- **Result page routing**: Add catch-all route `GET /result/{task_id}` that serves `index.html` for client-side routing

### Frontend SSE Consumption

- On page load, fetch task list via REST API
- For each task with status `processing`, open `EventSource` to `/api/tasks/{id}/stream`
- Update task card in-place when events arrive:
  - `stage_update` → update pipeline progress indicator
  - `log` → append to log area, auto-scroll
  - `complete` → update status to completed, close EventSource, fetch full content via `GET /api/tasks/{id}`, make card clickable
  - `error` → update status to failed, show error message, close EventSource

---

## 3. CLI Preservation

**No changes to `cli.py`**. The key mechanism:

- `VideoSummarizer.process()` gains an optional `progress_callback` parameter (default `None`)
- CLI calls `summarizer.process(url, output_dir)` without callback — identical to current behavior
- Web worker calls `summarizer.process(url, output_dir, callback=cb)` with callback
- All pipeline logic remains in `core/summarizer.py`, shared by both modes

---

## 4. Production Deployment

### Nginx Configuration

```
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

    # SSE support (only for stream endpoints)
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

### Deployment Steps

1. DNS A record: `www.cuiting.com` → server IP
2. Install Nginx + certbot
3. Configure Nginx reverse proxy (config above)
4. Run certbot for HTTPS certificate
5. Run uvicorn via systemd service
6. SSE requires `proxy_buffering off` in Nginx

### systemd Service

```ini
[Unit]
Description=cui_ting Web App
After=network.target

[Service]
User=www-data
WorkingDirectory=/path/to/cui_ting
ExecStart=/path/to/conda/env/bin/uvicorn web.app:app --host 127.0.0.1 --port 8000
Restart=always

[Install]
WantedBy=multi-user.target
```

---

## 5. README Update

Add/update the following sections:

- **CLI Usage**: `python cli.py` with `input_data.json` format explanation
- **Web Local Development**: `uvicorn web.app:app --host 0.0.0.0 --port 8000`
- **Production Deployment**: Nginx + HTTPS + systemd instructions
- **Configuration**: `.env` and `config.yaml` explanation
- **Web API Reference**: Updated endpoint table including SSE stream endpoint

---

## Files Changed

| File | Change |
|---|---|
| `web/static/index.html` | Complete rewrite: two-page app (list + result), indigo theme, pipeline UI |
| `web/static/style.css` | Complete rewrite: indigo theme, animations, pipeline indicators, responsive |
| `web/static/app.js` | Complete rewrite: SSE integration, two-page routing, toast notifications |
| `web/app.py` | Add SSE endpoint, per-task event queue, callback wiring |
| `core/summarizer.py` | Add optional `progress_callback` parameter with stage/log emissions |
| `README.md` | Major update: CLI usage, web usage, production deployment guide |

## Out of Scope

- Authentication/authorization
- Multi-user support
- Database migration (existing schema stays)
- WebSocket (SSE is sufficient)
- Docker containerization (can be added later)

# Comprehensive Optimization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix critical bugs (thinking content filter, prompt leak), enhance UI (GitHub Markdown, export, TOC), add granular progress feedback, implement task management features (tags, model selection), and optimize mobile experience.

**Architecture:** Incremental enhancements to the existing FastAPI + SQLite + vanilla JS stack. No new dependencies except what's already bundled (marked.min.js). All changes maintain backward compatibility with existing tasks.

**Tech Stack:** Python 3.10+, FastAPI, SQLAlchemy, SQLite, vanilla JavaScript, marked.js, yt-dlp

**Spec:** `docs/superpowers/specs/2026-05-09-comprehensive-optimization-design.md`

---

## File Structure

| File | Responsibility |
|------|---------------|
| `core/llm_processor.py` | Add thinking-content filter regex to `_call_llm()` |
| `core/downloader.py` | Add `progress_callback` parameter + yt-dlp progress hooks |
| `core/summarizer.py` | Wire downloader progress, add `enable_refine` override, structured progress events |
| `web/database.py` | Add `tags`, `model` columns to Task; update `create_task` signature |
| `web/app.py` | New endpoints, queue tracking, schema changes, prompt leak cleanup |
| `web/static/index.html` | Add toolbar, tags input, advanced options, TOC sidebar |
| `web/static/style.css` | GitHub Markdown theme, TOC, toolbar, tags, skeleton, mobile fixes |
| `web/static/app.js` | Markdown config, TOC, export, progress bar, queue, tags, model selector, chunked render |

---

## Phase 1: Critical Bug Fixes

### Task 1: Filter model thinking content from LLM output

**Files:**
- Modify: `core/llm_processor.py:84-96` (the `_call_llm` method)

- [ ] **Step 1: Add thinking content filter to `_call_llm()`**

In `core/llm_processor.py`, add `import re` at the top of the file (module level), then modify `_call_llm()` to strip thinking blocks:

```python
# At module top (add to existing imports):
import re

class LLMProcessor:
    # ... existing prompts ...

    _THINK_PATTERN = re.compile(
        r'<(?:think|thinking)(?:\s[^>]*)?>.*?</(?:think|thinking)\s*>',
        re.DOTALL
    )

    def _call_llm(self, model_name: str, prompt: str) -> str:
        model_cfg = self.model_configs.get(model_name)
        if model_cfg is None:
            raise ValueError(f"未配置的模型: {model_name}")

        client = self._get_client(model_name)
        response = client.chat.completions.create(
            model=model_cfg.model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            max_tokens=8192
        )
        content = response.choices[0].message.content
        content = self._THINK_PATTERN.sub('', content).strip()
        return content
```

- [ ] **Step 2: Verify with existing example**

Read `转录结果示例.md` and confirm lines 1-19 contain `<think ...>` style content that would be stripped. The regex pattern `<think ...>...</think >` (note the space before `>`) must match.

- [ ] **Step 3: Commit**

```bash
git add core/llm_processor.py
git commit -m "fix: strip model thinking content from LLM output"
```

---

### Task 2: Add prompt leak detection and cleanup

**Files:**
- Modify: `core/llm_processor.py:84-96` (extend `_call_llm`)
- Modify: `web/app.py:106-128` (the worker result collection)

- [ ] **Step 1: Add warning log for prompt echo in `_call_llm()`**

In `core/llm_processor.py`, after the thinking content filter, add a best-effort warning:

```python
_PROMPT_ECHO_PATTERNS = [
    "请对以下文本进行",
    "The user wants me to",
    "我需要对以下",
    "Let me process",
]

def _call_llm(self, model_name: str, prompt: str) -> str:
    # ... existing code ...
    content = self._THINK_PATTERN.sub('', content).strip()

    # Best-effort prompt echo detection (log only, don't block)
    first_line = content.split('\n', 1)[0][:100]
    for pattern in self._PROMPT_ECHO_PATTERNS:
        if pattern in first_line:
            logger.warning("Possible prompt echo detected in LLM response (model: %s)", model_name)
            break

    return content
```

- [ ] **Step 2: Add prompt fragment cleanup in worker**

In `web/app.py`, inside the `_worker()` function, after reading refined files (around line 117), add cleanup:

```python
# Inside the worker, after refined_parts collection:
def _clean_prompt_leak(text: str) -> str:
    """Strip leading prompt fragments that leaked into LLM output."""
    lines = text.split('\n')
    cleaned = []
    skip = True
    for line in lines:
        if skip and (line.strip().startswith('请对以下') or
                     line.strip().startswith('The user wants') or
                     line.strip().startswith('我需要')):
            continue
        skip = False
        cleaned.append(line)
    return '\n'.join(cleaned)

# Apply before joining:
refined_parts = [_clean_prompt_leak(p) for p in refined_parts]
```

- [ ] **Step 3: Commit**

```bash
git add core/llm_processor.py web/app.py
git commit -m "fix: detect and clean prompt echo from LLM output"
```

---

## Phase 2: Result Display & Reading Experience

### Task 3: Configure marked.js with GFM and better Markdown CSS

**Files:**
- Modify: `web/static/app.js:1-10` (add marked config)
- Modify: `web/static/style.css:487-541` (`.markdown-body` section)

- [ ] **Step 1: Configure marked with GFM in `app.js`**

Add at the top of `app.js`, after the state declarations:

```javascript
// Configure marked.js
marked.setOptions({
    gfm: true,
    breaks: false,
    headerIds: true,
});
```

- [ ] **Step 2: Replace `.markdown-body` CSS with GitHub-style theme**

Replace the entire `.markdown-body` section in `style.css` (lines 487-541) with enhanced styles:

```css
/* GitHub-style Markdown */
.markdown-body h1 {
    font-size: 22px;
    font-weight: 700;
    margin: 28px 0 10px;
    padding-bottom: 8px;
    border-bottom: 2px solid var(--border-color);
}
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
.markdown-body h4 {
    font-size: 15px;
    font-weight: 600;
    margin: 16px 0 4px;
}
.markdown-body p { margin: 10px 0; line-height: 1.8; }
.markdown-body ul, .markdown-body ol {
    margin: 10px 0;
    padding-left: 28px;
}
.markdown-body li { margin: 4px 0; }
.markdown-body li > ul, .markdown-body li > ol { margin: 4px 0; }
.markdown-body hr {
    border: none;
    border-top: 1px solid var(--border-color);
    margin: 20px 0;
}
.markdown-body blockquote {
    border-left: 4px solid var(--primary-color);
    padding: 8px 16px;
    color: var(--text-muted);
    margin: 12px 0;
    background: var(--input-bg);
    border-radius: 0 8px 8px 0;
}
.markdown-body code {
    background: rgba(94, 92, 230, 0.08);
    padding: 2px 6px;
    border-radius: 4px;
    font-size: 13px;
    font-family: "SF Mono", Menlo, "Courier New", monospace;
}
.markdown-body pre {
    background: #1d1d1f;
    color: #e5e5e7;
    padding: 16px;
    border-radius: 10px;
    overflow-x: auto;
    margin: 14px 0;
    border-left: 4px solid var(--primary-color);
}
.markdown-body pre code {
    background: none;
    padding: 0;
    color: inherit;
}
.markdown-body table {
    width: 100%;
    border-collapse: collapse;
    margin: 14px 0;
    font-size: 14px;
}
.markdown-body th, .markdown-body td {
    border: 1px solid var(--border-color);
    padding: 8px 12px;
    text-align: left;
}
.markdown-body th {
    background: var(--input-bg);
    font-weight: 600;
}
.markdown-body tr:nth-child(even) { background: var(--input-bg); }
.markdown-body strong { font-weight: 600; color: var(--text-main); }
.markdown-body img {
    max-width: 100%;
    border-radius: 8px;
    margin: 8px 0;
}
```

- [ ] **Step 3: Commit**

```bash
git add web/static/app.js web/static/style.css
git commit -m "feat: configure marked.js GFM and add GitHub-style Markdown CSS"
```

---

### Task 4: Add Table of Contents sidebar

**Files:**
- Modify: `web/static/index.html:77` (add TOC container)
- Modify: `web/static/app.js:495-509` (extend `renderResultContent`)
- Modify: `web/static/style.css` (add TOC styles)

- [ ] **Step 1: Add TOC container in `index.html`**

After line 77 (`<div id="result-content"...></div>`), add:

```html
<nav id="toc-sidebar" class="toc-sidebar" style="display:none;"></nav>
```

And wrap the result content and TOC in a flex container. Change line 77 to:

```html
<div class="result-body">
    <div id="result-content" class="result-content markdown-body"></div>
    <nav id="toc-sidebar" class="toc-sidebar" style="display:none;"></nav>
</div>
```

Add the wrapper div `result-body` around both elements (replace lines 77 with the wrapper).

- [ ] **Step 2: Add TOC extraction and rendering in `app.js`**

Add TOC functions after `renderResultContent()`:

```javascript
function extractHeadings(html) {
    const temp = document.createElement('div');
    temp.innerHTML = html;
    const headings = temp.querySelectorAll('h2, h3');
    if (headings.length < 3) return [];
    return Array.from(headings).map((h, i) => ({
        level: h.tagName === 'H2' ? 2 : 3,
        text: h.textContent,
        id: h.id || `heading-${i}`
    }));
}

function renderTOC(headings) {
    const sidebar = document.getElementById('toc-sidebar');
    if (!sidebar || headings.length < 3) {
        if (sidebar) sidebar.style.display = 'none';
        return;
    }
    sidebar.style.display = '';
    sidebar.innerHTML = '<div class="toc-title">目录</div>' +
        headings.map(h =>
            `<a class="toc-link level-${h.level}" href="#${h.id}" onclick="scrollToHeading(event, '${h.id}')">${escapeHtml(h.text)}</a>`
        ).join('');
}

function scrollToHeading(event, id) {
    event.preventDefault();
    const el = document.getElementById(id);
    if (el) el.scrollIntoView({ behavior: 'smooth', block: 'start' });
}
```

Modify `renderResultContent()` to call TOC after rendering:

```javascript
function renderResultContent() {
    if (!taskDataCache) return;
    const content = document.getElementById('result-content');
    const text = currentResultTab === 'refined'
        ? taskDataCache.refined_text
        : taskDataCache.raw_text;

    if (text) {
        content.innerHTML = marked.parse(text);
        // Add IDs to headings for TOC linking
        content.querySelectorAll('h2, h3').forEach((h, i) => {
            if (!h.id) h.id = `heading-${i}`;
        });
        const headings = extractHeadings(content.innerHTML);
        renderTOC(headings);
    } else if (taskDataCache.status === 'failed') {
        content.innerHTML = `<p class="error-msg">${escapeHtml(taskDataCache.error_message || '处理失败')}</p>`;
        renderTOC([]);
    } else {
        content.innerHTML = '<p class="empty-state">处理中，请稍候...</p>';
        renderTOC([]);
    }
}
```

- [ ] **Step 3: Add TOC CSS styles in `style.css`**

```css
.result-body {
    display: flex;
    gap: 20px;
    position: relative;
}
.result-content {
    flex: 1;
    min-width: 0;
}
.toc-sidebar {
    width: 180px;
    flex-shrink: 0;
    position: sticky;
    top: 20px;
    max-height: 70vh;
    overflow-y: auto;
    font-size: 13px;
}
.toc-title {
    font-weight: 600;
    font-size: 12px;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    color: var(--text-muted);
    margin-bottom: 8px;
}
.toc-link {
    display: block;
    padding: 3px 0;
    color: var(--text-muted);
    text-decoration: none;
    transition: color 0.2s;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
}
.toc-link:hover { color: var(--primary-color); }
.toc-link.level-3 { padding-left: 12px; }
```

Add responsive rule inside the existing `@media (max-width: 480px)` block:

```css
.toc-sidebar { display: none !important; }
```

- [ ] **Step 4: Commit**

```bash
git add web/static/index.html web/static/app.js web/static/style.css
git commit -m "feat: add table of contents sidebar for long documents"
```

---

### Task 5: Add export and copy toolbar

**Files:**
- Modify: `web/static/index.html:73` (add toolbar before tabs)
- Modify: `web/static/app.js` (add export/copy functions)
- Modify: `web/static/style.css` (add toolbar styles)

- [ ] **Step 1: Add toolbar HTML in `index.html`**

After the result-header div (line 72), add before the tabs:

```html
<div class="result-toolbar" id="result-toolbar">
    <button class="toolbar-btn" onclick="downloadMarkdown()">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>
        下载 .md
    </button>
    <button class="toolbar-btn" onclick="copyCurrentText()">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 01-2-2V4a2 2 0 012-2h9a2 2 0 012 2v1"/></svg>
        复制全文
    </button>
    <button class="toolbar-btn" id="copy-raw-btn" onclick="copyRawText()" style="display:none;">
        复制原文
    </button>
</div>
```

- [ ] **Step 2: Add export/copy functions in `app.js`**

```javascript
function downloadMarkdown() {
    if (!taskDataCache) return;
    const text = currentResultTab === 'refined'
        ? taskDataCache.refined_text
        : taskDataCache.raw_text;
    if (!text) return;

    const title = (taskDataCache.title || taskDataCache.video_id || 'transcript').replace(/[^\w一-鿿-]/g, '_');
    const blob = new Blob([text], { type: 'text/markdown;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `${title}.md`;
    a.click();
    URL.revokeObjectURL(url);
    showToast('已下载');
}

function copyCurrentText() {
    if (!taskDataCache) return;
    const text = currentResultTab === 'refined'
        ? taskDataCache.refined_text
        : taskDataCache.raw_text;
    if (!text) return;
    navigator.clipboard.writeText(text).then(() => showToast('已复制'));
}

function copyRawText() {
    if (!taskDataCache || !taskDataCache.raw_text) return;
    navigator.clipboard.writeText(taskDataCache.raw_text).then(() => showToast('已复制原文'));
}
```

Update `renderResultContent()` to toggle the "复制原文" button:

```javascript
// Inside renderResultContent, after setting content.innerHTML:
const copyRawBtn = document.getElementById('copy-raw-btn');
if (copyRawBtn) {
    copyRawBtn.style.display = (currentResultTab === 'refined' && taskDataCache.raw_text) ? '' : 'none';
}
```

- [ ] **Step 3: Add toolbar CSS**

```css
.result-toolbar {
    display: flex;
    gap: 6px;
    margin-bottom: 12px;
    overflow-x: auto;
    -webkit-overflow-scrolling: touch;
}
.toolbar-btn {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    padding: 6px 12px;
    border: 1px solid var(--border-color);
    border-radius: 8px;
    background: var(--surface-color);
    color: var(--text-muted);
    font-size: 13px;
    cursor: pointer;
    transition: var(--transition-base);
    white-space: nowrap;
    min-height: 36px;
}
.toolbar-btn:hover {
    border-color: var(--primary-color);
    color: var(--primary-color);
    background: rgba(94, 92, 230, 0.04);
}
```

- [ ] **Step 4: Commit**

```bash
git add web/static/index.html web/static/app.js web/static/style.css
git commit -m "feat: add download .md and copy text toolbar to result page"
```

---

## Phase 3: Processing Flow & Feedback

### Task 6: Add yt-dlp download progress callback

**Files:**
- Modify: `core/downloader.py:26-53` (add `progress_callback` to methods)

- [ ] **Step 1: Add `progress_callback` to `AudioDownloader`**

In `core/downloader.py`, modify the class:

```python
def __init__(self, cookies_path: str = None):
    self.cookies_path = cookies_path
    self.progress_callback = None

def _ydl_progress_hook(self, d):
    """yt-dlp progress hook — reports download percentage."""
    if not self.progress_callback:
        return
    if d['status'] == 'downloading':
        total = d.get('_total_bytes') or d.get('_total_bytes_estimate') or 0
        downloaded = d.get('_downloaded_bytes', 0)
        if total > 0:
            percent = int(downloaded / total * 100)
            self.progress_callback('progress', {
                'stage': 'downloading',
                'percent': percent,
                'detail': f'{percent}%'
            })
    elif d['status'] == 'finished':
        self.progress_callback('progress', {
            'stage': 'downloading',
            'percent': 100,
            'detail': '下载完成'
        })
```

Add `progress_callback` parameter to `download()`:

```python
def download(self, url: str, output_dir: str = None, progress_callback=None) -> Tuple[str, str]:
    """单视频下载"""
    self.progress_callback = progress_callback
    video_id = self.extract_video_id(url)
    if output_dir is None:
        output_dir = f"output/{video_id}"
    os.makedirs(output_dir, exist_ok=True)

    ydl_opts = {
        'format': 'bestaudio/best',
        'outtmpl': f"{output_dir}/source.%(ext)s",
        'postprocessors': [{'key': 'FFmpegExtractAudio', 'preferredcodec': 'mp3', 'preferredquality': '192'}],
        'cookiefile': self._cookiefile,
        'nocheckcertificate': True,
        'progress_hooks': [self._ydl_progress_hook],
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.download([url])

    final_path = os.path.join(output_dir, "source.mp3")
    return final_path, video_id
```

Similarly update `_process_playlist()` to pass `progress_callback` and add `progress_hooks` to the ydl_opts dict inside the for loop (line 76-82):

```python
def _process_playlist(self, url, output_dir, entries, max_duration, progress_callback=None):
    self.progress_callback = progress_callback
    # ... inside the for loop, add to ydl_opts:
    # 'progress_hooks': [self._ydl_progress_hook],
```

Update `download_and_merge()` signature to accept and forward `progress_callback`:

```python
def download_and_merge(self, url: str, output_dir: str = None, max_duration: int = 3600,
                       progress_callback=None) -> Tuple[str, str, List[str]]:
    video_id = self.extract_video_id(url)
    if output_dir is None:
        output_dir = f"output/{video_id}"
    os.makedirs(output_dir, exist_ok=True)

    # ... existing info extraction code ...

    if 'entries' in info and len(info['entries']) > 1:
        return self._process_playlist(url, output_dir, info['entries'], max_duration,
                                      progress_callback=progress_callback)
    else:
        path, vid = self.download(url, output_dir, progress_callback=progress_callback)
        return path, vid, [path]
```

- [ ] **Step 2: Commit**

```bash
git add core/downloader.py
git commit -m "feat: add yt-dlp download progress callback to AudioDownloader"
```

---

### Task 7: Wire downloader progress and add structured SSE progress events

**Files:**
- Modify: `core/summarizer.py:100-104` (wire downloader progress)
- Modify: `core/summarizer.py:115-121` (add chunk progress events)
- Modify: `web/app.py:97-98` (handle new `progress` event type)

- [ ] **Step 1: Wire downloader progress in `summarizer.py`**

In `process()`, pass `progress_callback` to `download_and_merge()`:

```python
# Line 194, change:
_, video_id, merged_files = self.downloader.download_and_merge(url, output_dir=output_dir)
# To:
_, video_id, merged_files = self.downloader.download_and_merge(
    url, output_dir=output_dir, progress_callback=progress_callback
)
```

- [ ] **Step 2: Add multi-part progress events in `_process_part()`**

In `_process_part()`, add structured progress for multi-part videos (around line 144):

```python
# After the existing progress_callback("log", {"message": f"正在处理第 {idx}/{total} 部分..."}):
if progress_callback:
    progress_callback('progress', {
        'stage': 'transcribing',
        'percent': int(idx / total * 100),
        'detail': f'第 {idx}/{total} 部分'
    })
```

- [ ] **Step 3: Add chunk progress events in `_refine()`**

In `_refine()`, add structured progress events alongside existing log events:

```python
# In _refine(), before the for loop:
total_chunks = len(chunks)
if progress_callback:
    progress_callback('progress', {
        'stage': 'refining',
        'percent': 0,
        'detail': f'共 {total_chunks} 块'
    })

# Inside the for loop, after existing progress_callback("log", ...):
if progress_callback:
    progress_callback('progress', {
        'stage': 'refining',
        'percent': int((i + 1) / total_chunks * 100),
        'detail': f'第 {i + 1}/{total_chunks} 块'
    })
```

- [ ] **Step 3: Commit**

```bash
git add core/summarizer.py
git commit -m "feat: wire downloader progress and add structured chunk progress events"
```

---

### Task 8: Frontend progress bar and enhanced log display

**Files:**
- Modify: `web/static/app.js:266-340` (SSE handlers)
- Modify: `web/static/style.css` (progress bar styles)

- [ ] **Step 1: Add `progress` event listener in `openSSE()`**

In `app.js`, inside `openSSE()`, add after the `log` listener:

```javascript
es.addEventListener('progress', (e) => {
    const data = JSON.parse(e.data);
    updateProgress(taskId, data);
});
```

- [ ] **Step 2: Add `updateProgress()` function in `app.js`**

```javascript
function updateProgress(taskId, data) {
    // Update progress text in pipeline
    const pipeline = document.getElementById(`pipeline-${taskId}`);
    if (!pipeline) return;

    let progressEl = pipeline.querySelector('.pipeline-progress');
    if (!progressEl) {
        progressEl = document.createElement('div');
        progressEl.className = 'pipeline-progress';
        pipeline.parentNode.insertBefore(progressEl, pipeline.nextSibling);
    }
    if (data.detail) {
        progressEl.textContent = data.detail;
        progressEl.style.display = '';
    }
}
```

- [ ] **Step 3: Update `appendLog()` to keep 8 lines instead of 5**

```javascript
// Change line 336:
while (logs.children.length > 8) {
```

- [ ] **Step 4: Add progress text CSS**

```css
.pipeline-progress {
    font-size: 11px;
    color: var(--primary-color);
    margin-top: 4px;
    font-weight: 500;
}
```

- [ ] **Step 5: Commit**

```bash
git add web/static/app.js web/static/style.css
git commit -m "feat: add SSE progress bar and increase log display to 8 lines"
```

---

### Task 9: Queue visibility

**Files:**
- Modify: `web/app.py:43` (add `_queue_order` list)
- Modify: `web/app.py:209-223` (update task creation and worker)
- Modify: `web/app.py:318-332` (update `_task_to_dict`)
- Modify: `web/static/app.js:208-257` (update `renderTasks`)

- [ ] **Step 1: Add `_queue_order` tracking in `web/app.py`**

After line 43 (`_task_queue: queue.Queue = ...`), add:

```python
_queue_order: list[str] = []
```

In `api_create_task()` (around line 221), change:

```python
_task_queue.put(task.id)
```

to:

```python
_queue_order.append(task.id)
_task_queue.put(task.id)
```

In `_worker()`, at the start of the loop (line 87), add removal:

```python
task_id = _task_queue.get()
# Remove from queue order
try:
    _queue_order.remove(task_id)
except ValueError:
    pass
```

- [ ] **Step 2: Add `queue_position` to `_task_to_dict()`**

In `_task_to_dict()`, add to the dict:

```python
d["queue_position"] = (
    _queue_order.index(task.id) + 1
    if task.status == "pending" and task.id in _queue_order
    else 0
)
```

- [ ] **Step 3: Update frontend to show queue position**

In `renderTasks()` in `app.js`, update the pending status display. Replace the status-dot section for pending tasks:

```javascript
// In the task-item template, update the task-meta div:
const queueHtml = t.status === 'pending' && t.queue_position
    ? `<span class="queue-badge">排队中 (第 ${t.queue_position} 位)</span>`
    : '';
// Add ${queueHtml} after the status span in task-meta
```

Add CSS:

```css
.queue-badge {
    background: rgba(94, 92, 230, 0.08);
    color: var(--primary-color);
    padding: 2px 8px;
    border-radius: 10px;
    font-size: 11px;
    font-weight: 500;
}
```

- [ ] **Step 4: Commit**

```bash
git add web/app.py web/static/app.js web/static/style.css
git commit -m "feat: show queue position for pending tasks"
```

---

## Phase 4: Task Management & Customization

### Task 10: Add tags column and model column to database

**Files:**
- Modify: `web/database.py:18-31` (Task model)
- Modify: `web/database.py:41-48` (`create_task` function)

- [ ] **Step 1: Add `tags` and `model` columns to Task model**

In `web/database.py`, add after the `error_message` column:

```python
tags = Column(Text, default="")  # JSON array string, e.g. '["AI","访谈"]'
model = Column(String, default="")  # Selected model name
```

- [ ] **Step 2: Update `create_task()` to accept optional tags and model**

```python
def create_task(url: str, video_id: str, tags: str = "", model: str = "") -> Task:
    session = get_session()
    task = Task(url=url, video_id=video_id, title=video_id, status="pending",
                tags=tags, model=model)
    session.add(task)
    session.commit()
    session.refresh(task)
    session.close()
    return task
```

- [ ] **Step 3: Add database migration for existing databases**

`Base.metadata.create_all()` only adds columns to new databases. Existing databases need ALTER TABLE. Add migration logic in `init_db()`:

```python
from sqlalchemy import text

def init_db():
    Base.metadata.create_all(engine)
    # Migrate: add tags and model columns to existing databases
    with engine.connect() as conn:
        existing = [row[1] for row in conn.execute(text("PRAGMA table_info(tasks)"))]
        if 'tags' not in existing:
            conn.execute(text("ALTER TABLE tasks ADD COLUMN tags TEXT DEFAULT ''"))
        if 'model' not in existing:
            conn.execute(text("ALTER TABLE tasks ADD COLUMN model VARCHAR DEFAULT ''"))
        conn.commit()
```

- [ ] **Step 4: Commit**

```bash
git add web/database.py
git commit -m "feat: add tags and model columns to Task database model"
```

---

### Task 11: Update API endpoints for tags, model selection, and advanced options

**Files:**
- Modify: `web/app.py:145-158` (request schemas)
- Modify: `web/app.py:209-223` (create task endpoint)
- Modify: `web/app.py:284-294` (rename endpoint → update endpoint)
- Modify: `web/app.py:318-332` (`_task_to_dict`)
- Add: new GET `/api/models` endpoint

- [ ] **Step 1: Update request schemas**

Replace `TaskRenameRequest` with `TaskUpdateRequest`:

```python
class TaskCreateRequest(BaseModel):
    url: str
    tags: str = ""
    model: str = ""
    enable_refine: bool = True

class TaskUpdateRequest(BaseModel):
    title: str | None = None
    tags: str | None = None

    def has_field(self):
        return self.title is not None or self.tags is not None
```

- [ ] **Step 2: Add `/api/models` endpoint**

After the auth routes, add:

```python
@app.get("/api/models", dependencies=[Depends(require_auth)])
def api_list_models():
    models = []
    for name, cfg in _app_config.models.items():
        models.append({
            "name": name,
            "display_name": cfg.model.split("/")[-1] if "/" in cfg.model else cfg.model
        })
    return models
```

- [ ] **Step 3: Update `api_create_task()` to accept tags and model**

```python
@app.post("/api/tasks", dependencies=[Depends(require_auth)])
def api_create_task(req: TaskCreateRequest):
    if "bilibili.com" not in req.url:
        raise HTTPException(status_code=400, detail="请输入有效的B站链接")

    match = re.search(r"(BV[a-zA-Z0-9]+)", req.url)
    video_id = match.group(1) if match else ""

    model_name = req.model if req.model else ""
    task = create_task(url=req.url, video_id=video_id, tags=req.tags, model=model_name)

    _sse_queues[task.id] = asyncio.Queue()
    _queue_order.append(task.id)
    _task_queue.put(task.id)

    return _task_to_dict(task, include_content=False)
```

- [ ] **Step 4: Update `api_rename_task()` to `api_update_task()`**

```python
@app.patch("/api/tasks/{task_id}", dependencies=[Depends(require_auth)])
def api_update_task(task_id: str, req: TaskUpdateRequest):
    if not req.has_field():
        raise HTTPException(status_code=400, detail="至少提供一个更新字段")
    task = get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")

    updates = {}
    if req.title is not None:
        if task.status != "completed":
            raise HTTPException(status_code=400, detail="只能重命名已完成的任务")
        if not req.title.strip():
            raise HTTPException(status_code=400, detail="名称不能为空")
        updates["title"] = req.title.strip()
    if req.tags is not None:
        updates["tags"] = req.tags

    updated = update_task(task_id, **updates)
    return _task_to_dict(updated, include_content=False)
```

- [ ] **Step 5: Add `tags` and `model` to `_task_to_dict()`**

In `_task_to_dict()`, add:

```python
d["tags"] = task.tags
d["model"] = task.model
```

- [ ] **Step 6: Pass model to summarizer in worker**

In `_worker()`, update the `process()` call:

```python
model_name = task.model if task.model else None
result = _summarizer.process(
    url=task.url,
    output_dir=output_dir,
    progress_callback=progress_callback,
    model_name=model_name,
    enable_refine=task.enable_refine if hasattr(task, 'enable_refine') else True,
)
```

Note: `enable_refine` is stored in the task record. We also need to add an `enable_refine` column to the database. In `web/database.py`, add to Task model:

```python
enable_refine = Column(String, default="true")  # "true"/"false" string
```

And add migration in `init_db()`:

```python
if 'enable_refine' not in existing:
    conn.execute(text("ALTER TABLE tasks ADD COLUMN enable_refine VARCHAR DEFAULT 'true'"))
```

Update `create_task()` to accept `enable_refine`:

```python
def create_task(url: str, video_id: str, tags: str = "", model: str = "",
                enable_refine: str = "true") -> Task:
    session = get_session()
    task = Task(url=url, video_id=video_id, title=video_id, status="pending",
                tags=tags, model=model, enable_refine=enable_refine)
    ...
```

In `summarizer.py`, update `process()` signature to accept and use `enable_refine` override:

```python
def process(self, url: str, model_name: str = None, output_dir: str = None,
            progress_callback=None, enable_refine: bool = None) -> Dict[str, Any]:
    # ...
    # Use override if provided, else fall back to app config
    should_refine = enable_refine if enable_refine is not None else self.app_config.enable_refine
```

Then in `_process_part()`, replace `self.app_config.enable_refine` with `should_refine` (passed as parameter).

- [ ] **Step 7: Commit**

```bash
git add web/app.py
git commit -m "feat: add model selection, tags API, and /api/models endpoint"
```

---

### Task 12: Frontend tags UI

**Files:**
- Modify: `web/static/index.html:46-51` (add tags input)
- Modify: `web/static/app.js:208-257` (render tags in task cards)
- Modify: `web/static/style.css` (tag chip styles)

- [ ] **Step 1: Add tags input in `index.html`**

After the submit button (line 50), add:

```html
<div class="tags-input-row" id="tags-input-row">
    <input type="text" id="tags-input" placeholder="标签（逗号分隔，可选）">
</div>
```

- [ ] **Step 2: Parse and display tags in task cards**

In `renderTasks()`, add tag chips after the title row:

```javascript
// After task-title-row div, add:
const tags = t.tags ? JSON.parse(t.tags || '[]').filter(Boolean) : [];
const tagsHtml = tags.length
    ? `<div class="task-tags">${tags.map(tag => `<span class="tag-chip">${escapeHtml(tag)}</span>`).join('')}</div>`
    : '';
```

Insert `${tagsHtml}` in the template after the task-title-row div.

Update `handleSubmit()` to send tags:

```javascript
// In handleSubmit, update body:
const tags = document.getElementById('tags-input').value.trim();
body: JSON.stringify({ url, tags }),
// After successful submit, also clear tags input:
document.getElementById('tags-input').value = '';
```

- [ ] **Step 3: Add tag chip CSS**

```css
.tags-input-row {
    margin-top: 8px;
}
.tags-input-row input {
    padding: 8px 12px;
    font-size: 13px;
}
.task-tags {
    display: flex;
    flex-wrap: wrap;
    gap: 4px;
    margin-top: 4px;
}
.tag-chip {
    background: rgba(94, 92, 230, 0.08);
    color: var(--primary-color);
    padding: 2px 8px;
    border-radius: 10px;
    font-size: 11px;
    font-weight: 500;
}
```

- [ ] **Step 4: Commit**

```bash
git add web/static/index.html web/static/app.js web/static/style.css
git commit -m "feat: add tags input and tag chip display in task list"
```

---

### Task 13: Frontend model selector and advanced options

**Files:**
- Modify: `web/static/index.html` (add collapsible advanced section)
- Modify: `web/static/app.js` (fetch models, persist selection)

- [ ] **Step 1: Add collapsible advanced options in `index.html`**

After the tags input row, add:

```html
<div class="advanced-toggle" id="advanced-toggle" onclick="toggleAdvanced()">
    <span>高级选项</span>
    <span class="toggle-arrow">▾</span>
</div>
<div class="advanced-options" id="advanced-options" style="display:none;">
    <div class="option-row">
        <label for="model-select">模型</label>
        <select id="model-select">
            <option value="">默认</option>
        </select>
    </div>
    <div class="option-row" style="margin-top:8px;">
        <label for="refine-toggle">启用精炼</label>
        <label class="toggle-switch">
            <input type="checkbox" id="refine-toggle" checked>
            <span class="toggle-slider"></span>
        </label>
    </div>
</div>
```

- [ ] **Step 2: Add model fetching and toggle logic in `app.js`**

```javascript
async function fetchModels() {
    try {
        const res = await authFetch('/api/models');
        const models = await res.json();
        const select = document.getElementById('model-select');
        if (!select || !models.length) return;

        // Restore saved selection
        const saved = localStorage.getItem('selected_model');
        select.innerHTML = '<option value="">默认 (' + escapeHtml(models[0].display_name) + ')</option>' +
            models.map(m =>
                `<option value="${escapeHtml(m.name)}" ${m.name === saved ? 'selected' : ''}>${escapeHtml(m.display_name)}</option>`
            ).join('');
    } catch { /* ignore */ }
}

function toggleAdvanced() {
    const el = document.getElementById('advanced-options');
    const arrow = document.querySelector('.toggle-arrow');
    if (el.style.display === 'none') {
        el.style.display = '';
        arrow.textContent = '▴';
    } else {
        el.style.display = 'none';
        arrow.textContent = '▾';
    }
}
```

Update `handleSubmit()` to include model and enable_refine:

```javascript
const model = document.getElementById('model-select').value;
const enable_refine = document.getElementById('refine-toggle').checked;
body: JSON.stringify({ url, tags, model, enable_refine }),
if (model) localStorage.setItem('selected_model', model);
```

Call `fetchModels()` at the end of `showListPage()`:

```javascript
function showListPage() {
    document.getElementById('page-list').style.display = '';
    document.getElementById('page-result').style.display = 'none';
    document.title = 'Transcribe - 智能视频转录';
    loadTasks();
    fetchModels();
}
```

- [ ] **Step 3: Add CSS for advanced options**

```css
.advanced-toggle {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-top: 10px;
    padding: 8px 0;
    font-size: 13px;
    color: var(--text-muted);
    cursor: pointer;
    user-select: none;
}
.advanced-toggle:hover { color: var(--primary-color); }
.toggle-arrow { font-size: 12px; }
.advanced-options {
    margin-top: 8px;
    padding: 12px;
    background: var(--input-bg);
    border-radius: var(--radius-md);
}
.option-row {
    display: flex;
    align-items: center;
    gap: 12px;
}
.option-row label {
    font-size: 13px;
    color: var(--text-muted);
    white-space: nowrap;
}
.option-row select {
    flex: 1;
    padding: 8px 12px;
    border: 1px solid var(--border-color);
    border-radius: 8px;
    background: var(--surface-color);
    font-size: 14px;
    outline: none;
}
/* Toggle switch */
.toggle-switch {
    position: relative;
    display: inline-block;
    width: 44px;
    height: 24px;
    flex-shrink: 0;
}
.toggle-switch input { opacity: 0; width: 0; height: 0; }
.toggle-slider {
    position: absolute;
    cursor: pointer;
    top: 0; left: 0; right: 0; bottom: 0;
    background: var(--border-color);
    border-radius: 24px;
    transition: 0.3s;
}
.toggle-slider::before {
    content: "";
    position: absolute;
    height: 18px; width: 18px;
    left: 3px; bottom: 3px;
    background: white;
    border-radius: 50%;
    transition: 0.3s;
}
.toggle-switch input:checked + .toggle-slider { background: var(--primary-color); }
.toggle-switch input:checked + .toggle-slider::before { transform: translateX(20px); }
```

- [ ] **Step 4: Commit**

```bash
git add web/static/index.html web/static/app.js web/static/style.css
git commit -m "feat: add model selector with collapsible advanced options"
```

---

## Phase 5: Mobile Optimization

### Task 14: Touch interaction improvements

**Files:**
- Modify: `web/static/style.css` (increase tap targets)
- Modify: `web/static/app.js:154-183` (auto-dismiss keyboard)
- Modify: `web/static/index.html` (add skeleton elements)

- [ ] **Step 1: Auto-dismiss keyboard after submit**

In `handleSubmit()` in `app.js`, after `input.value = ''`:

```javascript
input.blur(); // Dismiss keyboard on mobile
```

- [ ] **Step 2: Add haptic feedback on task actions**

In `deleteTask()` and `handleSubmit()`, add:

```javascript
navigator.vibrate?.(10);
```

- [ ] **Step 3: Add skeleton loading styles**

```css
.skeleton {
    background: linear-gradient(90deg, var(--input-bg) 25%, var(--border-color) 50%, var(--input-bg) 75%);
    background-size: 200% 100%;
    animation: shimmer 1.5s infinite;
    border-radius: 6px;
}
@keyframes shimmer {
    0% { background-position: -200% 0; }
    100% { background-position: 200% 0; }
}
```

Add skeleton rendering to `loadTasks()`:

```javascript
// In loadTasks(), before fetch:
const list = document.getElementById('task-list');
list.innerHTML = Array(3).fill('<div class="task-item"><div class="task-info"><div class="skeleton" style="height:16px;width:60%;margin-bottom:8px;"></div><div class="skeleton" style="height:12px;width:40%;"></div></div></div>').join('');
```

- [ ] **Step 4: Ensure minimum tap targets in mobile CSS**

Verify all interactive elements have min 44x44px in the mobile media query. The existing CSS already has `min-height: 44px` on several elements. Add any missing ones:

```css
@media (max-width: 480px) {
    .toolbar-btn { min-height: 44px; padding: 8px 12px; }
    .rename-btn { min-height: 44px; min-width: 44px; }
    .tag-chip { padding: 4px 10px; min-height: 28px; }
}
```

- [ ] **Step 5: Commit**

```bash
git add web/static/app.js web/static/style.css
git commit -m "feat: add skeleton loading, auto-dismiss keyboard, haptic feedback"
```

---

### Task 15: Long text chunked rendering

**Files:**
- Modify: `web/static/app.js:495-509` (update `renderResultContent`)

- [ ] **Step 1: Add chunked rendering logic**

Replace `renderResultContent()` with chunked version:

```javascript
const CHUNK_THRESHOLD = 50000;
const CHUNK_SIZE = 10000;

function renderResultContent() {
    if (!taskDataCache) return;
    const content = document.getElementById('result-content');
    const text = currentResultTab === 'refined'
        ? taskDataCache.refined_text
        : taskDataCache.raw_text;

    if (text) {
        if (text.length > CHUNK_THRESHOLD) {
            renderChunked(content, text);
        } else {
            content.innerHTML = marked.parse(text);
            addHeadingIds(content);
            renderTOC(extractHeadings(content.innerHTML));
        }
        updateToolbarButtons();
    } else if (taskDataCache.status === 'failed') {
        content.innerHTML = `<p class="error-msg">${escapeHtml(taskDataCache.error_message || '处理失败')}</p>`;
        renderTOC([]);
    } else {
        content.innerHTML = '<p class="empty-state">处理中，请稍候...</p>';
        renderTOC([]);
    }
}

function renderChunked(container, text) {
    const paragraphs = text.split('\n\n');
    let currentChunk = '';
    let rendered = 0;

    function renderNextChunk() {
        let chunkText = '';
        while (rendered < paragraphs.length && chunkText.length < CHUNK_SIZE) {
            chunkText += (chunkText ? '\n\n' : '') + paragraphs[rendered];
            rendered++;
        }
        if (!chunkText) return;

        const html = marked.parse(chunkText);
        container.insertAdjacentHTML('beforeend', html);

        if (rendered < paragraphs.length) {
            const loader = document.createElement('div');
            loader.className = 'chunk-loader';
            loader.textContent = '加载更多...';
            container.appendChild(loader);

            const observer = new IntersectionObserver((entries) => {
                if (entries[0].isIntersecting) {
                    observer.disconnect();
                    loader.remove();
                    renderNextChunk();
                }
            }, { rootMargin: '200px' });
            observer.observe(loader);
        }
    }

    container.innerHTML = '';
    renderNextChunk();
    renderTOC([]); // No TOC for chunked rendering
}

function addHeadingIds(container) {
    container.querySelectorAll('h2, h3').forEach((h, i) => {
        if (!h.id) h.id = `heading-${i}`;
    });
}

function updateToolbarButtons() {
    const copyRawBtn = document.getElementById('copy-raw-btn');
    if (copyRawBtn) {
        copyRawBtn.style.display = (currentResultTab === 'refined' && taskDataCache.raw_text) ? '' : 'none';
    }
}
```

- [ ] **Step 2: Add chunk loader CSS**

```css
.chunk-loader {
    text-align: center;
    padding: 16px;
    color: var(--text-muted);
    font-size: 13px;
}
```

- [ ] **Step 3: Commit**

```bash
git add web/static/app.js web/static/style.css
git commit -m "feat: add chunked rendering for long documents on mobile"
```

---

## Final Verification

### Task 16: Integration testing and cleanup

- [ ] **Step 1: Start the web server and verify all features**

```bash
conda activate cui_ting && uvicorn web.app:app --host 0.0.0.0 --port 8000
```

Check:
- Submit a task — verify SSE progress shows percentage
- View result — verify Markdown rendering with GitHub styles
- Check TOC sidebar appears for documents with 3+ headings
- Test download .md and copy buttons
- Test tags input and display
- Test model selector dropdown
- Test queue position display
- Check mobile responsiveness

- [ ] **Step 2: Verify thinking content is filtered**

Submit a task that triggers LLM processing and verify the refined text no longer contains `<think ...>` blocks.

- [ ] **Step 3: Final commit if any fixes needed**

```bash
git add -A
git commit -m "fix: integration test fixes"
```

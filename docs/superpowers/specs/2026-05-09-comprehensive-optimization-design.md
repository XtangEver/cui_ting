# Comprehensive Optimization Design

Date: 2026-05-09

## Overview

This spec covers all optimization items identified in 待优化说明.md, organized into 5 phases by priority: bug fixes first, then experience improvements, then feature extensions.

## Phase 1: Critical Bug Fixes

### 1.1 Filter Model Thinking Content from Output

**Problem**: LLM responses contain internal reasoning/thinking content (e.g., `<think ...>...</think >` blocks) that appears in the refined text output. Example visible in 转录结果示例.md lines 1-19.

**Solution**: In `core/llm_processor.py`, add a post-processing step to `_call_llm()` that strips thinking tags from the response content before returning.

Implementation:
- Add regex pattern to match `<think ...>...</think >` and similar variants (with or without attributes, with optional whitespace before closing `>`)
- Use `re.DOTALL` flag — thinking blocks span multiple lines
- Apply stripping in `_call_llm()` after extracting `response.choices[0].message.content`
- Also handle `<thinking>` tags for models that use that format
- Strip any leading/trailing whitespace after removal

### 1.2 Prevent Prompt Leakage in Structured Summary

**Problem**: The structured summary sometimes exposes the LLM system prompt instead of actual content. This happens when the model echoes instructions back.

**Solution**: Best-effort detection — this is inherently fragile (false positives are expected for prompt-engineering content):
1. In `_call_llm()`, detect if the response starts with prompt-like patterns (e.g., "请对以下文本", "The user wants me to") and log a warning (do NOT block/filter, just log)
2. In `web/app.py` worker, after reading refined files, strip any leading prompt fragments before storing to database

## Phase 2: Result Display & Reading Experience

### 2.1 Enhanced Markdown Rendering

**Current**: `marked.min.js` with default settings, basic CSS styling.

**Target**: GitHub-flavored Markdown style with better typography.

Implementation:
- Configure `marked` with GFM (GitHub Flavored Markdown) options enabled
- Add a GitHub-style Markdown CSS theme to `style.css` under `.markdown-body`:
  - Proper heading hierarchy (h1-h4 with distinct sizes and bottom borders)
  - Styled tables with alternating row colors
  - Better code blocks with left border accent
  - Blockquote styling with colored left border
  - Horizontal rules with subtle styling
  - Task list checkbox support
- No need for syntax highlighting library (this is Chinese text content, not code)
- Add table-of-contents (TOC) sidebar for long documents:
  - Extract h2/h3 headings via `marked` renderer
  - Floating sidebar on desktop (right side), collapsible on mobile
  - Click to scroll to heading
  - Only show when document has 3+ headings

### 2.2 Export & Copy Functionality

**Target**: Add download .md, copy full text, and copy raw text buttons to the result page.

Implementation:
- Add a toolbar above the result content area with 3 buttons:
  - "下载 .md" — triggers download of `task_title.md` with refined or raw content based on current tab
  - "复制全文" — copies current tab content to clipboard, shows toast "已复制"
  - "复制原文" — copies raw text to clipboard (only shown when viewing refined tab)
- Use `navigator.clipboard.writeText()` for copy
- Use Blob + URL.createObjectURL for download
- Mobile: buttons in a horizontal scrollable row

## Phase 3: Processing Flow & Feedback

### 3.1 Granular Progress Feedback

**Current SSE events**: `stage_update` (stage name only), `log` (text lines).

**Target**: Add percentage and sub-step progress to each stage.

Implementation:

Backend changes:

`core/downloader.py`:
- Add `progress_callback` parameter to `download()`, `download_and_merge()`, and `_process_playlist()` methods
- Configure yt-dlp `progress_hooks` in all `ydl_opts` dictionaries to report download percentage
- The progress hook extracts `_percent_str` or calculates from `_downloaded_bytes / _total_bytes`

`core/summarizer.py`:
- Wire downloader's `progress_callback` through to SSE
- Transcription stage: for multi-part videos, report "第 N/M 部分" (already logged); for single Whisper calls, no sub-progress available (MLX Whisper is a single-shot operation with no streaming)
- Refinement stage: report chunk progress (e.g., "第 2/5 块") — already partially logged but not as structured progress

SSE event format change:
- `stage_update` event adds optional `progress` field: `{"stage": "refining", "status": "active", "progress": 40, "detail": "第 2/5 块"}`
- New `progress` event type for fine-grained updates within a stage: `{"stage": "refining", "percent": 40, "detail": "第 2/5 块"}`

Frontend changes in `app.js`:
- Pipeline progress indicator: add percentage text below each stage dot
- Progress bar below the pipeline indicator showing overall percentage
- Log area: increase from 5 lines to 8 lines, add auto-scroll
- Both mobile and desktop: same UI, responsive sizing

### 3.2 Queue Visibility

**Target**: Show queue position for pending tasks.

Implementation:

Backend changes in `web/app.py`:
- Maintain a separate ordered list `_queue_order: list[str]` alongside `_task_queue` — `queue.Queue` does not support position inspection
- When enqueuing a task, also append its ID to `_queue_order`; when dequeuing, pop from front
- Add `queue_position` field to task list API response (index in `_queue_order` + 1, or 0 if not queued)

Frontend changes:
- For pending tasks, show "排队中 (第 N 位)" instead of just the gray dot
- When position changes (task ahead completes), update via polling or SSE

## Phase 4: Task Management & Customization

### 4.1 Tag/Category System

**Target**: Allow adding tags to tasks for filtering.

Implementation:

Database changes in `web/database.py`:
- Add `tags` column to Task model: `Text` field, storing JSON array of strings (e.g., `'["AI","访谈"]'`)
- Keep it simple — no separate tags table, just a JSON text field

API changes in `web/app.py`:
- Rename `TaskRenameRequest` to `TaskUpdateRequest` with optional `title: str` and `tags: str` fields, with a validator ensuring at least one is present
- PATCH `/api/tasks/{id}` — accept both `title` and `tags` fields
- GET `/api/tasks` — accept `?tag=xxx` query parameter for filtering

Frontend changes:
- Task card: show tags as small colored chips below the title
- Task creation: add optional tag input (comma-separated)
- Task list: add tag filter chips at the top (showing all existing tags)
- Task rename modal: include tag editing

### 4.2 Model Selection & Advanced Options

**Target**: Allow users to select model and parameters when submitting tasks.

Implementation:

Backend changes:
- GET `/api/models` — new endpoint returning available models with `name` (internal key) and `display_name` (human-readable)
- POST `/api/tasks` — accept optional `model` field (defaults to first configured model)
- Add `model` column to Task database model
- Pass selected model and `enable_refine` flag to `VideoSummarizer.process()` — currently `enable_refine` is read from global `AppConfig`; change `process()` to accept it as an override parameter
- Run both `tags` and `model` column migrations together in a single migration step

Frontend changes:
- Below the URL input, add a collapsible "高级选项" section:
  - Model selector dropdown (fetched from `/api/models`)
  - Toggle for "启用精炼" (enable refinement)
- Keep the section collapsed by default — simple UX for casual users
- Selected options persist in localStorage for convenience

## Phase 5: Mobile Optimization

### 5.1 Touch Interaction Improvements

Implementation:
- Increase tap target sizes: all interactive elements minimum 44x44px
- Auto-dismiss keyboard after URL submission
- Add loading skeleton screen for task list and result page
- Add subtle haptic feedback via `navigator.vibrate?.(10)` on task actions (feature-detect: iOS Safari does not support Vibration API)

### 5.2 Long Text Performance

**Problem**: Very long documents may cause rendering lag on mobile.

**Solution**: Lazy rendering with `marked` — not full virtual scrolling (overkill for this use case).

Implementation:
- For documents > 50,000 characters: render in chunks of 10,000 characters (threshold defined as a JS constant for easy tuning)
- Split on paragraph boundaries (double newline `\n\n`) rather than hard-cutting at character positions, to avoid breaking Markdown syntax mid-table or mid-code-block
- Use `IntersectionObserver` to render next chunk as user scrolls near bottom
- Show "加载更多..." indicator at chunk boundaries

## Architecture Decisions

### Thinking Content Filtering Strategy

Place the filter in `_call_llm()` (core layer), not in the web layer. This ensures:
- CLI mode also benefits from the fix
- Single point of maintenance
- The filter is model-agnostic (handles `<think/>`, `<thinking>`, and any future variants)

### Tags Storage

JSON text field rather than a separate tags table because:
- The project uses SQLite, not a high-concurrency RDBMS
- Tag queries are simple (exact match, no JOINs needed)
- Avoids schema complexity for a personal-use tool

### SSE Progress Enhancement

Add a new `progress` event type rather than modifying `stage_update` because:
- Backward compatible — existing `stage_update` consumers still work
- `progress` events are higher frequency, consumers can choose to ignore them
- Clean separation of concerns

## File Change Summary

| File | Changes |
|------|---------|
| `core/llm_processor.py` | Add thinking content filter, prompt leak detection |
| `core/downloader.py` | Add `progress_callback` parameter, yt-dlp progress hooks |
| `core/summarizer.py` | Wire downloader progress, granular progress callbacks (segment count, chunk progress) |
| `web/app.py` | New endpoints (models, queue position), SSE progress events, task model/tags field, prompt leak cleanup, `_queue_order` tracking |
| `web/database.py` | Add `tags` and `model` columns to Task (single migration) |
| `web/static/app.js` | Markdown config, TOC sidebar, export/copy buttons, progress bar, queue display, tags UI, model selector, chunked rendering |
| `web/static/index.html` | New UI elements (toolbar, tags, advanced options section) |
| `web/static/style.css` | GitHub Markdown theme, TOC sidebar, toolbar, tags chips, skeleton screens, mobile improvements |

## Implementation Order

Execute phases in order 1→2→3→4→5. Within each phase, items are ordered by dependency. Each phase produces a working, deployable state.

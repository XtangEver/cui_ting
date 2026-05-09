// State
const sseConnections = {};
let currentResultTab = 'refined';
let taskDataCache = null;

// Pipeline stage order (only moves forward)
const STAGES = ['downloading', 'transcribing', 'refining'];
const STAGE_LABELS = { downloading: '下载', transcribing: '转录', refining: 'LLM处理' };

// Configure marked.js
marked.setOptions({
    gfm: true,
    breaks: false,
    headerIds: true,
});

// --- Auth-aware fetch ---
async function authFetch(url, options = {}) {
    const res = await fetch(url, options);
    if (res.status === 401) {
        showLoginPage();
        throw new Error('未登录');
    }
    return res;
}

// --- Auth ---
async function checkAuth() {
    try {
        const res = await fetch('/api/auth/check');
        return res.ok;
    } catch {
        return false;
    }
}

function showLoginPage() {
    document.getElementById('page-login').style.display = '';
    document.getElementById('page-list').style.display = 'none';
    document.getElementById('page-result').style.display = 'none';
    document.title = 'Transcribe - 登录';
}

function showApp() {
    document.getElementById('page-login').style.display = 'none';
    document.getElementById('page-list').style.display = '';
    document.title = 'Transcribe - 智能视频转录';
    initRouter();
}

async function handleLogin() {
    const username = document.getElementById('login-username').value.trim();
    const password = document.getElementById('login-password').value.trim();
    const errorEl = document.getElementById('login-error');
    const btn = document.getElementById('login-btn');

    if (!username || !password) {
        errorEl.textContent = '请输入账号和密码';
        errorEl.style.display = '';
        return;
    }

    btn.disabled = true;
    errorEl.style.display = 'none';

    try {
        const res = await fetch('/api/auth/login', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ username, password }),
        });
        if (res.ok) {
            showApp();
        } else {
            const err = await res.json();
            errorEl.textContent = err.detail || '登录失败';
            errorEl.style.display = '';
        }
    } catch {
        errorEl.textContent = '网络错误';
        errorEl.style.display = '';
    } finally {
        btn.disabled = false;
    }
}

async function handleLogout() {
    await fetch('/api/auth/logout', { method: 'POST' });
    Object.keys(sseConnections).forEach(closeSSE);
    showLoginPage();
}

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
    fetchModels();
}

function showResultPage(taskId) {
    document.getElementById('page-list').style.display = 'none';
    document.getElementById('page-result').style.display = '';
    loadResult(taskId);
}

// --- Init ---
document.addEventListener('DOMContentLoaded', async () => {
    // Login form
    document.getElementById('login-btn').addEventListener('click', handleLogin);
    document.getElementById('login-password').addEventListener('keypress', (e) => {
        if (e.key === 'Enter') handleLogin();
    });

    // Logout
    document.getElementById('logout-btn').addEventListener('click', handleLogout);

    // Submit
    document.getElementById('submit-btn').addEventListener('click', handleSubmit);
    document.getElementById('url-input').addEventListener('keypress', (e) => {
        if (e.key === 'Enter') handleSubmit();
    });

    // Back button
    document.getElementById('back-btn').addEventListener('click', () => {
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

    // Check auth and show appropriate page
    if (await checkAuth()) {
        showApp();
    } else {
        showLoginPage();
    }
});

// --- Submit ---
async function fetchModels() {
    try {
        const res = await authFetch('/api/models');
        const models = await res.json();
        const select = document.getElementById('model-select');
        if (!select || !models.length) return;

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

async function handleSubmit() {
    const input = document.getElementById('url-input');
    const btn = document.getElementById('submit-btn');
    const url = input.value.trim();
    const tagsInput = document.getElementById('tags-input');
    const tags = tagsInput ? tagsInput.value.trim() : '';
    if (!url) {
        showToast('请输入有效链接');
        return;
    }

    btn.disabled = true;
    const model = document.getElementById('model-select')?.value || '';
    const enable_refine = document.getElementById('refine-toggle')?.checked ?? true;
    try {
        const res = await authFetch('/api/tasks', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ url, tags, model, enable_refine }),
        });
        if (!res.ok) {
            const err = await res.json();
            showToast(err.detail || '提交失败');
            return;
        }
        input.value = '';
        input.blur(); // Dismiss keyboard on mobile
        if (tagsInput) tagsInput.value = '';
        if (model) localStorage.setItem('selected_model', model);
        showToast('提交成功，正在处理');
        navigator.vibrate?.(10);
        await loadTasks();
    } catch (e) {
        if (e.message !== '未登录') showToast('网络错误');
    } finally {
        btn.disabled = false;
    }
}

// --- Task list ---
async function loadTasks() {
    try {
        const list = document.getElementById('task-list');
        list.innerHTML = Array(3).fill('<div class="task-item"><div class="task-info"><div class="skeleton" style="height:16px;width:60%;margin-bottom:8px;"></div><div class="skeleton" style="height:12px;width:40%;"></div></div></div>').join('');
        const res = await authFetch('/api/tasks');
        const tasks = await res.json();
        // Close all SSE before re-rendering (old DOM elements will be destroyed)
        Object.keys(sseConnections).forEach(closeSSE);

        renderTasks(tasks);

        // Re-open SSE for active tasks (new DOM elements)
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
        const displayName = escapeHtml(t.title || t.video_id || t.url);
        const renameBtn = isClickable
            ? `<button class="rename-btn" onclick="event.stopPropagation(); startRename('${t.id}')">✎</button>` : '';
        const queueHtml = t.status === 'pending' && t.queue_position
            ? `<span class="queue-badge">排队中 (第 ${t.queue_position} 位)</span>`
            : '';
        const tags = t.tags ? JSON.parse(t.tags || '[]').filter(Boolean) : [];
        const tagsHtml = tags.length
            ? `<div class="task-tags">${tags.map(tag => `<span class="tag-chip">${escapeHtml(tag)}</span>`).join('')}</div>`
            : '';

        return `
            <div class="task-item ${isClickable ? 'clickable' : ''}" data-id="${t.id}"
                 ${isClickable ? `onclick="window.location.href='/result/${t.id}'"` : ''}>
                <div class="task-info">
                    <div class="task-title-row">
                        <span class="task-bv" id="title-${t.id}">${displayName}</span>
                        ${renameBtn}
                    </div>
                    ${tagsHtml}
                    <div class="task-meta">
                        <span class="status-dot ${t.status}"></span>
                        <span>${statusLabel(t.status)}</span>
                        ${queueHtml}
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

    es.addEventListener('progress', (e) => {
        const data = JSON.parse(e.data);
        updateProgress(taskId, data);
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

    es.onerror = () => {
        // EventSource will auto-retry; we only clean up if the task is terminal
        // (the complete/task_error handlers above handle terminal cleanup)
    };
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

function updateProgress(taskId, data) {
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

function appendLog(taskId, message) {
    const logs = document.getElementById(`logs-${taskId}`);
    if (!logs) return;

    const line = document.createElement('div');
    line.textContent = message;
    logs.appendChild(line);

    // Keep last 5 lines
    while (logs.children.length > 8) {
        logs.removeChild(logs.firstChild);
    }
    logs.scrollTop = logs.scrollHeight;
}

// --- Delete ---
async function deleteTask(id, element) {
    navigator.vibrate?.(10);
    if (!confirm('确定删除此任务？')) return;
    closeSSE(id);

    if (element) {
        element.classList.add('exit-animation');
        await new Promise(r => setTimeout(r, 300));
    }

    await authFetch(`/api/tasks/${id}`, { method: 'DELETE' });
    showToast('任务已移除');
    await loadTasks();
}

// --- Rename ---
function startRename(taskId) {
    const titleEl = document.getElementById(`title-${taskId}`);
    if (!titleEl) return;
    const currentTitle = titleEl.textContent;

    const input = document.createElement('input');
    input.className = 'rename-input';
    input.value = currentTitle;
    input.onclick = (e) => e.stopPropagation();

    titleEl.replaceWith(input);
    input.focus();
    input.select();

    let saved = false;
    const save = async () => {
        if (saved) return;
        saved = true;
        const newTitle = input.value.trim();
        if (newTitle && newTitle !== currentTitle) {
            try {
                await authFetch(`/api/tasks/${taskId}`, {
                    method: 'PATCH',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ title: newTitle }),
                });
                showToast('已重命名');
            } catch { /* ignore */ }
        }
        loadTasks();
    };

    input.addEventListener('blur', save);
    input.addEventListener('keypress', (e) => {
        if (e.key === 'Enter') { e.preventDefault(); save(); }
        if (e.key === 'Escape') { saved = true; loadTasks(); }
    });
}

function startResultRename() {
    if (!taskDataCache || taskDataCache.status !== 'completed') return;
    const titleEl = document.getElementById('result-title');
    const renameBtn = document.getElementById('result-rename-btn');
    const currentTitle = titleEl.textContent;

    const input = document.createElement('input');
    input.className = 'rename-input';
    input.value = taskDataCache.title || currentTitle;

    titleEl.style.display = 'none';
    renameBtn.style.display = 'none';
    titleEl.parentNode.insertBefore(input, renameBtn);
    input.focus();
    input.select();

    let saved = false;
    const save = async () => {
        if (saved) return;
        saved = true;
        const newTitle = input.value.trim();
        if (newTitle && newTitle !== currentTitle) {
            try {
                const res = await authFetch(`/api/tasks/${taskDataCache.id}`, {
                    method: 'PATCH',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ title: newTitle }),
                });
                if (res.ok) {
                    taskDataCache.title = newTitle;
                    showToast('已重命名');
                }
            } catch { /* ignore */ }
        }
        input.remove();
        titleEl.textContent = taskDataCache.title || currentTitle;
        titleEl.style.display = '';
        renameBtn.style.display = '';
    };

    input.addEventListener('blur', save);
    input.addEventListener('keypress', (e) => {
        if (e.key === 'Enter') { e.preventDefault(); save(); }
        if (e.key === 'Escape') {
            saved = true;
            input.remove();
            titleEl.style.display = '';
            renameBtn.style.display = '';
        }
    });
}

// --- Result page ---
async function loadResult(taskId) {
    const title = document.getElementById('result-title');
    const content = document.getElementById('result-content');

    title.textContent = '加载中...';
    content.innerHTML = '';

    try {
        const res = await authFetch(`/api/tasks/${taskId}`);
        if (!res.ok) {
            title.textContent = '任务不存在';
            content.innerHTML = '<p class="empty-state">找不到该任务</p>';
            return;
        }
        taskDataCache = await res.json();
        title.textContent = taskDataCache.title || taskDataCache.video_id || '转录结果';

        // Show rename button for completed tasks
        const renameBtn = document.getElementById('result-rename-btn');
        renameBtn.style.display = taskDataCache.status === 'completed' ? '' : 'none';

        // If still processing, poll until done
        if (taskDataCache.status === 'pending' || taskDataCache.status === 'processing') {
            const checkDone = setInterval(async () => {
                try {
                    const r = await authFetch(`/api/tasks/${taskId}`);
                    const t = await r.json();
                    if (t.status === 'completed' || t.status === 'failed') {
                        clearInterval(checkDone);
                        taskDataCache = t;
                        renderResultContent();
                    }
                } catch {
                    clearInterval(checkDone);
                }
            }, 3000);
        }

        renderResultContent();
    } catch {
        title.textContent = '加载失败';
        content.innerHTML = '<p class="empty-state">网络错误</p>';
    }
}

function extractHeadings(container) {
    const headings = container.querySelectorAll('h2, h3');
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
        renderTOC(extractHeadings(content));
        const copyRawBtn = document.getElementById('copy-raw-btn');
        if (copyRawBtn) {
            copyRawBtn.style.display = (currentResultTab === 'refined' && taskDataCache.raw_text) ? '' : 'none';
        }
    } else if (taskDataCache.status === 'failed') {
        content.innerHTML = `<p class="error-msg">${escapeHtml(taskDataCache.error_message || '处理失败')}</p>`;
        renderTOC([]);
    } else {
        content.innerHTML = '<p class="empty-state">处理中，请稍候...</p>';
        renderTOC([]);
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

// --- Export & Copy ---
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

// --- Utils ---
function escapeHtml(str) {
    if (!str) return '';
    const d = document.createElement('div');
    d.textContent = str;
    return d.innerHTML;
}

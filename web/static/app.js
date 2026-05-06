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

        // If still processing, poll until done
        if (taskDataCache.status === 'pending' || taskDataCache.status === 'processing') {
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

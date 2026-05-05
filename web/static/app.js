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

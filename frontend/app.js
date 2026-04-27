// Report Master v0.7 - 前端主逻辑
// 重点：语料上传、任务可中止、A4 导出、简洁界面体验

const API_BASE = window.location.origin;
const STORAGE_CONFIG_KEY = 'reportmaster_config';
const STORAGE_HISTORY_KEY = 'reportmaster_history';
const MAX_HISTORY_ITEMS = 50;
const REQUIRED_ROLES = ['结构规划者', '调研者', '主笔人', '编辑', '审稿人'];

let socket = null;
let currentConfig = null;
let latestResultText = '';
let workflowRunning = false;
let uploadedCorpusText = '';

const DEFAULT_CONFIG = {
    '结构规划者': {
        description: '负责规划报告/论文的整体结构和大纲',
        system_prompt: '你是结构规划专家，请输出结构清晰、可执行的大纲。',
        api_config: {
            api_type: 'openai',
            api_key: '',
            base_url: 'https://api.openai.com/v1',
            model: 'gpt-4o-mini'
        },
        api_params: {
            temperature: 0.7,
            max_tokens: 2000
        }
    },
    '调研者': {
        description: '负责收集资料、文献和案例，补充论据',
        system_prompt: '你是调研专家，请输出可用于论文写作的资料要点与引用建议。',
        api_config: {
            api_type: 'openai',
            api_key: '',
            base_url: 'https://api.openai.com/v1',
            model: 'gpt-4o-mini'
        },
        api_params: {
            temperature: 0.6,
            max_tokens: 2000
        }
    },
    '主笔人': {
        description: '负责根据大纲与资料撰写完整初稿',
        system_prompt: '你是主笔人，请产出完整、逻辑清晰、学术表达规范的初稿。',
        api_config: {
            api_type: 'openai',
            api_key: '',
            base_url: 'https://api.openai.com/v1',
            model: 'gpt-4o-mini'
        },
        api_params: {
            temperature: 0.8,
            max_tokens: 3200
        }
    },
    '编辑': {
        description: '负责润色表达、优化结构和语言风格',
        system_prompt: '你是学术编辑，请对文本进行语言与结构双重优化。',
        api_config: {
            api_type: 'openai',
            api_key: '',
            base_url: 'https://api.openai.com/v1',
            model: 'gpt-4o-mini'
        },
        api_params: {
            temperature: 0.6,
            max_tokens: 2800
        }
    },
    '审稿人': {
        description: '负责审查质量并给出大修/小修/接收结论',
        system_prompt: '你是严谨审稿人，请给出明确决定与可执行修改建议。',
        api_config: {
            api_type: 'openai',
            api_key: '',
            base_url: 'https://api.openai.com/v1',
            model: 'gpt-4o-mini'
        },
        api_params: {
            temperature: 0.5,
            max_tokens: 1600
        }
    }
};

document.addEventListener('DOMContentLoaded', () => {
    initNavigation();
    loadConfig();
    renderConfigPage();
    initEventListeners();
    initSocket();
    initWordEditorControls();
    setWorkflowButtonState(false);
});

// ----------------------------
// 初始化与基础工具
// ----------------------------
function deepClone(obj) {
    return JSON.parse(JSON.stringify(obj));
}

function normalizeText(value) {
    if (value === null || value === undefined) return '';
    return typeof value === 'string' ? value : JSON.stringify(value, null, 2);
}

function safeParseJSON(raw, fallback) {
    try {
        return JSON.parse(raw);
    } catch {
        return fallback;
    }
}

function formatTime(ts) {
    if (!ts) return new Date().toLocaleTimeString('zh-CN');
    return new Date(ts * 1000).toLocaleTimeString('zh-CN');
}

function shortText(text, limit = 30) {
    const normalized = normalizeText(text).replace(/\s+/g, ' ').trim();
    if (normalized.length <= limit) return normalized;
    return `${normalized.slice(0, limit)}...`;
}

function decisionLabel(decision) {
    const map = {
        major_revision: '大修',
        minor_revision: '小修',
        accept: '接收'
    };
    return map[decision] || '未知';
}

// ----------------------------
// 导航
// ----------------------------
function initNavigation() {
    document.querySelectorAll('.nav-item').forEach(item => {
        item.addEventListener('click', () => {
            switchPage(item.dataset.page);
        });
    });
}

function switchPage(pageName) {
    document.querySelectorAll('.nav-item').forEach(item => {
        item.classList.toggle('active', item.dataset.page === pageName);
    });

    document.querySelectorAll('.page').forEach(page => {
        page.classList.toggle('active', page.id === `${pageName}-page`);
    });

    if (pageName === 'config') {
        renderConfigPage();
    }
    if (pageName === 'history') {
        renderHistoryPage();
    }
}

// ----------------------------
// Socket 通信
// ----------------------------
function initSocket() {
    socket = io(API_BASE, { transports: ['websocket', 'polling'] });

    socket.on('connect', () => {
        updateConnectionStatus(true);
        showToast('已连接到服务器', 'success');
    });

    socket.on('disconnect', () => {
        updateConnectionStatus(false);
        showToast('与服务器断开连接', 'error');
    });

    socket.on('workflow_start', data => {
        workflowRunning = true;
        setWorkflowButtonState(true);
        const loopText = data.max_iterations === 'unlimited'
            ? '无限迭代，直到审稿接收'
            : `最多${data.max_iterations || '-'}轮`;
        updateStatus('working', `工作中（${loopText}）`);
        addSystemMessage(`工作流启动：${data.topic}`);
        setEditorStage('阶段：等待角色产出');
    });

    socket.on('iteration_start', data => {
        addSystemMessage(`第 ${data.iteration} 轮开始${data.reason ? '（依据审稿反馈重试）' : ''}`);
    });

    socket.on('step_start', data => {
        if (data?.role) {
            addSystemMessage(`${data.role} 开始执行 ${data.step || '当前步骤'}`);
        }
    });

    socket.on('ai_message', data => {
        addConversationMessage(data);
        saveToHistory({ ...data, event: 'ai_message' });
    });

    socket.on('manuscript_update', data => {
        const content = normalizeText(data.content);
        setEditorContent(content);
        setEditorStage(`阶段：第${data.iteration || '-'}轮 · ${data.stage || '未命名阶段'}（${data.role || '未知角色'}）`);
        addSystemMessage(`稿件更新：${data.stage || '新阶段'} by ${data.role || '未知角色'}`);
    });

    socket.on('output_warning', data => {
        const role = data?.role || '系统';
        const warningMessage = normalizeText(data?.message || '检测到潜在输出风险');
        const suggestion = normalizeText(data?.suggestion || '');
        const meta = data?.meta ? normalizeText(data.meta) : '';

        const lines = [`[输出风险][${role}] ${warningMessage}`];
        if (suggestion) lines.push(`建议：${suggestion}`);
        if (meta) lines.push(`元信息：${meta}`);

        const merged = lines.join('\n');
        addSystemMessage(merged);
        saveToHistory({
            from: '系统',
            to: role,
            type: 'output_warning',
            content: merged
        });

        showToast(`${role}：${shortText(warningMessage)}`, 'warning');
    });

    socket.on('workflow_complete', data => {
        workflowRunning = false;
        setWorkflowButtonState(false);

        const result = normalizeText(data.result || data.final_content);
        if (!result.trim()) {
            updateStatus('error', '完成但无结果');
            showToast('工作流已结束，但未收到有效结果', 'error');
            return;
        }

        latestResultText = result;
        setEditorContent(result);

        const label = data.decision_label || decisionLabel(data.decision);
        setEditorStage(`阶段：已完成（审稿决定：${label}）`);
        updateStatus('success', `完成 · ${label}`);

        addSystemMessage(`工作流完成，共 ${data.iterations || '-'} 轮，审稿决定：${label}`);
        showToast('工作流完成！', 'success');
    });

    socket.on('workflow_error', data => {
        workflowRunning = false;
        setWorkflowButtonState(false);
        updateStatus('error', '错误');
        addSystemMessage(`工作流错误：${data.error || '未知错误'}`);
        showToast(`错误：${data.error || '未知错误'}`, 'error');
    });

    socket.on('workflow_cancelled', data => {
        workflowRunning = false;
        setWorkflowButtonState(false);
        updateStatus('error', '已中止');
        addSystemMessage(`工作流已中止：${normalizeText(data?.message || '任务已被手动中止')}`);
        setEditorStage('阶段：任务已中止');
        showToast('任务已中止', 'warning');
    });

    socket.on('role_status', data => {
        updateRoleStatus(data.role, data.status, data.message);
    });
}

function updateConnectionStatus(connected) {
    const dot = document.getElementById('connection-status');
    const text = document.getElementById('connection-text');

    if (connected) {
        dot.classList.add('connected');
        text.textContent = '已连接';
    } else {
        dot.classList.remove('connected');
        text.textContent = '未连接';
    }
}

// ----------------------------
// 配置管理
// ----------------------------
function loadConfig() {
    const raw = localStorage.getItem(STORAGE_CONFIG_KEY);
    const parsed = raw ? safeParseJSON(raw, null) : null;

    const base = deepClone(DEFAULT_CONFIG);
    if (!parsed || typeof parsed !== 'object') {
        currentConfig = base;
        return;
    }

    // 兼容旧版本字段并合并
    REQUIRED_ROLES.forEach(role => {
        const oldRole = parsed[role] || {};
        const merged = base[role];

        merged.description = oldRole.description || merged.description;
        merged.system_prompt = oldRole.system_prompt || merged.system_prompt;

        merged.api_config = {
            ...merged.api_config,
            ...(oldRole.api_config || {})
        };

        const oldTemp = oldRole.api_config?.temperature;
        const oldMaxTokens = oldRole.api_config?.max_tokens;

        merged.api_params = {
            ...merged.api_params,
            ...(oldRole.api_params || {})
        };

        // 兼容 v0.4：temperature / max_tokens 存在 api_config 中
        if (typeof oldTemp === 'number' && typeof merged.api_params.temperature !== 'number') {
            merged.api_params.temperature = oldTemp;
        }
        if (typeof oldMaxTokens === 'number' && typeof merged.api_params.max_tokens !== 'number') {
            merged.api_params.max_tokens = oldMaxTokens;
        }

        base[role] = merged;
    });

    currentConfig = base;
}

function saveConfig() {
    localStorage.setItem(STORAGE_CONFIG_KEY, JSON.stringify(currentConfig));
    showToast('配置已保存', 'success');
}

function resetConfig() {
    if (!confirm('确定要重置为默认配置吗？')) return;
    currentConfig = deepClone(DEFAULT_CONFIG);
    saveConfig();
    renderConfigPage();
    showToast('已重置为默认配置', 'success');
}

function renderConfigPage() {
    const container = document.getElementById('roles-config');
    if (!container) return;

    container.innerHTML = '';

    Object.entries(currentConfig).forEach(([role, config]) => {
        const card = document.createElement('div');
        card.className = 'role-card';
        card.innerHTML = `
            <h4>${role}</h4>
            <div class="form-group">
                <label>角色描述</label>
                <input type="text" data-role="${role}" data-section="root" data-field="description" value="${escapeAttr(config.description || '')}">
            </div>
            <div class="form-group">
                <label>System Prompt</label>
                <textarea rows="4" data-role="${role}" data-section="root" data-field="system_prompt">${escapeHtml(config.system_prompt || '')}</textarea>
            </div>
            <div class="form-row">
                <div class="form-group">
                    <label>API类型</label>
                    <select data-role="${role}" data-section="api_config" data-field="api_type">
                        <option value="openai" ${config.api_config.api_type === 'openai' ? 'selected' : ''}>openai</option>
                        <option value="claude" ${config.api_config.api_type === 'claude' ? 'selected' : ''}>claude</option>
                        <option value="custom" ${config.api_config.api_type === 'custom' ? 'selected' : ''}>custom</option>
                    </select>
                </div>
                <div class="form-group">
                    <label>模型</label>
                    <input type="text" data-role="${role}" data-section="api_config" data-field="model" value="${escapeAttr(config.api_config.model || '')}" placeholder="gpt-4o-mini">
                </div>
            </div>
            <div class="form-group">
                <label>API Key</label>
                <input type="password" data-role="${role}" data-section="api_config" data-field="api_key" value="${escapeAttr(config.api_config.api_key || '')}" placeholder="sk-...">
            </div>
            <div class="form-group">
                <label>Base URL</label>
                <input type="text" data-role="${role}" data-section="api_config" data-field="base_url" value="${escapeAttr(config.api_config.base_url || '')}">
            </div>
            <div class="form-row">
                <div class="form-group">
                    <label>Temperature</label>
                    <input type="number" step="0.1" min="0" max="2" data-role="${role}" data-section="api_params" data-field="temperature" value="${Number(config.api_params.temperature ?? 0.7)}">
                </div>
                <div class="form-group">
                    <label>Max Tokens</label>
                    <input type="number" step="100" min="200" max="8000" data-role="${role}" data-section="api_params" data-field="max_tokens" value="${Number(config.api_params.max_tokens ?? 2000)}">
                </div>
            </div>
        `;

        container.appendChild(card);
    });

    container.querySelectorAll('input, textarea, select').forEach(input => {
        input.addEventListener('change', handleConfigFieldChange);
    });
}

function handleConfigFieldChange(event) {
    const { role, section, field } = event.target.dataset;
    let value = event.target.value;

    if (!currentConfig?.[role]) return;

    if (event.target.type === 'number') {
        value = Number(value);
    }

    if (section === 'root') {
        currentConfig[role][field] = value;
    } else {
        currentConfig[role][section][field] = value;
    }
}

function escapeHtml(text) {
    return normalizeText(text)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;');
}

function escapeAttr(text) {
    return escapeHtml(text).replace(/"/g, '&quot;');
}

// ----------------------------
// 工作流
// ----------------------------
function initEventListeners() {
    document.getElementById('start-btn')?.addEventListener('click', startWorkflow);
    document.getElementById('stop-btn')?.addEventListener('click', stopWorkflow);
    document.getElementById('download-txt-btn')?.addEventListener('click', downloadAsTxt);
    document.getElementById('download-doc-btn')?.addEventListener('click', downloadAsDoc);
    document.getElementById('download-pdf-btn')?.addEventListener('click', downloadAsPdf);
    document.getElementById('save-config-btn')?.addEventListener('click', saveConfig);
    document.getElementById('reset-config-btn')?.addEventListener('click', resetConfig);
    document.getElementById('clear-history-btn')?.addEventListener('click', clearHistory);
    document.getElementById('corpus-files')?.addEventListener('change', uploadCorpusFiles);

    document.getElementById('sync-result-btn')?.addEventListener('click', syncEditorToResult);
}

function setWorkflowButtonState(isRunning) {
    const startBtn = document.getElementById('start-btn');
    const stopBtn = document.getElementById('stop-btn');
    if (startBtn) startBtn.disabled = !!isRunning;
    if (stopBtn) stopBtn.disabled = !isRunning;
}

function updateCorpusStatus(text, type = 'neutral') {
    const node = document.getElementById('corpus-upload-status');
    if (!node) return;
    node.textContent = text;
    node.className = `upload-status ${type}`;
}

async function uploadCorpusFiles(event) {
    const files = Array.from(event.target.files || []);
    if (!files.length) {
        uploadedCorpusText = '';
        updateCorpusStatus('尚未上传语料');
        return;
    }

    const formData = new FormData();
    files.forEach(file => formData.append('files', file));
    updateCorpusStatus('语料上传中...', 'working');

    try {
        const response = await fetch(`${API_BASE}/api/corpus/upload`, {
            method: 'POST',
            body: formData
        });

        const payload = await response.json();
        if (!response.ok || !payload.success) {
            throw new Error(payload.error || '上传失败');
        }

        uploadedCorpusText = normalizeText(payload.corpus_text);
        updateCorpusStatus(`已上传 ${payload.files.length} 个文件，语料 ${payload.corpus_chars} 字`, 'success');
        showToast('语料上传成功', 'success');
    } catch (error) {
        uploadedCorpusText = '';
        updateCorpusStatus(`上传失败：${error.message}`, 'error');
        showToast(`语料上传失败：${error.message}`, 'error');
    }
}

async function startWorkflow() {
    const topic = document.getElementById('topic').value.trim();
    const mode = document.getElementById('mode').value;

    if (!topic) {
        showToast('请输入主题', 'error');
        return;
    }

    const missingApiRoles = REQUIRED_ROLES.filter(role => !currentConfig?.[role]?.api_config?.api_key?.trim());
    if (missingApiRoles.length > 0) {
        showToast(`请先配置以下角色的API密钥：${missingApiRoles.join('、')}`, 'error');
        switchPage('config');
        return;
    }

    // 重置界面状态
    workflowRunning = true;
    setWorkflowButtonState(true);
    latestResultText = '';
    resetAllRoleStatus();
    clearConversation();
    setEditorContent('');
    setEditorStage('阶段：等待角色产出');
    updateStatus('working', '工作中');

    try {
        const response = await fetch(`${API_BASE}/api/start_workflow`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                topic,
                mode,
                corpus_text: uploadedCorpusText,
                config: currentConfig
            })
        });

        const payload = await response.json();
        if (!response.ok || !payload.success) {
            throw new Error(payload.error || '启动失败');
        }

        showToast('工作流已启动', 'success');
    } catch (error) {
        workflowRunning = false;
        setWorkflowButtonState(false);
        updateStatus('error', '错误');
        showToast(`启动失败：${error.message}`, 'error');
    }
}

async function stopWorkflow() {
    if (!workflowRunning) return;

    try {
        const response = await fetch(`${API_BASE}/api/stop_workflow`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' }
        });

        const payload = await response.json();
        if (!response.ok || !payload.success) {
            throw new Error(payload.error || '中止失败');
        }

        showToast('已发送中止指令', 'warning');
    } catch (error) {
        showToast(`中止失败：${error.message}`, 'error');
    }
}

function clearConversation() {
    const container = document.getElementById('conversation');
    container.innerHTML = '';
}

function addSystemMessage(messageText) {
    const container = document.getElementById('conversation');
    const item = document.createElement('div');
    item.className = 'message-item system-message';

    const content = document.createElement('div');
    content.className = 'message-content';
    content.textContent = `[系统] ${messageText}`;

    item.appendChild(content);
    container.appendChild(item);
    container.scrollTop = container.scrollHeight;
}

function addConversationMessage(data) {
    const container = document.getElementById('conversation');
    const item = document.createElement('div');
    item.className = 'message-item';

    const header = document.createElement('div');
    header.className = 'message-header';

    const from = document.createElement('span');
    from.className = 'message-from';
    from.textContent = `📤 ${data.from || '未知发送者'}`;

    const to = document.createElement('span');
    to.className = 'message-to';
    to.textContent = `📥 ${data.to || '未知接收者'} · ${formatTime(data.timestamp)}`;

    header.appendChild(from);
    header.appendChild(to);

    const content = document.createElement('pre');
    content.className = 'message-content';
    content.textContent = normalizeText(data.content);

    item.appendChild(header);
    item.appendChild(content);
    container.appendChild(item);
    container.scrollTop = container.scrollHeight;
}

function textToEditableHtml(text) {
    const safe = escapeHtml(normalizeText(text));
    return safe.replace(/\n/g, '<br>');
}

function getEditorElement() {
    return document.getElementById('editor-content');
}

function getEditorText() {
    const editor = getEditorElement();
    return editor ? normalizeText(editor.innerText || editor.textContent) : '';
}

function getEditorHtml() {
    const editor = getEditorElement();
    return editor ? normalizeText(editor.innerHTML) : '';
}

function setEditorContent(text) {
    const editor = getEditorElement();
    if (!editor) return;

    const normalized = normalizeText(text);
    if (!normalized.trim()) {
        editor.innerHTML = '<p><br></p>';
        return;
    }

    editor.innerHTML = textToEditableHtml(normalized);
}

function setEditorStage(text) {
    const stage = document.getElementById('editor-stage');
    if (stage) stage.textContent = text;
}

function syncEditorToResult() {
    const text = getEditorText();
    if (!text.trim()) {
        showToast('编辑器内容为空，无法同步', 'error');
        return;
    }

    latestResultText = text;
    showToast('已同步当前 Word 页面内容', 'success');
}

function getExportText() {
    const candidates = [
        latestResultText,
        getEditorText()
    ];

    return candidates.find(text => normalizeText(text).trim()) || '';
}

function downloadBlob(blob, filename) {
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    a.click();
    URL.revokeObjectURL(url);
}

function downloadAsTxt() {
    const text = getExportText();
    if (!text.trim()) {
        showToast('当前没有可导出的内容', 'error');
        return;
    }

    const blob = new Blob([text], { type: 'text/plain;charset=utf-8' });
    downloadBlob(blob, `report_${Date.now()}.txt`);
    showToast('TXT 已下载', 'success');
}

function downloadAsDoc() {
    const text = getExportText();
    if (!text.trim()) {
        showToast('当前没有可导出的内容', 'error');
        return;
    }

    const editor = getEditorElement();
    const bodyHtml = editor ? editor.innerHTML : textToEditableHtml(text);
    const fontFamily = document.getElementById('font-family-select')?.value || 'Microsoft YaHei';
    const fontSize = Number(document.getElementById('font-size-select')?.value || 16);

    const docHtml = `<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <style>
        @page {
            size: A4;
            margin: 20mm;
        }
        body {
            font-family: ${fontFamily};
            font-size: ${fontSize}px;
            line-height: 1.8;
            color: #222;
            margin: 0;
        }
    </style>
</head>
<body>${bodyHtml}</body>
</html>`;

    const blob = new Blob(['\ufeff', docHtml], { type: 'application/msword;charset=utf-8' });
    downloadBlob(blob, `report_${Date.now()}.doc`);
    showToast('DOC 已下载', 'success');
}

async function downloadAsPdf() {
    const text = getExportText();
    if (!text.trim()) {
        showToast('当前没有可导出的内容', 'error');
        return;
    }

    if (typeof html2pdf === 'undefined') {
        showToast('PDF 导出组件加载失败，请刷新页面后重试', 'error');
        return;
    }

    const editor = getEditorElement();
    const container = document.createElement('div');
    container.style.background = '#fff';
    container.style.padding = '0';
    container.style.width = '210mm';
    container.style.minHeight = '297mm';

    const printable = editor ? editor.cloneNode(true) : document.createElement('div');
    if (!editor) {
        printable.innerHTML = textToEditableHtml(text);
    }
    printable.style.minHeight = 'auto';
    printable.style.maxHeight = 'none';
    printable.style.boxShadow = 'none';
    printable.style.border = 'none';
    printable.style.margin = '0 auto';
    printable.style.padding = '20mm';
    printable.style.width = '210mm';
    printable.style.minHeight = '297mm';
    printable.style.boxSizing = 'border-box';
    container.appendChild(printable);

    try {
        await html2pdf().set({
            margin: [0, 0, 0, 0],
            filename: `report_${Date.now()}.pdf`,
            image: { type: 'jpeg', quality: 0.98 },
            html2canvas: { scale: 2, useCORS: true },
            jsPDF: { unit: 'mm', format: 'a4', orientation: 'portrait' }
        }).from(container).save();
        showToast('PDF 已下载', 'success');
    } catch (error) {
        showToast(`PDF 导出失败：${error.message || '未知错误'}`, 'error');
    }
}

function initWordEditorControls() {
    const editor = getEditorElement();
    if (!editor) return;

    document.querySelectorAll('.format-btn[data-command]').forEach(btn => {
        btn.addEventListener('click', () => {
            const command = btn.dataset.command;
            const value = btn.dataset.value || null;
            editor.focus();
            document.execCommand('styleWithCSS', false, true);
            document.execCommand(command, false, value);
        });
    });

    document.getElementById('font-family-select')?.addEventListener('change', event => {
        editor.style.fontFamily = event.target.value;
    });

    document.getElementById('font-size-select')?.addEventListener('change', event => {
        const size = Number(event.target.value || 16);
        editor.style.fontSize = `${size}px`;
    });
}

// ----------------------------
// 状态、历史与通知
// ----------------------------
function updateStatus(type, text) {
    const badge = document.getElementById('status-badge');
    badge.className = `badge ${type}`;
    badge.textContent = text;
}

function updateRoleStatus(role, status, message) {
    const roleItem = document.querySelector(`.role-status-item[data-role="${role}"]`);
    if (!roleItem) return;

    const indicator = roleItem.querySelector('.role-indicator');
    const stateText = roleItem.querySelector('.role-state');

    indicator.classList.remove('idle', 'working', 'completed', 'error');

    switch (status) {
        case 'working':
            indicator.classList.add('working');
            stateText.textContent = '工作中...';
            break;
        case 'completed':
            indicator.classList.add('completed');
            stateText.textContent = '已完成';
            break;
        case 'error':
            indicator.classList.add('error');
            stateText.textContent = '错误';
            break;
        default:
            indicator.classList.add('idle');
            stateText.textContent = '待命';
    }

    if (message) {
        stateText.textContent = message;
    }
}

function resetAllRoleStatus() {
    document.querySelectorAll('.role-status-item').forEach(item => {
        const indicator = item.querySelector('.role-indicator');
        const stateText = item.querySelector('.role-state');
        indicator.className = 'role-indicator idle';
        stateText.textContent = '待命';
    });
}

function saveToHistory(data) {
    const list = safeParseJSON(localStorage.getItem(STORAGE_HISTORY_KEY) || '[]', []);
    const row = {
        timestamp: new Date().toLocaleString('zh-CN'),
        from: data.from || '系统',
        to: data.to || '-',
        type: data.type || data.event || '-',
        content: normalizeText(data.content)
    };

    list.unshift(row);
    if (list.length > MAX_HISTORY_ITEMS) {
        list.length = MAX_HISTORY_ITEMS;
    }

    localStorage.setItem(STORAGE_HISTORY_KEY, JSON.stringify(list));
}

function renderHistoryPage() {
    const container = document.getElementById('history-list');
    if (!container) return;

    const history = safeParseJSON(localStorage.getItem(STORAGE_HISTORY_KEY) || '[]', []);
    container.innerHTML = '';

    history.forEach(item => {
        const wrapper = document.createElement('div');
        wrapper.className = 'history-item';

        const title = document.createElement('strong');
        title.textContent = `${item.from} → ${item.to}（${item.type}）`;

        const content = document.createElement('pre');
        content.className = 'history-content';
        content.textContent = normalizeText(item.content);

        const stamp = document.createElement('small');
        stamp.style.color = 'var(--text-secondary)';
        stamp.textContent = item.timestamp;

        wrapper.appendChild(title);
        wrapper.appendChild(content);
        wrapper.appendChild(stamp);
        container.appendChild(wrapper);
    });
}

function clearHistory() {
    if (!confirm('确定要清空所有历史记录吗？')) return;
    localStorage.removeItem(STORAGE_HISTORY_KEY);
    renderHistoryPage();
    showToast('历史记录已清空', 'success');
}

function showToast(message, type = 'info') {
    const toast = document.getElementById('toast');
    toast.textContent = message;
    toast.className = `toast ${type} show`;
    setTimeout(() => toast.classList.remove('show'), 3000);
}

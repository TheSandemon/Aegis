/* Aegis Board Module — Card CRUD, rendering, drag & drop, modals */
let cards = [];
let columns = [];
let config = {};
let currentCardId = null;
let terminalRefreshInterval = null;
let searchFilter = '';
const collapsedColumns = {};

async function init() {
    await loadConfig();
    await loadColumns();
    populateColumnSelects();
    await loadAgents();
    await loadCards();
    connectWebSocket();
    renderBoard();
    document.getElementById('loadingSpinner').style.display = 'none';
    setupViewRouting();
}

async function loadConfig() {
    try { const res = await fetch('/api/config'); if (!res.ok) throw 0; config = await res.json(); }
    catch (e) { console.error('Error loading config:', e); showToast('Failed to load configuration'); }
}

async function loadColumns() {
    try { const res = await fetch('/api/columns'); if (!res.ok) throw 0; columns = await res.json(); }
    catch (e) { console.error('Error loading columns:', e); showToast('Failed to load columns'); }
}

async function loadCards() {
    try { const res = await fetch('/api/cards'); if (!res.ok) throw 0; cards = await res.json(); if (typeof updateGlowEffects === 'function') updateGlowEffects(); }
    catch (e) { console.error('Error loading cards:', e); showToast('Failed to load cards'); }
}

function populateColumnSelects() {
    const colNames = columns.map(c => c.name);
    ['cardColumn', 'detailColumn'].forEach(id => {
        const sel = document.getElementById(id);
        if (sel) sel.innerHTML = colNames.map(c => `<option value="${c}">${c}</option>`).join('');
    });
    const assigneeSel = document.getElementById('detailAssignee');
    const activeInstances = typeof instancesData !== 'undefined' ? instancesData.map(i => i.instance_name) : [];
    assigneeSel.innerHTML = '<option value="">Unassigned</option>' + activeInstances.map(a => `<option value="${escapeHtml(a)}">${escapeHtml(a)}</option>`).join('');
}

function filterCards() {
    searchFilter = document.getElementById('searchInput').value;
    document.getElementById('searchClear').classList.toggle('visible', searchFilter.length > 0);
    renderBoard();
}
function clearSearch() { document.getElementById('searchInput').value = ''; filterCards(); }

function getColumnColor(colObj) {
    if (typeof colObj === 'string') {
        // Fallback for string names
        const colors = {
            'Inbox': '#3b82f6', 'Planned': '#8b5cf6', 'In Progress': '#f59e0b',
            'Blocked': '#ef4444', 'Review': '#06b6d4', 'Done': '#22c55e'
        };
        return colors[colObj] || '#6366f1';
    }
    if (colObj.color) return colObj.color;
    const colors = {
        'Inbox': '#3b82f6', 'Planned': '#8b5cf6', 'In Progress': '#f59e0b',
        'Blocked': '#ef4444', 'Review': '#06b6d4', 'Done': '#22c55e'
    };
    return colors[colObj.name] || '#6366f1';
}

function renderBoard() {
    const board = document.getElementById('board');
    board.innerHTML = '';
    const doneIds = new Set(cards.filter(c => c.column === 'Done' || c.column === columns[columns.length - 1]?.name).map(c => c.id));

    columns.forEach(colObj => {
        const column = colObj.name;
        let columnCards = cards.filter(c => c.column === column);
        if (searchFilter) {
            const f = searchFilter.toLowerCase();
            columnCards = columnCards.filter(c => c.title.toLowerCase().includes(f) || (c.description && c.description.toLowerCase().includes(f)));
        }
        const colDiv = document.createElement('div');
        const isCollapsed = collapsedColumns[column];
        colDiv.className = 'column' + (isCollapsed ? ' collapsed' : '');
        colDiv.dataset.column = column;
        const colColor = getColumnColor(colObj);
        const isIntegrated = colObj.integration_type;
        colDiv.innerHTML = `
            <div class="col-color-stripe" style="background:${colColor}" onclick="toggleColumn('${column.replace(/'/g, "\\'")}')"></div>
            <div class="col-vertical-name" style="color:${colColor}" onclick="toggleColumn('${column.replace(/'/g, "\\'")}')">${column}</div>
            <div class="col-collapsed-count">${columnCards.length}</div>
            <div class="column-header">
                <h2 class="col-name-text" onclick="toggleColumn('${column}')" style="cursor:pointer; flex:1;">
                    ${column} <span class="count">${columnCards.length}</span>
                    ${isIntegrated ? '<span style="font-size:0.65rem; opacity:0.6;"> 🔗</span>' : ''}
                </h2>
                <button class="col-settings-btn" onclick="event.stopPropagation(); openColumnSettings(${colObj.id}, '${column.replace(/'/g, "\\'")}')"
                    style="padding:0.1rem 0.3rem; font-size:0.7rem; border:none; background:transparent; cursor:pointer;" title="Column Settings">⚙</button>
                <button class="col-delete-btn secondary" onclick="event.stopPropagation(); deleteColumn(${colObj.id}, '${column.replace(/'/g, "\\'")}')" 
                    style="padding:0.1rem 0.3rem; font-size:0.7rem; border:none; background:transparent; opacity:0.4;" title="Delete Column">🗑</button>
                <span class="collapse-icon" onclick="toggleColumn('${column}')" style="cursor:pointer;">▼</span>
            </div>
            <div class="column-body" data-column="${column}">
                ${columnCards.length ? columnCards.map(card => renderCard(card, doneIds)).join('') :
                `<div class="empty-state"><div class="empty-state-icon">${searchFilter ? '🔍' : '📭'}</div><div class="empty-state-text">${searchFilter ? 'No matching cards' : 'No cards'}</div></div>`}
            </div>`;
        const colBody = colDiv.querySelector('.column-body');
        colBody.addEventListener('dragover', handleDragOver);
        colBody.addEventListener('drop', handleDrop);
        colBody.addEventListener('dragleave', handleDragLeave);
        board.appendChild(colDiv);
    });

    document.querySelectorAll('.card').forEach(card => {
        card.addEventListener('dragstart', handleDragStart);
        card.addEventListener('dragend', handleDragEnd);
        card.addEventListener('click', () => openCardDetail(parseInt(card.dataset.id)));
    });
}

function toggleColumn(column) { collapsedColumns[column] = !collapsedColumns[column]; renderBoard(); }

function renderCard(card, doneIds) {
    const age = formatRelativeTime(card.updated_at);
    let statusClass = '';
    if (card.status === 'running') statusClass = 'status-running';
    else if (card.status === 'completed') statusClass = 'status-completed';
    else if (card.column === 'Blocked') statusClass = 'status-blocked';

    const priority = card.priority || 'normal';
    const deps = card.depends_on || [];
    const depHtml = deps.length ? `<div class="card-deps">${deps.map(d => {
        const resolved = doneIds && doneIds.has(d);
        return `<span class="dep-badge ${resolved ? 'resolved' : ''}" title="Depends on #${d}">#${d} ${resolved ? '✓' : '⏳'}</span>`;
    }).join('')}</div>` : '';

    const activityHtml = card.activity && card.activity !== 'idle' ?
        `<div class="card-activity"><span class="activity-dot"></span>${escapeHtml(card.activity)}</div>` : '';

    return `
        <div class="card ${card.status === 'running' ? 'agent-active' : ''}" draggable="true" data-id="${card.id}">
            <div class="card-title">${escapeHtml(card.title)}</div>
            ${depHtml}
            ${activityHtml}
            <div class="card-meta">
                <div class="card-meta-left">
                    ${card.assignee ? `<span class="card-assignee">${card.assignee}</span>` : ''}
                    ${card.status ? `<span class="card-status ${statusClass}">${card.status}</span>` : ''}
                    ${priority !== 'normal' ? `<span class="card-priority priority-${priority}">${priority}</span>` : ''}
                </div>
                <span class="card-age">${age}</span>
            </div>
        </div>`;
}

// Drag & Drop
let draggedCardId = null;
function handleDragStart(e) { draggedCardId = parseInt(e.target.dataset.id); e.target.classList.add('dragging'); }
function handleDragEnd(e) { e.target.classList.remove('dragging'); document.querySelectorAll('.column-body').forEach(cb => cb.classList.remove('drag-over')); }
function handleDragOver(e) { e.preventDefault(); e.currentTarget.classList.add('drag-over'); }
function handleDragLeave(e) { e.currentTarget.classList.remove('drag-over'); }
async function handleDrop(e) {
    e.preventDefault();
    const column = e.currentTarget.dataset.column;
    const card = cards.find(c => c.id === draggedCardId);
    if (card && card.column !== column) {
        await fetch(`/api/cards/${card.id}`, { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ column }) });
        await loadCards();
        renderBoard();
    }
    draggedCardId = null;
}

// Modals
function openNewCardModal() { document.getElementById('newCardModal').classList.add('active'); document.getElementById('cardTitle').focus(); }

function openNewColumnModal() { document.getElementById('newColumnModal').classList.add('active'); document.getElementById('columnName').focus(); }

// ── Integration field definitions ────────────────────────────────────────────
const INTEGRATION_CRED_FIELDS = {
    github: [
        { id: 'gh_token', label: 'GitHub Token (ghp_...)', type: 'password', key: 'token' },
        { id: 'gh_repo', label: 'Repository (owner/repo)', type: 'text', key: 'repo' },
        { id: 'gh_labels', label: 'Label filter (comma-separated, optional)', type: 'text', key: 'labels', isFilter: true },
        { id: 'gh_state', label: 'Issue state', type: 'select', key: 'state', isFilter: true, options: ['open', 'closed', 'all'] },
    ],
    jira: [
        { id: 'jira_email', label: 'Jira Email', type: 'text', key: 'email' },
        { id: 'jira_token', label: 'Jira API Token', type: 'password', key: 'token' },
        { id: 'jira_base_url', label: 'Base URL (https://company.atlassian.net)', type: 'text', key: 'base_url' },
        { id: 'jira_project', label: 'Project Key (e.g. PROJ)', type: 'text', key: 'project_key', isFilter: true },
    ],
    linear: [
        { id: 'lin_api_key', label: 'Linear API Key (lin_api_...)', type: 'password', key: 'api_key' },
        { id: 'lin_team_id', label: 'Team ID', type: 'text', key: 'team_id', isFilter: true },
    ],
    firestore: [
        { id: 'fs_api_key', label: 'Firebase Web API Key', type: 'password', key: 'api_key' },
        { id: 'fs_project_id', label: 'Firebase Project ID', type: 'text', key: 'project_id' },
        { id: 'fs_collection', label: 'Collection name (e.g. tasks)', type: 'text', key: 'collection' },
    ],
};

function toggleIntegrationSection() {
    const enabled = document.getElementById('enableIntegration').checked;
    document.getElementById('integrationSection').style.display = enabled ? 'block' : 'none';
}

function onIntegrationTypeChange() {
    const type = document.getElementById('integrationType').value;
    const container = document.getElementById('integrationCredFields');
    container.innerHTML = '';
    if (!type || !INTEGRATION_CRED_FIELDS[type]) return;
    INTEGRATION_CRED_FIELDS[type].forEach(field => {
        const div = document.createElement('div');
        div.className = 'form-group';
        let inputHtml;
        if (field.type === 'select') {
            inputHtml = `<select id="${field.id}">${field.options.map(o => `<option value="${o}">${o}</option>`).join('')}</select>`;
        } else {
            inputHtml = `<input type="${field.type}" id="${field.id}" placeholder="${field.label}">`;
        }
        div.innerHTML = `<label>${field.label}</label>${inputHtml}`;
        container.appendChild(div);
    });
}

function _collectIntegrationPayload() {
    const type = document.getElementById('integrationType').value;
    if (!type) return null;
    const fieldDefs = INTEGRATION_CRED_FIELDS[type] || [];
    const credentials = {};
    const filters = {};
    fieldDefs.forEach(f => {
        const el = document.getElementById(f.id);
        if (!el) return;
        const val = el.value.trim();
        if (f.isFilter) {
            filters[f.key] = val;
        } else {
            credentials[f.key] = val;
        }
    });
    return {
        type,
        mode: document.getElementById('integrationMode').value,
        credentials,
        filters,
        sync_interval_ms: parseInt(document.getElementById('integrationSyncInterval').value) || 60000,
        webhook_secret: document.getElementById('integrationWebhookSecret').value || null,
    };
}

function _resetColumnModal() {
    document.getElementById('columnName').value = '';
    document.getElementById('enableIntegration').checked = false;
    document.getElementById('integrationSection').style.display = 'none';
    document.getElementById('integrationType').value = '';
    document.getElementById('integrationCredFields').innerHTML = '';
    document.getElementById('integrationMode').value = 'read';
    document.getElementById('integrationSyncInterval').value = '60000';
    document.getElementById('integrationWebhookSecret').value = '';
}

async function createColumn() {
    const name = document.getElementById('columnName').value.trim();
    if (!name) { showToast('Name is required'); return; }
    const position = columns.length;

    const body = { name, position };

    const integrationEnabled = document.getElementById('enableIntegration')?.checked;
    if (integrationEnabled) {
        const integration = _collectIntegrationPayload();
        if (!integration) { showToast('Please select an integration service'); return; }
        body.integration = integration;
    }

    const res = await fetch('/api/columns', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
    });
    if (res.ok) {
        closeModal('newColumnModal');
        _resetColumnModal();
        await loadColumns();
        populateColumnSelects();
        renderBoard();
        showToast(integrationEnabled ? 'Column added with integration' : 'Column added');
    } else {
        const err = await res.json();
        showToast(`⚠️ ${err.detail || 'Failed to add column'}`);
    }
}

async function deleteColumn(id, name) {
    const colObj = columns.find(c => c.id === id);
    const isIntegrated = colObj && colObj.integration_type;

    let msg = `Delete column '${name}'?`;
    if (isIntegrated) {
        msg = `Delete integrated column '${name}'?\n\nCards synced from ${colObj.integration_type} will remain in the external service. Use Column Settings to remove just the integration.`;
    }
    if (!confirm(msg)) return;

    const param = isIntegrated ? '?force=true' : '?cascade=move';
    const res = await fetch(`/api/columns/${id}${param}`, { method: 'DELETE' });
    if (res.ok) {
        await loadColumns();
        populateColumnSelects();
        renderBoard();
        showToast('Column deleted');
    } else {
        const err = await res.json().catch(() => null);
        showToast(err?.detail || 'Failed to delete column');
    }
}

async function createCard() {
    const title = document.getElementById('cardTitle').value.trim();
    const description = document.getElementById('cardDescription').value;
    const column = document.getElementById('cardColumn').value;
    const priority = document.getElementById('cardPriority')?.value || 'normal';
    if (!title) { showToast('Title is required'); return; }
    await fetch('/api/cards', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ title, description, column, priority }) });
    closeModal('newCardModal');
    document.getElementById('cardTitle').value = '';
    document.getElementById('cardDescription').value = '';
    await loadCards();
    renderBoard();
}

let currentInstanceId = null;

async function openCardDetail(cardId) {
    currentCardId = cardId;
    const card = cards.find(c => c.id === cardId);
    if (!card) return;
    document.getElementById('detailTitleInput').value = card.title;
    document.getElementById('detailDescription').value = card.description || '';
    document.getElementById('detailAssignee').value = card.assignee || '';
    document.getElementById('detailColumn').value = card.column;
    const dp = document.getElementById('detailPriority');
    if (dp) dp.value = card.priority || 'normal';

    const isRunning = card.status === 'running';
    const hasLogs = card.logs && card.logs.length > 0;
    const isReview = card.column === 'Review';
    const isDone = card.column === 'Done' || card.column === 'Review';

    // Terminal section always visible when running or has logs
    const termSec = document.getElementById('terminalSection');
    termSec.style.display = (isRunning || hasLogs) ? 'flex' : 'none';

    // Intervention controls
    document.getElementById('injectSection').style.display = isRunning ? 'block' : 'none';
    document.getElementById('interventionBar').style.display = isRunning ? 'flex' : 'none';
    document.getElementById('stopAgentBtn').style.display = isRunning ? 'inline-block' : 'none';
    document.getElementById('approveBtn').style.display = isReview ? 'inline-block' : 'none';
    document.getElementById('pauseBtn').style.display = isRunning ? 'inline-block' : 'none';
    document.getElementById('resumeBtn').style.display = 'none';

    // Find the instance ID for intervention
    currentInstanceId = card.assignee || null;

    // Load initial logs
    if (isRunning || hasLogs) loadTerminalLogs(cardId);

    // Artifacts for done/review cards
    if (isDone && currentInstanceId) {
        loadArtifacts(currentInstanceId);
    } else {
        document.getElementById('artifactsSection').style.display = 'none';
    }

    document.getElementById('cardDetailModal').classList.add('active');
}

async function loadTerminalLogs(cardId) {
    try {
        const res = await fetch(`/api/cards/${cardId}/logs`); const data = await res.json();
        const t = document.getElementById('terminalOutput');
        t.innerHTML = data.logs?.map(l => `<div>${escapeHtml(l)}</div>`).join('') || 'Waiting...';
        t.scrollTop = t.scrollHeight;
    } catch (e) { document.getElementById('terminalOutput').textContent = 'No logs available'; }
}

// Real-time WebSocket log appending (called from the WebSocket handler)
function appendLogEntry(cardId, entry) {
    if (currentCardId !== cardId) return;
    const t = document.getElementById('terminalOutput');
    if (!t) return;
    if (t.textContent === 'Waiting for output...' || t.textContent === 'Waiting...') t.innerHTML = '';
    const div = document.createElement('div');
    div.textContent = entry;
    // Color code injection entries
    if (entry.startsWith('[INJECT]')) div.style.color = '#f59e0b';
    if (entry.startsWith('[STDERR]')) div.style.color = '#ef4444';
    t.appendChild(div);
    t.scrollTop = t.scrollHeight;
}

// ─── Intervention Functions ─────────────────────────────────────────────────

async function pauseAgent() {
    if (!currentInstanceId) { showToast('No instance to pause'); return; }
    try {
        const res = await fetch(`/api/instances/${currentInstanceId}/pause`, { method: 'POST' });
        if (res.ok) {
            showToast('⏸ Agent paused');
            document.getElementById('pauseBtn').style.display = 'none';
            document.getElementById('resumeBtn').style.display = 'inline-block';
        } else { const err = await res.json(); showToast(`⚠️ ${err.detail || 'Pause failed'}`); }
    } catch (e) { showToast('Pause failed'); }
}

async function resumeAgent() {
    if (!currentInstanceId) { showToast('No instance to resume'); return; }
    try {
        const res = await fetch(`/api/instances/${currentInstanceId}/resume`, { method: 'POST' });
        if (res.ok) {
            showToast('▶ Agent resumed');
            document.getElementById('resumeBtn').style.display = 'none';
            document.getElementById('pauseBtn').style.display = 'inline-block';
        } else { const err = await res.json(); showToast(`⚠️ ${err.detail || 'Resume failed'}`); }
    } catch (e) { showToast('Resume failed'); }
}

async function injectContext() {
    if (!currentInstanceId) { showToast('No instance running'); return; }
    const input = document.getElementById('injectInput');
    const text = input.value.trim();
    if (!text) return;
    try {
        const res = await fetch(`/api/instances/${currentInstanceId}/inject`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ text })
        });
        if (res.ok) {
            input.value = '';
            showToast('💉 Context injected');
        } else { const err = await res.json(); showToast(`⚠️ ${err.detail || 'Inject failed'}`); }
    } catch (e) { showToast('Inject failed'); }
}

async function loadArtifacts(instanceId) {
    try {
        const res = await fetch(`/api/instances/${instanceId}/artifacts`);
        const data = await res.json();
        const section = document.getElementById('artifactsSection');
        const list = document.getElementById('artifactsList');
        if (data.files && data.files.length > 0) {
            section.style.display = 'block';
            list.innerHTML = data.files.map(f => {
                const sizeKb = (f.size / 1024).toFixed(1);
                return `<div style="padding:0.2rem 0;border-bottom:1px solid var(--border);">📄 ${escapeHtml(f.name)} <span style="color:var(--text-secondary);">(${sizeKb} KB)</span></div>`;
            }).join('');
        } else { section.style.display = 'none'; }
    } catch (e) { document.getElementById('artifactsSection').style.display = 'none'; }
}

async function saveCardDetails() {
    const updates = { title: document.getElementById('detailTitleInput').value, description: document.getElementById('detailDescription').value, assignee: document.getElementById('detailAssignee').value || null, column: document.getElementById('detailColumn').value };
    const dp = document.getElementById('detailPriority');
    if (dp) updates.priority = dp.value;
    await fetch(`/api/cards/${currentCardId}`, { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(updates) });
    closeModal('cardDetailModal');
    if (terminalRefreshInterval) clearInterval(terminalRefreshInterval);
    await loadCards();
    renderBoard();
}

async function deleteCurrentCard() {
    if (!confirm('Delete this card?')) return;
    await fetch(`/api/cards/${currentCardId}`, { method: 'DELETE' });
    closeModal('cardDetailModal');
    await loadCards();
    renderBoard();
}

async function stopCurrentAgent() {
    if (!confirm('Stop the running agent?')) return;
    const res = await fetch(`/api/cards/${currentCardId}/agent`, { method: 'DELETE' });
    if (res.ok) {
        showToast('⏹ Agent stopped');
        document.getElementById('stopAgentBtn').style.display = 'none';
        document.getElementById('pauseBtn').style.display = 'none';
        document.getElementById('resumeBtn').style.display = 'none';
        document.getElementById('injectSection').style.display = 'none';
        await loadCards();
        renderBoard();
    } else { showToast('Failed to stop agent'); }
}

async function approveCurrentCard() {
    const res = await fetch(`/api/cards/${currentCardId}/approve`, { method: 'POST' });
    if (res.ok) { showToast('✅ Card approved!'); document.getElementById('approveBtn').style.display = 'none'; closeModal('cardDetailModal'); await loadCards(); renderBoard(); }
    else { const err = await res.json(); showToast(`⚠️ ${err.detail || 'Approval failed'}`); }
}



// Utils
function closeModal(id) { document.getElementById(id).classList.remove('active'); if (id === 'cardDetailModal' && terminalRefreshInterval) { clearInterval(terminalRefreshInterval); terminalRefreshInterval = null; } }
function showToast(message) {
    const toast = document.createElement('div');
    toast.className = 'toast'; toast.textContent = message;
    document.getElementById('toastContainer').appendChild(toast);
    setTimeout(() => toast.remove(), (config.toast_duration_seconds || 3) * 1000);
}
function escapeHtml(text) { const div = document.createElement('div'); div.textContent = text; return div.innerHTML; }
function formatRelativeTime(iso) {
    if (!iso) return '';
    const diff = Math.floor((new Date() - new Date(iso)) / 1000);
    if (diff < 60) return 'now';
    if (diff < 3600) return Math.floor(diff / 60) + 'm';
    if (diff < 86400) return Math.floor(diff / 3600) + 'h';
    const d = Math.floor(diff / 86400);
    return d < 7 ? d + 'd' : Math.floor(d / 7) + 'w';
}

// View Routing
function setupViewRouting() {
    const hash = window.location.hash || '#board';
    switchView(hash.replace('#', ''));
    window.addEventListener('hashchange', () => switchView(window.location.hash.replace('#', '')));
}
function switchView(view) {
    document.querySelectorAll('.view-nav button').forEach(b => b.classList.toggle('active', b.dataset.view === view));
    document.getElementById('boardView').style.display = view === 'board' ? 'flex' : 'none';
    const tv = document.getElementById('telemetryView');
    if (tv) { tv.classList.toggle('active', view === 'telemetry'); if (view === 'telemetry') loadTelemetry(); }
    const iv = document.getElementById('integrationsView');
    if (iv) { iv.style.display = view === 'integrations' ? 'block' : 'none'; if (view === 'integrations') loadIntegrations(); }
}
function navigateTo(view) { window.location.hash = '#' + view; }


// ─── Broker Controls ─────────────────────────────────────────────────────────

async function toggleBrokerPause() {
    const endpoint = window._brokerPaused ? '/api/broker/resume' : '/api/broker/pause';
    try {
        const res = await fetch(endpoint, { method: 'POST' });
        if (res.ok) {
            window._brokerPaused = !window._brokerPaused;
            showToast(window._brokerPaused ? '⏸ Broker paused' : '▶ Broker resumed');
        }
    } catch (e) { showToast('Failed to toggle broker'); }
}

async function setBrokerRate() {
    const input = document.getElementById('brokerRateInput');
    const ppm = parseInt(input.value);
    if (!ppm || ppm < 1) { showToast('PPM must be ≥ 1'); return; }
    try {
        const res = await fetch('/api/broker/rate', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ prompts_per_minute: ppm })
        });
        if (res.ok) { showToast(`Rate set to ${ppm} PPM`); }
    } catch (e) { showToast('Failed to set rate'); }
}


// ─── Column Settings ─────────────────────────────────────────────────────────

function openColumnSettings(colId, colName) {
    const col = columns.find(c => c.id === colId);
    if (!col) return;
    document.getElementById('editColId').value = colId;
    document.getElementById('editColName').value = col.name;
    document.getElementById('editColPosition').value = col.position ?? '';
    document.getElementById('editColColor').value = getColumnColor(col);
    const intStatus = document.getElementById('editColIntegrationStatus');
    if (col.integration_type) {
        intStatus.innerHTML = `🔗 <strong>${col.integration_type}</strong> (${col.integration_mode || 'read'})`;
        document.getElementById('editColRemoveIntegration').style.display = 'block';
    } else {
        intStatus.innerHTML = '<span style="color:var(--text-secondary)">None</span>';
        document.getElementById('editColRemoveIntegration').style.display = 'none';
    }
    document.getElementById('editColumnModal').classList.add('active');
}

async function saveColumnSettings() {
    const colId = document.getElementById('editColId').value;
    const name = document.getElementById('editColName').value.trim();
    const position = document.getElementById('editColPosition').value;
    const color = document.getElementById('editColColor').value;
    const removeIntegration = document.getElementById('editColRemoveInt')?.checked || false;

    const body = {};
    if (name) body.name = name;
    if (position !== '') body.position = parseInt(position);
    if (color) body.color = color;
    if (removeIntegration) body.remove_integration = true;

    try {
        const res = await fetch(`/api/columns/${colId}`, {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body)
        });
        if (res.ok) {
            closeModal('editColumnModal');
            await loadColumns();
            populateColumnSelects();
            renderBoard();
            showToast('Column updated');
        } else {
            const err = await res.json().catch(() => null);
            showToast(err?.detail || 'Failed to update column');
        }
    } catch (e) { showToast('Failed to update column'); }
}

// Event Listeners
document.addEventListener('DOMContentLoaded', () => {
    document.querySelectorAll('.modal-overlay').forEach(o => o.addEventListener('mousedown', e => { if (e.target === o) o.classList.remove('active'); }));
    document.addEventListener('keydown', e => {
        if (e.key === 'Escape') document.querySelectorAll('.modal-overlay.active').forEach(m => m.classList.remove('active'));
        if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') return;
        if (e.key === 'n' || e.key === 'N') { e.preventDefault(); openNewCardModal(); }
        else if (e.key === '/') { e.preventDefault(); document.getElementById('searchInput').focus(); }
        else if (e.key === 'r' || e.key === 'R') { e.preventDefault(); loadCards(); showToast('Refreshing...'); }
    });
    init();
});

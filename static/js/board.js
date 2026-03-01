/* Aegis Board Module — Card CRUD, rendering, drag & drop, modals */
let cards = [];
let columns = [];
let config = {};
let currentCardId = null;
let terminalRefreshInterval = null;
let searchFilter = '';
const collapsedColumns = {};

/**
 * Highlight a card with the agent's color while the agent is actively working on it.
 * Called from websocket.js on agent_log / agent_pulse / agent_stopped events.
 */
function setCardAgentHighlight(cardId, color, active) {
    const el = document.querySelector(`.card[data-id="${cardId}"]`);
    if (!el) return;
    if (active && color) {
        el.style.setProperty('--agent-highlight', color);
        el.classList.add('agent-working');
    } else {
        el.classList.remove('agent-working');
    }
}

async function init() {
    await loadConfig();
    if (typeof loadServiceModels === 'function') await loadServiceModels();
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
                    ${isIntegrated ? `<span title="Integration: ${colObj.integration_type} (${colObj.integration_status || 'active'})" style="font-size:0.65rem; cursor:default;">
                        <span style="color:${colObj.integration_status === 'error' ? '#ef4444' : '#22c55e'}">●</span>🔗</span>` : ''}
                </h2>
                <button class="col-settings-btn" onclick="event.stopPropagation(); openColumnSettings(${colObj.id}, '${column.replace(/'/g, "\\'")}')"
                    style="padding:0.1rem 0.3rem; font-size:0.7rem; border:none; background:transparent; cursor:pointer;" title="Column Settings">⚙</button>
                <button class="col-delete-btn secondary" onclick="event.stopPropagation(); deleteColumn(${colObj.id}, '${column.replace(/'/g, "\\'")}')" 
                    style="padding:0.1rem 0.3rem; font-size:0.7rem; border:none; background:transparent; opacity:0.4;" title="Delete Column">🗑</button>
                <span class="collapse-icon" onclick="toggleColumn('${column}')" style="cursor:pointer;">▼</span>
            </div>
            <div class="column-body" data-column="${column}">
                ${renderColumnCards(columnCards, doneIds)}
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

/**
 * Render column cards with optional group section headers.
 * Cards with no card_group are rendered first, then each named group.
 */
function renderColumnCards(columnCards, doneIds) {
    if (!columnCards.length) {
        return `<div class="empty-state"><div class="empty-state-icon">${searchFilter ? '🔍' : '📭'}</div><div class="empty-state-text">${searchFilter ? 'No matching cards' : 'No cards'}</div></div>`;
    }
    const ungrouped = columnCards.filter(c => !c.card_group);
    const groupMap = {};
    columnCards.filter(c => c.card_group).forEach(c => {
        (groupMap[c.card_group] = groupMap[c.card_group] || []).push(c);
    });

    let html = ungrouped.map(c => renderCard(c, doneIds)).join('');
    Object.entries(groupMap).forEach(([groupName, groupCards]) => {
        html += `<div class="card-group-header" data-group="${escapeHtml(groupName)}">
            <span class="group-name">${escapeHtml(groupName)}</span>
            <span class="group-count">(${groupCards.length})</span>
            <button class="group-toggle" onclick="toggleCardGroup(this)" title="Collapse group">▾</button>
        </div>
        <div class="card-group-body">
            ${groupCards.map(c => renderCard(c, doneIds)).join('')}
        </div>`;
    });
    return html;
}

function toggleCardGroup(btn) {
    const body = btn.closest('.card-group-header').nextElementSibling;
    if (!body) return;
    const collapsed = body.classList.toggle('group-collapsed');
    btn.textContent = collapsed ? '▸' : '▾';
}

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

    const tags = card.card_tags || [];
    const tagsHtml = tags.length ? `<div class="card-tags">${tags.map(t => `<span class="card-tag">#${escapeHtml(t)}</span>`).join('')}</div>` : '';

    return `
        <div class="card ${card.status === 'running' ? 'agent-active' : ''}" draggable="true" data-id="${card.id}">
            <div class="card-title">${escapeHtml(card.title)}</div>
            ${depHtml}
            ${tagsHtml}
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
    const dgEl = document.getElementById('detailGroup');
    if (dgEl) dgEl.value = card.card_group || '';
    const dtEl = document.getElementById('detailTags');
    if (dtEl) dtEl.value = (card.card_tags || []).join(', ');

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
    const dgEl = document.getElementById('detailGroup');
    if (dgEl) updates.card_group = dgEl.value.trim() || null;
    const dtEl = document.getElementById('detailTags');
    if (dtEl) updates.card_tags = dtEl.value.split(',').map(t => t.trim()).filter(Boolean);
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
    const wv = document.getElementById('workspacesView');
    if (wv) { wv.style.display = view === 'workspaces' ? 'block' : 'none'; if (view === 'workspaces') loadWorkspaces(); }
}
function navigateTo(view) { window.location.hash = '#' + view; }


// ─── Workflowspaces ──────────────────────────────────────────────────────────

async function loadWorkspaces() {
    const el = document.getElementById('workspacesList');
    if (!el) return;
    el.innerHTML = '<div style="color:var(--text-secondary);font-size:0.85rem;">Loading...</div>';
    try {
        const res = await fetch('/api/workspaces');
        const workspaces = await res.json();
        if (!workspaces.length) {
            el.innerHTML = '<div class="empty-state"><div class="empty-state-icon">💾</div><div class="empty-state-text">No saved workflowspaces yet.<br>Save your current board and agents to get started.</div></div>';
            return;
        }
        el.innerHTML = workspaces.map(w => {
            const agentBadge = w.agents > 0
                ? `<span style="color:var(--accent);margin-left:0.3rem;">· ${w.agents} agent${w.agents !== 1 ? 's' : ''}</span>`
                : '';
            return `
        <div style="background:var(--bg-card);border:1px solid var(--border);border-radius:0.5rem;padding:1rem;margin-bottom:0.75rem;display:flex;justify-content:space-between;align-items:center;gap:1rem;flex-wrap:wrap;">
            <div>
                <div style="font-weight:600;">${escapeHtml(w.name)}</div>
                <div style="font-size:0.75rem;color:var(--text-secondary);margin-top:0.2rem;">
                    ${w.columns} columns · ${w.cards} cards${agentBadge}
                    ${w.exported_at ? ' · Saved ' + _formatWorkspaceTime(w.exported_at) : ''}
                </div>
            </div>
            <div style="display:flex;gap:0.5rem;flex-wrap:wrap;">
                <button onclick="loadWorkspace('${escapeHtml(w.name)}', false)"
                    style="font-size:0.78rem;padding:0.25rem 0.7rem;background:var(--accent);">⬇ Load</button>
                <button onclick="loadWorkspace('${escapeHtml(w.name)}', true)"
                    style="font-size:0.78rem;padding:0.25rem 0.7rem;background:var(--bg-dark);" title="Merge into current board">⊕ Merge</button>
                <a href="/api/workspaces/export?name=${encodeURIComponent(w.name)}" download="${escapeHtml(w.name)}.json"
                    style="font-size:0.78rem;padding:0.25rem 0.7rem;background:var(--bg-dark);border:1px solid var(--border);border-radius:4px;text-decoration:none;color:var(--text-primary);cursor:pointer;">⬆ Export</a>
                <button onclick="deleteWorkspace('${escapeHtml(w.name)}')"
                    style="font-size:0.78rem;padding:0.25rem 0.7rem;background:transparent;border:1px solid #ef4444;color:#ef4444;">🗑</button>
            </div>
        </div>`;
        }).join('');
    } catch (e) { el.innerHTML = '<div class="empty-state" style="color:#ef4444;">Failed to load workflowspaces</div>'; }
}

async function saveWorkspace() {
    const nameEl = document.getElementById('workspaceSaveName');
    const name = (nameEl?.value || '').trim();
    if (!name) { showToast('Enter a workflowspace name'); return; }
    try {
        const res = await fetch(`/api/workspaces/${encodeURIComponent(name)}/save`, { method: 'POST' });
        if (res.ok) {
            const data = await res.json();
            const agentNote = data.agents > 0 ? `, ${data.agents} agent${data.agents !== 1 ? 's' : ''}` : '';
            showToast(`Saved "${data.name}" — ${data.columns} columns, ${data.cards} cards${agentNote}`);
            if (nameEl) nameEl.value = '';
            loadWorkspaces();
        } else {
            const err = await res.json().catch(() => null);
            showToast(err?.detail || 'Save failed');
        }
    } catch (e) { showToast('Save failed'); }
}

async function loadWorkspace(name, merge = false) {
    const action = merge ? 'Merge' : 'Load';
    const warn = merge ? '' : ' This will replace your current board and restore saved agents.';
    if (!confirm(`${action} workflowspace "${name}"?${warn}`)) return;
    try {
        const res = await fetch(`/api/workspaces/${encodeURIComponent(name)}/load?merge=${merge}`, { method: 'POST' });
        if (res.ok) {
            const data = await res.json();
            const agentNote = data.agents > 0 ? `, ${data.agents} agent${data.agents !== 1 ? 's' : ''} restored` : '';
            showToast(`Workflowspace "${name}" loaded${agentNote}`);
            await loadColumns();
            await loadCards();
            populateColumnSelects();
            renderBoard();
            if (typeof loadInstances === 'function') await loadInstances();
            navigateTo('board');
        } else {
            const err = await res.json().catch(() => null);
            showToast(err?.detail || 'Load failed');
        }
    } catch (e) { showToast('Load failed'); }
}

async function deleteWorkspace(name) {
    if (!confirm(`Delete workflowspace "${name}"?`)) return;
    try {
        const res = await fetch(`/api/workspaces/${encodeURIComponent(name)}`, { method: 'DELETE' });
        if (res.ok) { showToast(`Deleted "${name}"`); loadWorkspaces(); }
        else showToast('Delete failed');
    } catch (e) { showToast('Delete failed'); }
}

async function exportCurrentBoard() {
    try {
        const res = await fetch('/api/workspaces/export');
        const data = await res.json();
        const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `aegis-board-${new Date().toISOString().slice(0, 10)}.json`;
        a.click();
        URL.revokeObjectURL(url);
    } catch (e) { showToast('Export failed'); }
}

function _formatWorkspaceTime(iso) {
    try {
        const diff = Date.now() - new Date(iso).getTime();
        const mins = Math.floor(diff / 60000);
        if (mins < 1) return 'just now';
        if (mins < 60) return `${mins}m ago`;
        const hrs = Math.floor(mins / 60);
        if (hrs < 24) return `${hrs}h ago`;
        return new Date(iso).toLocaleDateString();
    } catch { return ''; }
}

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

function onEditIntegrationTypeChange() {
    const type = document.getElementById('editIntegrationType').value;
    const container = document.getElementById('editIntegrationCredFields');
    container.innerHTML = '';
    if (!type || !INTEGRATION_CRED_FIELDS[type]) return;
    INTEGRATION_CRED_FIELDS[type].forEach(field => {
        const div = document.createElement('div');
        div.className = 'form-group';
        let inputHtml;
        if (field.type === 'select') {
            inputHtml = `<select id="edit_${field.id}">${field.options.map(o => `<option value="${o}">${o}</option>`).join('')}</select>`;
        } else {
            inputHtml = `<input type="${field.type}" id="edit_${field.id}" placeholder="${field.label}">`;
        }
        div.innerHTML = `<label>${field.label}</label>${inputHtml}`;
        container.appendChild(div);
    });
}

function toggleEditIntegrationSection() {
    const enabled = document.getElementById('editColEnableIntegration').checked;
    document.getElementById('editIntegrationSection').style.display = enabled ? 'block' : 'none';
}

function onEditRemoveIntChange() {
    if (document.getElementById('editColRemoveInt').checked) {
        document.getElementById('editColReplaceInt').checked = false;
        document.getElementById('editIntegrationSection').style.display = 'none';
    }
}

function onEditReplaceIntChange() {
    const replacing = document.getElementById('editColReplaceInt').checked;
    if (replacing) {
        document.getElementById('editColRemoveInt').checked = false;
        document.getElementById('editIntegrationSection').style.display = 'block';
    } else {
        document.getElementById('editIntegrationSection').style.display = 'none';
    }
}

function _collectEditIntegrationPayload() {
    const type = document.getElementById('editIntegrationType').value;
    if (!type) return null;
    const fieldDefs = INTEGRATION_CRED_FIELDS[type] || [];
    const credentials = {};
    const filters = {};
    fieldDefs.forEach(f => {
        const el = document.getElementById(`edit_${f.id}`);
        if (!el) return;
        const val = el.value.trim();
        if (f.isFilter) filters[f.key] = val;
        else credentials[f.key] = val;
    });
    return {
        type,
        mode: document.getElementById('editIntegrationMode').value,
        credentials,
        filters,
        sync_interval_ms: parseInt(document.getElementById('editIntegrationSyncInterval').value) || 60000,
        webhook_secret: document.getElementById('editIntegrationWebhookSecret').value || null,
    };
}

function openColumnSettings(colId) {
    const col = columns.find(c => c.id === colId);
    if (!col) return;

    document.getElementById('editColId').value = colId;
    document.getElementById('editColName').value = col.name;
    document.getElementById('editColPosition').value = col.position ?? '';
    document.getElementById('editColColor').value = col.color || getColumnColor(col);

    // Reset all integration UI
    document.getElementById('editColEnableIntegration').checked = false;
    document.getElementById('editColRemoveInt').checked = false;
    document.getElementById('editColReplaceInt').checked = false;
    document.getElementById('editIntegrationSection').style.display = 'none';
    document.getElementById('editIntegrationType').value = '';
    document.getElementById('editIntegrationCredFields').innerHTML = '';
    document.getElementById('editIntegrationMode').value = 'read';
    document.getElementById('editIntegrationSyncInterval').value = '60000';
    document.getElementById('editIntegrationWebhookSecret').value = '';

    const intStatus = document.getElementById('editColIntegrationStatus');
    if (col.integration_type) {
        const dotColor = col.integration_status === 'error' ? '#ef4444' : '#22c55e';
        intStatus.innerHTML = `<span style="color:${dotColor}">●</span> <strong>${col.integration_type}</strong> · ${col.integration_mode || 'read'}`;
        document.getElementById('editColAddIntegrationRow').style.display = 'none';
        document.getElementById('editColRemoveIntegration').style.display = 'block';
    } else {
        intStatus.innerHTML = '<span style="color:var(--text-secondary)">None</span>';
        document.getElementById('editColAddIntegrationRow').style.display = 'block';
        document.getElementById('editColRemoveIntegration').style.display = 'none';
    }

    document.getElementById('editColumnModal').classList.add('active');
}

async function saveColumnSettings() {
    const colId = document.getElementById('editColId').value;
    const name = document.getElementById('editColName').value.trim();
    const position = document.getElementById('editColPosition').value;
    const color = document.getElementById('editColColor').value;
    const removeInt = document.getElementById('editColRemoveInt')?.checked || false;
    const addInt = document.getElementById('editColEnableIntegration')?.checked || false;
    const replaceInt = document.getElementById('editColReplaceInt')?.checked || false;

    const body = {};
    if (name) body.name = name;
    if (position !== '') body.position = parseInt(position);
    if (color) body.color = color;

    if (removeInt) {
        body.remove_integration = true;
    } else if (addInt || replaceInt) {
        const integration = _collectEditIntegrationPayload();
        if (!integration || !integration.type) { showToast('Please select an integration service'); return; }
        body.integration = integration;
    }

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

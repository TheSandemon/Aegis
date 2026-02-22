/* Aegis Board Module — Card CRUD, rendering, drag & drop, modals, settings */
let cards = [];
let config = {};
let currentCardId = null;
let terminalRefreshInterval = null;
let searchFilter = '';
const collapsedColumns = {};

async function init() {
    await loadConfig();
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

async function loadCards() {
    try { const res = await fetch('/api/cards'); if (!res.ok) throw 0; cards = await res.json(); updateGlowEffects(); }
    catch (e) { console.error('Error loading cards:', e); showToast('Failed to load cards'); }
}

function populateColumnSelects() {
    const columns = config.columns || ['Inbox', 'Planned', 'In Progress', 'Blocked', 'Review', 'Done'];
    ['cardColumn', 'detailColumn'].forEach(id => {
        const sel = document.getElementById(id);
        sel.innerHTML = columns.map(c => `<option value="${c}">${c}</option>`).join('');
    });
    const assigneeSel = document.getElementById('detailAssignee');
    const agents = Object.keys(config.agents || {});
    assigneeSel.innerHTML = '<option value="">Unassigned</option>' + agents.map(a => `<option value="${a}">${a}</option>`).join('');
}

function filterCards() {
    searchFilter = document.getElementById('searchInput').value;
    document.getElementById('searchClear').classList.toggle('visible', searchFilter.length > 0);
    renderBoard();
}
function clearSearch() { document.getElementById('searchInput').value = ''; filterCards(); }

function renderBoard() {
    const board = document.getElementById('board');
    board.innerHTML = '';
    const columns = config.columns || ['Inbox', 'Planned', 'In Progress', 'Blocked', 'Review', 'Done'];
    const doneIds = new Set(cards.filter(c => c.column === 'Done').map(c => c.id));

    columns.forEach(column => {
        let columnCards = cards.filter(c => c.column === column);
        if (searchFilter) {
            const f = searchFilter.toLowerCase();
            columnCards = columnCards.filter(c => c.title.toLowerCase().includes(f) || (c.description && c.description.toLowerCase().includes(f)));
        }
        const colDiv = document.createElement('div');
        colDiv.className = 'column' + (collapsedColumns[column] ? ' collapsed' : '');
        colDiv.dataset.column = column;
        colDiv.innerHTML = `
            <div class="column-header" onclick="toggleColumn('${column}')">
                <h2>${column} <span class="count">${columnCards.length}</span></h2>
                <span class="collapse-icon">▼</span>
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

    return `
        <div class="card" draggable="true" data-id="${card.id}">
            <div class="card-title">${escapeHtml(card.title)}</div>
            ${depHtml}
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
    }
    draggedCardId = null;
}

// Modals
function openNewCardModal() { document.getElementById('newCardModal').classList.add('active'); document.getElementById('cardTitle').focus(); }

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
}

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
    document.getElementById('stopAgentBtn').style.display = card.status === 'running' ? 'block' : 'none';
    document.getElementById('approveBtn').style.display = card.column === 'Review' ? 'block' : 'none';
    if (card.status === 'running' || (card.logs && card.logs.length > 0)) {
        document.getElementById('terminalSection').style.display = 'block';
        loadTerminalLogs(cardId);
    } else { document.getElementById('terminalSection').style.display = 'none'; }
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

async function saveCardDetails() {
    const updates = { title: document.getElementById('detailTitleInput').value, description: document.getElementById('detailDescription').value, assignee: document.getElementById('detailAssignee').value || null, column: document.getElementById('detailColumn').value };
    const dp = document.getElementById('detailPriority');
    if (dp) updates.priority = dp.value;
    await fetch(`/api/cards/${currentCardId}`, { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(updates) });
    closeModal('cardDetailModal');
    if (terminalRefreshInterval) clearInterval(terminalRefreshInterval);
}

async function deleteCurrentCard() {
    if (!confirm('Delete this card?')) return;
    await fetch(`/api/cards/${currentCardId}`, { method: 'DELETE' });
    closeModal('cardDetailModal');
}
async function stopCurrentAgent() {
    if (!confirm('Stop the running agent?')) return;
    const res = await fetch(`/api/cards/${currentCardId}/agent`, { method: 'DELETE' });
    res.ok ? (showToast('Agent stop signal sent'), document.getElementById('stopAgentBtn').style.display = 'none') : showToast('Failed to stop agent');
}
async function approveCurrentCard() {
    const res = await fetch(`/api/cards/${currentCardId}/approve`, { method: 'POST' });
    if (res.ok) { showToast('✅ Card approved!'); document.getElementById('approveBtn').style.display = 'none'; closeModal('cardDetailModal'); }
    else { const err = await res.json(); showToast(`⚠️ ${err.detail || 'Approval failed'}`); }
}

// Settings
function openSettingsModal() {
    renderAgentConfigs();
    document.getElementById('configPollingRate').value = config.polling_rate_ms || 5000;
    document.getElementById('configMaxAgents').value = config.max_concurrent_agents || 4;
    document.getElementById('configToastDuration').value = config.toast_duration_seconds || 3;
    document.getElementById('settingsModal').classList.add('active');
}
function renderAgentConfigs() {
    const container = document.getElementById('agentConfigs');
    const agents = config.agents || {};
    if (!Object.keys(agents).length) { container.innerHTML = '<p style="color:var(--text-secondary);font-size:0.8rem;">No agents configured.</p>'; return; }
    container.innerHTML = Object.entries(agents).map(([name, agent]) => `
        <div class="agent-config"><div class="agent-config-info"><div><div class="agent-config-name">${name}</div><div class="agent-config-binary">${agent.binary || 'unknown'}</div></div></div>
        <label class="toggle"><input type="checkbox" ${agent.enabled ? 'checked' : ''} onchange="toggleAgent('${name}', this.checked)"><span class="toggle-slider"></span></label></div>`).join('');
}
async function toggleAgent(name, enabled) { config.agents[name].enabled = enabled; await saveSettings(); }
async function saveSettings() {
    config.polling_rate_ms = parseInt(document.getElementById('configPollingRate').value);
    config.max_concurrent_agents = parseInt(document.getElementById('configMaxAgents').value);
    config.toast_duration_seconds = parseInt(document.getElementById('configToastDuration').value);
    try {
        const res = await fetch('/api/config', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(config) });
        res.ok ? (showToast('Settings saved'), closeModal('settingsModal')) : showToast('Failed to save settings');
    } catch (e) { showToast('Error saving settings'); }
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
}
function navigateTo(view) { window.location.hash = '#' + view; }

// Event Listeners
document.addEventListener('DOMContentLoaded', () => {
    document.querySelectorAll('.modal-overlay').forEach(o => o.addEventListener('click', e => { if (e.target === o) o.classList.remove('active'); }));
    document.addEventListener('keydown', e => {
        if (e.key === 'Escape') document.querySelectorAll('.modal-overlay.active').forEach(m => m.classList.remove('active'));
        if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') return;
        if (e.key === 'n' || e.key === 'N') { e.preventDefault(); openNewCardModal(); }
        else if (e.key === '/') { e.preventDefault(); document.getElementById('searchInput').focus(); }
        else if (e.key === 'r' || e.key === 'R') { e.preventDefault(); loadCards(); showToast('Refreshing...'); }
    });
    init();
});

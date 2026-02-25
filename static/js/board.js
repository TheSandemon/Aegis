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
    try { const res = await fetch('/api/cards'); if (!res.ok) throw 0; cards = await res.json(); updateGlowEffects(); }
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
        colDiv.className = 'column' + (collapsedColumns[column] ? ' collapsed' : '');
        colDiv.dataset.column = column;
        colDiv.innerHTML = `
            <div class="column-header">
                <h2 onclick="toggleColumn('${column}')" style="cursor:pointer; flex:1;">${column} <span class="count">${columnCards.length}</span></h2>
                <button class="secondary" onclick="deleteColumn(${colObj.id}, '${column}')" style="padding:0.1rem 0.3rem; font-size:0.7rem; margin-right:0.25rem; border:none; background:transparent;" title="Delete Column">🗑</button>
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

function openNewColumnModal() { document.getElementById('newColumnModal').classList.add('active'); document.getElementById('columnName').focus(); }

async function createColumn() {
    const name = document.getElementById('columnName').value.trim();
    if (!name) { showToast('Name is required'); return; }
    const position = columns.length;
    const res = await fetch('/api/columns', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ name, position }) });
    if (res.ok) {
        closeModal('newColumnModal');
        document.getElementById('columnName').value = '';
        await loadColumns();
        populateColumnSelects();
        renderBoard();
        showToast('Column added');
    } else {
        const err = await res.json();
        showToast(`⚠️ ${err.detail || 'Failed to add column'}`);
    }
}

async function deleteColumn(id, name) {
    if (!confirm(`Delete column '${name}'?`)) return;
    const res = await fetch(`/api/columns/${id}`, { method: 'DELETE' });
    if (res.ok) {
        await loadColumns();
        populateColumnSelects();
        renderBoard();
        showToast('Column deleted');
    } else {
        showToast('Failed to delete column (make sure it has no cards)');
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
}

async function deleteCurrentCard() {
    if (!confirm('Delete this card?')) return;
    await fetch(`/api/cards/${currentCardId}`, { method: 'DELETE' });
    closeModal('cardDetailModal');
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
    } else { showToast('Failed to stop agent'); }
}

async function approveCurrentCard() {
    const res = await fetch(`/api/cards/${currentCardId}/approve`, { method: 'POST' });
    if (res.ok) { showToast('✅ Card approved!'); document.getElementById('approveBtn').style.display = 'none'; closeModal('cardDetailModal'); }
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
}
function navigateTo(view) { window.location.hash = '#' + view; }

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

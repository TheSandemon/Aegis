/* Aegis Agents Module */
let agentStatus = {};
let registryData = [];

async function loadAgents() {
    try {
        const res = await fetch('/api/agents/params');
        agentStatus = await res.json();
        renderAgentMenu();
    } catch (e) { console.error('Error loading agents:', e); }
}

function renderAgentMenu() {
    const list = document.getElementById('agentCardsList');
    if (!list) return;
    list.innerHTML = Object.entries(agentStatus).map(([id, data]) => {
        const isRunning = data.status === 'running';
        const rgb = hexToRgb(data.color);
        return `
            <div class="agent-sidebar-card ${isRunning ? 'active' : ''}" 
                 style="--agent-color: ${data.color}; --agent-color-rgb: ${rgb.r}, ${rgb.g}, ${rgb.b}">
                <div class="agent-sidebar-header">
                    <div class="agent-avatar" style="border-color: ${data.color}">${getAgentEmoji(id)}</div>
                    <div class="agent-info-main">
                        <div class="agent-name">${data.name}</div>
                        <div class="agent-status-tag ${isRunning ? 'running' : ''}">
                            <div class="dot"></div>
                            <span>${data.status.charAt(0).toUpperCase() + data.status.slice(1)}</span>
                        </div>
                    </div>
                </div>
                ${isRunning && data.current_card ? `<div class="agent-working-on"><b>Working on:</b> ${data.current_card.title || 'Card #' + data.current_card.id}</div>` : ''}
                <div class="agent-params">
                    <div class="param-row"><span>Profile</span><b>${data.params.profile || 'default'}</b></div>
                    <div class="param-row"><span>Isolation</span><b>${data.params.isolation || 'subprocess'}</b></div>
                    <div class="param-row"><span>Enabled</span>
                        <label class="toggle"><input type="checkbox" ${data.params.enabled ? 'checked' : ''} onchange="updateAgentParam('${id}', 'enabled', this.checked)"><span class="toggle-slider"></span></label>
                    </div>
                </div>
            </div>`;
    }).join('');
    updateGlowEffects();
}

function getAgentEmoji(id) {
    const emojis = { architect: '🏗️', coder: '💻', researcher: '🔍', security: '🛡️' };
    return emojis[id] || '🤖';
}
function hexToRgb(hex) {
    const result = /^#?([a-f\d]{2})([a-f\d]{2})([a-f\d]{2})$/i.exec(hex);
    return result ? { r: parseInt(result[1], 16), g: parseInt(result[2], 16), b: parseInt(result[3], 16) } : { r: 99, g: 102, b: 241 };
}

async function updateAgentParam(agentId, key, value) {
    try {
        const res = await fetch(`/api/agents/params/${agentId}`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ [key]: value }) });
        if (res.ok) { agentStatus[agentId].params[key] = value; showToast(`${agentId} parameter updated`); }
    } catch (e) { showToast('Failed to update agent parameter'); }
}

function updateGlowEffects() {
    document.querySelectorAll('.card').forEach(c => { c.classList.remove('agent-active'); c.style.removeProperty('--agent-color'); });
    Object.entries(agentStatus).forEach(([id, data]) => {
        if (data.status === 'running' && data.current_card) {
            const el = document.querySelector(`.card[data-id="${data.current_card.id}"]`);
            if (el) { el.classList.add('agent-active'); el.style.setProperty('--agent-color', data.color); }
        }
    });
}

// Marketplace
async function openMarketplaceModal() { document.getElementById('marketplaceModal').classList.add('active'); await loadRegistry(); }

function switchMarketTab(tabId, btn) {
    document.querySelectorAll('#marketplaceModal .tab-bar button').forEach(b => b.classList.remove('active'));
    document.querySelectorAll('#marketplaceModal .tab-content').forEach(t => t.classList.remove('active'));
    btn.classList.add('active');
    document.getElementById('tab-' + tabId).classList.add('active');
    if (tabId === 'runtimes') loadActiveRuntimes();
}

async function loadRegistry() {
    try { const res = await fetch('/api/registry'); registryData = await res.json(); renderRegistry(registryData); }
    catch (e) { document.getElementById('registryGrid').textContent = 'Failed to load registry'; }
}

function renderRegistry(agents) {
    document.getElementById('registryGrid').innerHTML = agents.map(a => `
        <div class="agent-card">
            <div class="agent-card-header">
                <span class="agent-icon">${a.icon || '🤖'}</span>
                <div class="agent-card-info"><h4>${escapeHtml(a.name)}</h4><small>v${a.version} · ${a.license}</small></div>
                ${a.installed ? '<span class="badge badge-installed">Installed</span>' : ''}
                ${a.runtime_status === 'running' ? '<span class="badge badge-running">Running</span>' : ''}
            </div>
            <div class="agent-card-desc">${escapeHtml(a.description)}</div>
            <div class="agent-card-actions">
                <a href="${a.support_url}" target="_blank" style="text-decoration:none;"><button class="secondary" style="font-size:0.75rem;">⭐ GitHub</button></a>
                ${!a.installed ? `<button onclick="installAgent('${a.id}')">📥 Install</button>` : ''}
                ${a.installed && a.runtime_status !== 'running' ? `<button onclick="startAgent('${a.id}')" style="background:#22c55e;">▶ Start</button>` : ''}
                ${a.runtime_status === 'running' ? `<button class="danger" onclick="stopAgent('${a.id}')">⏹ Stop</button>` : ''}
            </div>
        </div>`).join('');
}

async function installAgent(agentId) {
    showToast(`Installing ${agentId}...`);
    try {
        const res = await fetch(`/api/agents/install/${agentId}`, { method: 'POST' }); const d = await res.json();
        showToast(d.status === 'installed' || d.status === 'already_installed' ? `✅ ${agentId} installed!` : `⚠️ ${d.status}`);
        await loadRegistry();
    } catch (e) { showToast('Install failed'); }
}
async function startAgent(agentId) {
    showToast(`Starting ${agentId}...`);
    try {
        const res = await fetch(`/api/agents/start/${agentId}`, { method: 'POST' });
        res.ok ? showToast(`▶ ${agentId} started!`) : showToast(`⚠️ ${(await res.json()).detail || 'Start failed'}`);
        await loadRegistry();
    } catch (e) { showToast('Start failed'); }
}
async function stopAgent(agentId) {
    try {
        const res = await fetch(`/api/agents/stop/${agentId}`, { method: 'POST' });
        res.ok ? showToast(`⏹ ${agentId} stopped`) : showToast(`⚠️ ${(await res.json()).detail || 'Stop failed'}`);
        await loadRegistry();
    } catch (e) { showToast('Stop failed'); }
}

async function loadActiveRuntimes() {
    try {
        const res = await fetch('/api/agents/active'); const runtimes = await res.json();
        const container = document.getElementById('runtimesList');
        if (runtimes.length === 0) { container.innerHTML = '<div class="empty-state"><div class="empty-state-icon">💤</div><div class="empty-state-text">No active runtimes.</div></div>'; return; }
        container.innerHTML = runtimes.map(r => {
            const agent = registryData.find(a => a.id === r.agent_id) || {};
            return `<div class="runtime-row"><span class="agent-icon">${agent.icon || '🤖'}</span><div class="runtime-info"><h4>${agent.name || r.agent_id}</h4><small>PID: ${r.pid} · <span class="badge badge-${r.status}">${r.status}</span> · ${r.log_count} logs</small></div>${r.status === 'running' ? `<button class="danger" style="font-size:0.75rem;" onclick="stopAgent('${r.agent_id}')">⏹</button>` : ''}</div><div class="runtime-logs" id="logs-${r.agent_id}">Loading...</div>`;
        }).join('');
        for (const r of runtimes) loadRuntimeLogs(r.agent_id);
    } catch (e) { document.getElementById('runtimesList').textContent = 'Failed to load runtimes'; }
}
async function loadRuntimeLogs(agentId) {
    try {
        const res = await fetch(`/api/agents/${agentId}/logs?tail=50`); const d = await res.json();
        const el = document.getElementById(`logs-${agentId}`);
        if (el) { el.innerHTML = d.logs.length > 0 ? d.logs.map(l => `<div>${escapeHtml(l)}</div>`).join('') : 'No output yet...'; el.scrollTop = el.scrollHeight; }
    } catch (e) { /* ignore */ }
}

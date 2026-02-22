/* Aegis Workers Module — Instance-based sidebar with per-instance settings */
let instancesData = [];
let registryData = [];

async function loadInstances() {
    try {
        const res = await fetch('/api/instances');
        instancesData = await res.json();
        renderInstancesSidebar();
    } catch (e) { console.error('Error loading instances:', e); }
}

function renderInstancesSidebar() {
    const list = document.getElementById('agentCardsList');
    if (!list) return;

    if (instancesData.length === 0) {
        list.innerHTML = `
            <div class="empty-state" style="padding:2rem 1rem;">
                <div class="empty-state-icon" style="font-size:2rem;">🏗️</div>
                <div class="empty-state-text" style="font-size:0.8rem;">No workers yet.<br>Create one from an installed template.</div>
            </div>`;
        return;
    }

    list.innerHTML = instancesData.map(inst => {
        const isRunning = inst.runtime_status === 'running';
        const color = inst.color || '#6366f1';
        const rgb = hexToRgb(color);
        const serviceBadge = inst.service ? `<span style="font-size:0.6rem;background:var(--bg-dark);padding:0.1rem 0.3rem;border-radius:3px;color:var(--text-secondary)">${inst.service}</span>` : '';
        const modelBadge = inst.model ? `<span style="font-size:0.6rem;background:var(--bg-dark);padding:0.1rem 0.3rem;border-radius:3px;color:var(--text-secondary)">${inst.model}</span>` : '';
        return `
            <div class="agent-sidebar-card ${isRunning ? 'active' : ''}"
                 style="--agent-color: ${color}; --agent-color-rgb: ${rgb.r}, ${rgb.g}, ${rgb.b}"
                 data-instance-id="${inst.instance_id}">
                <div class="agent-sidebar-header">
                    <div class="agent-avatar" style="border-color: ${color}">${inst.icon || '🤖'}</div>
                    <div class="agent-info-main">
                        <div class="agent-name">${escapeHtml(inst.instance_name)}</div>
                        <div class="agent-status-tag ${isRunning ? 'running' : ''}">
                            <div class="dot"></div>
                            <span>${inst.runtime_status ? inst.runtime_status.charAt(0).toUpperCase() + inst.runtime_status.slice(1) : 'Stopped'}</span>
                        </div>
                    </div>
                </div>
                <div class="agent-params">
                    <div class="param-row"><span>Template</span><b>${escapeHtml(inst.template_id)}</b></div>
                    <div style="display:flex;gap:0.25rem;flex-wrap:wrap;margin-top:0.25rem;">${serviceBadge}${modelBadge}</div>
                </div>
                <div style="display:flex;gap:0.25rem;margin-top:0.5rem;">
                    ${!isRunning ? `<button onclick="startInstance('${inst.instance_id}')" style="flex:1;background:#22c55e;font-size:0.7rem;">▶ Start</button>` : ''}
                    ${isRunning ? `<button class="danger" onclick="stopInstance('${inst.instance_id}')" style="flex:1;font-size:0.7rem;">⏹ Stop</button>` : ''}
                    <button class="secondary" onclick="openInstanceSettings('${inst.instance_id}')" style="font-size:0.7rem;" title="Settings">⚙️</button>
                    <button class="secondary" onclick="viewInstanceLogs('${inst.instance_id}')" style="font-size:0.7rem;">📋</button>
                    ${!isRunning ? `<button class="danger" onclick="deleteWorkerInstance('${inst.instance_id}')" style="font-size:0.7rem;">🗑</button>` : ''}
                </div>
            </div>`;
    }).join('');
}

function hexToRgb(hex) {
    const result = /^#?([a-f\d]{2})([a-f\d]{2})([a-f\d]{2})$/i.exec(hex);
    return result ? { r: parseInt(result[1], 16), g: parseInt(result[2], 16), b: parseInt(result[3], 16) } : { r: 99, g: 102, b: 241 };
}

// ─── Instance Actions ───────────────────────────────────────────────────

async function startInstance(instanceId) {
    showToast('Starting...');
    try {
        const res = await fetch(`/api/instances/${instanceId}/start`, { method: 'POST' });
        const d = await res.json();
        if (res.ok) { showToast(`✅ Started`); await loadInstances(); }
        else { showToast(`⚠️ ${d.detail || 'Start failed'}`); }
    } catch (e) { showToast('Start failed'); }
}

async function stopInstance(instanceId) {
    try {
        const res = await fetch(`/api/instances/${instanceId}/stop`, { method: 'POST' });
        if (res.ok) { showToast('⏹ Stopped'); await loadInstances(); }
        else { showToast('Stop failed'); }
    } catch (e) { showToast('Stop failed'); }
}

async function deleteWorkerInstance(instanceId) {
    if (!confirm('Delete this worker instance?')) return;
    try {
        const res = await fetch(`/api/instances/${instanceId}`, { method: 'DELETE' });
        if (res.ok) { showToast('🗑 Deleted'); await loadInstances(); }
        else { showToast('Delete failed'); }
    } catch (e) { showToast('Delete failed'); }
}

async function viewInstanceLogs(instanceId) {
    try {
        const res = await fetch(`/api/instances/${instanceId}/logs?tail=50`);
        const d = await res.json();
        const logs = d.logs || [];
        alert(logs.length > 0 ? logs.join('\n') : 'No output yet.');
    } catch (e) { showToast('Failed to load logs'); }
}

// ─── Create Worker Modal (with per-instance settings) ───────────────────

async function openCreateWorkerModal() {
    document.getElementById('createWorkerModal').classList.add('active');
    try {
        const res = await fetch('/api/registry');
        registryData = await res.json();
        const select = document.getElementById('workerTemplate');
        select.innerHTML = '<option value="">Select a template...</option>';
        registryData.filter(a => a.installed).forEach(a => {
            select.innerHTML += `<option value="${a.id}">${a.icon || '🤖'} ${escapeHtml(a.name)} (${a.id})</option>`;
        });
        if (registryData.filter(a => a.installed).length === 0) {
            select.innerHTML += '<option value="" disabled>No templates installed. Visit Marketplace first.</option>';
        }
    } catch (e) { console.error('Failed to load registry', e); }
    // Clear fields
    document.getElementById('workerName').value = '';
    document.getElementById('workerModel').value = '';
    document.getElementById('createEnvVarsSection').innerHTML = '';
}

function onTemplateChange() {
    const templateId = document.getElementById('workerTemplate').value;
    const tmpl = registryData.find(a => a.id === templateId);
    const section = document.getElementById('createEnvVarsSection');
    if (!tmpl || !tmpl.execution || !tmpl.execution.env_vars_required || tmpl.execution.env_vars_required.length === 0) {
        section.innerHTML = '';
        return;
    }
    // Auto-select service based on template
    const serviceMap = { 'ANTHROPIC_API_KEY': 'anthropic', 'GOOGLE_API_KEY': 'google', 'OPENAI_API_KEY': 'openai' };
    const firstKey = tmpl.execution.env_vars_required[0];
    if (serviceMap[firstKey]) {
        document.getElementById('workerService').value = serviceMap[firstKey];
    }
    section.innerHTML = tmpl.execution.env_vars_required.map(key => `
        <div class="form-group">
            <label>🔑 ${key}</label>
            <input type="password" class="create-env-input" data-key="${key}" placeholder="Enter ${key}">
        </div>
    `).join('');
}

async function createWorkerInstance() {
    const templateId = document.getElementById('workerTemplate').value;
    const instanceName = document.getElementById('workerName').value.trim();
    const service = document.getElementById('workerService').value;
    const model = document.getElementById('workerModel').value.trim();

    if (!templateId) { showToast('Select a template'); return; }
    if (!instanceName) { showToast('Enter a worker name'); return; }

    // Gather env vars from inputs
    const env_vars = {};
    document.querySelectorAll('.create-env-input').forEach(input => {
        const key = input.dataset.key;
        if (key && input.value) env_vars[key] = input.value;
    });

    showToast(`Creating ${instanceName}...`);
    try {
        const res = await fetch('/api/instances/create', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ template_id: templateId, instance_name: instanceName, service, model, env_vars })
        });
        if (res.ok) {
            showToast(`✅ Worker "${instanceName}" created!`);
            closeModal('createWorkerModal');
            await loadInstances();
        } else {
            const err = await res.json();
            showToast(`⚠️ ${err.detail || 'Create failed'}`);
        }
    } catch (e) { showToast('Create failed'); }
}

// ─── Instance Settings Modal (edit existing worker) ─────────────────────

async function openInstanceSettings(instanceId) {
    const inst = instancesData.find(i => i.instance_id === instanceId);
    if (!inst) { showToast('Instance not found'); return; }

    document.getElementById('instSettingsId').value = instanceId;
    document.getElementById('instSettingsTitle').textContent = inst.instance_name;
    document.getElementById('instSettingsName').value = inst.instance_name;
    document.getElementById('instSettingsService').value = inst.service || 'anthropic';
    document.getElementById('instSettingsModel').value = inst.model || '';
    document.getElementById('instSettingsEnabled').checked = inst.enabled !== false;

    // Render env var inputs
    const tmpl = registryData.find(a => a.id === inst.template_id);
    const requiredKeys = (tmpl && tmpl.execution && tmpl.execution.env_vars_required) ? tmpl.execution.env_vars_required : [];
    const savedEnv = inst.env_vars || {};

    // Merge required + any extra saved keys
    const allKeys = new Set([...requiredKeys, ...Object.keys(savedEnv)]);

    const section = document.getElementById('instEnvVarsSection');
    let html = '';
    allKeys.forEach(key => {
        html += `
            <div class="form-group">
                <label>🔑 ${key}</label>
                <input type="password" class="inst-env-input" data-key="${key}" value="${savedEnv[key] || ''}" placeholder="Enter ${key}">
            </div>
        `;
    });
    section.innerHTML = html;

    document.getElementById('instanceSettingsModal').classList.add('active');
}

async function saveInstanceSettings() {
    const instanceId = document.getElementById('instSettingsId').value;
    const instance_name = document.getElementById('instSettingsName').value.trim();
    const service = document.getElementById('instSettingsService').value;
    const model = document.getElementById('instSettingsModel').value.trim();
    const enabled = document.getElementById('instSettingsEnabled').checked;

    const env_vars = {};
    document.querySelectorAll('.inst-env-input').forEach(input => {
        const key = input.dataset.key;
        if (key && input.value) env_vars[key] = input.value;
    });

    try {
        const res = await fetch(`/api/instances/${instanceId}/settings`, {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ instance_name, service, model, enabled, env_vars })
        });
        if (res.ok) {
            showToast('⚙️ Settings saved');
            closeModal('instanceSettingsModal');
            await loadInstances();
        } else {
            const err = await res.json();
            showToast(`⚠️ ${err.detail || 'Save failed'}`);
        }
    } catch (e) { showToast('Error saving settings'); }
}

// ─── Marketplace (kept for install flow) ──────────────────────────────

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
            </div>
            <div class="agent-card-desc">${escapeHtml(a.description)}</div>
            <div class="agent-card-actions">
                <a href="${a.support_url}" target="_blank" style="text-decoration:none;"><button class="secondary" style="font-size:0.75rem;">⭐ GitHub</button></a>
                ${!a.installed ? `<button onclick="installAgent('${a.id}')">📥 Install</button>` : `<span style="color:var(--text-secondary);font-size:0.75rem;">✓ Ready to instance</span>`}
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

async function loadActiveRuntimes() {
    try {
        const res = await fetch('/api/agents/active'); const runtimes = await res.json();
        const container = document.getElementById('runtimesList');
        if (runtimes.length === 0) { container.innerHTML = '<div class="empty-state"><div class="empty-state-icon">💤</div><div class="empty-state-text">No active runtimes.</div></div>'; return; }
        container.innerHTML = runtimes.map(r => {
            return `<div class="runtime-row"><span class="agent-icon">${r.instance_name ? '⚙️' : '🤖'}</span><div class="runtime-info"><h4>${r.instance_name || r.agent_id}</h4><small>PID: ${r.pid} · <span class="badge badge-${r.status}">${r.status}</span> · ${r.log_count} logs</small></div>${r.status === 'running' ? `<button class="danger" style="font-size:0.75rem;" onclick="stopInstance('${r.instance_id || r.agent_id}')">⏹</button>` : ''}</div>`;
        }).join('');
    } catch (e) { document.getElementById('runtimesList').textContent = 'Failed to load runtimes'; }
}

// Glow effects
function updateGlowEffects() {
    document.querySelectorAll('.card').forEach(c => { c.classList.remove('agent-active'); c.style.removeProperty('--agent-color'); });
}

// Called on page load — renamed from loadAgents
async function loadAgents() { await loadInstances(); }

function updateAgentParam(agentId, key, value) { /* Legacy no-op */ }

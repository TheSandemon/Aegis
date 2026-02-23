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

// ─── Service & Model Definitions ──────────────────────────────────────────

const SERVICE_MODELS = {
    'anthropic': {
        name: 'Anthropic',
        key_env: 'ANTHROPIC_API_KEY',
        models: [
            { id: 'claude-3-7-sonnet-latest', name: 'Claude 3.7 Sonnet' },
            { id: 'claude-3-5-sonnet-latest', name: 'Claude 3.5 Sonnet' },
            { id: 'claude-3-5-haiku-latest', name: 'Claude 3.5 Haiku' },
            { id: 'claude-3-opus-latest', name: 'Claude 3 Opus' }
        ]
    },
    'google': {
        name: 'Google',
        key_env: 'GOOGLE_API_KEY',
        models: [
            { id: 'gemini-2.5-pro', name: 'Gemini 2.5 Pro' },
            { id: 'gemini-2.5-flash', name: 'Gemini 2.5 Flash' },
            { id: 'gemini-2.0-pro-exp-02-05', name: 'Gemini 2.0 Pro Experimental' },
            { id: 'gemini-2.0-flash', name: 'Gemini 2.0 Flash' }
        ]
    },
    'openai': {
        name: 'OpenAI',
        key_env: 'OPENAI_API_KEY',
        models: [
            { id: 'o3-mini', name: 'o3-mini' },
            { id: 'o1', name: 'o1' },
            { id: 'gpt-4o', name: 'GPT-4o' },
            { id: 'gpt-4o-mini', name: 'GPT-4o Mini' }
        ]
    },
    'deepseek': {
        name: 'DeepSeek',
        key_env: 'DEEPSEEK_API_KEY',
        models: [
            { id: 'deepseek-reasoner', name: 'DeepSeek Reasoner (R1)' },
            { id: 'deepseek-chat', name: 'DeepSeek Chat (V3)' }
        ]
    },
    'custom': {
        name: 'Custom',
        key_env: '',
        models: []
    }
};

function renderModelDropdown(service, selectEl, customInputEl, selectedValue = '') {
    const svc = SERVICE_MODELS[service];
    if (!svc || service === 'custom') {
        selectEl.style.display = 'none';
        customInputEl.style.display = 'block';
        if (selectedValue && !svc?.models.find(m => m.id === selectedValue)) {
            customInputEl.value = selectedValue;
        }
        return;
    }

    selectEl.style.display = 'block';
    customInputEl.style.display = 'none';
    selectEl.innerHTML = svc.models.map(m => `<option value="${m.id}" ${m.id === selectedValue ? 'selected' : ''}>${m.name}</option>`).join('') + '<option value="custom">-- Custom --</option>';

    // If the saved value isn't in the list, pre-select custom
    if (selectedValue && !svc.models.find(m => m.id === selectedValue)) {
        selectEl.value = 'custom';
        customInputEl.style.display = 'block';
        customInputEl.value = selectedValue;
    }
}

let apiKeyDebounceTimer = null;

async function verifyApiKey(keyStr, mode) {
    if (!keyStr || keyStr.length < 10) return;
    const feedbackEl = document.getElementById(`feedback-${mode}-apikey`);
    if (feedbackEl) feedbackEl.innerHTML = ' ⏳ <i>Verifying...</i>';

    try {
        const res = await fetch('/api/keys/verify', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ api_key: keyStr })
        });
        const data = await res.json();

        if (data.valid) {
            if (feedbackEl) feedbackEl.innerHTML = ' ✅ <span style="color:var(--success);font-size:0.8rem;">Verified</span>';

            const prefix = mode === 'create' ? 'worker' : 'instSettings';
            const serviceStr = data.service;
            document.getElementById(`${prefix}Service`).value = serviceStr;

            // Clear existing models for this service before adding new ones to prevent duplicates
            if (SERVICE_MODELS[serviceStr]) {
                SERVICE_MODELS[serviceStr].models = [];
            }

            if (data.models && data.models.length > 0) {
                if (SERVICE_MODELS[serviceStr]) {
                    SERVICE_MODELS[serviceStr].models = data.models;
                }
            }

            const selectEl = document.getElementById(`${prefix}ModelSelect`);
            const customEl = document.getElementById(`${prefix}ModelCustom`);
            renderModelDropdown(serviceStr, selectEl, customEl, data.default_model);

            if (data.default_model) {
                selectEl.value = data.default_model;
            }

            // Reveal model selection
            const modelGroup = document.getElementById(`modelGroup-${mode}`);
            if (modelGroup) modelGroup.style.display = 'block';

        } else {
            if (feedbackEl) feedbackEl.innerHTML = ' ❌ <span style="color:var(--danger);font-size:0.8rem;">Invalid Key</span>';
        }
    } catch (e) {
        if (feedbackEl) feedbackEl.innerHTML = ' ⚠️ <span style="color:var(--warning);font-size:0.8rem;">Check failed</span>';
    }
}

function handleUnifiedKeyInput(e, mode) {
    clearTimeout(apiKeyDebounceTimer);
    apiKeyDebounceTimer = setTimeout(() => {
        verifyApiKey(e.target.value.trim(), mode);
    }, 800);
}

function onServiceChange(mode) {
    const isCreate = mode === 'create';
    const prefix = isCreate ? 'worker' : 'instSettings';
    const service = document.getElementById(`${prefix}Service`).value;
    const selectEl = document.getElementById(`${prefix}ModelSelect`);
    const customEl = document.getElementById(`${prefix}ModelCustom`);

    renderModelDropdown(service, selectEl, customEl);
}

function onModelSelectChange(mode) {
    const prefix = mode === 'create' ? 'worker' : 'instSettings';
    const selectEl = document.getElementById(`${prefix}ModelSelect`);
    const customEl = document.getElementById(`${prefix}ModelCustom`);
    if (selectEl.value === 'custom') {
        customEl.style.display = 'block';
        customEl.focus();
    } else {
        customEl.style.display = 'none';
    }
}

// ─── Config Schema Dynamic Forms ────────────────────────────────────────

function renderConfigSchema(templateId, containerId, savedConfig = {}) {
    const container = document.getElementById(containerId);
    if (!container) return;
    const tmpl = registryData.find(a => a.id === templateId);
    if (!tmpl || !tmpl.config_schema) { container.innerHTML = ''; return; }

    const schema = tmpl.config_schema;
    let html = '<label style="font-weight:600;margin-bottom:0.25rem;display:block;">⚙️ Configuration</label>';

    for (const [key, def] of Object.entries(schema)) {
        const saved = savedConfig[key] !== undefined ? savedConfig[key] : def.default;
        html += `<div class="form-group" style="margin-bottom:0.5rem;">`;
        html += `<label style="font-size:0.85rem;">${def.label || key}</label>`;

        switch (def.type) {
            case 'textarea':
                html += `<textarea class="config-input" data-config-key="${key}" rows="2" style="font-size:0.8rem;">${escapeHtml(String(saved))}</textarea>`;
                break;
            case 'range':
                html += `<div style="display:flex;align-items:center;gap:0.5rem;">`;
                html += `<input type="range" class="config-input" data-config-key="${key}" min="${def.min}" max="${def.max}" step="${def.step}" value="${saved}" oninput="this.nextElementSibling.textContent=this.value" style="flex:1;">`;
                html += `<span style="font-size:0.8rem;min-width:2rem;">${saved}</span>`;
                html += `</div>`;
                break;
            case 'number':
                html += `<input type="number" class="config-input" data-config-key="${key}" value="${saved}" style="font-size:0.8rem;">`;
                break;
            case 'select':
                html += `<select class="config-input" data-config-key="${key}" style="font-size:0.8rem;">`;
                (def.options || []).forEach(opt => {
                    html += `<option value="${opt}" ${opt === saved ? 'selected' : ''}>${opt}</option>`;
                });
                html += `</select>`;
                break;
            case 'multiselect':
                const selectedArr = Array.isArray(saved) ? saved : [];
                html += `<div class="config-input" data-config-key="${key}" data-type="multiselect" style="display:flex;flex-wrap:wrap;gap:0.25rem;">`;
                (def.options || []).forEach(opt => {
                    const checked = selectedArr.includes(opt) ? 'checked' : '';
                    html += `<label style="font-size:0.75rem;display:flex;align-items:center;gap:0.2rem;"><input type="checkbox" value="${opt}" ${checked}> ${opt}</label>`;
                });
                html += `</div>`;
                break;
            default:
                html += `<input type="text" class="config-input" data-config-key="${key}" value="${escapeHtml(String(saved))}" style="font-size:0.8rem;">`;
        }
        html += `</div>`;
    }
    container.innerHTML = html;
}

function collectConfigValues(containerId) {
    const config = {};
    const container = document.getElementById(containerId);
    if (!container) return config;
    container.querySelectorAll('.config-input').forEach(el => {
        const key = el.dataset.configKey;
        if (!key) return;
        if (el.dataset.type === 'multiselect') {
            config[key] = [...el.querySelectorAll('input[type=checkbox]:checked')].map(cb => cb.value);
        } else if (el.type === 'range' || el.type === 'number') {
            config[key] = Number(el.value);
        } else {
            config[key] = el.value;
        }
    });
    return config;
}

// ─── Create Worker Modal (with per-instance settings) ───────────────────

async function openCreateWorkerModal() {
    document.getElementById('createWorkerModal').classList.add('active');
    try {
        const res = await fetch('/api/registry');
        registryData = await res.json();
        const select = document.getElementById('workerTemplate');
        select.innerHTML = '<option value="">Select an agent type...</option>';
        registryData.filter(a => a.installed).forEach(a => {
            select.innerHTML += `<option value="${a.id}">${a.icon || '🤖'} ${escapeHtml(a.name)} (${a.id})</option>`;
        });
        if (registryData.filter(a => a.installed).length === 0) {
            select.innerHTML += '<option value="" disabled>No templates installed. Visit Marketplace first.</option>';
        }
    } catch (e) { console.error('Failed to load registry', e); }
    // Clear fields
    document.getElementById('workerName').value = '';
    document.getElementById('workerModelCustom').value = '';
    document.getElementById('workerService').value = '';
    document.getElementById('unifiedApiKey-create').value = '';
    document.getElementById('feedback-create-apikey').innerHTML = '';
    document.getElementById('modelGroup-create').style.display = 'none';
    document.getElementById('createConfigSection').innerHTML = '';
}

function onTemplateChange() {
    const templateId = document.getElementById('workerTemplate').value;
    const tmpl = registryData.find(a => a.id === templateId);
    if (!tmpl) return;

    // Render config schema
    renderConfigSchema(templateId, 'createConfigSection');
}

async function createWorkerInstance() {
    const templateId = document.getElementById('workerTemplate').value;
    const instanceName = document.getElementById('workerName').value.trim();
    const service = document.getElementById('workerService').value;

    let model = document.getElementById('workerModelSelect').value;
    if (model === 'custom' || !model) {
        model = document.getElementById('workerModelCustom').value.trim();
    }

    if (!templateId) { showToast('Select an agent type'); return; }
    if (!instanceName) { showToast('Enter a worker name'); return; }

    const apiKey = document.getElementById('unifiedApiKey-create').value.trim();
    const env_vars = {};
    if (apiKey && SERVICE_MODELS[service]) {
        env_vars[SERVICE_MODELS[service].key_env] = apiKey;
    }

    // Gather config schema values
    const config = collectConfigValues('createConfigSection');

    showToast(`Creating ${instanceName}...`);
    try {
        const res = await fetch('/api/instances/create', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ template_id: templateId, instance_name: instanceName, service, model, env_vars, config })
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
    document.getElementById('instSettingsEnabled').checked = inst.enabled !== false;

    const svc = inst.service || '';
    document.getElementById('instSettingsService').value = svc;

    document.getElementById('unifiedApiKey-edit').value = ''; // Don't show the saved key
    document.getElementById('feedback-edit-apikey').innerHTML = '';

    // Render the dropdowns and API keys based on service
    onServiceChange('edit');

    // Now set the model value
    const modelSelect = document.getElementById('instSettingsModelSelect');
    const modelCustom = document.getElementById('instSettingsModelCustom');
    const modelGroup = document.getElementById('modelGroup-edit');
    const savedModel = inst.model || '';

    if (svc) {
        modelGroup.style.display = 'block';
    } else {
        modelGroup.style.display = 'none';
    }

    const svcData = SERVICE_MODELS[svc];
    if (svcData && svcData.models.find(m => m.id === savedModel)) {
        modelSelect.value = savedModel;
        modelCustom.style.display = 'none';
    } else {
        modelSelect.value = 'custom';
        modelCustom.style.display = 'block';
        modelCustom.value = savedModel;
    }

    // Render config schema with saved values
    renderConfigSchema(inst.template_id, 'editConfigSection', inst.config || {});

    document.getElementById('instanceSettingsModal').classList.add('active');
}

async function saveInstanceSettings() {
    const instanceId = document.getElementById('instSettingsId').value;
    const instance_name = document.getElementById('instSettingsName').value.trim();
    const service = document.getElementById('instSettingsService').value;

    let model = document.getElementById('instSettingsModelSelect').value;
    if (model === 'custom' || !model) {
        model = document.getElementById('instSettingsModelCustom').value.trim();
    }

    const enabled = document.getElementById('instSettingsEnabled').checked;

    const apiKey = document.getElementById('unifiedApiKey-edit').value.trim();
    const env_vars = {};
    if (apiKey && SERVICE_MODELS[service]) {
        env_vars[SERVICE_MODELS[service].key_env] = apiKey;
    }

    // Gather config schema values
    const config = collectConfigValues('editConfigSection');

    const updateData = { instance_name, service, model, enabled, config };
    // Only include env_vars if a new API key was actually entered
    if (Object.keys(env_vars).length > 0) {
        updateData.env_vars = env_vars;
    }

    try {
        const res = await fetch(`/api/instances/${instanceId}/settings`, {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(updateData)
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

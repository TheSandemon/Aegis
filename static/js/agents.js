/* Aegis Workers Module — Instance-based sidebar with per-instance settings */
let instancesData = [];
let registryData = [];

async function ensureRegistryLoaded() {
    if (registryData.length > 0) return;
    try {
        const res = await fetch('/api/registry');
        registryData = await res.json();
    } catch (e) { console.error('Failed to load registry', e); }
}

async function loadInstances() {
    await ensureRegistryLoaded();
    try {
        const res = await fetch('/api/instances');
        instancesData = await res.json();
        renderInstancesSidebar();
    } catch (e) { console.error('Error loading instances:', e); }
}

let profilesData = [];

async function loadProfiles() {
    try {
        const res = await fetch('/api/profiles');
        profilesData = await res.json();
        populateProfileDropdown();
    } catch (e) { console.error('Error loading profiles:', e); }
}

function populateProfileDropdown() {
    const dd = document.getElementById('profileDropdown');
    if (!dd) return;
    dd.innerHTML = '<option value="">— Start from scratch —</option>' +
        profilesData.map(p => {
            const label = `${p.icon || '🤖'} ${escapeHtml(p.name)} (${p.template_id})`;
            return `<option value="${p.id}">${label}</option>`;
        }).join('');
}

function applyProfile(profileId) {
    if (!profileId) return; // "Start from scratch" selected
    createFromProfile(profileId);
}

async function uploadWorkerIcon(mode) {
    const fileInput = document.getElementById(`iconUpload-${mode}`);
    if (!fileInput.files.length) return;

    const formData = new FormData();
    formData.append('file', fileInput.files[0]);

    try {
        const res = await fetch('/api/assets/upload', {
            method: 'POST',
            body: formData
        });
        const data = await res.json();
        if (data.url) {
            const inputId = mode === 'create' ? 'workerIcon' : 'instSettingsIcon';
            document.getElementById(inputId).value = data.url;
            updateIconPreview(mode);
            showToast('✅ Icon uploaded');
        } else {
            showToast('⚠️ Upload failed');
        }
    } catch (e) {
        console.error('Upload error:', e);
        showToast('⚠️ Upload failed');
    }
}

// ─── Emoji / Icon Picker ─────────────────────────────────────────────────

const AGENT_EMOJIS = [
    '🤖', '🦾', '🧠', '🔬', '🔭', '🛸', '🚀', '⚡',
    '🔧', '🛠️', '🤝', '📝', '🎯', '🔍', '🧩', '💡',
    '🏗️', '🔐', '🌐', '📊', '🧬', '👾', '🦉', '🐉'
];

function initEmojiGrid(containerId, mode) {
    const container = document.getElementById(containerId);
    if (!container) return;
    container.innerHTML = AGENT_EMOJIS.map(e =>
        `<button class="emoji-btn" onclick="selectAgentIcon('${e}','${mode}')" title="${e}">${e}</button>`
    ).join('');
}

function selectAgentIcon(emoji, mode) {
    const prefix = mode === 'create' ? 'worker' : 'instSettings';
    const input = document.getElementById(`${prefix}Icon`);
    if (input) input.value = emoji;
    updateIconPreview(mode);
}

function updateIconPreview(mode) {
    const prefix = mode === 'create' ? 'worker' : 'instSettings';
    const val = document.getElementById(`${prefix}Icon`)?.value || '🤖';
    const preview = document.getElementById(`iconPreview-${mode}`);
    if (!preview) return;
    if (val.startsWith('http') || val.startsWith('/assets/')) {
        preview.innerHTML = `<img src="${val}" style="width:100%;height:100%;border-radius:50%;object-fit:cover;">`;
    } else {
        preview.innerHTML = '';
        preview.textContent = val || '🤖';
    }
}

async function deleteProfile(profileId) {
    if (!confirm('Delete this profile?')) return;
    try {
        const res = await fetch(`/api/profiles/${profileId}`, { method: 'DELETE' });
        if (res.ok) {
            showToast('🗑 Profile deleted');
            loadProfiles();
        }
    } catch (e) { console.error('Error deleting profile:', e); }
}

function createFromProfile(profileId) {
    const profile = profilesData.find(p => p.id === profileId);
    if (!profile) return;

    openCreateWorkerModal();

    // Select the template
    const templateIdx = registryData.findIndex(a => a.id === profile.template_id);
    if (templateIdx !== -1) {
        const tpl = registryData[templateIdx];
        // Note: Creating worker needs a registry item context, but index is usually enough for the UI
        selectTemplateForCreation(templateIdx);
    }

    // Fill the rest
    document.getElementById('workerName').value = profile.name || '';
    document.getElementById('workerIcon').value = profile.icon || '🤖';
    document.getElementById('workerColor').value = profile.color || '#6366f1';

    if (profile.model) {
        const modelSelect = document.getElementById('workerModelSelect');
        if (modelSelect) {
            modelSelect.value = profile.model;
            // Trigger change to show custom model input if needed
            modelSelect.dispatchEvent(new Event('change'));
        }
    }
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

        const iconHtml = inst.icon && (inst.icon.startsWith('http') || inst.icon.startsWith('/assets/'))
            ? `<img src="${inst.icon}" class="agent-avatar-img" style="border-color: ${color}">`
            : `<div class="agent-avatar" style="border-color: ${color}">${inst.icon || '🤖'}</div>`;

        return `
            <div class="agent-sidebar-card ${isRunning ? 'active' : ''}"
                 style="--agent-color: ${color}; --agent-color-rgb: ${rgb.r}, ${rgb.g}, ${rgb.b};"
                 data-instance-id="${inst.instance_id}">
                <div class="agent-sidebar-header">
                    ${iconHtml}
                    <div class="agent-info-main">
                        <div class="agent-name">${escapeHtml(inst.instance_name)}</div>
                        <div class="agent-status-tag ${isRunning ? 'running' : ''}">
                            <div class="dot"></div>
                            <span>${inst.runtime_status ? inst.runtime_status.charAt(0).toUpperCase() + inst.runtime_status.slice(1) : 'Stopped'}</span>
                        </div>
                        ${isRunning ? `<div class="agent-activity-indicator" id="activity-${inst.instance_id}" style="font-size: 0.7rem; color: var(--text-secondary); margin-top: 4px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">💤 Idle</div>
                        <div id="pulse-${inst.instance_id}" style="font-size: 0.65rem; color: var(--primary); margin-top: 2px; font-weight: bold;"></div>` : ''}
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

let terminalPollInterval = null;

async function viewInstanceLogs(instanceId) {
    const inst = instancesData.find(i => i.instance_id === instanceId);
    const displayName = inst?.instance_name || instanceId;
    document.getElementById('terminalModal').classList.add('active');
    document.getElementById('terminalTitle').textContent = `Terminal — ${displayName}`;
    const output = document.getElementById('workerTerminalOutput');
    output.textContent = 'Connecting to terminal...';

    // Clear any existing poll
    if (terminalPollInterval) clearInterval(terminalPollInterval);

    const fetchLogs = async () => {
        try {
            const res = await fetch(`/api/instances/${instanceId}/logs?tail=200`);
            if (!res.ok) throw new Error('Failed to fetch');
            const d = await res.json();
            const logs = d.logs || [];

            // Check if scroll is at bottom before update
            const isScrolledToBottom = output.scrollHeight - output.clientHeight <= output.scrollTop + 1;

            output.textContent = logs.length > 0 ? logs.join('\n') : 'No output yet.';

            // Auto-scroll if it was previously at bottom
            if (isScrolledToBottom) {
                output.scrollTop = output.scrollHeight;
            }
        } catch (e) {
            console.error('Terminal poll error:', e);
        }
    };

    // Initial fetch and start polling every 2s
    await fetchLogs();
    // Scroll to bottom immediately on open
    output.scrollTop = output.scrollHeight;
    terminalPollInterval = setInterval(fetchLogs, 2000);
}

function closeTerminal() {
    document.getElementById('terminalModal').classList.remove('active');
    if (terminalPollInterval) {
        clearInterval(terminalPollInterval);
        terminalPollInterval = null;
    }
}

// ─── Pulse Countdown Logic ────────────────────────────────────────────────
let pulseTimers = {};

window.startPulseCountdown = function (instanceId, secondsCount) {
    const el = document.getElementById(`pulse-${instanceId}`);
    if (!el) return;

    if (pulseTimers[instanceId]) clearInterval(pulseTimers[instanceId]);

    let remaining = secondsCount;
    el.innerHTML = `⏱️ Pulse in ${remaining}s...`;

    pulseTimers[instanceId] = setInterval(() => {
        remaining--;
        if (remaining <= 0) {
            clearInterval(pulseTimers[instanceId]);
            el.innerHTML = '⚡ Pulsing...';
        } else {
            el.innerHTML = `⏱️ Pulse in ${remaining}s...`;
        }
    }, 1000);
};

// ─── Agent Speech Bubbles ─────────────────────────────────────────────────
const bubbleTimers = {};

function showAgentBubble(instanceId, text, mood = 'thought') {
    const card = document.querySelector(`.agent-sidebar-card[data-instance-id="${instanceId}"]`);
    if (!card) return;

    // Remove existing bubble
    const existing = card.querySelector('.agent-speech-bubble');
    if (existing) existing.remove();
    if (bubbleTimers[instanceId]) clearTimeout(bubbleTimers[instanceId]);

    // Truncate to 180 chars (increased for personality)
    const truncated = text.length > 180 ? text.substring(0, 177) + '...' : text;

    const bubble = document.createElement('div');
    bubble.className = `agent-speech-bubble bubble-${mood}`;

    let prefix = '💡';
    if (mood === 'error') prefix = '🛑';
    if (mood === 'attention') prefix = '⚠️';

    bubble.innerHTML = `<span class="bubble-prefix">${prefix}</span> ${escapeHtml(truncated)}<button class="bubble-dismiss" onclick="event.stopPropagation(); dismissBubble('${instanceId}')">×</button>`;
    card.appendChild(bubble);

    // Auto-dismiss after 10s
    bubbleTimers[instanceId] = setTimeout(() => dismissBubble(instanceId), 10000);
}

function dismissBubble(instanceId) {
    if (bubbleTimers[instanceId]) {
        clearTimeout(bubbleTimers[instanceId]);
        delete bubbleTimers[instanceId];
    }
    const card = document.querySelector(`.agent-sidebar-card[data-instance-id="${instanceId}"]`);
    if (card) {
        const bubble = card.querySelector('.agent-speech-bubble');
        if (bubble) bubble.remove();
    }
}

// ─── Service & Model Definitions ──────────────────────────────────────────
// Populated from GET /api/models at startup — single source of truth is main.py

let SERVICE_MODELS = {};

async function loadServiceModels() {
    try {
        const res = await fetch('/api/models');
        if (!res.ok) throw new Error('Failed to load models');
        const data = await res.json();
        // Merge server data into SERVICE_MODELS, preserving any already-loaded keys
        Object.assign(SERVICE_MODELS, data);
        // Re-render any open service selects
        document.querySelectorAll('select[id$="Service"]').forEach(sel => {
            _populateServiceSelect(sel);
        });
    } catch (e) {
        console.warn('Could not load model registry from server, using fallback');
    }
}

function _populateServiceSelect(selectEl) {
    if (!selectEl) return;
    const current = selectEl.value;
    selectEl.innerHTML = '<option value="">Select a service...</option>';
    Object.entries(SERVICE_MODELS).forEach(([id, svc]) => {
        const opt = document.createElement('option');
        opt.value = id;
        opt.textContent = svc.name;
        if (id === current) opt.selected = true;
        selectEl.appendChild(opt);
    });
}

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
                html += `<textarea class="config-input" data-config-key="${key}" data-mention="true" rows="2" style="font-size:0.8rem;">${escapeHtml(String(saved))}</textarea>`;
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
    await ensureRegistryLoaded();

    // Default to aegis-worker
    const templateId = 'aegis-worker';

    // Clear fields
    document.getElementById('workerName').value = '';
    document.getElementById('workerModelCustom').value = '';
    document.getElementById('workerService').value = '';
    document.getElementById('unifiedApiKey-create').value = '';
    document.getElementById('feedback-create-apikey').innerHTML = '';
    document.getElementById('workerIcon').value = '🤖';
    document.getElementById('workerColor').value = '#6366f1';
    document.getElementById('saveAsProfile').checked = false;

    // Populate profile dropdown
    populateProfileDropdown();
    const dd = document.getElementById('profileDropdown');
    if (dd) dd.value = '';

    onServiceChange('create');
    initEmojiGrid('emojiGrid-create', 'create');
    updateIconPreview('create');

    // Render config schema for the default worker
    renderConfigSchema(templateId, 'createConfigSection');
}

async function createWorkerInstance() {
    const templateId = 'aegis-worker';
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

    const icon = document.getElementById('workerIcon').value || '🤖';
    const color = document.getElementById('workerColor').value || '#6366f1';
    const saveProfile = document.getElementById('saveAsProfile').checked;

    const payload = {
        template_id: templateId,
        instance_name: instanceName,
        service: service,
        model: model,
        env_vars: env_vars,
        config: config,
        icon: icon,
        color: color
    };

    if (saveProfile) {
        const template = registryData.find(a => a.id === templateId);
        await fetch('/api/profiles', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                name: instanceName,
                template_id: template.id,
                icon: icon,
                color: color,
                service: service,
                model: model,
                config: config
            })
        });
        loadProfiles();
    }

    showToast(`Creating ${instanceName}...`);
    try {
        const res = await fetch('/api/instances/create', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
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
    const savedModel = inst.model || '';

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

    document.getElementById('instSettingsIcon').value = inst.icon || '🤖';
    document.getElementById('instSettingsColor').value = inst.color || '#6366f1';

    initEmojiGrid('emojiGrid-edit', 'edit');
    updateIconPreview('edit');

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

    const icon = document.getElementById('instSettingsIcon').value;
    const color = document.getElementById('instSettingsColor').value;

    const updateData = { instance_name, service, model, enabled, config, icon, color };
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

// Glow effects
function updateGlowEffects() {
    document.querySelectorAll('.card').forEach(c => { c.classList.remove('agent-active'); c.style.removeProperty('--agent-color'); });
}

// Called on page load
async function loadAgents() {
    await loadInstances();
    await loadProfiles();
}

function updateAgentParam(agentId, key, value) { /* Legacy no-op */ }

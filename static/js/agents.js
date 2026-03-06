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
    const delBtn = document.getElementById('deleteProfileBtn');
    if (!profileId) {
        if (delBtn) delBtn.style.display = 'none';
        return; // "Start from scratch" selected
    }
    if (delBtn) delBtn.style.display = 'block';
    createFromProfile(profileId);
}

async function deleteSelectedProfile() {
    const dd = document.getElementById('profileDropdown');
    const profileId = dd.value;
    if (!profileId) return;
    if (!confirm('Are you sure you want to delete this saved profile?')) return;
    try {
        const res = await fetch(`/api/profiles/${profileId}`, { method: 'DELETE' });
        if (res.ok) {
            showToast('🗑️ Profile deleted');
            dd.value = '';
            if (document.getElementById('deleteProfileBtn')) {
                document.getElementById('deleteProfileBtn').style.display = 'none';
            }
            await loadProfiles();
        } else {
            showToast('⚠️ Failed to delete profile');
        }
    } catch (e) { console.error(e); }
}

async function saveInstanceAsProfile() {
    const instanceId = document.getElementById('instSettingsId').value;
    const inst = instancesData.find(i => i.instance_id === instanceId);
    if (!inst) return;

    // Gather latest data from modal form
    const instanceName = document.getElementById('instSettingsName').value.trim() + ' (Copy)';
    const service = document.getElementById('instSettingsService').value;

    let model = document.getElementById('instSettingsModelSelect').value;
    if (model === 'custom' || !model) {
        model = document.getElementById('instSettingsModelCustom').value.trim();
    }
    const config = collectConfigValues('editConfigSection');
    const icon = document.getElementById('instSettingsIcon').value || '🤖';
    const color = document.getElementById('instSettingsColor').value || '#6366f1';

    try {
        const res = await fetch('/api/profiles', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                name: instanceName,
                template_id: inst.template_id,
                icon: icon,
                color: color,
                service: service,
                model: model,
                config: config
            })
        });
        if (res.ok) {
            showToast(`✅ Saved as reusable profile "${instanceName}"`);
            loadProfiles();
        } else {
            showToast('⚠️ Failed to save profile');
        }
    } catch (e) { console.error(e); }
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


        const iconHtml = inst.icon && (inst.icon.startsWith('http') || inst.icon.startsWith('/assets/'))
            ? `<img src="${inst.icon}" class="agent-avatar-img" style="border-color: ${color}">`
            : `<div class="agent-avatar" style="border-color: ${color}">${inst.icon || '🤖'}</div>`;

        return `
            <div class="agent-sidebar-card ${isRunning ? 'active' : ''}"
                 style="--agent-color: ${color}; --agent-color-rgb: ${rgb.r}, ${rgb.g}, ${rgb.b};"
                 data-instance-id="${inst.instance_id}"
                 draggable="true"
                 ondragstart="handleAgentDragStart(event, '${inst.instance_id}')"
                 ondragover="handleAgentDragOver(event)"
                 ondragenter="handleAgentDragEnter(event)"
                 ondragleave="handleAgentDragLeave(event)"
                 ondrop="handleAgentDrop(event, '${inst.instance_id}')"
                 ondragend="handleAgentDragEnd(event)">
                
                <div class="agent-sidebar-header">
                    ${iconHtml}
                    <div class="agent-info-main" style="display:flex;gap:0.5rem;align-items:center;overflow:hidden;">
                        <div class="agent-name">${escapeHtml(inst.instance_name)}</div>
                        <div class="agent-status-tag ${isRunning ? 'running' : ''}">
                            <div class="dot"></div>
                            <span>${inst.runtime_status ? inst.runtime_status.charAt(0).toUpperCase() + inst.runtime_status.slice(1) : 'Stopped'}</span>
                        </div>
                    </div>
                </div>

                ${isRunning ? `<div style="position:absolute;top:0.25rem;right:0.25rem;display:flex;flex-direction:column;align-items:flex-end;z-index:3;">
                    <div class="agent-activity-indicator" id="activity-${inst.instance_id}" style="font-size: 0.6rem; color: var(--text-secondary); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 100px;">💤 Idle</div>
                    <div id="pulse-${inst.instance_id}" style="font-size: 0.55rem; color: var(--primary); font-weight: bold;"></div>
                </div>` : ''}



                <!-- Inline Mini Terminal -->
                <div class="mini-terminal-container" onclick="viewInstanceLogs('${inst.instance_id}')" title="Click to open full terminal">
                    <div id="mini-term-${inst.instance_id}" style="width: 100%; height: 100%;"></div>
                </div>
                
                <div class="agent-sidebar-actions">
                    ${!isRunning ? `<button onclick="startInstance('${inst.instance_id}')" style="background:#22c55e;font-size:0.75rem;padding:0.25rem 0.5rem;">▶</button>` : ''}
                    ${isRunning ? `<button class="danger" onclick="stopInstance('${inst.instance_id}')" style="font-size:0.75rem;padding:0.25rem 0.5rem;" title="Stop Worker">⏹</button>` : ''}
                    <button class="secondary" onclick="openInstanceSettings('${inst.instance_id}')" style="font-size:0.75rem;padding:0.25rem 0.5rem;" title="Settings">⚙️</button>
                </div>
            </div>`;
    }).join('');

    // Reattach mini xterm terminals after DOM update
    setTimeout(() => {
        instancesData.forEach(inst => {
            const el = document.getElementById(`mini-term-${inst.instance_id}`);
            if (el) {
                const mini = getOrCreateMiniTerminal(inst.instance_id);
                if (!el.querySelector('.xterm')) {
                    el.innerHTML = ''; // clear any old canvas
                    mini.term.open(el);
                }
                mini.fit.fit();

                // If it's a new terminal without history but backend sent recent_logs, seed it
                if (!window.terminals.history[inst.instance_id] && inst.recent_logs) {
                    writeToTerminal(inst.instance_id, inst.recent_logs.replace(/\n/g, '\r\n'));
                }
            }
        });
    }, 0);
}

function hexToRgb(hex) {
    const result = /^#?([a-f\d]{2})([a-f\d]{2})([a-f\d]{2})$/i.exec(hex);
    return result ? { r: parseInt(result[1], 16), g: parseInt(result[2], 16), b: parseInt(result[3], 16) } : { r: 99, g: 102, b: 241 };
}

// ─── Drag & Drop Workers ────────────────────────────────────────────────
let draggedAgentId = null;

function handleAgentDragStart(e, id) {
    draggedAgentId = id;
    e.dataTransfer.effectAllowed = 'move';
    setTimeout(() => {
        if (e.target) e.target.style.opacity = '0.4';
    }, 0);
}

function handleAgentDragOver(e) {
    if (!draggedAgentId) return; // Prevent board cards from triggering
    e.preventDefault();
    e.dataTransfer.dropEffect = 'move';
}

function handleAgentDragEnter(e) {
    if (!draggedAgentId) return; // Prevent board cards from triggering
    e.preventDefault();
    const card = e.target.closest('.agent-sidebar-card');
    if (card && card.dataset.instanceId !== draggedAgentId) {
        card.style.transform = 'translateY(4px)';
        card.style.transition = 'transform 0.1s ease';
        card.style.boxShadow = '0 -4px 10px rgba(0,0,0,0.5)';
    }
}

function handleAgentDragLeave(e) {
    if (!draggedAgentId) return;
    const card = e.target.closest('.agent-sidebar-card');
    // only remove transform if leaving the card entirely
    if (card && !card.contains(e.relatedTarget)) {
        card.style.transform = '';
        card.style.boxShadow = '';
    }
}

function handleAgentDragEnd(e) {
    draggedAgentId = null;
    e.target.style.opacity = '1';
    document.querySelectorAll('.agent-sidebar-card').forEach(c => {
        c.style.transform = '';
        c.style.boxShadow = '';
    });
}

async function handleAgentDrop(e, targetId) {
    if (!draggedAgentId) return; // Prevent board cards from dropping
    e.preventDefault();

    const sourceId = draggedAgentId;
    handleAgentDragEnd(e);

    if (sourceId === targetId) return;

    const fromIndex = instancesData.findIndex(i => i.instance_id === sourceId);
    const toIndex = instancesData.findIndex(i => i.instance_id === targetId);
    if (fromIndex < 0 || toIndex < 0) return;

    // Reorder locally
    const item = instancesData.splice(fromIndex, 1)[0];
    instancesData.splice(toIndex, 0, item);
    renderInstancesSidebar();

    // Persist
    try {
        await fetch('/api/instances/order', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ order: instancesData.map(i => i.instance_id) })
        });
    } catch (e) {
        console.error('Save order error:', e);
        showToast('Failed to save order');
    }
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

async function deleteWorkerInstanceFromSettings() {
    const instanceId = document.getElementById('instSettingsId').value;
    if (!instanceId) return;
    closeModal('instanceSettingsModal');
    await deleteWorkerInstance(instanceId);
}

let terminalPollInterval = null;

async function viewInstanceLogs(instanceId) {
    const inst = instancesData.find(i => i.instance_id === instanceId);
    const displayName = inst?.instance_name || instanceId;
    document.getElementById('terminalModal').classList.add('active');
    document.getElementById('terminalTitle').textContent = `Terminal — ${displayName}`;

    // Force a fit after CSS animation/layout completes
    setTimeout(() => {
        if (window.terminals.modalFit) {
            try { window.terminals.modalFit.fit(); } catch (e) { }
        }
    }, 150);

    // Store the active instance ID for the chat function
    const activeIdInput = document.getElementById('activeTerminalInstanceId');
    if (activeIdInput) activeIdInput.value = instanceId;

    // Set active terminal before opening it so logs start routing correctly
    window.terminals.activeModalInstance = instanceId;

    // Initialize the modal terminal if we haven't
    initModalTerminal();

    // Mount xterm to the container only if not already mounted
    const outputEl = document.getElementById('workerTerminalOutput');
    if (!outputEl.querySelector('.xterm')) {
        outputEl.innerHTML = '';
        window.terminals.modal.open(outputEl);
    }

    // Setup a ResizeObserver to ensure the terminal always fills the container
    // especially during modal animations or window resizes.
    if (!window.terminals.modalResizeObserver) {
        window.terminals.modalResizeObserver = new ResizeObserver(() => {
            if (window.terminals.modalFit) {
                clearTimeout(window._termModFitStr);
                window._termModFitStr = setTimeout(() => {
                    try { window.terminals.modalFit.fit(); } catch (e) { }
                }, 50);
            }
        });
        window.terminals.modalResizeObserver.observe(outputEl);
    }

    // Clear and reset state instead of remounting
    window.terminals.modal.clear();

    // Replay history if we have it
    if (window.terminals.history[instanceId]) {
        window.terminals.modal.write(window.terminals.history[instanceId]);
    } else {
        // Fallback to fetch from backend 
        try {
            const res = await fetch(`/api/instances/${instanceId}/logs?tail=200`);
            if (res.ok) {
                const d = await res.json();
                const logs = d.logs || [];
                const block = logs.join('\r\n');
                window.terminals.history[instanceId] = block;
                window.terminals.modal.write(block);
            }
        } catch (e) {
            console.error('Initial log fetch failed:', e);
        }
    }

    // (The ResizeObserver now handles fitting automatically)
    // Add a delayed fallback to catch the end of modal CSS animations
    setTimeout(() => {
        if (window.terminals.modalFit) {
            try { window.terminals.modalFit.fit(); } catch (e) { }
        }
    }, 300);
}

function closeTerminal() {
    document.getElementById('terminalModal').classList.remove('active');
    window.terminals.activeModalInstance = null;
}

async function sendTerminalMessage() {
    const input = document.getElementById('terminalChatInput');
    const instanceId = document.getElementById('activeTerminalInstanceId')?.value;
    const message = input.value.trim();

    if (!message || !instanceId) return;

    input.disabled = true;
    const originalPlaceholder = input.placeholder;
    input.placeholder = "Sending...";

    try {
        const res = await fetch(`/api/instances/${instanceId}/chat`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ message: message })
        });

        if (res.ok) {
            input.value = '';
            showToast('Message sent to agent');
            // Optimistically add user message to the terminal view
            if (window.terminals.modal) {
                window.terminals.modal.writeln(`\r\n\x1b[38;5;12m👤 USER: ${message}\x1b[0m`);
            }
        } else {
            const d = await res.json();
            showToast(`⚠️ Failed to send: ${d.detail || 'Unknown error'}`);
        }
    } catch (e) {
        console.error("Chat send error:", e);
        showToast('⚠️ Failed to send message');
    } finally {
        input.disabled = false;
        input.placeholder = originalPlaceholder;
        input.focus();
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
        const desc = def.description ? `<div style="font-size:0.7rem;color:var(--text-secondary);margin-top:0.15rem;">${escapeHtml(def.description)}</div>` : '';

        html += `<div class="form-group" style="margin-bottom:0.5rem;">`;

        switch (def.type) {
            case 'boolean':
                const checked = (saved === true || saved === 'true') ? 'checked' : '';
                html += `<div style="display:flex;align-items:center;justify-content:space-between;">`;
                html += `<label style="font-size:0.85rem;margin-bottom:0;">${def.label || key}</label>`;
                html += `<label class="toggle"><input type="checkbox" class="config-input" data-config-key="${key}" data-type="boolean" ${checked}><span class="toggle-slider"></span></label>`;
                html += `</div>`;
                html += desc;
                break;
            case 'folder':
                html += `<label style="font-size:0.85rem;">${def.label || key}</label>`;
                html += `<div style="display:flex;gap:0.25rem;">`;
                html += `<input type="text" class="config-input" data-config-key="${key}" value="${escapeHtml(String(saved))}" style="font-size:0.8rem;flex:1;" id="folder-${containerId}-${key}">`;
                html += `<button type="button" class="secondary" style="font-size:0.75rem;padding:0.25rem 0.5rem;white-space:nowrap;" onclick="browseFolderFor('folder-${containerId}-${key}')">📂 Browse</button>`;
                html += `</div>`;
                html += desc;
                break;
            case 'textarea':
                html += `<label style="font-size:0.85rem;">${def.label || key}</label>`;
                html += `<textarea class="config-input" data-config-key="${key}" data-mention="true" rows="2" style="font-size:0.8rem;">${escapeHtml(String(saved))}</textarea>`;
                html += desc;
                break;
            case 'range':
                html += `<label style="font-size:0.85rem;">${def.label || key}</label>`;
                html += `<div style="display:flex;align-items:center;gap:0.5rem;">`;
                html += `<input type="range" class="config-input" data-config-key="${key}" min="${def.min}" max="${def.max}" step="${def.step}" value="${saved}" oninput="this.nextElementSibling.textContent=this.value" style="flex:1;">`;
                html += `<span style="font-size:0.8rem;min-width:2rem;">${saved}</span>`;
                html += `</div>`;
                html += desc;
                break;
            case 'number':
                html += `<label style="font-size:0.85rem;">${def.label || key}</label>`;
                html += `<input type="number" class="config-input" data-config-key="${key}" value="${saved}" style="font-size:0.8rem;">`;
                html += desc;
                break;
            case 'select':
                html += `<label style="font-size:0.85rem;">${def.label || key}</label>`;
                html += `<select class="config-input" data-config-key="${key}" style="font-size:0.8rem;">`;
                (def.options || []).forEach(opt => {
                    html += `<option value="${opt}" ${opt === saved ? 'selected' : ''}>${opt}</option>`;
                });
                html += `</select>`;
                html += desc;
                break;
            case 'multiselect':
                html += `<label style="font-size:0.85rem;">${def.label || key}</label>`;
                const selectedArr = Array.isArray(saved) ? saved : [];
                html += `<div class="config-input" data-config-key="${key}" data-type="multiselect" style="display:flex;flex-wrap:wrap;gap:0.25rem;">`;
                (def.options || []).forEach(opt => {
                    const mchecked = selectedArr.includes(opt) ? 'checked' : '';
                    html += `<label style="font-size:0.75rem;display:flex;align-items:center;gap:0.2rem;"><input type="checkbox" value="${opt}" ${mchecked}> ${opt}</label>`;
                });
                html += `</div>`;
                html += desc;
                break;
            default:
                html += `<label style="font-size:0.85rem;">${def.label || key}</label>`;
                html += `<input type="text" class="config-input" data-config-key="${key}" value="${escapeHtml(String(saved))}" style="font-size:0.8rem;">`;
                html += desc;
        }
        html += `</div>`;
    }
    container.innerHTML = html;
}

async function browseFolderFor(inputId) {
    try {
        const res = await fetch('/api/browse-folder');
        const data = await res.json();
        if (data.path) {
            document.getElementById(inputId).value = data.path;
        }
    } catch (e) {
        console.error('Folder browse error:', e);
        showToast('⚠️ Could not open folder picker');
    }
}

function collectConfigValues(containerId) {
    const config = {};
    const container = document.getElementById(containerId);
    if (!container) return config;
    container.querySelectorAll('.config-input').forEach(el => {
        const key = el.dataset.configKey;
        if (!key) return;
        if (el.dataset.type === 'boolean') {
            config[key] = el.checked;
        } else if (el.dataset.type === 'multiselect') {
            config[key] = [...el.querySelectorAll('input[type=checkbox]:checked')].map(cb => cb.value);
        } else if (el.type === 'range' || el.type === 'number') {
            config[key] = Number(el.value);
        } else {
            config[key] = el.value;
        }
    });
    return config;
}

function switchWorkerTab(modalType, tabName) {
    const parentId = modalType === 'create' ? 'createWorkerModal' : 'instanceSettingsModal';
    const modal = document.getElementById(parentId);
    if (!modal) return;

    // Reset all buttons
    modal.querySelectorAll('.tab-btn').forEach(btn => {
        btn.classList.remove('active');
        btn.style.color = 'var(--text-secondary)';
        btn.style.borderBottom = '2px solid transparent';
        btn.style.fontWeight = '500';
    });

    // Reset all content
    modal.querySelectorAll('.tab-content').forEach(content => {
        content.style.display = 'none';
        content.classList.remove('active');
    });

    // Activate selected
    const activeBtn = modal.querySelector(`#btn-${modalType}-${tabName}`);
    const activeContent = modal.querySelector(`#tab-${modalType}-${tabName}`);

    if (activeBtn) {
        activeBtn.classList.add('active');
        activeBtn.style.color = 'var(--primary)';
        activeBtn.style.borderBottom = '2px solid var(--primary)';
        activeBtn.style.fontWeight = '600';
    }
    if (activeContent) {
        activeContent.style.display = 'block';
        activeContent.classList.add('active');
    }
}

// ─── Create Worker Modal (with per-instance settings) ───────────────────

async function openCreateWorkerModal() {
    document.getElementById('createWorkerModal').classList.add('active');
    document.getElementById('workerName').value = '';

    // Reset tabs to general
    switchWorkerTab('create', 'general');

    // Populate Agent Type dropdown from registry
    const agentTypeSelect = document.getElementById('workerAgentType');
    if (agentTypeSelect) {
        agentTypeSelect.innerHTML = registryData.map(agent =>
            `<option value="${agent.id}" ${agent.id === 'aegis-worker' ? 'selected' : ''}>${agent.icon || '🤖'} ${agent.name}</option>`
        ).join('');
    }

    document.getElementById('unifiedApiKey-create').value = '';
    document.getElementById('feedback-create-apikey').innerHTML = '';

    loadProfiles(); // Populate the load profile dropdown

    document.getElementById('workerService').value = 'anthropic';
    document.getElementById('workerIcon').value = '🤖';
    document.getElementById('workerColor').value = '#6366f1';
    document.getElementById('saveAsProfile').checked = false;

    // Trigger service updates to populate models
    onServiceChange('create');
    initEmojiGrid('emojiGrid-create', 'create');
    updateIconPreview('create');

    // Toggle form based on agent type
    onAgentTypeChange();

    // Load available skills
    await loadAvailableSkills('createSettingsSkillsList');

    // Render config schema for the selected template
    const selectedTemplate = agentTypeSelect?.value || 'aegis-worker';
    renderConfigSchema(selectedTemplate, 'createConfigSection');
}

function onAgentTypeChange() {
    const agentTypeSelect = document.getElementById('workerAgentType');
    const selectedId = agentTypeSelect?.value || 'aegis-worker';
    const template = registryData.find(a => a.id === selectedId);
    const isCliAgent = template?.cli_agent || false;

    // Update description
    const desc = document.getElementById('agentTypeDescription');
    if (desc) desc.textContent = template?.description || '';

    // Toggle form sections
    const standardFields = document.getElementById('standardWorkerFields');
    const cliFields = document.getElementById('cliAgentFields');
    if (standardFields) standardFields.style.display = isCliAgent ? 'none' : 'block';
    if (cliFields) cliFields.style.display = isCliAgent ? 'block' : 'none';

    if (isCliAgent) {
        // Update CLI key label and hint
        const keyEnvName = template.api_key_env || 'API_KEY';
        const keyLabel = document.getElementById('cliKeyLabel');
        const keyHint = document.getElementById('cliKeyHint');
        if (keyLabel) {
            if (selectedId === 'claude-code') {
                keyLabel.textContent = 'Anthropic API Key';
                if (keyHint) keyHint.textContent = 'Your Anthropic API key (sk-ant-...). Required for Claude Code.';
            } else if (selectedId === 'gemini-cli') {
                keyLabel.textContent = 'Gemini API Key';
                if (keyHint) keyHint.textContent = 'Your Gemini API key or Google Cloud key. Required for Gemini CLI.';
            } else {
                keyLabel.textContent = keyEnvName.replace(/_/g, ' ');
                if (keyHint) keyHint.textContent = `Environment variable: ${keyEnvName}`;
            }
        }

        // Set icon to match the CLI agent
        document.getElementById('workerIcon').value = template.icon || '🤖';
        updateIconPreview('create');
    }

    // Re-render config schema for the new template
    renderConfigSchema(selectedId, 'createConfigSection');

    // Hide skills tab for CLI agents (they don't use Aegis skills)
    const skillsTab = document.getElementById('btn-create-skills');
    if (skillsTab) skillsTab.style.display = isCliAgent ? 'none' : '';
}

async function createWorkerInstance() {
    const agentTypeSelect = document.getElementById('workerAgentType');
    const templateId = agentTypeSelect?.value || 'aegis-worker';
    const template = registryData.find(a => a.id === templateId);
    const isCliAgent = template?.cli_agent || false;
    const instanceName = document.getElementById('workerName').value.trim();

    let service = '';
    let model = '';
    const env_vars = {};

    if (isCliAgent) {
        // CLI agent: use the CLI-specific API key field
        const cliKey = document.getElementById('cliApiKey-create').value.trim();
        if (cliKey) {
            // Store under generic 'api_key' — engine maps it to the right env var
            env_vars['api_key'] = cliKey;
        }
        service = templateId; // e.g. 'claude-code' or 'gemini-cli'
    } else {
        // Standard worker: use the service/model selectors
        service = document.getElementById('workerService').value;
        model = document.getElementById('workerModelSelect').value;
        if (model === 'custom' || !model) {
            model = document.getElementById('workerModelCustom').value.trim();
        }
        const apiKey = document.getElementById('unifiedApiKey-create').value.trim();
        if (apiKey && SERVICE_MODELS[service]) {
            env_vars[SERVICE_MODELS[service].key_env] = apiKey;
        }
    }

    if (!templateId) { showToast('Select an agent type'); return; }
    if (!instanceName) { showToast('Enter a worker name'); return; }

    // Gather config schema values
    const config = collectConfigValues('createConfigSection');

    // Gather skills (only for standard workers)
    if (!isCliAgent) {
        const skillsBoxes = document.querySelectorAll('#createSettingsSkillsList input[type="checkbox"]:checked');
        config.skills = Array.from(skillsBoxes).map(cb => cb.value);
    }

    const icon = document.getElementById('workerIcon').value || (template?.icon || '🤖');
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
        await fetch('/api/profiles', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                name: instanceName,
                template_id: templateId,
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

    // Default to general tab
    switchWorkerTab('edit', 'general');

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

    // Load available skills
    await loadAvailableSkills('instSettingsSkillsList', inst.config?.skills || []);

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

    // Gather skills
    const skillsBoxes = document.querySelectorAll('#instSettingsSkillsList input[type="checkbox"]:checked');
    config.skills = Array.from(skillsBoxes).map(cb => cb.value);

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

// ─── Skills & Marketplace ───────────────────────────────────────────────

async function loadAvailableSkills(containerId, selectedSkills = []) {
    const container = document.getElementById(containerId);
    if (!container) return;
    try {
        const res = await fetch('/api/tools');
        const tools = await res.json();
        if (!tools || tools.length === 0) {
            container.innerHTML = '<div style="font-size:0.8rem; color:var(--text-secondary); padding:1rem; text-align:center;">No skills installed yet.</div>';
            return;
        }

        // Add a search bar to the skills list
        const searchInputHtml = `
            <div style="margin-bottom: 0.75rem; position: relative;">
                <input type="text" class="skills-search-input" placeholder="Search equipped skills..." style="width: 100%; padding: 0.5rem 0.5rem 0.5rem 2rem; border-radius: 6px; border: 1px solid var(--border-color); background: var(--bg-card); color: var(--text-primary); font-size: 0.85rem;" onkeyup="filterEquippedSkills(this, '${containerId}-grid')">
                <span style="position: absolute; left: 0.6rem; top: 50%; transform: translateY(-50%); color: var(--text-secondary); font-size: 0.9rem;">🔍</span>
            </div>
        `;

        const skillsGridHtml = tools.map(t => {
            const isChecked = selectedSkills.includes(t.name);
            return `
            <label class="skill-card ${isChecked ? 'selected' : ''}" style="display: flex; flex-direction: column; gap: 0.35rem; padding: 0.75rem; border-radius: 8px; border: 1px solid ${isChecked ? 'var(--primary)' : 'var(--border-color)'}; background: ${isChecked ? 'rgba(99, 102, 241, 0.05)' : 'var(--bg-card)'}; cursor: pointer; transition: all 0.2s ease; position: relative; overflow: hidden;" data-skill-name="${t.name.toLowerCase()}" data-skill-desc="${t.description.toLowerCase()}">
                <div style="display: flex; justify-content: space-between; align-items: flex-start;">
                    <div style="font-weight: 600; color: ${isChecked ? 'var(--primary)' : 'var(--text-primary)'}; font-size: 0.9rem; display: flex; align-items: center; gap: 0.4rem;">
                        <span style="font-size: 1.1rem;">${getSkillIcon(t.name)}</span>
                        ${t.name}
                        ${t.is_core ? '<span style="font-size: 0.55rem; background: var(--primary); color: white; padding: 1px 4px; border-radius: 4px; font-weight: 700; letter-spacing: 0.05em;">CORE</span>' : ''}
                    </div>
                    <input type="checkbox" value="${t.name}" ${isChecked ? 'checked' : ''} style="accent-color: var(--primary); width: 16px; height: 16px; cursor: pointer;" onchange="this.closest('.skill-card').classList.toggle('selected', this.checked); this.closest('.skill-card').style.borderColor = this.checked ? 'var(--primary)' : 'var(--border-color)'; this.closest('.skill-card').style.background = this.checked ? 'rgba(99, 102, 241, 0.05)' : 'var(--bg-card)';">
                </div>
                <div style="font-size: 0.75rem; color: var(--text-secondary); line-height: 1.3; overflow: hidden; text-overflow: ellipsis; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical;">${t.description}</div>
                ${isChecked ? '<div style="position: absolute; top: 0; left: 0; width: 4px; height: 100%; background: var(--primary);"></div>' : ''}
            </label>`;
        }).join('');

        container.style.padding = "0.75rem";
        container.style.border = "none";
        container.style.background = "transparent";
        container.innerHTML = searchInputHtml + `<div id="${containerId}-grid" class="skills-grid" style="display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap: 0.75rem; max-height: 250px; overflow-y: auto; padding-right: 0.25rem;">${skillsGridHtml}</div>`;
    } catch (e) {
        container.innerHTML = '<div style="font-size:0.8rem; color:var(--danger); padding:1rem;">Failed to load skills</div>';
    }
}

function filterEquippedSkills(inputEl, gridId) {
    const q = inputEl.value.toLowerCase();
    const grid = document.getElementById(gridId);
    if (!grid) return;
    const cards = grid.querySelectorAll('.skill-card');
    cards.forEach(card => {
        const name = card.getAttribute('data-skill-name') || '';
        const desc = card.getAttribute('data-skill-desc') || '';
        if (name.includes(q) || desc.includes(q)) {
            card.style.display = 'flex';
        } else {
            card.style.display = 'none';
        }
    });
}

// Temporary helper for nicer icons depending on text
function getSkillIcon(name) {
    const lower = name.toLowerCase();
    if (lower.includes('scrape') || lower.includes('web')) return '🕸️';
    if (lower.includes('os') || lower.includes('system') || lower.includes('mulch')) return '💻';
    if (lower.includes('security') || lower.includes('audit')) return '🛡️';
    if (lower.includes('devops') || lower.includes('ci')) return '🚀';
    if (lower.includes('search')) return '🔍';
    if (lower.includes('url')) return '🌐';
    if (lower.includes('shell')) return '🐚';
    return '🛠️';
}

let marketplaceSkills = [];
let marketplaceCursor = null;
let installedSkillsSet = new Set();
let installedSkillsFull = [];

async function openSkillsMarketplaceModal() {
    document.getElementById('skillsMarketplaceModal').classList.add('active');
    const listEl = document.getElementById('marketplaceList');
    listEl.innerHTML = '<div class="loading-spinner">Loading curated skills...</div>';

    try {
        // Fetch installed skills to know which button to show and populate "Installed" filter
        const toolsRes = await fetch('/api/tools');
        const tools = await toolsRes.json();
        installedSkillsSet = new Set();
        installedSkillsFull = [];

        tools.forEach(t => {
            if (!t.is_core) {
                const s_id = t.id || t.name;
                installedSkillsSet.add(s_id.toLowerCase());
                installedSkillsSet.add(t.name.toLowerCase());
                installedSkillsFull.push({
                    id: s_id,
                    name: t.name,
                    description: t.description,
                    github_url: `https://clawhub.ai/api/v1/download?slug=${s_id}`,
                    stats: { downloads: 0, stars: 0 },
                    tags: { latest: 'installed' }
                });
            }
        });

        // Fetch first page
        const res = await fetch('/api/skills/marketplace');
        const data = await res.json();
        marketplaceSkills = data.items || [];
        marketplaceCursor = data.nextCursor || null;
        renderMarketplaceSkills();
    } catch (e) {
        listEl.innerHTML = '<div style="color:var(--danger); padding:1rem;">Failed to load marketplace</div>';
    }
}

async function loadMoreMarketplaceSkills() {
    if (!marketplaceCursor) return;
    const loadBtn = document.getElementById('btn-load-more-skills');
    if (loadBtn) loadBtn.innerText = 'Loading...';

    try {
        const res = await fetch(`/api/skills/marketplace?cursor=${encodeURIComponent(marketplaceCursor)}`);
        const data = await res.json();
        marketplaceSkills = marketplaceSkills.concat(data.items || []);
        marketplaceCursor = data.nextCursor || null;
        renderMarketplaceSkills();
    } catch (e) {
        if (loadBtn) loadBtn.innerText = 'Failed to load more. Try again.';
    }
}

let searchDebounceTimeout = null;

function debounceSearchMarketplaceSkills() {
    clearTimeout(searchDebounceTimeout);
    searchDebounceTimeout = setTimeout(() => {
        performMarketplaceSearch();
    }, 400);
}

async function performMarketplaceSearch() {
    const q = (document.getElementById('marketplaceSearch').value || '').trim();
    const listEl = document.getElementById('marketplaceList');
    listEl.innerHTML = '<div class="loading-spinner">Searching skills...</div>';

    try {
        let url = '/api/skills/marketplace';
        if (q) {
            url += `?q=${encodeURIComponent(q)}`;
        }

        const res = await fetch(url);
        const data = await res.json();

        // Reset full state with the new search results
        marketplaceSkills = data.items || [];
        marketplaceCursor = data.nextCursor || null;

        renderMarketplaceSkills();
    } catch (e) {
        listEl.innerHTML = '<div style="color:var(--danger); padding:1rem; grid-column: 1 / -1; text-align: center;">Search failed. Try again.</div>';
    }
}

function renderMarketplaceSkills() {
    const q = (document.getElementById('marketplaceSearch').value || '').toLowerCase();
    const filter = document.getElementById('marketplaceFilter')?.value || 'all';
    const sort = document.getElementById('marketplaceSort')?.value || 'name';
    const listEl = document.getElementById('marketplaceList');

    let sourceSkills = marketplaceSkills;
    if (filter === 'installed') {
        sourceSkills = installedSkillsFull;
    }

    let filtered = sourceSkills.filter(s => {
        // If we are looking at Installed skills but we typed a search query, we must filter locally.
        if (filter === 'installed' && q) {
            const matchesQ = s.name.toLowerCase().includes(q) || (s.description && s.description.toLowerCase().includes(q));
            if (!matchesQ) return false;
        }

        const isInstalled = installedSkillsSet.has(s.name.toLowerCase()) || installedSkillsSet.has(s.id.toLowerCase());

        if (filter === 'installed' && !isInstalled) return false;
        if (filter === 'not_installed' && isInstalled) return false;
        return true;
    });

    // Sort logic (only if not actively searching, to preserve relevance)
    if (!q) {
        if (sort === 'name') {
            filtered.sort((a, b) => a.name.localeCompare(b.name));
        } else if (sort === 'recent') {
            filtered.sort((a, b) => b.id.localeCompare(a.id));
        } else if (sort === 'downloads') {
            filtered.sort((a, b) => (b.stats?.downloads || 0) - (a.stats?.downloads || 0));
        }
    }

    if (filtered.length === 0) {
        listEl.innerHTML = '<div style="color:var(--text-secondary); padding:2rem; text-align:center; grid-column: 1 / -1;">No matching skills found. Try tweaking your search.</div>';
        return;
    }

    // Add grid styling to the container. Erase flex direction.
    listEl.style.flexDirection = '';
    listEl.style.display = 'grid';
    listEl.style.gridTemplateColumns = 'repeat(auto-fill, minmax(260px, 1fr))';
    listEl.style.gap = '1rem';
    listEl.style.padding = '0.5rem';

    let htmlParts = filtered.map(s => {
        return `
            <div class="marketplace-skill-card" style="background:var(--bg-column); border:1px solid var(--border-color); border-radius:12px; padding:1.25rem; display:flex; flex-direction:column; gap:0.75rem; transition: all 0.2s ease; position:relative; overflow:hidden; min-height:180px; height:auto; cursor: pointer;" onclick="this.classList.toggle('expanded')">
                <!-- Decorative background glow -->
                <div style="position:absolute; top:-20px; right:-20px; width:100px; height:100px; background:var(--primary); opacity:0.05; filter:blur(40px); border-radius:50%; pointer-events:none;"></div>

                <div style="display:flex; justify-content:space-between; align-items:flex-start; margin-bottom: 0.25rem;">
                    <div style="flex: 1; padding-right: 0.5rem;">
                        <div style="display:flex; align-items:center; gap:0.5rem; margin-bottom: 0.25rem;">
                            <span style="font-size: 1.25rem;">${getSkillIcon(s.name)}</span>
                            <div style="font-weight:600; color:var(--text-primary); font-size:1.05rem; letter-spacing:-0.01em;">${s.name}</div>
                        </div>
                        <div style="font-size:0.75rem; color:var(--text-muted); font-family:var(--font-mono, monospace); line-height: 1;">v${s.tags?.latest || '1.0.0'} • ${s.id}</div>
                    </div>
                </div>

                <div class="skill-desc" style="font-size:0.85rem; color:var(--text-secondary); line-height:1.5; flex-grow: 1; display:-webkit-box; -webkit-line-clamp:4; line-clamp:4; -webkit-box-orient:vertical; overflow:hidden;">${s.description}</div>

                <div style="margin-top:auto; padding-top:1rem; border-top:1px solid rgba(255,255,255,0.05); display:flex; justify-content:space-between; align-items:center;">
                    <div style="display:flex; gap: 0.5rem; font-size: 0.75rem; color: var(--text-muted);">
                        <span title="Downloads">⬇️ ${s.stats?.downloads || 0}</span>
                        <span title="Stars">⭐ ${s.stats?.stars || 0}</span>
                    </div>
                    ${installedSkillsSet.has(s.name.toLowerCase()) || installedSkillsSet.has(s.id.toLowerCase())
                ? `<button class="danger" id="btn-uninstall-${s.id}" onclick="event.stopPropagation(); uninstallMarketplaceSkill('${s.id}', '${s.name}')" style="font-size:0.8rem; padding:0.4rem 0.8rem; border-radius:6px; font-weight:500; z-index:2; position:relative; background: var(--danger);">Uninstall</button>`
                : `<button id="btn-install-${s.id}" onclick="event.stopPropagation(); installSkill('${s.github_url}', '${s.id}')" style="font-size:0.8rem; padding:0.4rem 0.8rem; border-radius:6px; font-weight:500; z-index:2; position:relative;">Install Skill</button>`
            }
                </div>
            </div>
        `;
    });

    // Add "Load More" if pagination cursor exists
    if (marketplaceCursor) {
        htmlParts.push(`
            <div style="grid-column: 1 / -1; display:flex; justify-content:center; padding: 1rem;">
                <button id="btn-load-more-skills" onclick="loadMoreMarketplaceSkills()" style="background:var(--bg-card); color:var(--text-primary); border:1px solid var(--border-color); padding:0.75rem 2rem; border-radius:8px; cursor:pointer;" onmouseover="this.style.background='var(--bg-hover)'" onmouseout="this.style.background='var(--bg-card)'">Load More Skills</button>
            </div>
        `);
    }

    listEl.innerHTML = htmlParts.join('');
}

async function installSkill(githubUrl, skillId) {
    const btn = document.getElementById(`btn-install-${skillId}`);
    if (btn) {
        btn.disabled = true;
        btn.textContent = 'Installing...';
    }

    try {
        const res = await fetch('/api/skills/install', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ github_url: githubUrl })
        });
        const d = await res.json();

        if (res.ok) {
            if (d.status === 'already_installed') {
                showToast(`Skill ${skillId} is already installed`);
            } else {
                showToast(`✅ Successfully installed ${skillId}`);
                installedSkillsSet.add(skillId.toLowerCase());
                // Refresh full installed skills array
                fetch('/api/tools').then(r => r.json()).then(tools => {
                    installedSkillsFull = [];
                    tools.forEach(t => {
                        if (!t.is_core) {
                            installedSkillsFull.push({
                                id: t.id || t.name,
                                name: t.name,
                                description: t.description,
                                github_url: `https://clawhub.ai/api/v1/download?slug=${t.id || t.name}`,
                                stats: { downloads: 0, stars: 0 },
                                tags: { latest: 'installed' }
                            });
                        }
                    });
                    renderMarketplaceSkills();
                });
            }
            if (btn) {
                btn.textContent = 'Installed';
                btn.style.background = 'var(--success)';
            }
        } else {
            showToast(`⚠️ Install failed: ${d.detail || 'Unknown error'}`);
            if (btn) {
                btn.disabled = false;
                btn.textContent = 'Retry Install';
            }
        }
    } catch (e) {
        showToast('⚠️ Install failed');
        if (btn) {
            btn.disabled = false;
            btn.textContent = 'Retry Install';
        }
    }
}

async function uninstallMarketplaceSkill(skillId, skillName) {
    const btn = document.getElementById(`btn-uninstall-${skillId}`);
    if (btn) {
        btn.disabled = true;
        btn.textContent = 'Uninstalling...';
    }

    try {
        const res = await fetch(`/api/skills/uninstall/${skillId}`, { method: 'DELETE' });
        const d = await res.json();

        if (res.ok) {
            showToast(`✅ Successfully uninstalled ${skillName}`);
            installedSkillsSet.delete(skillName.toLowerCase());
            installedSkillsSet.delete(skillId.toLowerCase());
            installedSkillsFull = installedSkillsFull.filter(s => s.id.toLowerCase() !== skillId.toLowerCase());
            renderMarketplaceSkills();

            // Optionally, refresh available skills if the worker settings modal happens to be active behind this one
            if (document.getElementById('workerSettingsModal')?.classList.contains('active')) {
                loadAvailableSkills('workerSkillsList', getCheckedSkills('workerSkillsList'));
            }
        } else {
            showToast(`⚠️ Uninstall failed: ${d.detail || 'Unknown error'}`);
            if (btn) {
                btn.disabled = false;
                btn.textContent = 'Retry Uninstall';
            }
        }
    } catch (e) {
        showToast('⚠️ Uninstall failed');
        if (btn) {
            btn.disabled = false;
            btn.textContent = 'Retry Uninstall';
        }
    }
}

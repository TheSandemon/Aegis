/* ═══════════════════════════════════════════════════════════════════════════════
   Aegis Integrations Dashboard Module
   - Saved Connections management (multi-connection)
   - Active Column Integrations display
   ═══════════════════════════════════════════════════════════════════════════════ */

const INTEGRATION_TYPE_LABELS = {
    github: { icon: '🐙', name: 'GitHub Issues' },
    jira: { icon: '🔵', name: 'Jira' },
    linear: { icon: '🟣', name: 'Linear' },
    firestore: { icon: '🔥', name: 'Firebase Firestore' },
};

const INTEGRATION_MODE_LABELS = {
    read: 'Read only',
    write: 'Write only',
    read_write: 'Read + Write',
};

// ─── Cached connections (loaded on view open) ────────────────────────────────────

window._savedConnections = [];

// ─── Integrations View Entry Point ───────────────────────────────────────────────

async function loadIntegrations() {
    loadSavedConnections();
    try {
        const res = await fetch('/api/integrations');
        if (!res.ok) throw new Error('Server error');
        const integrations = await res.json();
        renderIntegrations(integrations);
    } catch (e) {
        const el = document.getElementById('integrationsList');
        if (el) el.innerHTML = '<div class="empty-state"><div class="empty-state-icon">⚠️</div><div class="empty-state-text">Failed to load integrations.</div></div>';
    }
}

// ─── GitHub Device Flow ──────────────────────────────────────────────────────────

let isPollingDeviceFlow = false;
let deviceFlowIntervalId = null;

async function startGithubDeviceFlow() {
    const loginBtn = document.getElementById('primaryLoginBtn');
    loginBtn.disabled = true;
    loginBtn.innerHTML = 'Requesting code... <span class="loader" style="width:12px;height:12px;border-width:2px;margin-left:8px;display:inline-block;border-radius:50%;border-top-color:transparent;animation:spin 1s linear infinite;"></span>';

    try {
        const res = await fetch('/api/github/device/start', { method: 'POST' });
        if (!res.ok) throw new Error('Failed to start login flow');

        const data = await res.json();

        // Hide login button, show device flow UI
        loginBtn.style.display = 'none';

        const dfSection = document.getElementById('deviceFlowSection');
        dfSection.style.display = 'block';

        document.getElementById('deviceUserCode').textContent = data.user_code;

        // Configure the copy & open button
        const actionBtn = document.getElementById('deviceActionBtn');
        actionBtn.onclick = () => {
            navigator.clipboard.writeText(data.user_code);
            window.open(data.verification_uri, '_blank');
            actionBtn.innerHTML = '✓ Copied & Opened';
            setTimeout(() => { actionBtn.innerHTML = 'Copy Code & Open GitHub'; }, 3000);
        };

        // Start polling
        startPollingDeviceFlow(data.device_code, data.interval || 5);

    } catch (e) {
        showToast(e.message);
        loginBtn.disabled = false;
        loginBtn.innerHTML = `<svg height="20" aria-hidden="true" viewBox="0 0 16 16" version="1.1" width="20" data-view-component="true" style="fill:currentColor;"><path d="M8 0c4.42 0 8 3.58 8 8a8.013 8.013 0 0 1-5.45 7.59c-.4.08-.55-.17-.55-.38 0-.27.01-1.13.01-2.2 0-.75-.25-1.23-.54-1.48 1.78-.2 3.65-.88 3.65-3.95 0-.88-.31-1.59-.82-2.15.08-.2.36-1.02-.08-2.12 0 0-.67-.22-2.2.82-.64-.18-1.32-.27-2-.27-.68 0-1.36.09-2 .27-1.53-1.03-2.2-.82-2.2-.82-.44 1.1-.16 1.92-.08 2.12-.51.56-.82 1.28-.82 2.15 0 3.06 1.86 3.75 3.64 3.95-.23.2-.44.55-.51 1.07-.46.21-1.61.55-2.33-.66-.15-.24-.6-.83-1.23-.82-.67.01-.27.38.01.53.34.19.73.9.82 1.13.16.45.68 1.31 2.69.94 0 .67.01 1.3.01 1.49 0 .21-.15.45-.55.38A7.995 7.995 0 0 1 0 8c0-4.42 3.58-8 8-8Z"></path></svg> Log in with GitHub`;
    }
}

function startPollingDeviceFlow(deviceCode, intervalSecs) {
    isPollingDeviceFlow = true;
    let currentInterval = intervalSecs * 1000;

    const poll = async () => {
        if (!isPollingDeviceFlow) return;

        try {
            const res = await fetch('/api/github/device/poll', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ device_code: deviceCode })
            });

            const data = await res.json();

            if (data.status === 'success') {
                stopPollingDeviceFlow();
                showToast('GitHub connected successfully!');
                await loadSavedConnections();
                toggleAddConnectionForm();
            } else if (data.status === 'slow_down') {
                currentInterval = (data.interval || 5) * 1000;
                scheduleNext();
            } else if (data.status === 'pending') {
                scheduleNext();
            } else if (data.status === 'expired') {
                stopPollingDeviceFlow();
                document.getElementById('deviceFlowStatus').innerHTML = '<span style="color:#ef4444;">Code expired. Please try again.</span>';
            } else {
                stopPollingDeviceFlow();
                document.getElementById('deviceFlowStatus').innerHTML = `<span style="color:#ef4444;">Error: ${data.message}</span>`;
            }
        } catch (e) {
            scheduleNext(); // Network errors, just keep trying
        }
    };

    const scheduleNext = () => {
        if (isPollingDeviceFlow) {
            deviceFlowIntervalId = setTimeout(poll, currentInterval);
        }
    };

    scheduleNext();
}

function stopPollingDeviceFlow() {
    isPollingDeviceFlow = false;
    if (deviceFlowIntervalId) {
        clearTimeout(deviceFlowIntervalId);
        deviceFlowIntervalId = null;
    }
}

// ─── Saved Connections ───────────────────────────────────────────────────────────

async function loadSavedConnections() {
    try {
        const res = await fetch('/api/connections');
        if (!res.ok) return;
        window._savedConnections = await res.json();
        renderConnectionsList();
    } catch (e) {
        console.error('Failed to load connections:', e);
    }
}

function renderConnectionsList() {
    const el = document.getElementById('connectionsList');
    if (!el) return;
    const conns = window._savedConnections;

    if (!conns || conns.length === 0) {
        el.innerHTML = '<div style="font-size:0.8rem;color:var(--text-secondary);padding:0.5rem 0;">No connections yet. Click "Add Integration" to get started.</div>';
        return;
    }

    el.innerHTML = conns.map(c => {
        const typeInfo = INTEGRATION_TYPE_LABELS[c.type] || { icon: '🔗', name: c.type };
        const user = c.user_info || {};
        const avatarHtml = user.avatar_url
            ? `<img src="${user.avatar_url}" alt="" style="width:28px;height:28px;border-radius:50%;border:1.5px solid var(--accent);">`
            : `<div style="width:28px;height:28px;border-radius:50%;background:var(--accent);display:flex;align-items:center;justify-content:center;font-size:0.8rem;">${typeInfo.icon}</div>`;

        return `
        <div style="display:flex;align-items:center;gap:0.6rem;padding:0.5rem 0;border-bottom:1px solid var(--border);">
            ${avatarHtml}
            <div style="flex:1;min-width:0;">
                <div style="font-weight:600;font-size:0.85rem;">${escapeHtml(c.name)}</div>
                <div style="font-size:0.72rem;color:var(--text-secondary);">
                    ${typeInfo.icon} ${typeInfo.name}${user.login ? ` · @${user.login}` : ''}
                </div>
            </div>
            <span style="font-size:0.68rem;color:#22c55e;background:#22c55e18;padding:0.1rem 0.4rem;border-radius:4px;">Active</span>
            <button class="danger" onclick="deleteConnection('${c.id}')" style="font-size:0.68rem;padding:0.15rem 0.4rem;" title="Remove">✕</button>
        </div>`;
    }).join('');
}

function toggleAddConnectionForm() {
    const form = document.getElementById('addConnectionForm');
    if (!form) return;
    const isVisible = form.style.display !== 'none';
    form.style.display = isVisible ? 'none' : 'block';
    if (!isVisible) {
        // Reset form
        const nameEl = document.getElementById('newConnName');
        const tokenEl = document.getElementById('newConnToken');
        const validEl = document.getElementById('newConnValidation');
        if (nameEl) nameEl.value = '';
        if (tokenEl) tokenEl.value = '';
        if (validEl) { validEl.style.display = 'none'; validEl.innerHTML = ''; }
    }
}

async function addNewConnection() {
    const type = document.getElementById('newConnType')?.value || 'github';
    const name = document.getElementById('newConnName')?.value.trim();
    const token = document.getElementById('newConnToken')?.value.trim();
    const validEl = document.getElementById('newConnValidation');
    const saveBtn = document.getElementById('addConnSaveBtn');

    if (!name) { _showConnValidation('⚠️ Please enter a connection name', 'warning'); return; }
    if (!token) { _showConnValidation('⚠️ Please enter a token', 'warning'); return; }

    // Show validating state
    _showConnValidation('⏳ Validating token...', 'info');
    if (saveBtn) saveBtn.disabled = true;

    try {
        const res = await fetch('/api/connections', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ type, name, token }),
        });

        if (!res.ok) {
            const err = await res.json().catch(() => null);
            _showConnValidation(`❌ ${err?.detail || 'Validation failed'}`, 'error');
            return;
        }

        const data = await res.json();
        _showConnValidation(`✅ Connected as @${data.user_info?.login || 'unknown'}`, 'success');

        // Refresh connections list
        await loadSavedConnections();

        // Auto-close form after brief delay
        setTimeout(() => {
            toggleAddConnectionForm();
        }, 1000);

        showToast(`✅ Connection "${name}" added`);
    } catch (e) {
        _showConnValidation('❌ Connection failed — check your network', 'error');
    } finally {
        if (saveBtn) saveBtn.disabled = false;
    }
}

function _showConnValidation(message, level) {
    const el = document.getElementById('newConnValidation');
    if (!el) return;
    el.style.display = 'block';
    const colors = {
        info: { bg: 'var(--bg-card)', color: 'var(--text-secondary)', border: 'var(--border)' },
        warning: { bg: '#f59e0b18', color: '#f59e0b', border: '#f59e0b44' },
        error: { bg: '#ef444418', color: '#fca5a5', border: '#ef444444' },
        success: { bg: '#22c55e18', color: '#22c55e', border: '#22c55e44' },
    };
    const c = colors[level] || colors.info;
    el.style.background = c.bg;
    el.style.color = c.color;
    el.style.border = `1px solid ${c.border}`;
    el.textContent = message;
}

async function deleteConnection(connId) {
    if (!confirm('Remove this connection? Columns using it will keep their current config.')) return;
    try {
        await fetch(`/api/connections/${connId}`, { method: 'DELETE' });
        await loadSavedConnections();
        showToast('Connection removed');
    } catch (e) {
        showToast('Failed to remove connection');
    }
}


// ─── Active Column Integrations ──────────────────────────────────────────────────

function renderIntegrations(integrations) {
    const el = document.getElementById('integrationsList');
    if (!el) return;

    if (!integrations || integrations.length === 0) {
        el.innerHTML = `
            <div class="empty-state">
                <div class="empty-state-icon">🔗</div>
                <div class="empty-state-text">No integrations configured yet.<br>
                Create a column and toggle "Link to External Service" to connect GitHub Issues, Jira, Linear, or Firebase Firestore.</div>
            </div>`;
        return;
    }

    el.innerHTML = integrations.map(intg => {
        const typeInfo = INTEGRATION_TYPE_LABELS[intg.type] || { icon: '🔗', name: intg.type };
        const modeLabel = INTEGRATION_MODE_LABELS[intg.mode] || intg.mode;
        const syncTime = intg.last_synced_at
            ? _formatRelativeTime(intg.last_synced_at)
            : 'Never';
        const statusColor = intg.status === 'error' ? '#ef4444' : intg.status === 'active' ? '#22c55e' : '#94a3b8';
        const pollBadge = intg.poll_active
            ? '<span style="font-size:0.7rem;background:var(--accent);color:#fff;border-radius:9999px;padding:0.1rem 0.4rem;">polling</span>'
            : '';

        return `
        <div style="background:var(--bg-card);border:1px solid var(--border);border-radius:0.5rem;padding:1rem;margin-bottom:0.75rem;">
            <div style="display:flex;justify-content:space-between;align-items:flex-start;flex-wrap:wrap;gap:0.5rem;">
                <div>
                    <span style="font-size:1rem;">${typeInfo.icon}</span>
                    <strong style="margin-left:0.25rem;">${escapeHtml(intg.column_name)}</strong>
                    <span style="color:var(--text-secondary);font-size:0.8rem;margin-left:0.5rem;">
                        ${typeInfo.name} · ${modeLabel}
                    </span>
                    ${pollBadge}
                </div>
                <div style="display:flex;gap:0.5rem;align-items:center;flex-wrap:wrap;">
                    <span style="font-size:0.75rem;color:var(--text-secondary);">Last sync: ${syncTime}</span>
                    <span style="font-size:0.75rem;font-weight:600;color:${statusColor};">${intg.status || 'active'}</span>
                    <button
                        onclick="forceSyncIntegration(${intg.column_id})"
                        style="font-size:0.75rem;padding:0.25rem 0.6rem;border-radius:0.25rem;cursor:pointer;">
                        ↻ Sync Now
                    </button>
                </div>
            </div>
            ${intg.error ? `<div style="margin-top:0.5rem;padding:0.4rem 0.6rem;background:#ef444418;border:1px solid #ef444444;border-radius:0.3rem;font-size:0.75rem;color:#fca5a5;">⚠️ ${escapeHtml(intg.error)}</div>` : ''}
            <div style="margin-top:0.5rem;font-size:0.75rem;color:var(--text-secondary);">
                Webhook endpoint: <code style="background:var(--bg-input,#1e293b);padding:0.1rem 0.3rem;border-radius:0.2rem;">/api/webhooks/${intg.column_id}</code>
            </div>
        </div>`;
    }).join('');
}

async function forceSyncIntegration(columnId) {
    showToast('Syncing...');
    try {
        const res = await fetch(`/api/integrations/${columnId}/sync`, { method: 'POST' });
        const data = await res.json();
        showToast(`Synced ${data.synced || 0} item(s)`);
        if (typeof loadCards === 'function') {
            await loadCards();
            if (typeof renderBoard === 'function') renderBoard();
        }
        await loadIntegrations();
    } catch (e) {
        showToast('Sync failed');
    }
}


// ─── GitHub Repo Picker (used in column config) ─────────────────────────────────

async function _renderGitHubRepoPicker(container, connId, currentRepo, isEdit) {
    const prefix = isEdit ? 'edit_' : '';
    container.innerHTML = `
        <div class="form-group">
            <label>Repository (e.g. owner/repo)</label>
            <input type="text" id="${prefix}gh_repo_picker" list="${prefix}gh_repo_datalist" placeholder="Search or type owner/repo..." style="width:100%;" value="${currentRepo || ''}">
            <datalist id="${prefix}gh_repo_datalist"></datalist>
        </div>
        <div class="form-group">
            <label>Label filter (comma-separated, optional)</label>
            <input type="text" id="${prefix}gh_labels" placeholder="e.g. bug,feature">
        </div>
        <div class="form-group">
            <label>Issue state</label>
            <select id="${prefix}gh_state">
                <option value="open" selected>open</option>
                <option value="closed">closed</option>
                <option value="all">all</option>
            </select>
        </div>
        <div id="${prefix}gh_permissions" style="font-size:0.72rem;color:var(--text-secondary);margin-top:0.25rem;"></div>
    `;

    const checkPerms = async () => {
        const input = document.getElementById(`${prefix}gh_repo_picker`);
        const permEl = document.getElementById(`${prefix}gh_permissions`);
        if (!input || !permEl) return;
        const fullName = input.value.trim();
        if (!fullName || !fullName.includes('/')) { permEl.innerHTML = ''; return; }

        permEl.innerHTML = '<span style="color:var(--text-secondary);">Checking permissions...</span>';
        try {
            const [owner, repo] = fullName.split('/');
            const pRes = await fetch(`/api/connections/${connId}/repos/${owner}/${repo}/permissions`);
            if (!pRes.ok) throw new Error('');
            const data = await pRes.json();
            const p = data.permissions;
            permEl.innerHTML = [
                p.can_read_issues ? '✅ Issues' : '❌ Issues',
                p.can_write_issues ? '✅ Write' : '❌ Write',
                p.can_read_prs ? '✅ PRs' : '❌ PRs',
                p.can_manage_webhooks ? '✅ Webhooks' : '❌ Webhooks',
            ].map(s => `<span style="margin-right:0.5rem;">${s}</span>`).join('');
        } catch (e) {
            permEl.innerHTML = '<span style="color:#ef4444;">Could not check permissions (or repo not found)</span>';
        }
    };

    // Attach listener
    setTimeout(() => {
        const input = document.getElementById(`${prefix}gh_repo_picker`);
        if (input) {
            input.addEventListener('change', checkPerms);
            if (input.value) checkPerms();
        }
    }, 0);

    try {
        const res = await fetch(`/api/connections/${connId}/repos`);
        if (!res.ok) throw new Error('Failed to fetch repos');
        const repos = await res.json();
        const datalist = document.getElementById(`${prefix}gh_repo_datalist`);
        if (!datalist) return;

        datalist.innerHTML = repos.map(r => {
            return `<option value="${r.full_name}">${r.private ? '🔒' : '🌐'} ${r.full_name}</option>`;
        }).join('');


        // Show permissions on selection is handled by checkPerms listener above.

        // Trigger change event if there's a current repo
        if (currentRepo) {
            const input = document.getElementById(`${prefix}gh_repo_picker`);
            if (input) {
                input.value = currentRepo;
                checkPerms();
            }
        }
    } catch (e) {
        const input = document.getElementById(`${prefix}gh_repo_picker`);
        if (input) input.placeholder = 'Type owner/repo... (failed to load list)';
    }
}


// ─── Utilities ───────────────────────────────────────────────────────────────────

function _formatRelativeTime(isoString) {
    try {
        const diff = Date.now() - new Date(isoString).getTime();
        const mins = Math.floor(diff / 60000);
        if (mins < 1) return 'just now';
        if (mins < 60) return `${mins}m ago`;
        const hrs = Math.floor(mins / 60);
        if (hrs < 24) return `${hrs}h ago`;
        return `${Math.floor(hrs / 24)}d ago`;
    } catch {
        return '—';
    }
}

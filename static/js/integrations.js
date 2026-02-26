/* Aegis Integrations Dashboard Module */

const INTEGRATION_TYPE_LABELS = {
    github:    { icon: '🐙', name: 'GitHub Issues' },
    jira:      { icon: '🔵', name: 'Jira' },
    linear:    { icon: '🟣', name: 'Linear' },
    firestore: { icon: '🔥', name: 'Firebase Firestore' },
};

const INTEGRATION_MODE_LABELS = {
    read:       'Read only',
    write:      'Write only',
    read_write: 'Read + Write',
};

async function loadIntegrations() {
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
        // Refresh card list and integrations panel
        if (typeof loadCards === 'function') {
            await loadCards();
            if (typeof renderBoard === 'function') renderBoard();
        }
        await loadIntegrations();
    } catch (e) {
        showToast('Sync failed');
    }
}

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

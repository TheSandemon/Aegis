/* Aegis Telemetry Dashboard Module */

let telemetryData = null;

async function loadTelemetry() {
    try {
        const res = await fetch('/api/telemetry');
        telemetryData = await res.json();
        renderTelemetry(telemetryData);
    } catch (e) {
        console.error('Telemetry load error:', e);
        document.getElementById('telemetryView').innerHTML = '<div class="empty-state"><div class="empty-state-icon">📊</div><div class="empty-state-text">Failed to load telemetry data</div></div>';
    }
}

function renderTelemetry(data) {
    const broker = data.broker || {};
    const agents = data.agents || [];
    const view = document.getElementById('telemetryContent');
    if (!view) return;

    const totalTokens = broker.estimated_tokens || 0;
    const costEst = (totalTokens / 1000 * 0.003).toFixed(4);

    view.innerHTML = `
        <div class="telemetry-stats">
            <div class="stat-card"><div class="stat-label">Prompts Submitted</div><div class="stat-value">${broker.submitted || 0}</div><div class="stat-sublabel">Total requests to LLM</div></div>
            <div class="stat-card"><div class="stat-label">Prompts Processed</div><div class="stat-value">${broker.processed || 0}</div><div class="stat-sublabel">Successfully completed</div></div>
            <div class="stat-card"><div class="stat-label">Failed / Retried</div><div class="stat-value">${broker.failed || 0} / ${broker.retried || 0}</div><div class="stat-sublabel">Errors and retries</div></div>
            <div class="stat-card"><div class="stat-label">Est. Tokens Used</div><div class="stat-value">${formatNumber(totalTokens)}</div><div class="stat-sublabel">≈ $${costEst} estimated cost</div></div>
            <div class="stat-card"><div class="stat-label">Queue Depth</div><div class="stat-value">${broker.queue_depth || 0}</div><div class="stat-sublabel">Pending in queue</div></div>
            <div class="stat-card"><div class="stat-label">Dead Letters</div><div class="stat-value">${broker.dead_letters || 0}</div><div class="stat-sublabel">Max-retries exceeded</div></div>
        </div>

        <div class="telemetry-section">
            <h3>📊 Agent Activity</h3>
            ${agents.length > 0 ? `<div class="agent-stats-grid">${agents.map(a => `
                <div class="agent-stat-card">
                    <div class="agent-stat-header">${getAgentEmoji(a.agent_id)} ${a.agent_id}</div>
                    <div class="agent-stat-row"><span>Status</span><span class="badge badge-${a.status}">${a.status}</span></div>
                    <div class="agent-stat-row"><span>Card</span><span>${a.card_id || '—'}</span></div>
                    <div class="agent-stat-row"><span>Log Lines</span><span>${a.log_count || 0}</span></div>
                    <div class="agent-stat-row"><span>Started</span><span>${a.started_at ? new Date(a.started_at).toLocaleTimeString() : '—'}</span></div>
                </div>
            `).join('')}</div>` : '<div class="empty-state"><div class="empty-state-icon">💤</div><div class="empty-state-text">No agents have been active yet</div></div>'}
        </div>

        <div class="telemetry-section">
            <h3>📈 Prompt Pipeline</h3>
            <div class="bar-chart">
                ${renderBar('Submitted', broker.submitted || 0, Math.max(broker.submitted || 1, 1), 'accent')}
                ${renderBar('Processed', broker.processed || 0, Math.max(broker.submitted || 1, 1), 'green')}
                ${renderBar('Retried', broker.retried || 0, Math.max(broker.submitted || 1, 1), 'amber')}
                ${renderBar('Failed', broker.failed || 0, Math.max(broker.submitted || 1, 1), 'red')}
            </div>
        </div>
    `;
}

function renderBar(label, value, max, colorClass) {
    const pct = Math.max((value / max) * 100, value > 0 ? 3 : 0);
    return `<div class="bar-row"><div class="bar-label">${label}</div><div class="bar-track"><div class="bar-fill ${colorClass}" style="width:${pct}%">${value}</div></div></div>`;
}

function formatNumber(n) {
    if (n >= 1000000) return (n / 1000000).toFixed(1) + 'M';
    if (n >= 1000) return (n / 1000).toFixed(1) + 'K';
    return n.toString();
}

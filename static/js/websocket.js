/* ═══════════════════════════════════════════════════════════
   Aegis WebSocket Module
   ═══════════════════════════════════════════════════════════ */

let ws = null;

function connectWebSocket() {
    updateConnectionStatus('connecting');
    ws = new WebSocket(`ws://${location.host}/ws`);

    ws.onopen = () => updateConnectionStatus('connected');
    ws.onclose = () => { updateConnectionStatus('disconnected'); setTimeout(connectWebSocket, 3000); };
    ws.onerror = () => updateConnectionStatus('disconnected');

    ws.onmessage = (event) => {
        const data = JSON.parse(event.data);
        handleWebSocketMessage(data);
    };
}

function updateConnectionStatus(status) {
    document.querySelectorAll('.status-dot').forEach(dot => {
        dot.className = 'status-dot ' + status;
    });
    document.querySelectorAll('#wsStatusText').forEach(text => {
        text.textContent = status === 'connected' ? 'Live' : status === 'connecting' ? 'Connecting...' : 'Disconnected';
    });
}

function handleWebSocketMessage(data) {
    switch (data.type) {
        case 'card_created':
            cards.push(data.card);
            renderBoard();
            showToast('Card created');
            break;
        case 'card_updated':
            const idx = cards.findIndex(c => c.id === data.card.id);
            if (idx !== -1) { cards[idx] = data.card; renderBoard(); }
            break;
        case 'card_deleted':
            cards = cards.filter(c => c.id !== data.card_id);
            renderBoard();
            break;
        case 'card_assigned':
            showToast(`Card assigned to ${data.agent}`);
            break;
        case 'agent_started':
            if (agentStatus[data.agent_id]) {
                agentStatus[data.agent_id].status = 'running';
                agentStatus[data.agent_id].current_card = { id: data.card_id };
                renderAgentMenu();
            }
            break;
        case 'agent_stopped':
        case 'agent_status_changed':
            if (agentStatus[data.agent_id]) {
                agentStatus[data.agent_id].status = data.status || 'stopped';
                if (data.status !== 'running') delete agentStatus[data.agent_id].current_card;
                renderAgentMenu();
            }
            // Refresh runtimes if panel is visible
            if (document.getElementById('tab-runtimes')?.classList.contains('active')) {
                loadActiveRuntimes();
            }
            break;
        case 'agent_params_updated':
            if (agentStatus[data.agent_id]) {
                agentStatus[data.agent_id].params = data.params;
                renderAgentMenu();
            }
            break;
        case 'agent_log':
            const logEl = document.getElementById(`logs-${data.agent_id}`);
            if (logEl) {
                const entry = document.createElement('div');
                entry.textContent = data.entry;
                logEl.appendChild(entry);
                logEl.scrollTop = logEl.scrollHeight;
            }

            // Extract and update agent activity
            const targetId = data.instance_id || data.agent_id;
            const activityEl = document.getElementById(`activity-${targetId}`);
            if (activityEl) {
                const text = data.entry;
                if (text.includes('📡 PULSE: Fetching board state')) {
                    activityEl.innerHTML = '<span style="color: #60a5fa">📡 Fetching board state...</span>';
                } else if (text.includes('🧠 THINKING: Consulting LLM')) {
                    activityEl.innerHTML = '<span style="color: #c084fc">🧠 Thinking...</span>';
                } else if (text.includes('⚡ ACTION:')) {
                    const actionMatch = text.match(/⚡ ACTION: ([^{\n]+)/);
                    if (actionMatch) {
                        activityEl.innerHTML = `<span style="color: #facc15">⚡ Action: ${actionMatch[1].trim()}</span>`;
                    }
                } else if (text.includes('✅ Action complete') || text.includes('💤 Waiting')) {
                    activityEl.innerHTML = '<span style="color: var(--text-secondary)">💤 Sleeping</span>';
                } else if (text.includes('❌ ERROR:')) {
                    activityEl.innerHTML = '<span style="color: var(--danger)">❌ Error</span>';
                }
            }
            break;
        case 'log_entry':
            appendLogEntry(data.card_id, data.entry);
            break;
        case 'agent_paused':
            showToast(`⏸ ${data.agent_id} paused`);
            break;
        case 'agent_resumed':
            showToast(`▶ ${data.agent_id} resumed`);
            break;
        case 'agent_pulse':
            if (window.startPulseCountdown) {
                window.startPulseCountdown(data.instance_id, data.interval);
            }
            break;
    }
}

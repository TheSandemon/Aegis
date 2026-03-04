/* ═══════════════════════════════════════════════════════════
   Aegis WebSocket Module
   ═══════════════════════════════════════════════════════════ */

let ws = null;
const agentCardMap = {}; // instance_id → { card_id, color }

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
            loadCards().then(() => {
                renderBoard();
                showToast(`Card assigned to ${data.agent}`);
            });
            break;
        case 'column_updated':
            const colIdx = columns.findIndex(c => c.id === data.column.id);
            if (colIdx !== -1) { columns[colIdx] = data.column; }
            populateColumnSelects();
            renderBoard();
            break;
        case 'agent_started':
            if (data.instance_id && data.card_id) {
                agentCardMap[data.instance_id] = { card_id: data.card_id, color: data.color || 'var(--primary)' };
            }
            if (typeof renderInstancesSidebar === 'function') renderInstancesSidebar();
            break;
        case 'agent_stopped':
            // Remove card highlight and clean up map entry
            if (typeof setCardAgentHighlight === 'function') {
                const stoppedMapping = agentCardMap[data.instance_id];
                if (stoppedMapping) setCardAgentHighlight(stoppedMapping.card_id, null, false);
            }
            delete agentCardMap[data.instance_id];
            if (typeof renderInstancesSidebar === 'function') renderInstancesSidebar();
            if (document.getElementById('tab-runtimes')?.classList.contains('active')) {
                loadActiveRuntimes();
            }
            break;
        case 'agent_status_changed':
            if (typeof renderInstancesSidebar === 'function') renderInstancesSidebar();
            if (document.getElementById('tab-runtimes')?.classList.contains('active')) {
                loadActiveRuntimes();
            }
            break;
        case 'agent_params_updated':
            if (typeof renderInstancesSidebar === 'function') renderInstancesSidebar();
            break;
        case 'agent_log':
            const targetId = data.instance_id || data.agent_id;

            // Strip [STDOUT] [worker_name] prefix for cleaner UI display
            const displayEntry = data.entry.replace(/^\[.*?\]\s*\[.*?\]\s*/, '');

            // Try to append to full terminal if open
            const activeTerminalId = document.getElementById('activeTerminalInstanceId')?.value;
            if (activeTerminalId && activeTerminalId === targetId) {
                const output = document.getElementById('workerTerminalOutput');
                if (output) {
                    const isScrolledToBottom = output.scrollHeight - output.clientHeight <= output.scrollTop + 1;
                    output.textContent += (output.textContent ? '\n' : '') + displayEntry;
                    if (isScrolledToBottom) {
                        output.scrollTop = output.scrollHeight;
                    }
                }
            }

            // Append to Mini Terminal on Worker Card
            const miniTerm = document.getElementById(`mini-term-${targetId}`);
            if (miniTerm) {
                // If log is just starting, clear placeholder
                if (miniTerm.textContent === 'Waiting for logs...') miniTerm.textContent = '';

                miniTerm.textContent += (miniTerm.textContent ? '\n' : '') + displayEntry;

                // Keep only the last ~4 lines in DOM to prevent bloating
                const lines = miniTerm.textContent.split('\n');
                if (lines.length > 5) {
                    miniTerm.textContent = lines.slice(-5).join('\n');
                }
                // Scroll to bottom
                miniTerm.scrollTop = miniTerm.scrollHeight;
            }

            // Extract and update agent activity
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

            // Agent-card highlight: glow the card while agent is actively logging
            if (data.instance_id && typeof setCardAgentHighlight === 'function') {
                const mapping = agentCardMap[data.instance_id];
                if (mapping) {
                    const isActive = data.entry.includes('THOUGHT') || data.entry.includes('ACTION') ||
                        data.entry.includes('THINKING') || data.entry.includes('PULSE');
                    if (isActive) setCardAgentHighlight(mapping.card_id, mapping.color, true);
                }
            }

            // Speech Bubbles: Show thought on THOUGHT, ERROR, ATTENTION, or explicit NOTIFY logs
            if (data.entry && typeof showAgentBubble === 'function') {
                const id = data.instance_id || data.agent_id;
                const thoughtMatch = data.entry.match(/💡 THOUGHT: (.+)/);
                const errorMatch = data.entry.match(/🛑 ERROR: (.+)/);
                const attentionMatch = data.entry.match(/⚠️ ATTENTION: (.+)/);
                const notifyMatch = data.entry.match(/📢 NOTIFY: (.+)/);
                const warnNotify = data.entry.match(/⚠️ NOTIFY: (.+)/);
                const errNotify = data.entry.match(/🛑 NOTIFY: (.+)/);

                if (thoughtMatch) showAgentBubble(id, thoughtMatch[1], 'thought');
                if (errorMatch) showAgentBubble(id, errorMatch[1], 'error');
                if (attentionMatch) showAgentBubble(id, attentionMatch[1], 'attention');
                if (notifyMatch) showAgentBubble(id, notifyMatch[1], 'notify');
                if (warnNotify) showAgentBubble(id, warnNotify[1], 'attention');
                if (errNotify) showAgentBubble(id, errNotify[1], 'error');
            }
            break;
        case 'log_entry':
            appendLogEntry(data.card_id, data.entry);
            break;
        case 'agent_conflict':
            showToast(`⚠️ Agent ${data.agent_id} encountered a fatal error/conflict!`, 'error');
            if (typeof triggerConflictWizard === 'function') {
                triggerConflictWizard(data);
            }
            break;
        case 'agent_paused':
            if (typeof renderInstancesSidebar === 'function') renderInstancesSidebar();
            showToast(`⏸ ${data.agent_id} paused`);
            break;
        case 'agent_resumed':
            if (typeof renderInstancesSidebar === 'function') renderInstancesSidebar();
            showToast(`▶ ${data.agent_id} resumed`);
            break;
        case 'agent_pulse':
            if (window.startPulseCountdown) {
                window.startPulseCountdown(data.instance_id, data.interval);
            }
            // Dismiss speech bubble on pulse (agent is sleeping)
            if (typeof dismissBubble === 'function') {
                dismissBubble(data.instance_id);
            }
            // Remove card highlight — agent is sleeping
            if (typeof setCardAgentHighlight === 'function') {
                const mapping = agentCardMap[data.instance_id];
                if (mapping) setCardAgentHighlight(mapping.card_id, null, false);
            }
            break;
        case 'agent_activity':
            const actId = data.instance_id || data.sender;
            const actEl = document.getElementById(`activity-${actId}`);
            if (actEl) {
                let color = "var(--text-secondary)";
                if (data.status.toLowerCase().includes("thinking")) color = "#c084fc";
                if (data.status.toLowerCase().includes("acting")) color = "#facc15";
                actEl.innerHTML = `<span style="color: ${color}">${data.status}...</span>`;
            }
            // Speech Bubbles: Show thought on activity
            if (data.thought && typeof showAgentBubble === 'function') {
                showAgentBubble(actId, data.thought);
            }
            break;
        case 'board_loaded':
            loadCards().then(() => { loadColumns().then(() => { populateColumnSelects(); renderBoard(); }); });
            showToast(`Board workspace "${data.workspace}" loaded`);
            break;
        case 'integration_status':
            // Update the column's integration badge and trigger card/column reload
            const intCol = columns.find(c => c.id === data.column_id);
            if (intCol) {
                intCol.integration_status = data.status;
                intCol.last_synced_at = data.last_synced_at || intCol.last_synced_at;
                renderBoard();
            }
            if (data.status === 'error') {
                showToast(`⚠️ Integration error on "${intCol?.name || 'column'}": ${data.error || 'sync failed'}`);
            } else if (data.synced_count > 0) {
                loadCards().then(() => renderBoard());
            }
            break;
        case 'broker_update':
            const stats = data.stats;
            const qDepth = document.getElementById('brokerQueueDepth');
            const processed = document.getElementById('brokerProcessed');
            const brokerStatus = document.getElementById('brokerStatus');
            const brokerInProgress = document.getElementById('brokerInProgress');
            const brokerRateInput = document.getElementById('brokerRateInput');
            const brokerMinPulse = document.getElementById('brokerMinPulse');
            const brokerPauseBtn = document.getElementById('brokerPauseBtn');

            if (qDepth) qDepth.textContent = stats.queue_depth;
            if (processed) processed.textContent = stats.total_processed;

            if (brokerStatus) {
                window._brokerPaused = stats.paused;
                brokerStatus.textContent = stats.paused ? 'PAUSED' : 'ACTIVE';
                brokerStatus.style.color = stats.paused ? '#f59e0b' : '#22c55e';
            }
            if (brokerInProgress) {
                brokerInProgress.textContent = stats.in_progress
                    ? `${stats.in_progress.agent_name} (card #${stats.in_progress.card_id})`
                    : '—';
            }
            if (brokerRateInput && document.activeElement !== brokerRateInput) {
                brokerRateInput.value = stats.prompts_per_minute || 1;
            }
            if (brokerMinPulse) {
                brokerMinPulse.textContent = Math.round(stats.broker_interval_seconds || 60);
            }
            if (brokerPauseBtn) {
                brokerPauseBtn.textContent = stats.paused ? '▶ Resume' : '⏸ Pause';
                brokerPauseBtn.style.background = stats.paused ? '#22c55e' : 'var(--accent)';
            }
            break;
    }
}

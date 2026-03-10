/* ═══════════════════════════════════════════════════════════
   Aegis WebSocket Module
   ═══════════════════════════════════════════════════════════ */

let ws = null;
const agentCardMap = {}; // instance_id → { card_id, color }

// ─── Xterm.js Terminal Manager ────────────────────────────────────────────────
// Global maps to hold terminal instances
window.terminals = {
    modal: null,               // Single Terminal instance for the modal
    modalFit: null,            // FitAddon for modal
    activeModalInstance: null, // Which instance is currently viewed in modal
    card: null,                // Single Terminal instance for the card modal
    cardFit: null,             // FitAddon for card modal
    activeCardInstance: null,  // Which instance is currently viewed in card modal
    minis: {},                 // instanceId -> { term: Terminal, fit: FitAddon }
    history: {}                // instanceId -> raw log history for replaying
};

function initModalTerminal() {
    if (window.terminals.modal) return;
    const term = new Terminal({
        theme: {
            background: '#0d1117', // GitHub Dark-ish
            foreground: '#c9d1d9',
            cursor: '#58a6ff',
            cursorAccent: '#0d1117',
            selection: '#388bfd33',
            black: '#484f58',
            red: '#ff7b72',
            green: '#3fb950',
            yellow: '#d29922',
            blue: '#58a6ff',
            magenta: '#bc8cff',
            cyan: '#39c5cf',
            white: '#b1bac4',
            brightBlack: '#6e7681',
            brightRed: '#ffa198',
            brightGreen: '#56d364',
            brightYellow: '#e3b341',
            brightBlue: '#79c0ff',
            brightMagenta: '#d2a8ff',
            brightCyan: '#56d4dd',
            brightWhite: '#ffffff'
        },
        fontFamily: "'Fira Code', 'Cascadia Code', Consolas, 'Courier New', monospace",
        fontSize: 14,
        fontWeight: '500',
        convertEol: true,
        cursorBlink: true,
        cursorStyle: 'block'
    });
    const fitAddon = new FitAddon.FitAddon();
    term.loadAddon(fitAddon);

    // Capture keystrokes (stdin) and send to backend
    term.onData(data => {
        const activeId = window.terminals.activeModalInstance;
        if (activeId && window.ws && window.ws.readyState === WebSocket.OPEN) {
            window.ws.send(JSON.stringify({
                type: 'stdin',
                instance_id: activeId,
                data: data
            }));
        }
    });

    window.terminals.modal = term;
    window.terminals.modalFit = fitAddon;
}

function initCardTerminal() {
    if (window.terminals.card) return;
    const term = new Terminal({
        theme: {
            background: '#0d1117',
            foreground: '#c9d1d9',
            cursor: '#58a6ff',
            selection: '#388bfd33',
            black: '#484f58', red: '#ff7b72', green: '#3fb950', yellow: '#d29922', blue: '#58a6ff', magenta: '#bc8cff', cyan: '#39c5cf', white: '#b1bac4'
        },
        fontFamily: "'Fira Code', 'Cascadia Code', Consolas, 'Courier New', monospace",
        fontSize: 12, // Slightly smaller for the card modal
        convertEol: true,
        disableStdin: true, // Card view doesn't allow interaction right now
        cursorBlink: false
    });
    const fitAddon = new FitAddon.FitAddon();
    term.loadAddon(fitAddon);

    window.terminals.card = term;
    window.terminals.cardFit = fitAddon;
}

function getOrCreateMiniTerminal(instanceId) {
    if (!window.terminals.minis[instanceId]) {
        const term = new Terminal({
            theme: {
                background: '#0d1117',
                foreground: '#8b949e', // Dimmer foreground for the mini view
                black: '#484f58', red: '#ff7b72', green: '#3fb950', yellow: '#d29922', blue: '#58a6ff', magenta: '#bc8cff', cyan: '#39c5cf', white: '#b1bac4'
            },
            fontFamily: "'Fira Code', 'Cascadia Code', Consolas, 'Courier New', monospace",
            fontSize: 10,
            convertEol: true,
            disableStdin: true,
            cursorBlink: false,
            scrollback: 20 // Keep it incredibly light for the mini view
        });
        const fitAddon = new FitAddon.FitAddon();
        term.loadAddon(fitAddon);
        window.terminals.minis[instanceId] = { term, fit: fitAddon };
    }
    return window.terminals.minis[instanceId];
}

function writeToTerminal(instanceId, chunk) {
    // Save to history
    if (!window.terminals.history[instanceId]) window.terminals.history[instanceId] = '';
    window.terminals.history[instanceId] += chunk;
    if (window.terminals.history[instanceId].length > 50000) {
        window.terminals.history[instanceId] = window.terminals.history[instanceId].slice(-50000);
    }

    // Write to modal if active
    if (window.terminals.activeModalInstance === instanceId && window.terminals.modal) {
        window.terminals.modal.write(chunk);
    }

    // Write to card modal if active
    if (window.terminals.activeCardInstance === instanceId && window.terminals.card) {
        window.terminals.card.write(chunk);
    }

    // Write to mini terminal
    const mini = window.terminals.minis[instanceId];
    if (mini) {
        mini.term.write(chunk);
    }
}

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
            // Animate agent character to the new card if assignee matches a running agent
            if (data.card && data.card.assignee && window.getAgentAnimator) {
                setTimeout(() => {
                    const cardEl = document.querySelector(`.card[data-id="${data.card.id}"]`);
                    if (cardEl) {
                        const animator = getAgentAnimator();
                        // Find instance by assignee name
                        const inst = (window.instancesData || []).find(i => (i.instance_name || i.agent_id) === data.card.assignee);
                        if (inst) {
                            const charType = animator.getCharacterType(inst.instance_id);
                            animator.animateToCard(inst.instance_id, cardEl, charType, () => {
                                setTimeout(() => animator.returnToStart(inst.instance_id, charType), 3000);
                            });
                        }
                    }
                }, 300);
            }
            break;
        case 'card_updated':
            if (!data.card) break;
            const idx = cards.findIndex(c => c.id === data.card.id);
            if (idx !== -1) { cards[idx] = data.card; renderBoard(); }
            // Animate agent character to updated card if assignee matches a running agent
            if (data.card && data.card.assignee && window.getAgentAnimator) {
                setTimeout(() => {
                    const cardEl = document.querySelector(`.card[data-id="${data.card.id}"]`);
                    if (cardEl) {
                        const animator = getAgentAnimator();
                        const inst = (window.instancesData || []).find(i => (i.instance_name || i.agent_id) === data.card.assignee);
                        if (inst) {
                            const charType = animator.getCharacterType(inst.instance_id);
                            animator.animateToCard(inst.instance_id, cardEl, charType, () => {
                                setTimeout(() => animator.returnToStart(inst.instance_id, charType), 3000);
                            });
                        }
                    }
                }, 300);
            }
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
            if (!data.column) break;
            const colIdx = columns.findIndex(c => c.id === data.column.id);
            if (colIdx !== -1) { columns[colIdx] = data.column; }
            populateColumnSelects();
            renderBoard();
            break;
        case 'agent_started':
            if (data.instance_id && data.card_id) {
                agentCardMap[data.instance_id] = { card_id: data.card_id, color: data.color || 'var(--primary)' };
            }
            if (typeof loadInstances === 'function') loadInstances();
            break;
        case 'agent_stopped':
            // Remove card highlight and clean up map entry
            if (typeof setCardAgentHighlight === 'function') {
                const stoppedMapping = agentCardMap[data.instance_id];
                if (stoppedMapping) setCardAgentHighlight(stoppedMapping.card_id, null, false);
            }
            delete agentCardMap[data.instance_id];
            if (typeof loadInstances === 'function') loadInstances();
            if (document.getElementById('tab-runtimes')?.classList.contains('active')) {
                loadActiveRuntimes();
            }
            break;
        case 'agent_status_changed':
            if (typeof loadInstances === 'function') loadInstances();
            if (document.getElementById('tab-runtimes')?.classList.contains('active')) {
                loadActiveRuntimes();
            }
            break;
        case 'agent_params_updated':
            if (typeof renderInstancesSidebar === 'function') renderInstancesSidebar();
            break;
        case 'agent_log':
            const targetId = data.instance_id || data.agent_id;

            // Write the raw payload directly to xterm so ANSI colors and progress bars render natively
            let chunk = data.entry;
            // Xterm expects CRLF for proper newline rendering
            if (!chunk.includes('\r') && chunk.includes('\n')) {
                chunk = chunk.replace(/\n/g, '\r\n');
            } else if (!chunk.includes('\n') && !chunk.includes('\r')) {
                chunk += '\r\n'; // basic fallback line
            }

            writeToTerminal(targetId, chunk);

            // Extract and update agent activity
            const activityEl = document.getElementById(`activity-${targetId}`);
            if (activityEl) {
                const text = data.entry;
                let isActive = false;

                // Aegis Worker patterns + CLI agent shared patterns
                if (text.includes('📡 PULSE: Fetching board state')) {
                    activityEl.innerHTML = '<span style="color: #60a5fa">📡 Fetching board...</span>';
                    isActive = true;
                } else if (text.includes('📋 Board loaded')) {
                    activityEl.innerHTML = '<span style="color: #60a5fa">📋 Board loaded</span>';
                    isActive = true;
                } else if (text.includes('🧠 THINKING: Consulting LLM')) {
                    activityEl.innerHTML = '<span style="color: #c084fc">🧠 Thinking...</span>';
                    isActive = true;
                } else if (text.includes('⚡ WORKING:') || text.includes('⚡ ACTION:')) {
                    const actionMatch = text.match(/⚡ (?:ACTION|WORKING): ([^{\n]+)/);
                    const label = actionMatch ? actionMatch[1].trim() : 'Working...';
                    activityEl.innerHTML = `<span style="color: #facc15">⚡ ${label}</span>`;
                    isActive = true;
                } else if (text.includes('✅ Action complete') || text.includes('💤 Waiting')) {
                    activityEl.innerHTML = '<span style="color: var(--text-secondary)">💤 Sleeping</span>';
                    isActive = false;
                } else if (text.includes('❌ ERROR:')) {
                    activityEl.innerHTML = '<span style="color: var(--danger)">❌ Error</span>';
                    isActive = false;
                }
                // CLI Agent raw output patterns (Claude Code, Gemini CLI)
                else if (/thinking|reasoning/i.test(text)) {
                    activityEl.innerHTML = '<span style="color: #c084fc">🧠 Thinking...</span>';
                    isActive = true;
                } else if (/\btool[:\s]/i.test(text) || /ReadFile|WriteFile|SearchReplace|ListDir/i.test(text)) {
                    const toolMatch = text.match(/(?:Tool[:\s]+|)(ReadFile|WriteFile|SearchReplace|ListDir|Bash|Edit|TodoRead|TodoWrite|WebSearch|Grep|Glob|LS)\b/i);
                    const toolName = toolMatch ? toolMatch[1] : 'tool';
                    activityEl.innerHTML = `<span style="color: #facc15">🔧 ${toolName}</span>`;
                    isActive = true;
                } else if (/\bBash\b/i.test(text)) {
                    activityEl.innerHTML = '<span style="color: #34d399">💻 Running command...</span>';
                    isActive = true;
                } else if (/\b(result|output)[:\s]/i.test(text) && text.length > 10) {
                    activityEl.innerHTML = '<span style="color: #60a5fa">📄 Processing result...</span>';
                    isActive = true;
                }

                // Toggle the pulsing animation class
                if (isActive) {
                    activityEl.classList.add('active');
                } else {
                    activityEl.classList.remove('active');
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

            // Walking Agent Characters: Trigger animation when agent logs contain card actions
            if (data.instance_id && window.getAgentAnimator && data.entry) {
                const actionCardMatch = data.entry.match(/⚡ (?:ACTION|WORKING):[^]*?card[\s#]*?(\d+)/i)
                    || data.entry.match(/(?:update_card|move_card|create_card|delete_card)[^]*?(?:card_id|#)(\d+)/i)
                    || data.entry.match(/PATCH.*\/cards\/(\d+)/i)
                    || data.entry.match(/moved card #?(\d+)/i);
                if (actionCardMatch) {
                    const cardId = actionCardMatch[1];
                    setTimeout(() => {
                        const cardEl = document.querySelector(`.card[data-id="${cardId}"]`);
                        if (cardEl) {
                            const animator = getAgentAnimator();
                            const charType = animator.getCharacterType(data.instance_id);
                            animator.animateToCard(data.instance_id, cardEl, charType, () => {
                                setTimeout(() => animator.returnToStart(data.instance_id, charType), 2500);
                            });
                        }
                    }, 100);
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
        case 'admin_auth_request':
            showToast(`🛡️ Agent ${data.agent_name} requested Admin Authorization!`, 'attention');
            if (typeof showAdminAuthModal === 'function') {
                showAdminAuthModal(data);
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
            // Animate character back to start (going to sleep)
            if (window.getAgentAnimator) {
                const animator = getAgentAnimator();
                animator.handleAgentPulse(data.instance_id);
            }
            break;
        case 'agent_activity':
            const actId = data.instance_id || data.sender;
            console.log('[WS] agent_activity:', actId, 'card_id:', data.card_id, 'status:', data.status);
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
            // Animate character to the card being worked on
            if (data.card_id && window.getAgentAnimator) {
                const animator = getAgentAnimator();
                animator.handleAgentActivity(actId, data.card_id);
            }
            break;
        case 'agent_presence':
            // Handle real-time presence updates for character animation
            console.log('[WS] agent_presence:', data.agent_id, 'card_id:', data.card_id, 'activity:', data.activity);
            const presenceAgentId = data.agent_id;
            const presenceCardId = data.card_id;
            const presenceActivity = data.activity;
            // Update activity indicator
            const presActEl = document.getElementById(`activity-${presenceAgentId}`);
            if (presActEl) {
                let presColor = "var(--text-secondary)";
                if (presenceActivity === "thinking") presColor = "#c084fc";
                if (presenceActivity === "working") presColor = "#facc15";
                if (presenceActivity === "idle") presColor = "var(--text-secondary)";
                presActEl.innerHTML = `<span style="color: ${presColor}">${presenceActivity}...</span>`;
            }
            // Animate character based on presence
            if (window.getAgentAnimator) {
                const animator = getAgentAnimator();
                if (presenceCardId) {
                    animator.handleAgentActivity(presenceAgentId, presenceCardId);
                } else {
                    // No card - return to sidebar/header
                    animator.handleAgentActivity(presenceAgentId, null);
                }
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

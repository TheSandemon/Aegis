/**
 * Aegis Onboarding Wizard
 * A beautiful, hand-holding guide for first-time users.
 */

class OnboardingWizard {
    constructor() {
        this.currentStep = 1;
        this.totalSteps = 5;
        this.isOpen = false;

        // Form states
        this.provider = '';
        this.apiKey = '';
        this.boardName = 'Main Board';
        this.workerName = 'Aegis Assistant';
        this.workerTemplate = 'aegis-worker';

        this.init();
    }

    async init() {
        try {
            const res = await fetch('/api/system/status');
            const data = await res.json();

            if (data.is_first_run) {
                // Wait for main UI to render, then show wizard
                setTimeout(() => this.open(), 1000);
            }
        } catch (err) {
            console.error('Failed to check system status for onboarding:', err);
        }
    }

    open() {
        this.isOpen = true;

        // Create overlay if it doesn't exist
        if (!document.getElementById('onboardingOverlay')) {
            this.createOverlay();
        }

        const overlay = document.getElementById('onboardingOverlay');
        const card = document.getElementById('wizardCard');
        const mask = document.getElementById('spotlightMask');

        // Reset visual state after a tour run
        if (card) {
            card.style.display = 'block';
            card.style.opacity = '0';
        }
        if (mask) mask.style.display = 'none';

        overlay.style.display = 'flex';
        // Small delay to allow display flex to apply before opacity transition
        setTimeout(() => {
            overlay.classList.add('active');
            this.renderStep();
        }, 50);
    }

    close() {
        this.isOpen = false;

        const tooltip = document.getElementById('tourTooltip');
        if (tooltip) {
            tooltip.remove();
        }

        const overlay = document.getElementById('onboardingOverlay');
        if (overlay) {
            overlay.classList.remove('active');
            setTimeout(() => {
                overlay.style.display = 'none';
                overlay.style.backdropFilter = '';
                overlay.style.webkitBackdropFilter = '';
                overlay.style.background = '';
            }, 500); // match transition time
        }
    }

    createOverlay() {
        const overlay = document.createElement('div');
        overlay.id = 'onboardingOverlay';
        overlay.className = 'onboarding-overlay';
        overlay.style.display = 'none';

        overlay.innerHTML = `
            <div class="wizard-card" id="wizardCard">
                <!-- Content injected by renderStep -->
            </div>
            <div class="spotlight-mask" id="spotlightMask" style="display: none;"></div>
        `;

        document.body.appendChild(overlay);
    }

    renderStep() {
        const card = document.getElementById('wizardCard');
        if (!card) return;

        let content = '';

        if (this.currentStep === 1) {
            content = `
                <div class="wizard-header">
                    <div class="wizard-icon">🛡️</div>
                    <h2>Welcome to Aegis</h2>
                    <p>The Multi-Agent Kanban Orchestrator</p>
                </div>
                <div class="wizard-body">
                    <p>We're thrilled to have you! Aegis lets you set up an army of AI workers to autonomously manage your kanban boards, write code, and solve complex problems.</p>
                    <p>Since this is a fresh setup, let's take two minutes to configure your very first board and deploy your first AI worker.</p>
                </div>
                <div class="wizard-footer">
                    <button class="btn secondary" onclick="window.onboarding.close()">Skip Tutorial</button>
                    <button class="btn primary" onclick="window.onboarding.nextStep()">Let's Go 🚀</button>
                </div>
            `;
        } else if (this.currentStep === 2) {
            content = `
                <div class="wizard-header">
                    <h2>Step 1: Configure Provider</h2>
                    <p>Aegis needs access to an LLM provider to power your agents.</p>
                </div>
                <div class="wizard-body">
                    <p style="margin-bottom: 1rem;">Select a provider and enter your API key. You can safely skip this if you've already set it via environment variables or plan to run a local model.</p>
                    
                    <div class="form-group">
                        <label>Provider</label>
                        <select id="wizardProvider" onchange="window.onboarding.provider = this.value" style="width: 100%; padding: 0.5rem; background: var(--bg-dark); border: 1px solid var(--border); color: #fff; border-radius: 4px;">
                            <option value="">Select Provider...</option>
                            <option value="ANTHROPIC_API_KEY">Anthropic (Claude)</option>
                            <option value="GEMINI_API_KEY">Google (Gemini)</option>
                            <option value="OPENAI_API_KEY">OpenAI (GPT)</option>
                        </select>
                    </div>
                    
                    <div class="form-group" style="margin-top: 1rem;">
                        <label>API Key (Optional)</label>
                        <input type="password" id="wizardApiKey" onchange="window.onboarding.apiKey = this.value" placeholder="sk-..." style="width: 100%; padding: 0.5rem; background: var(--bg-dark); border: 1px solid var(--border); color: #fff; border-radius: 4px;">
                    </div>
                </div>
                <div class="wizard-footer">
                    <button class="btn secondary" onclick="window.onboarding.prevStep()">Back</button>
                    <button class="btn primary" onclick="window.onboarding.saveProviderAndNext()">Next: Board Setup</button>
                </div>
            `;
        } else if (this.currentStep === 3) {
            content = `
                <div class="wizard-header">
                    <h2>Step 2: Create a Board</h2>
                    <p>Where your agents will manage their tasks.</p>
                </div>
                <div class="wizard-body">
                    <div class="form-group">
                        <label>Board Name</label>
                        <input type="text" id="wizardBoardName" value="${this.boardName}" onchange="window.onboarding.boardName = this.value" style="width: 100%; padding: 0.5rem; background: var(--bg-dark); border: 1px solid var(--border); color: #fff; border-radius: 4px;">
                    </div>
                    <p style="margin-top: 1rem; font-size: 0.85rem; color: var(--text-secondary);">We will automatically create the standard columns for you: Inbox, Planned, In Progress, Review, and Done.</p>
                </div>
                <div class="wizard-footer">
                    <button class="btn secondary" onclick="window.onboarding.prevStep()">Back</button>
                    <button class="btn primary" onclick="window.onboarding.nextStep()">Next: Hire Worker</button>
                </div>
            `;
        } else if (this.currentStep === 4) {
            content = `
                <div class="wizard-header">
                    <h2>Step 3: Deploy First Agent</h2>
                    <p>Hire an AI worker to manage your board.</p>
                </div>
                <div class="wizard-body">
                    <div class="form-group">
                        <label>Worker Name</label>
                        <input type="text" id="wizardWorkerName" value="${this.workerName}" onchange="window.onboarding.workerName = this.value" style="width: 100%; padding: 0.5rem; background: var(--bg-dark); border: 1px solid var(--border); color: #fff; border-radius: 4px;">
                    </div>
                    
                    <div class="form-group" style="margin-top: 1rem;">
                        <label>Template</label>
                        <select id="wizardTemplate" onchange="window.onboarding.workerTemplate = this.value" style="width: 100%; padding: 0.5rem; background: var(--bg-dark); border: 1px solid var(--border); color: #fff; border-radius: 4px;">
                            <option value="aegis-worker">Aegis Native Worker (Default)</option>
                            <option value="claude-code">Claude Code CLI</option>
                            <option value="gemini-cli">Gemini CLI</option>
                        </select>
                    </div>
                </div>
                <div class="wizard-footer">
                    <button class="btn secondary" onclick="window.onboarding.prevStep()">Back</button>
                    <button class="btn primary" onclick="window.onboarding.finishSetup()" id="btnFinishSetup">Deploy & Finish</button>
                </div>
            `;
        } else if (this.currentStep === 5) {
            content = `
                <div class="wizard-header">
                    <h2>Setup Complete! 🎉</h2>
                    <p>Your workspace is ready.</p>
                </div>
                <div class="wizard-body" style="text-align: center;">
                    <p>Excellent! We've created your board and deployed your worker.</p>
                    <p style="margin-top: 1rem;">To use Aegis:</p>
                    <ul style="text-align: left; margin: 1rem auto; max-width: 250px; font-size: 0.9rem; color: #c9d1d9;">
                        <li>➕ Add a card to the Inbox</li>
                        <li>🤖 Assign it to your worker</li>
                        <li>▶️ Start your worker</li>
                    </ul>
                </div>
                <div class="wizard-footer" style="justify-content: center;">
                    <button class="btn primary" onclick="window.onboarding.startTour()">Start Quick Tour</button>
                    <button class="btn secondary" onclick="window.onboarding.close()">Explore on my own</button>
                </div>
            `;
        }

        // Add step indicators
        if (this.currentStep > 1 && this.currentStep < 5) {
            content += `
                <div class="wizard-progress">
                    <div class="dot ${this.currentStep === 2 ? 'active' : ''}"></div>
                    <div class="dot ${this.currentStep === 3 ? 'active' : ''}"></div>
                    <div class="dot ${this.currentStep === 4 ? 'active' : ''}"></div>
                </div>
            `;
        }

        card.style.opacity = '0';
        setTimeout(() => {
            card.innerHTML = content;
            card.style.opacity = '1';

            // Re-bind values to DOM elements if needed
            if (document.getElementById('wizardProvider')) document.getElementById('wizardProvider').value = this.provider;
            if (document.getElementById('wizardApiKey')) document.getElementById('wizardApiKey').value = this.apiKey;
            if (document.getElementById('wizardBoardName')) document.getElementById('wizardBoardName').value = this.boardName;
            if (document.getElementById('wizardWorkerName')) document.getElementById('wizardWorkerName').value = this.workerName;
            if (document.getElementById('wizardTemplate')) document.getElementById('wizardTemplate').value = this.workerTemplate;

        }, 200);
    }

    nextStep() {
        if (this.currentStep < this.totalSteps) {
            this.currentStep++;
            this.renderStep();
        }
    }

    prevStep() {
        if (this.currentStep > 1) {
            this.currentStep--;
            this.renderStep();
        }
    }

    async saveProviderAndNext() {
        if (this.provider && this.apiKey) {
            try {
                // Fetch existing config
                const res = await fetch('/api/profiles/config');
                let conf = {};
                if (res.ok) conf = await res.json();

                // Update env var
                if (!conf.env_vars) conf.env_vars = {};
                conf.env_vars[this.provider] = this.apiKey;

                // Save config
                await fetch('/api/profiles/config', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(conf)
                });
            } catch (err) {
                console.error('Failed to save API key:', err);
                showToast('Failed to save API Key', 'error');
            }
        }
        this.nextStep();
    }

    async finishSetup() {
        const btn = document.getElementById('btnFinishSetup');
        if (btn) {
            btn.textContent = 'Deploying...';
            btn.disabled = true;
        }

        try {
            // 1. We don't need to explicitly create the "Inbox" "Planned" etc columns
            // because AegisStore seeding logic already does it. We just accept the board name.
            // Currently Aegis is single-board, so creating a board just conceptually means
            // we are ready. If multi-board is supported, add column creation here.

            // 2. Create the worker agent instance
            await fetch('/api/instances/create', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    template_id: this.workerTemplate,
                    instance_name: this.workerName,
                    service: '',
                    model: '',
                    config: {},
                    env_vars: {},
                    color: '#6366f1',
                    icon: '🤖'
                })
            });

            // Reload frontend state
            if (typeof loadInstances === 'function') await loadInstances();

            showToast('Setup Complete!', 'success');
            this.nextStep(); // go to step 5

        } catch (err) {
            console.error('Failed to provision default setup:', err);
            showToast('Failed to complete setup', 'error');
            if (btn) {
                btn.textContent = 'Retry';
                btn.disabled = false;
            }
        }
    }

    startTour() {
        const card = document.getElementById('wizardCard');
        if (card) {
            card.style.display = 'none'; // hide the main modal card
        }

        const overlay = document.getElementById('onboardingOverlay');
        if (overlay) {
            overlay.style.backdropFilter = 'none';
            overlay.style.webkitBackdropFilter = 'none';
            overlay.style.background = 'transparent';
        }

        let step = 0;
        const steps = [
            { id: '', selector: '.agent-menu', text: 'This is the sidebar. From here, you can navigate your boards, skills, and settings.' },
            { id: 'agentCardsList', selector: '', text: 'Here are your AI Workers. You can start, stop, and inspect them here.' },
            { id: 'board', selector: '', text: 'This is your Kanban Board! Agents will read these columns and move cards autonomously.' },
            { id: '', selector: 'button[onclick="openNewCardModal()"]', text: 'Click here to add a new task for your worker. Good luck!' } // Note: ensure button has id or use class
        ];

        const mask = document.getElementById('spotlightMask');
        if (!mask) return;

        mask.style.display = 'block';

        const showTooltip = () => {
            if (step >= steps.length) {
                this.close();
                return;
            }

            const currentStepData = steps[step];
            const target = currentStepData.id
                ? document.getElementById(currentStepData.id)
                : document.querySelector(currentStepData.selector);

            if (!target) {
                console.warn('Tour target not found:', steps[step].id);
                step++;
                showTooltip();
                return;
            }

            const rect = target.getBoundingClientRect();

            // Position the mask cutout
            const padding = 10;
            const borderSize = 4000; // Large border to cover screen
            mask.style.borderWidth = `${rect.top - padding}px ${window.innerWidth - rect.right - padding}px ${window.innerHeight - rect.bottom - padding}px ${rect.left - padding}px`;

            // Create tooltip element
            let tooltip = document.getElementById('tourTooltip');
            if (!tooltip) {
                tooltip = document.createElement('div');
                tooltip.id = 'tourTooltip';
                tooltip.className = 'tour-tooltip';
                document.body.appendChild(tooltip);
            }

            tooltip.innerHTML = `
                <p>${steps[step].text}</p>
                <div style="text-align: right; margin-top: 1rem;">
                    <button class="btn primary btn-sm" onclick="window.onboarding.nextTourStep()">Next</button>
                </div>
            `;

            // Position tooltip smartly
            tooltip.style.display = 'block';
            let topPos = rect.bottom + padding + 10;
            if (topPos + 100 > window.innerHeight) {
                topPos = rect.top - padding - 100; // Above target if no space below
            }

            tooltip.style.top = topPos + 'px';
            tooltip.style.left = Math.max(10, rect.left + (rect.width / 2) - 125) + 'px';
        };

        this.nextTourStep = () => {
            step++;
            showTooltip();
        };

        showTooltip();
    }
}

// Initialize on script load
window.onboarding = new OnboardingWizard();

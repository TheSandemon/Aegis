# Aegis: Multi-Agent Kanban & Orchestration Hub

Aegis is a highly configurable, local-first Kanban board and orchestration dashboard built to manage, track, and dynamically route tasks across a fleet of autonomous AI agents. Rather than wrestling with tangled CLI outputs and context bleed, Aegis treats each task card as an isolated environment. It natively binds to OpenClaw (Moltbot), PicoClaw, and the Gemini CLI, turning raw agentic execution into a unified, visual, and strictly controlled development pipeline.

## 🌟 Core Features

### Total Session Isolation
Dragging a card to "In Progress" automatically spins up a sandboxed agent session. Each task gets its own dedicated memory and workspace, guaranteeing zero context bleed between concurrent jobs.

### Dynamic Task Routing
Agents are treated as a specialized workforce. Assign a card to the Security Auditor or UI Architect, and the system routes the objective directly to that specific agent's prompt queue.

### Peer-to-Peer Tagging
Agents can collaborate asynchronously. If your coder agent hits a blocker, it can @mention the research agent in the card's comments, triggering a sub-session to resolve the issue.

### Live Terminal Viewer
Click on any active card to open a split-pane view displaying the agent's real-time standard output and thought process. No more waiting blindly for a task to finish.

### Human-in-the-Loop (HITL) Enforcement
Agents can move cards through "Backlog", "Planned", and "In Progress", but they hit a hard stop at "Review". Only a human operator can verify the work and move the card to "Done", preventing rogue commits.

## 🏗️ System Architecture

Aegis is built on a lightweight, modular stack optimized for local server environments, but flexible enough for cloud scaling.

- **Frontend**: Vanilla JavaScript with WebSockets. Framework-less design for maximum speed and zero bloat, ensuring real-time UI updates when agents change card states.
- **Backend / Gateway**: Python (FastAPI). Handles the REST API, WebSocket broadcasts, and execution of shell commands to spawn agent instances.
- **Database Layers**: 
  - Local Default: Thread-safe SQLite (perfect for concurrent agent read/writes on a home server)
  - Cloud Adapter: Built-in Firebase integration. If you want to host this dashboard publicly, simply toggle the Firebase configuration in the .env to sync state across the web.
- **Message Broker**: In-memory queue for task handoffs and rate-limit management.

## ⚙️ The Orchestration Engine

Modern agent orchestration relies on distinct patterns. Aegis supports two primary modes out of the box:

### Supervisor Mode (Default)
Aegis acts as the central brain. It reads the Kanban board state every 5 seconds, identifies unassigned tasks in the "Planned" column, matches them to an agent's SOUL.md description, and fires off the execution command.

### Adaptive Network Mode
A decentralized approach where a single "Manager Agent" is granted read/write access to the board's JSON state. The Manager evaluates the backlog and autonomously assigns, creates, or re-prioritizes cards for the sub-agents.

## 🎛️ Adjustable Parameters

All core behaviors can be tweaked via the `aegis.config.json` file:

```json
{
  "polling_rate_ms": 5000,
  "max_concurrent_agents": 4,
  "isolation_mode": "strict",
  "rate_limits": {
    "prompts_per_minute": 1,
    "max_retries_on_fail": 3
  },
  "columns": ["Inbox", "Planned", "In Progress", "Blocked", "Review", "Done"],
  "agents": {
    "architect": {"binary": "openclaw", "profile": "sys_arch"},
    "coder": {"binary": "gemini-cli", "profile": "dev_mode"}
  }
}
```

## 🚀 Quick Start

### Prerequisites
- Node.js (v22+) and Python 3.10+
- At least one initialized agent workspace (OpenClaw, PicoClaw, etc.)

### Installation

```bash
# Clone the repository
git clone https://github.com/TheSandemon/Aegis.git
cd Aegis

# Create virtual environment
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Edit .env to point to your agent binary paths and set your Database preference (SQLite vs Firebase)

# Run the server
python main.py
```

### Access the Dashboard
Open http://localhost:8080 in your browser.

## 🛣️ Roadmap

- [ ] Containerized Sandboxing: Option to wrap every dispatched agent session in a disposable Docker container to protect host system files.
- [ ] Vector Memory Integration: Hook into long-term episodic memory so agents can recall past completed cards when tackling similar new tasks.
- [ ] Webhook Triggers: Allow external apps (like Discord bots) to create tasks directly in the Inbox column.

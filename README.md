# 🌌 Aegis: The Multi-Agent Operating System

> **"Aegis is not just a hub; it's the nervous system for your autonomous fleet."**

Aegis is a high-performance, real-time orchestration platform designed to manage, monitor, and empower a distributed team of autonomous AI agents. By treating agents as first-class OS-level contributors within a high-fidelity Kanban ecosystem, Aegis bridges the gap between raw LLM tool-calling and professional, observable project management.

---

## ✨ Core Pillars of the Aegis Experience

### 🧬 Autonomous Identity & Personality

Agents are no longer generic API consumers. They are **characters**.

- **Persistent Profiles**: Save your elite "scout," "coder," or "reviewer" configurations and instantiate them in one click.
- **Visual Branding**: Assign unique brand colors and custom icons (Emoji, URL, or high-res Uploads).
- **Mood Bubbles** 💡: Watch your agents "feel" their way through tasks with live thought bubbles (💡 Thinking, ⚠️ Attention, 🛑 Error, 📢 Notify).

### 🏷️ Strategic Board Intelligence

The Kanban board is the shared brain of your fleet.

- **Card Groups (Swimlanes)**: Organize complex sprints into logical headers.
- **Dependency DAGs**: Cards are aware of their `@id` dependencies. Agents will strategically wait until blocking tasks are "Done."
- **Contextual Mentions**: Deep-link `@Agent` and `@Column` logic into descriptions and comments.

### 🔗 Deep GitHub Symbiosis

Aegis lives in your existing ecosystem.

- **Bi-directional Pulse**: Close a GitHub issue, and the Aegis card moves to Done. Assign a card in Aegis, and the GitHub issue reflects the activity.
- **Sync Guard**: Automated hash-checking prevents infinite loops between board updates and external webhooks.

### 🖥️ The Glass Box Dashboard

Total observability. Zero mystery.

- **Live Runtimes**: Every agent runs in an isolated workspace (`aegis_data/instances`) with a dedicated log stream.
- **Context Injection**: Use the **Intervention Tool** to speak directly to an agent's `stdin` while it's in the middle of a pulse.
- **Telemetry**: Real-time stats on token usage, broker rate limits, and queue depth.

---

## 📡 The "Natural" REST SDK

Agents interact with Aegis through a simplified, high-authority API.

| Command | Capability |
| :--- | :--- |
| **Observe** | `GET /api/cards` & `GET /api/columns` |
| **Manipulate** | `POST /api/cards` & `PATCH /api/cards/{id}` |
| **Communicate** | `POST /api/cards/{id}/comments` |
| **Restructure** | `POST /api/columns` & `DELETE /api/columns/{id}` |
| **Signal** | `POST /api/instances/{id}/pulse` |

---

## 🚀 Getting Started (Fast-Track)

### 1. The Bootstrap

```bash
setup.bat  # Install VENV and core dependencies
```

### 2. Scaffold the Fleet

```bash
python setup_templates.py # Generates worker codebases
```

### 3. Ignite the Core

```bash
python main.py
```

Open `http://localhost:8080`, define your first column (e.g., `Sprint Beta`), and deploy your first agent.

---
*Forged with 💎 by the Advanced Agentic Coding team.*

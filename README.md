# Aegis 4.0: Autonomous Multi-Agent OS & Orchestration Hub

Aegis is a high-performance Kanban-based orchestration hub designed to manage, monitor, and interact with teams of autonomous AI agents. Aegis treats AI agents as a managed fleet of contributors, providing unified discovery, "Glass Box" real-time observability, and a robust REST SDK for agent-to-board interaction.

---

## 🚀 Core Features

- 🤖 **Autonomous Sandbox Bots** — Workers operate on a persistent ReAct loop, self-assigning tasks and using LLM tool calling to interact with the board.
- 📋 **Dynamic Board Architecture** — Fully customizable Kanban workflows. Add or remove columns to fit your specific pipeline needs, and agents will adapt.
- 🏗️ **Smart Agent Registry** — Bootstrap workers instantly from a registry. Aegis automatically handles local scaffolding and dependency management.
- 🖥️ **Glass Box Control Panel** — Real-time observability. See live terminal logs, inject context into stdin, or pause/resume agent processes.
- 📡 **Live Activity Monitoring** — Real-time indicators showing exactly what an agent is doing (Thinking, Processing, Acting) via WebSockets.
- ⚙️ **Dynamic Goal Tuning** — Change agent goals on the fly. Update an agent's objective while paused and resume work without a rebuild.
- 🚦 **Prompt Broker** — Centralized rate-limiting and token estimation ensuring your team respects API quotas (OpenAI, Anthropic, Gemini, DeepSeek).
- 🔑 **Streamlined Onboarding** — Auto-detection for providers (sk-ant, AIza, sk-) and dynamic model fetching.
- 🌍 **Cross-Platform Stability** — Full UTF-8/Unicode support for Windows and Linux environments.

---

## 🏗️ Architecture

Aegis uses a decentralized execution model where agents interact with the core orchestrator as if it were a local OS service.

```mermaid
graph TD
    subgraph "Frontend (Dashboard)"
        H["Kanban Board"]
        UI["Glass Box Modal"]
        AG["Agent Control Panel"]
    end

    subgraph "Backend (Core)"
        C["API Gateway"]
        ST["SQLite Store"]
        EE["Execution Engine"]
        BR["Prompt Broker"]
    end

    subgraph "Agent Fleet"
        W1["Generic Bot (Worker)"]
        W2["Custom Bot (Worker)"]
    end

    W1 <-->|REST SDK Tools| C
    W2 <-->|REST SDK Tools| C
    EE -.->|Spawn/Monitor| W1
    EE -.->|Spawn/Monitor| W2
    C <--> ST
    UI <-->|WebSocket Logs| EE
```

---

## 🤖 Autonomous Sandbox Bots

Aegis 4.0 shifts from specialized scripts to **Fully Autonomous Sandbox Bots** powered by a "Natural API" toolset.

### The ReAct Loop

Agents operate on a continuous loop governed by a configurable `pulse_interval`:

```mermaid
sequenceDiagram
    participant B as Kanban API
    participant W as Agent Worker
    participant L as LLM (ReAct)
    
    loop Every Pulse
        W->>B: GET /api/cards & /api/columns
        B-->>W: Board State & Configuration
        W->>L: Context (State + Goal)
        L-->>W: Reasoning + Action (JSON)
        W->>B: Execute Tool (POST/PATCH/DELETE)
        B-->>W: Result
        Note over W: Sleep (Pulse Interval)
    end
```

### "Natural" API Capabilities

Bots aren't just consumers; they are first-class citizens with full authority to manage the board:

- **Card CRUD**: Create, Update, and **Delete** cards as needed.
- **Workflow Management**: Create and Delete **Columns** to dynamically restructure the Kanban board.
- **Context Richness**: Bots parse card comments, priorities, and dependency chains to make informed decisions.
- **Proactive Communication**: Reasoning is logged as comments, providing a "paper trail" for autonomous actions.

---

## 🛠️ Getting Started

1. **Bootstrap**: Run `setup.bat` (Windows) or `setup.sh` (POSIX).
2. **Setup Registry**: Run `python setup_templates.py` to generate the local template scaffolds.
3. **Launch**: `python main.py` and navigate to `http://localhost:8080`.
4. **Define Workflows**: Use the "+ Add Column" button to structure your board.
5. **Drop a Task**: Create a worker, give it an API key and an arbitrary goal, and drop a task in its intended start column!

---

## 🔒 Security & RBAC

- **Provider Isolation**: API keys are injected only into the process environment of the specific worker.
- **Protocol Guard**: All board updates originating from agents are validated against active instance IDs and required headers.

---

Built with ❤️ for the next generation of autonomous development.

# 🛡️ Aegis — The Multi-Agent Operating System

> **"Aegis is not just a hub; it's the nervous system for your autonomous fleet."**

Aegis is a high-performance, real-time orchestration platform for managing, monitoring, and empowering a distributed team of autonomous AI agents. Agents operate as first-class contributors within a Kanban ecosystem, capable of cloning repos, writing code, opening pull requests, merging branches, and managing their own task lifecycle — all autonomously.

---

## Table of Contents

1. [Architecture Overview](#-architecture-overview)
2. [Quick Start](#-quick-start)
3. [File Structure](#-file-structure)
4. [Core Backend — `main.py`](#-core-backend--mainpy)
5. [Persistence Layer — `AegisStore`](#-persistence-layer--aegisstore)
6. [Execution Engine — `execution_engine.py`](#-execution-engine--execution_enginepy)
7. [Prompt Broker — `prompt_broker.py`](#-prompt-broker--prompt_brokerpy)
8. [Worker Template — `worker.py`](#-worker-template--workerpy)
9. [System Prompt — Agent Instruction Set](#-system-prompt--agent-instruction-set)
10. [Integrations Framework](#-integrations-framework)
11. [GitHub DevOps — Full Lifecycle](#-github-devops--full-lifecycle)
12. [A2A Protocol Layer — `a2a.py`](#-a2a-protocol-layer--a2apy)
13. [MCP Server — `mcp_server.py`](#-mcp-server--mcp_serverpy)
14. [Skill Manager — `skill_manager.py`](#-skill-manager--skill_managerpy)
15. [Frontend Dashboard](#-frontend-dashboard)
16. [WebSocket Events](#-websocket-events)
17. [Configuration — `aegis.config.json`](#-configuration--aegisconfigjson)
18. [REST API Reference](#-rest-api-reference)
19. [Safety & Guardrails](#-safety--guardrails)

---

## 🏛️ Architecture Overview

```
┌─────────────────────── Aegis Core ───────────────────────┐
│                                                          │
│  ┌──────────┐  ┌─────────────┐  ┌────────────────────┐   │
│  │  FastAPI  │  │  WebSocket  │  │  Static Frontend   │   │
│  │  REST API │  │  Broadcast  │  │  (Glass Box UI)    │   │
│  └────┬─────┘  └──────┬──────┘  └────────────────────┘   │
│       │               │                                   │
│  ┌────┴───────────────┴──────────────────────────────┐   │
│  │              AegisStore (SQLite / Firebase)        │   │
│  │      Cards · Columns · Comments · Metadata        │   │
│  └───────────────────────────────────────────────────┘   │
│       │               │               │                   │
│  ┌────┴────┐   ┌──────┴──────┐  ┌────┴─────────────┐    │
│  │Execution│   │   Prompt    │  │  Integration     │    │
│  │ Engine  │   │   Broker    │  │  Manager         │    │
│  └────┬────┘   └─────────────┘  └────┬─────────────┘    │
│       │                               │                   │
│  ┌────┴────────────┐   ┌─────────────┴──────────────┐   │
│  │  Worker Instances│   │ GitHub · Jira · Linear ·   │   │
│  │  (Subprocesses / │   │ Firebase Adapters          │   │
│  │   Docker)        │   └────────────────────────────┘   │
│  └──────────────────┘                                     │
│       │                                                   │
│  ┌────┴───────────────────┐  ┌──────────────────────┐    │
│  │  A2A Protocol Layer    │  │  MCP Server Layer    │    │
│  │  (Agent-to-Agent)      │  │  (Model Context)     │    │
│  └────────────────────────┘  └──────────────────────┘    │
│                                                          │
│  ┌───────────────────────────────────────────────────┐   │
│  │           Skill Manager (ClawHub Skills)          │   │
│  └───────────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────┘
```

**Data flows:**

1. The **Dashboard** connects via WebSocket and renders real-time state.
2. **Worker agents** run as isolated processes, polling the REST API each pulse cycle.
3. The **Execution Engine** manages process lifecycles (start, stop, health-check, auto-kill).
4. The **Prompt Broker** rate-limits all outbound LLM requests across all agents.
5. **Integration adapters** poll external services (GitHub Issues/PRs, Jira, Linear, Firebase) and sync bidirectionally.
6. **A2A** and **MCP** protocol layers allow Aegis to interoperate with other agent systems and expose structured tool access.

---

## 🚀 Quick Start

### Windows

```bash
setup.bat          # Creates venv, installs deps, generates templates, starts server
```

### Linux / macOS

```bash
chmod +x setup.sh && ./setup.sh
```

### Manual

```bash
python -m venv venv
venv\Scripts\activate        # or: source venv/bin/activate
pip install -r requirements.txt
python setup_templates.py    # Generate worker codebases
python main.py               # Start at http://localhost:8080
```

**Requirements**: Python 3.10+, Git (for worker git tools).

---

## 📁 File Structure

```
Aegis/
├── main.py                    # Core FastAPI app (2200+ lines)
├── execution_engine.py        # Worker process lifecycle manager
├── prompt_broker.py           # Centralized rate-limited LLM queue
├── a2a.py                     # Agent-to-Agent protocol endpoints
├── mcp_server.py              # Model Context Protocol server
├── skill_manager.py           # Modular skill/tool loader
├── setup_templates.py         # Worker template scaffolding
├── setup.bat / setup.sh       # One-click bootstrap scripts
├── aegis.config.json          # Master configuration
├── requirements.txt           # Python dependencies
│
├── integrations/              # External service adapters
│   ├── base.py                # Abstract BaseIntegration class
│   ├── manager.py             # IntegrationManager (coordinator)
│   ├── github_integration.py  # GitHub Issues + PRs + Branches
│   ├── jira_integration.py    # Jira Cloud adapter
│   ├── linear_integration.py  # Linear.app adapter
│   └── firebase_integration.py# Firebase Firestore adapter
│
├── static/                    # Frontend dashboard
│   ├── index.html             # Single-page Kanban UI
│   ├── css/aegis.css          # Design system
│   └── js/
│       ├── board.js           # Kanban board logic (drag & drop, columns, cards)
│       ├── agents.js          # Worker sidebar, profiles, create/edit modals
│       ├── websocket.js       # WebSocket client, real-time event dispatch
│       ├── integrations.js    # Integration management UI
│       ├── telemetry.js       # Telemetry dashboard rendering
│       └── mentions.js        # @mention autocomplete system
│
├── aegis_data/                # Runtime data directory
│   ├── system_prompt.txt      # Editable system prompt for all agents
│   ├── instances.json         # Worker instance registry
│   ├── templates/             # Read-only agent templates
│   │   └── aegis-worker/
│   │       └── worker.py      # The autonomous agent script
│   ├── instances/             # Isolated per-instance working directories
│   ├── profiles/              # Saved worker configuration profiles
│   ├── skills/                # Modular skills (ClawHub format)
│   ├── workspaces/            # Saved board snapshots
│   └── assets/                # Uploaded icons and media
│
└── agents/                    # Legacy agent directory
```

---

## ⚙️ Core Backend — `main.py`

The monolithic FastAPI application (2200+ lines) is organized into clearly separated sections:

| Section | Lines | Description |
|---|---|---|
| Configuration & System Prompt | 1–140 | Config loading, default system prompt with all agent instructions |
| `AegisStore` class | 146–401 | SQLite persistence (cards, columns, comments, metadata) |
| `ConnectionManager` | 424–443 | WebSocket broadcast manager |
| Discord Webhook | 477–501 | Auto-fires when cards enter Review |
| Lifespan & App Init | 507–555 | FastAPI lifespan, static mounts, router includes |
| Pydantic Models | 562–637 | Request/response schemas for all endpoints |
| Column CRUD | 644–866 | Create, update, delete columns with integration config |
| Card CRUD | 902–1128 | Create, update, delete, context bundles, git diffs |
| Comments | 1133–1155 | Add comments with external integration sync |
| HITL Validation | 1157–1208 | Human-in-the-loop approve/reject workflow |
| Prompt Broker API | 1230–1330 | Submit prompts, broker stats, rate control |
| GitHub DevOps Proxy | 1332–1394 | Branch, PR, merge proxy endpoints |
| Agent Registry | 1396–1420 | Template listing, start/stop agents |
| Instance Management | 1450–1650 | CRUD for worker instances, config, logs |
| Workspaces | 1700–1800 | Save/load/delete board snapshots |
| Model Registry | 725–794 | Authoritative service/model definitions |
| WebSocket Endpoint | 2000+ | `/ws` for real-time event streaming |

### Supported LLM Services

The backend maintains a canonical `SERVICE_MODELS` registry:

| Service | Models |
|---|---|
| **Anthropic** | Claude Opus 4.6, Sonnet 4, Haiku 3.5 |
| **Google** | Gemini 2.5 Pro, Pro Preview, Flash, Flash-Lite |
| **OpenAI** | GPT-4o, GPT-4o Mini, o3-mini, o1 |
| **DeepSeek** | Reasoner (R1), Chat (V3) |
| **MiniMax** | Text-01, MiniMax-01 |
| **Custom** | Any model via manual ID entry |

---

## 💾 Persistence Layer — `AegisStore`

SQLite-backed (default) or Firebase Firestore (optional). The store manages:

### Tables

**`columns`**

| Field | Type | Description |
|---|---|---|
| `id` | INTEGER PK | Auto-increment ID |
| `name` | TEXT | Display name |
| `position` | INTEGER | Sort order |
| `color` | TEXT | Hex color code |
| `integration_type` | TEXT | `github`, `jira`, `linear`, `firebase`, or NULL |
| `integration_mode` | TEXT | `read`, `write`, or `read_write` |
| `integration_credentials` | TEXT | JSON-encoded service credentials |
| `integration_filters` | TEXT | JSON-encoded filter params |
| `sync_interval_ms` | INTEGER | Polling interval in milliseconds |
| `integration_status` | TEXT | Last sync status |

**`cards`**

| Field | Type | Description |
|---|---|---|
| `id` | INTEGER PK | Auto-increment ID |
| `title` | TEXT | Card title |
| `description` | TEXT | Full description (supports @mentions) |
| `column` | TEXT | Current column name |
| `assignee` | TEXT | Worker instance name or NULL |
| `status` | TEXT | `idle`, `assigned`, `running`, `approved`, `rejected` |
| `priority` | TEXT | `low`, `normal`, `high` |
| `depends_on` | TEXT | JSON array of card IDs |
| `comments` | TEXT | JSON array of `{author, content, timestamp}` |
| `card_group` | TEXT | Swimlane group header |
| `card_tags` | TEXT | JSON array of tag strings |
| `external_id` | TEXT | ID in external system (e.g. `issue-42`, `pr-7`) |
| `external_source` | TEXT | Source identifier (`github`, `jira`, etc.) |
| `external_url` | TEXT | Direct link to external item |
| `metadata` | TEXT | JSON blob (labels, assignees, PR state, etc.) |
| `last_synced_hash` | TEXT | SHA-256 of last synced description (loop guard) |
| `created_at` | TEXT | ISO timestamp |

### Key Methods

| Method | Description |
|---|---|
| `create_card(title, description, column, assignee, **kwargs)` | Creates card with optional external/metadata fields |
| `update_card(card_id, **kwargs)` | Updates arbitrary fields |
| `get_card(card_id)` | Full card with parsed JSON fields |
| `get_cards(column=None)` | All cards, optionally filtered |
| `delete_card(card_id)` | Hard delete |
| `find_card_by_external_id(external_id, source)` | Deduplication lookup |
| `create_column(name, position, color)` | New board column |
| `update_column(col_id, **kwargs)` | Update display properties |
| `update_column_integration(col_id, **kwargs)` | Update integration config fields |

---

## 🔧 Execution Engine — `execution_engine.py`

Factory-pattern architecture for managing agent process lifecycles.

### Components

**`AgentProcess`** — Tracks a running agent with full metadata:

- `agent_id`, `pid`, `process` handle
- `instance_id`, `instance_name`
- `icon`, `color` (visual identity)
- `started_at`, `exit_code`
- `logs[]`, `activity` (Thinking/Acting/Waiting)

**`ExecutionAdapter`** — Abstract strategy interface:

- `create_process(agent_id, config, card, env)` → `AgentProcess`
- `kill_process(agent_proc)`

**`SubprocessAdapter`** — Default. Runs agents as bare-metal Python subprocesses:

- Sets up environment variables (`AEGIS_API_URL`, `INSTANCE_ID`, API keys)
- Redirects `stdout`/`stderr` to pipes for log capture
- Graceful termination with `SIGTERM` → `SIGKILL` fallback

**`DockerAdapter`** — Optional. Runs agents in isolated Docker containers:

- Auto-detects Docker availability
- Mounts instance workspace as a volume
- Container naming: `aegis-{agent_id}-{card_id}`
- Network isolation with `--network none` option

### `ExecutionEngine`

The central coordinator:

| Method | Description |
|---|---|
| `run_agent(card_id, agent_id, config, card, store)` | Create process + start monitoring |
| `stop_agent(card_id)` | Kill process by card ID |
| `stop_instance(instance_id)` | Kill process by instance ID |
| `running_tasks()` | List all active `AgentProcess` dicts |
| `start_health_polling()` | 5-second crash detection loop |
| `lifecycle_hook(card_id, new_column, store)` | Auto-kill on Review/Done transitions |
| `write_to_stdin(instance_id, text)` | Intervention tool — inject input into running agent |
| `get_instance_logs(instance_id, tail)` | Read last N log lines |

### Instance Management Flow

```
Template (read-only)  →  Instance (working copy)  →  Running Process
     aegis-worker/          aegis-worker-a3f2/         PID 12345
     worker.py              worker.py (copy)           ↓
                            config.json                stdout → logs
                            workspace/                 ↓
                                                       health polling
```

1. **Templates** live in `aegis_data/templates/`. They are the source-of-truth code.
2. **Instances** are created from templates via `POST /api/instances`. Each gets a unique ID, its own directory under `aegis_data/instances/`, and a copy of the template code.
3. **Processes** are spawned by the Execution Engine when an instance is started. Environment variables inject the API URL, instance ID, API keys, and model selection.

---

## 🚦 Prompt Broker — `prompt_broker.py`

Centralized rate-limited queue for all outbound LLM requests. Prevents API quota exhaustion when multiple agents are active.

### Architecture

```
Agent A ──┐
Agent B ──┤──→ [Queue] ──→ Rate Limiter ──→ LLM API
Agent C ──┘         ↑           ↓
                    └── Retry / Dead-Letter
```

### Configuration

| Parameter | Default | Description |
|---|---|---|
| `prompts_per_minute` | 1 | PPM rate limit (configurable via UI) |
| `max_retries` | 3 | Retry count before dead-lettering |

### API

| Method | Description |
|---|---|
| `start()` | Start the async processing loop |
| `stop()` | Graceful shutdown |
| `pause()` / `resume()` | Pause/unpause processing |
| `set_rate(ppm)` | Update PPM dynamically |
| `submit(request)` | Enqueue a `PromptRequest` |
| `get_stats()` | Returns queue depth, processing status, token estimates |

### Stats Returned

```json
{
  "total_submitted": 42,
  "total_processed": 40,
  "total_failed": 1,
  "total_retried": 3,
  "dead_letters": 1,
  "estimated_tokens": 18400,
  "queue_depth": 1,
  "paused": false,
  "prompts_per_minute": 1,
  "broker_interval_seconds": 60.0,
  "in_progress": {"card_id": 7, "agent_name": "coder-01"}
}
```

---

## 🤖 Worker Template — `worker.py`

The agent script that runs inside each worker instance. Implements a **ReAct (Reason + Act) loop**.

### Lifecycle

```
BOOT → [Configure from env vars]
  ↓
PULSE LOOP (repeats every pulse_interval seconds):
  ├── Fetch live config from /api/instances/{id}/config
  ├── Fetch board state: GET /api/cards + GET /api/columns
  ├── Fetch system prompt: GET /api/system_prompt
  ├── If assigned to a card → GET /api/cards/{id}/context (smart context)
  ├── Build board snapshot string for LLM
  ├── ReAct Loop (max 5 steps per pulse):
  │   ├── THINK: LLM reasons about what to do
  │   ├── ACT: Execute the chosen action
  │   └── OBSERVE: Capture result, feed back to LLM
  ├── Send pulse heartbeat to UI
  └── Sleep pulse_interval seconds
```

### Environment Variables

| Variable | Description |
|---|---|
| `AEGIS_API_URL` | Base URL of the Aegis server |
| `INSTANCE_ID` | Unique instance identifier |
| `AGENT_NAME` | Display name for this worker |
| `AGENT_GOAL` | Natural-language goal directive |
| `ANTHROPIC_API_KEY` | Anthropic API key |
| `OPENAI_API_KEY` | OpenAI API key |
| `GOOGLE_API_KEY` | Google/Gemini API key |
| `DEEPSEEK_API_KEY` | DeepSeek API key |
| `MINIMAX_API_KEY` | MiniMax API key |
| `AEGIS_SERVICE` | LLM service to use |
| `AEGIS_MODEL` | Model ID |
| `AEGIS_PULSE_INTERVAL` | Seconds between pulses |
| `AEGIS_MODE` | `continuous` or `one-shot` |

### Supported LLM Services

The worker supports direct API calls to:

- **Anthropic** (Claude) — Messages API
- **Google** (Gemini) — GenerateContent API
- **OpenAI** — Chat Completions API
- **DeepSeek** — OpenAI-compatible endpoint
- **MiniMax** — Chat Completions endpoint

### Available Actions (Full Tool Set)

#### Board Management

| Action | Arguments | Description |
|---|---|---|
| `create_card` | `title, description, column, assignee` | Create a new task card |
| `update_card` | `card_id, title, description, column, assignee, status, priority` | Update any card field |
| `delete_card` | `card_id` | Remove a card |
| `post_comment` | `card_id, content` | Add a comment to a card |
| `create_column` | `name, position` | Create a new board column |
| `delete_column` | `column_id` | Delete a column |

#### File System

| Action | Arguments | Description |
|---|---|---|
| `list_dir` | `path` | List files in a directory |
| `read_file` | `path` | Read file contents |
| `write_file` | `path, content` | Write/overwrite a file |

#### Git CLI (Local Operations)

| Action | Arguments | Description |
|---|---|---|
| `git_clone` | `repo_url, dest` | Shallow-clone a repository |
| `git_branch` | `branch_name, checkout, cwd` | Create/checkout a local branch |
| `git_commit` | `message, files, cwd` | Stage + commit (auto-attributed with `[Aegis: AgentName]`) |
| `git_push` | `remote, branch, cwd` | Push to remote |

#### GitHub API (via Aegis Proxy)

| Action | Arguments | Description |
|---|---|---|
| `create_branch_remote` | `branch_name, base` | Create a branch via GitHub API |
| `create_pr` | `title, body, head, base` | Open a Pull Request |
| `merge_pr` | `pr_number, merge_method, commit_message` | Merge a PR (squash/merge/rebase) |
| `list_prs` | `state` | List Pull Requests |
| `list_branches` | — | List repo branches |

#### Control Flow

| Action | Arguments | Description |
|---|---|---|
| `wait` | `reason` | End the pulse (agent is blocked or idle) |
| `done` | `reason` | Mark task as complete |
| `notify` | `message, mood` | Emit a notification bubble |

### Smart Context System

When a worker is assigned to a card, it receives an optimized context bundle via `GET /api/cards/{id}/context`:

```json
{
  "focus_card": { /* Full card details */ },
  "related_context": [ /* Cards referenced via @id mentions */ ],
  "board_directory": [ /* Skinny list of all other cards */ ],
  "column_info": { "name": "In Progress", "is_read_only": false }
}
```

This minimizes LLM token usage while providing full situational awareness.

---

## 📋 System Prompt — Agent Instruction Set

Stored in `aegis_data/system_prompt.txt` (editable via the UI at runtime). The default prompt includes:

- **Board structure rules**: Columns, cards, priorities, statuses
- **Core rules**: Always act via JSON, never duplicate work, use @mentions for linking
- **All available actions**: Board, file, git, and GitHub tools with exact argument schemas
- **Safety warnings**: Branch protection, commit attribution
- **Personality system**: Agents express themselves via the `thought` field
- **ReAct format**: Strict JSON array with `thought`, `action`, `args` per step

Template variables `{agent_name}` and `{goal}` are substituted at runtime.

---

## 🔗 Integrations Framework

### Architecture

```
IntegrationManager (coordinator)
    ├── GitHub Integration (Issues + PRs + Branches)
    ├── Jira Integration (Jira Cloud)
    ├── Linear Integration (Linear.app)
    └── Firebase Integration (Firestore collections)
```

### `BaseIntegration` (Abstract)

All adapters implement:

| Method | Description |
|---|---|
| `sync_in()` | Pull external items → Aegis cards |
| `sync_out(card, event_type)` | Push card changes → external service |
| `handle_webhook(payload, headers)` | Process inbound webhooks |
| `register_webhook(url)` | Register webhook with external service |

### `IntegrationManager`

Central coordinator that:

1. Loads integrations from DB at startup
2. Manages per-integration async polling loops
3. Routes webhooks to correct adapter
4. Notifies adapters of card changes for sync-out
5. Exposes status via `GET /api/integrations`

### Binding

Integrations are column-bound. Each column can have at most one integration:

```
POST /api/columns
{
  "name": "GitHub Issues",
  "integration": {
    "type": "github",
    "mode": "read_write",
    "credentials": {"token": "ghp_...", "repo": "owner/repo"},
    "filters": {"state": "open", "labels": "bug"},
    "sync_interval_ms": 60000
  }
}
```

### Deduplication & Loop Guard

- **Deduplication**: Uses `(external_id, external_source)` composite key to avoid duplicate cards.
- **Sync Guard**: SHA-256 hash of description content (`last_synced_hash`) prevents infinite sync loops between board and external service.

---

## 🔀 GitHub DevOps — Full Lifecycle

Workers can autonomously manage the complete development lifecycle:

### PR Sync-In

The GitHub adapter pulls open PRs into Aegis as cards prefixed `[PR #N]`, with rich metadata:

```json
{
  "type": "pull_request",
  "state": "open",
  "head_branch": "fix/login-bug",
  "base_branch": "main",
  "mergeable": true,
  "draft": false,
  "labels": ["enhancement"]
}
```

### Backend Proxy Endpoints

Workers call GitHub operations through the Aegis API (centralized auth):

| Endpoint | Method | Description |
|---|---|---|
| `/api/github/branches` | GET | List all branches |
| `/api/github/branches` | POST | Create a new branch |
| `/api/github/pulls` | GET | List pull requests |
| `/api/github/pulls` | POST | Open a pull request |
| `/api/github/pulls/merge` | POST | Merge a pull request |

### Autonomous Workflow Example

```
1. Worker picks up card "Fix login bug"
2. git_clone → clones the repo
3. git_branch → creates "fix/login-bug"
4. read_file, write_file → makes code changes
5. git_commit → commits with "[Aegis: WorkerName] Fix login bug"
6. git_push → pushes branch to origin
7. create_pr → opens PR "Fix login bug" (head: fix/login-bug → base: main)
8. post_comment → notes PR URL on the card
9. update_card → moves card to Review
```

### Safety Controls

- **Branch Protection**: Agents create feature branches. System prompt warns never to push directly to `main`.
- **Commit Attribution**: All commits are prefixed `[Aegis: AgentName]` for traceability.
- **Merge Methods**: Supports `squash`, `merge`, and `rebase` strategies.

---

## 🤝 A2A Protocol Layer — `a2a.py`

Implements the [Agent-to-Agent (A2A)](https://google.github.io/A2A/) protocol for cross-system interoperability.

### Endpoints

| Endpoint | Method | Description |
|---|---|---|
| `/.well-known/agent.json` | GET | AgentCard discovery (name, version, capabilities) |
| `/api/a2a/messages` | POST | Receive A2A messages from external agents |
| `/api/a2a/agents` | GET | List registered agent configurations |

### AgentCard

```json
{
  "name": "Aegis Orchestrator",
  "version": "2.0.0",
  "protocols": ["a2a/1.0", "mcp/1.0"],
  "capabilities": [
    {"name": "task_management", "description": "Create, update, and manage Kanban task cards"},
    {"name": "agent_orchestration", "description": "Route tasks to registered agents"},
    {"name": "log_streaming", "description": "Real-time agent output streaming via WebSocket"},
    {"name": "hitl_validation", "description": "Human-in-the-loop approval for completed work"}
  ]
}
```

### Supported Message Types

| Type | Description |
|---|---|
| `task.create` | External agent creates a card in the Inbox |
| `task.status` | External agent reports its activity state |

---

## 🔌 MCP Server — `mcp_server.py`

Implements the [Model Context Protocol (MCP)](https://modelcontextprotocol.io/) for structured tool access.

### Endpoints (all under `/api/mcp`)

| Endpoint | Method | Description |
|---|---|---|
| `/resources` | GET | List all MCP workspace directories |
| `/tools` | GET | List all available tools (core + skills) |
| `/tools/read_file` | POST | Read a file from a permitted workspace |
| `/tools/write_file` | POST | Write to a file in a permitted workspace |
| `/tools/list_dir` | POST | List directory contents |
| `/tools/call` | POST | Execute any registered tool by name |

### Path Validation & RBAC

- All file operations are scoped to permitted MCP workspaces (configured in `aegis.config.json`).
- Agent permissions are checked via `X-Aegis-Agent` header against the registry.
- Path traversal is blocked (`..` cannot escape workspace roots).

---

## 🧩 Skill Manager — `skill_manager.py`

Loads modular skills from the `aegis_data/skills/` directory. Compatible with the ClawHub skill format.

### Core Tools (Built-in)

| Tool | Description |
|---|---|
| `search_web` | Perform a web search |
| `read_url` | Fetch content from a URL |
| `shell_command` | Execute whitelisted shell commands (`ls`, `dir`, `pwd`, `date`, `whoami`) |

### Skill Loading

Skills are stored as directories with a `SKILL.md` file:

```
aegis_data/skills/
└── Calculator/
    ├── SKILL.md          # Name, description, parameter schema
    └── logic.py          # Execution entrypoint
```

The `SkillManager` scans for `SKILL.md` files, parses them for name/description/JSON schema, and registers them as MCP-compatible tools.

---

## 🖥️ Frontend Dashboard

Single-page application served from `static/index.html`.

### Views

| View | Description |
|---|---|
| **Board** | Kanban board with drag-and-drop, card groups, dependency badges |
| **Telemetry** | Real-time LLM usage stats, agent activity, cost metrics |
| **Integrations** | Manage column-bound external service connections |
| **Workflowspaces** | Save/load/delete board snapshots |

### Sidebar

| Section | Description |
|---|---|
| **Workers** | List of active worker instances with start/stop/delete/settings/logs |
| **Prompt Broker** | Collapsible panel with queue depth, PPM control, pause/resume |

### JS Modules

| Module | Lines | Purpose |
|---|---|---|
| `board.js` | 44K | Kanban rendering, drag-and-drop, card modals, column management |
| `agents.js` | 33K | Worker sidebar, create/edit modals, profile dropdown, icon picker |
| `websocket.js` | 12K | WebSocket lifecycle, event dispatch, reconnection |
| `mentions.js` | 9K | `@agent` and `@card` autocomplete in description/comment fields |
| `telemetry.js` | 6K | Telemetry dashboard charts and stats |
| `integrations.js` | 5K | Integration configuration UI |

### Create Worker Modal

The modal includes:

1. **Load Profile** dropdown — Select a saved profile to auto-fill all fields
2. Worker Name, Service, API Key (with live validation)
3. Model selection (populated from backend registry)
4. Icon picker (Emoji grid, URL, or file upload)
5. Brand color picker
6. Template-specific config form (rendered from config schema)
7. **Save as reusable profile** checkbox

---

## 📡 WebSocket Events

The dashboard connects to `/ws` for real-time updates. All events are JSON:

| Event Type | Payload | Trigger |
|---|---|---|
| `card_created` | `{card}` | New card created |
| `card_updated` | `{card}` | Card field changed |
| `card_deleted` | `{card_id}` | Card removed |
| `column_created` | `{column}` | New column |
| `column_deleted` | `{column_id}` | Column removed |
| `agent_started` | `{agent_id, instance_id, card_id}` | Worker process spawned |
| `agent_stopped` | `{agent_id, instance_id}` | Worker process terminated |
| `agent_log` | `{instance_id, line}` | New log line from worker |
| `agent_activity` | `{instance_id, status}` | Activity phase change |
| `agent_bubble` | `{instance_id, text, mood}` | Thought bubble (💡⚠️🛑📢) |
| `pulse` | `{instance_id, interval}` | Worker heartbeat for countdown |
| `integration_status` | `{column_id, status, error}` | Sync success/failure |
| `broker_stats` | `{queue_depth, ...}` | Broker state update |
| `intervention` | `{instance_id, text}` | Glass box stdin injection |

---

## 🔧 Configuration — `aegis.config.json`

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
    "aegis-worker": {
      "enabled": true,
      "isolation": "subprocess"
    }
  },
  "orchestration_mode": "supervisor",
  "database": "sqlite",
  "fire_base": {
    "enabled": false,
    "project_id": "",
    "credentials_path": ""
  },
  "a2a": { "agent_name": "Aegis Orchestrator", "version": "2.0.0" },
  "mcp": { "workspaces": [] },
  "discord": { "webhook_url": "" }
}
```

| Key | Description |
|---|---|
| `polling_rate_ms` | Integration sync polling interval |
| `max_concurrent_agents` | Max workers running simultaneously |
| `isolation_mode` | `strict` (subprocess) or `docker` |
| `rate_limits` | Prompt broker rate and retry config |
| `orchestration_mode` | `supervisor` (board-driven) |
| `database` | `sqlite` or `firebase` |
| `discord.webhook_url` | Discord notification webhook for Review cards |

---

## 📖 REST API Reference

### Columns

| Endpoint | Method | Description |
|---|---|---|
| `/api/columns` | GET | List all columns |
| `/api/columns` | POST | Create column (with optional integration) |
| `/api/columns/{id}` | PATCH | Update column name, position, color, integration |
| `/api/columns/{id}` | DELETE | Delete column (cascade or block) |

### Cards

| Endpoint | Method | Description |
|---|---|---|
| `/api/cards` | GET | List all cards (optional `?column=` filter) |
| `/api/cards` | POST | Create a card |
| `/api/cards/{id}` | GET | Get a single card |
| `/api/cards/{id}` | PATCH | Update card fields |
| `/api/cards/{id}` | DELETE | Delete card (optional `?close_external=true`) |
| `/api/cards/{id}/context` | GET | Smart context bundle for agents |
| `/api/cards/{id}/comments` | POST | Add comment `{author, content}` |
| `/api/cards/{id}/diff` | GET | Git diff of agent workspace changes |
| `/api/cards/{id}/approve` | POST | HITL approval → moves to Done |

### Workers & Instances

| Endpoint | Method | Description |
|---|---|---|
| `/api/registry` | GET | List available worker templates |
| `/api/instances` | GET | List all worker instances |
| `/api/instances` | POST | Create new instance from template |
| `/api/instances/{id}` | GET | Get instance details |
| `/api/instances/{id}` | PATCH | Update instance config |
| `/api/instances/{id}` | DELETE | Delete instance and files |
| `/api/instances/{id}/start` | POST | Start worker process |
| `/api/instances/{id}/stop` | POST | Stop worker process |
| `/api/instances/{id}/logs` | GET | Tail worker logs |
| `/api/instances/{id}/config` | GET | Get live config (polled by workers) |
| `/api/instances/{id}/pulse` | POST | Worker heartbeat event |
| `/api/instances/{id}/intervene` | POST | Glass box stdin injection |

### Profiles

| Endpoint | Method | Description |
|---|---|---|
| `/api/profiles` | GET | List saved profiles |
| `/api/profiles` | POST | Save a new profile |
| `/api/profiles/{id}` | DELETE | Delete a profile |

### Prompt Broker

| Endpoint | Method | Description |
|---|---|---|
| `/api/broker/stats` | GET | Queue stats, processing status |
| `/api/broker/submit` | POST | Submit prompt for rate-limited processing |
| `/api/broker/pause` | POST | Pause broker |
| `/api/broker/resume` | POST | Resume broker |
| `/api/broker/rate` | POST | Update PPM `{prompts_per_minute}` |
| `/api/broker/min-pulse` | GET | Minimum safe pulse interval |

### GitHub DevOps

| Endpoint | Method | Description |
|---|---|---|
| `/api/github/branches` | GET | List branches |
| `/api/github/branches` | POST | Create branch `{branch_name, base}` |
| `/api/github/pulls` | GET | List PRs `?state=open` |
| `/api/github/pulls` | POST | Create PR `{title, body, head, base}` |
| `/api/github/pulls/merge` | POST | Merge PR `{pr_number, merge_method}` |

### System

| Endpoint | Method | Description |
|---|---|---|
| `/api/config` | GET | Get `aegis.config.json` |
| `/api/config` | POST | Update config |
| `/api/system_prompt` | GET | Get current system prompt |
| `/api/system_prompt` | POST | Update system prompt |
| `/api/models` | GET | Service/model registry |
| `/api/models/{service}` | GET | Models for a specific service |
| `/api/assets/upload` | POST | Upload icon/media file |
| `/api/integrations` | GET | Integration status for all columns |
| `/api/integrations/{column_id}/sync` | POST | Force-sync an integration |
| `/api/verify-key` | POST | Validate an API key |

### Workspaces

| Endpoint | Method | Description |
|---|---|---|
| `/api/workspaces` | GET | List saved workspaces |
| `/api/workspaces` | POST | Save current board as workspace |
| `/api/workspaces/{name}` | GET | Load a workspace |
| `/api/workspaces/{name}` | DELETE | Delete a workspace |
| `/api/workspaces/{name}/merge` | POST | Merge workspace into current board |

### A2A Protocol

| Endpoint | Method | Description |
|---|---|---|
| `/.well-known/agent.json` | GET | AgentCard discovery |
| `/api/a2a/messages` | POST | Receive A2A messages |
| `/api/a2a/agents` | GET | List registered agents |

### MCP Protocol

| Endpoint | Method | Description |
|---|---|---|
| `/api/mcp/resources` | GET | List workspace resources |
| `/api/mcp/tools` | GET | List all tools |
| `/api/mcp/tools/read_file` | POST | Read file |
| `/api/mcp/tools/write_file` | POST | Write file |
| `/api/mcp/tools/list_dir` | POST | List directory |
| `/api/mcp/tools/call` | POST | Execute arbitrary tool |

---

## 🛡️ Safety & Guardrails

| Layer | Mechanism |
|---|---|
| **Read-Only Columns** | Columns with `integration_mode=read` block card writes/deletes from agents |
| **Branch Protection** | System prompt instructs agents to never push to `main` |
| **Commit Attribution** | All agent commits prefixed `[Aegis: AgentName]` |
| **Rate Limiting** | Prompt Broker enforces PPM with retry + dead-letter queue |
| **MCP Path Jail** | All file operations scoped to permitted workspace roots |
| **Shell Restrictions** | Only `ls`, `dir`, `pwd`, `date`, `whoami` allowed via MCP |
| **HITL Validation** | Cards must pass through Review before reaching Done |
| **Sync Loop Guard** | SHA-256 hash prevents infinite sync between board and external services |
| **Health Polling** | 5-second crash detection with auto-broadcast of agent termination |
| **Glass Box Intervention** | Humans can inject `stdin` into running agents at any time |
| **Discord Notifications** | Auto-webhook when cards enter Review for human attention |

---

*Forged with 💎 by the Advanced Agentic Coding team.*

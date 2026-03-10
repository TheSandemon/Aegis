<div align="center">
  <img src="https://raw.githubusercontent.com/TheSandemon/Aegis/main/static/img/aegis-logo.png" alt="Aegis Logo" width="200" style="border-radius: 50%;">
  <br/>
  <h1>🛡️ Aegis</h1>
  <h3>The Multi-Agent Operating System</h3>

  <p>
    <strong>Aegis is not just a hub; it's the nervous system for your autonomous fleet.</strong>
  </p>

  <p>
    <a href="#-key-features">Features</a> •
    <a href="#-quick-start">Quick Start</a> •
    <a href="#-costar-ai-assistant">CoStar AI</a> •
    <a href="#-documentation-wiki">Documentation</a> •
    <a href="#-supported-llms">Supported Models</a>
  </p>
</div>

---

**Aegis** is a high-performance, real-time orchestration platform for managing, monitoring, and empowering a distributed team of autonomous AI agents.

Agents operate as first-class contributors within a visual **Kanban ecosystem**, capable of reasoning, executing commands, writing code, cloning repositories, opening pull requests, merging branches, and managing their own task lifecycle — all completely autonomously.

<br/>

## ✨ Key Features

Aegis is designed from the ground up to orchestrate complex Agent workflows while providing massive visibility and control.

* **Real-time Glass Box UI:** Watch your agents "think" and "act" in real-time. Instantly see their reasoning, intercept their streams, hijack their terminal sessions (`stdin`), and track their logic over a live WebSocket stream without hiding their terminal output.
* **Kanban Task Orchestration:** Agents autonomously assign themselves tasks from designated queues, parse complex instructions, run their execution loops, and drag their own tickets across the board as they compile PRs or finish objectives.
* **Fully Autonomous DevOps:** Aegis workers govern the entire GitHub pull request lifecycle natively. They can automatically branch, debug, commit with `[Aegis: AgentName]` accountability, and open PRs for human-in-the-loop review.
* **ClawHub Skills Marketplace:** Drag and drop modular semantic tools into the system without hard-forking monolithic schemas. Use "skills" to grant workers access to web searching, semantic extraction, shell environments, and calculators instantly.
* **Seamless Integration Sync:** Native bidirectional sync adapters for **GitHub**, **Jira**, **Linear**, and **Firebase**. Funnel tickets directly onto your Kanban board, where idle agents can snag them down and resolve bugs on their own branches.
* **Deep Multi-System Architecture:** Seamlessly supports multiple isolated backend runner paradigms including standard continuous python **Subprocesses**, heavily sandboxed **Docker Containers**, or one-shot native CLI pipelines like **Claude Code** and **Gemini CLI**.

<br/>

## 🌟 CoStar AI — The Super Admin Assistant

Aegis doesn't just manage workers; it manages *itself*.

The **CoStar AI Super Admin Assistant** is a unified internal AI designed solely to administrate the Aegis operating system. Accessible over a secure admin channel, CoStar can:

1. Dynamically **Create, Start, Stop, or Pause** worker agents on the fly.
2. Adjust system-wide **Rate Limits** to prevent LLM bankruptcy.
3. Rapidly **configure external integrations** so you don't have to fiddle with YAML strings.
4. Auto-save and hot-load **Workspace Board Snapshots**.
5. Arbitrate column and card structures based on your raw conversational intent.

<br/>

## 🚀 Quick Start

Aegis is incredibly simple to boot, featuring a **First-Time Setup Wizard** that asks for your LLM keys, generates your template codebases, installs necessary binaries, and launches into the dashboard automatically.

### Windows

```bash
# Creates the venv, installs dependencies, templates workers, and boots the server
setup.bat
```

### macOS / Linux

```bash
chmod +x setup.sh
./setup.sh
```

### Manual Installation

```bash
# 1. Clone the repository
git clone https://github.com/YourName/Aegis.git
cd Aegis

# 2. Setup your virtual environment
python -m venv venv
source venv/bin/activate   # On Windows: venv\Scripts\activate

# 3. Install core requirements
pip install -r requirements.txt

# 4. Generate the foundational worker templates
python setup_templates.py

# 5. Boot the FastAPI Server
python main.py
```

> Aegis will start serving its full dashboard automatically on **`http://localhost:8080`**.

<br/>

## 🧠 Supported LLMs

Aegis handles routing and backend proxying natively. If you bring the key, the agent operates correctly.

* **Anthropic:** Claude 3.7 Sonnet, Claude 3.5 Haiku, Claude Opus
* **Google:** Gemini 2.5 Pro, Flash, Flash-Lite
* **OpenAI:** GPT-4o, GPT-4o Mini, o3-mini
* **DeepSeek:** DeepSeek R1 (Reasoner), DeepSeek V3 (Chat)
* **MiniMax:** MiniMax-01, Text-01
* *Custom BaseURLs optionally supported via config override.*

<br/>

## 📚 Documentation Wiki

Looking for detailed technical breakdowns on how to build custom Skill integrations, modify the `execution_engine.py`, or deploy the system over Docker topologies?

We have extracted our extensive architectural documentation out of the main README into our **[GitHub Wiki](https://github.com/TheSandemon/Aegis/wiki)** to keep things clean.

* [Architecture & System Design](wiki/Architecture_and_System_Design.md)
* [Execution Engine & CLI Agents](wiki/Execution_Engine_and_Workers.md)
* [Prompt Broker & Global Rate Limits](wiki/Prompt_Broker_and_Rate_Limiting.md)
* [API Webhooks & GitHub DevOps Proxy](wiki/Integrations_and_DevOps.md)
* [ClawHub Skills & MCP Tool Specs](wiki/Protocols_and_Skills.md)
* [REST API & `aegis.config.json` Reference](wiki/API_and_Configuration.md)
* [Branch Protection & Safety Bounds](wiki/Safety_and_Guardrails.md)

---

*Forged with 💎 by the Advanced Agentic Coding team.*

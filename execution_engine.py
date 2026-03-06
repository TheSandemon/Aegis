"""
Aegis Unified Execution Engine
Factory-pattern architecture: Templates are read-only installed agent code,
Instances are isolated working copies that can run concurrently.
"""

import os
import json
import asyncio
import time
import shutil
import logging
import secrets
from pathlib import Path
from typing import Optional, Callable, Coroutine, Any
from datetime import datetime
import sys

CONFIG_PATH = Path(__file__).parent / "aegis.config.json"
from abc import ABC, abstractmethod

logger = logging.getLogger("aegis.engine")

# Legacy compat
AGENTS_DIR = Path(__file__).parent / "agents"
AGENTS_DIR.mkdir(exist_ok=True)

# Factory directories
AEGIS_DATA = Path(__file__).parent / "aegis_data"
TEMPLATES_DIR = AEGIS_DATA / "templates"
INSTANCES_DIR = AEGIS_DATA / "instances"
INSTANCES_STATE_FILE = AEGIS_DATA / "instances.json"

AEGIS_DATA.mkdir(exist_ok=True)
TEMPLATES_DIR.mkdir(exist_ok=True)
INSTANCES_DIR.mkdir(exist_ok=True)


# ═══════════════════════════════════════════════════════════════════════════════════
# AGENT PROCESS STATE
# ═══════════════════════════════════════════════════════════════════════════════════

class AgentProcess:
    """Tracks a single running agent/instance process with full metadata."""

    def __init__(self, agent_id: str, pid: int, process,
                 card_id: Optional[int] = None, color: str = "#6366f1",
                 instance_id: Optional[str] = None,
                 instance_name: Optional[str] = None,
                 icon: str = "🤖"):
        self.agent_id = agent_id          # template id (e.g. openclaw-core)
        self.instance_id = instance_id    # unique instance id (e.g. openclaw-core-a1b2)
        self.instance_name = instance_name  # user-chosen name (e.g. Frontend-Coder)
        self.pid = pid
        self.process = process
        self.status = "running"
        self.paused = False
        self.card_id = card_id
        self.color = color
        self.icon = icon
        self.started_at = datetime.now().isoformat()
        self.exit_code: Optional[int] = None
        self.logs: list[str] = []
        self.activity: str = "idle" # Current phase (Thinking, Acting, Waiting)

    def to_dict(self) -> dict:
        return {
            "agent_id": self.agent_id,
            "instance_id": self.instance_id,
            "instance_name": self.instance_name,
            "pid": self.pid,
            "status": self.status,
            "paused": self.paused,
            "activity": self.activity,
            "card_id": self.card_id,
            "color": self.color,
            "icon": self.icon,
            "started_at": self.started_at,
            "exit_code": self.exit_code,
            "log_count": len(self.logs),
        }


# ═══════════════════════════════════════════════════════════════════════════════════
# EXECUTION ADAPTERS
# ═══════════════════════════════════════════════════════════════════════════════════

class ExecutionAdapter(ABC):
    """Base class for agent execution strategies."""

    @abstractmethod
    async def create_process(self, agent_id: str, agent_config: dict,
                             card: dict, env: dict,
                             instance_dir: Optional[Path] = None) -> Optional[asyncio.subprocess.Process]:
        ...

    @abstractmethod
    async def kill_process(self, agent_proc: AgentProcess) -> bool:
        ...


class SubprocessAdapter(ExecutionAdapter):
    """Runs agents as bare-metal subprocesses."""

    async def create_process(self, agent_id, agent_config, card, env,
                             instance_dir=None):
        command = agent_config.get("binary", "")
        if not command:
            exec_config = agent_config.get("execution", {})
            command = exec_config.get("command", "")
        if not command:
            logger.error(f"No command configured for agent '{agent_id}'")
            return None

        is_cli_agent = agent_config.get("cli_agent", False)

        # Instance dir takes priority over config working_dir
        if instance_dir and instance_dir.exists():
            working_dir = instance_dir
        else:
            working_dir = agent_config.get("execution", {}).get("working_dir", ".")
            working_dir = Path(working_dir).resolve()

        # Cross-platform command adjustments
        if os.name == "nt" and command.startswith("./"):
            parts = command.split(" ", 1)
            exe = parts[0].replace("/", "\\")
            if not any(exe.endswith(ext) for ext in [".exe", ".bat", ".cmd"]):
                exe += ".exe"
            command = exe + (" " + parts[1] if len(parts) > 1 else "")

        # Use sys.executable instead of "python" to ensure we use the same environment
        if command.startswith("python "):
            command = command.replace("python ", f'"{sys.executable}" ', 1)

        # CLI agents: resolve npx/global binaries, skip worker.py sync
        if is_cli_agent:

            # On Windows, try to find the CLI as a .cmd script (npm global installs)
            if os.name == "nt":
                cmd_base = command.split()[0]
                cmd_path = shutil.which(cmd_base) or shutil.which(cmd_base + ".cmd")
                if cmd_path:
                    command = command.replace(cmd_base, f'"{cmd_path}"', 1)

            logger.info(f"CLI agent starting: command={command}, cwd={working_dir}")
        elif working_dir and working_dir.exists():
             # Auto-sync worker.py from template on every start (standard workers only)
             template_worker = TEMPLATES_DIR / agent_id / "worker.py"
             instance_worker = working_dir / "worker.py"
             if template_worker.exists():
                 try:
                     shutil.copy2(str(template_worker), str(instance_worker))
                     logger.info(f"Auto-synced worker.py from template '{agent_id}' to {working_dir}")
                 except Exception as e:
                     logger.warning(f"Failed to auto-sync worker.py: {e}")

             worker_exists = instance_worker.exists()
             logger.info(f"Subprocess starting: command={command}, cwd={working_dir}, worker_exists={worker_exists}")
             if not worker_exists:
                 logger.error(f"CRITICAL: worker.py MISSING in {working_dir}")
        else:
             logger.warning(f"Subprocess starting with NO CWD or non-existent CWD: {working_dir}")

        # CLI agents need stdin for interactive operation
        needs_stdin = is_cli_agent or agent_config.get("execution", {}).get("interactive", False)

        process = await asyncio.create_subprocess_shell(
            command,
            stdin=asyncio.subprocess.PIPE if needs_stdin else asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(working_dir) if working_dir and working_dir.exists() else None,
            env=env
        )
        return process

    async def kill_process(self, agent_proc):
        try:
            if os.name == 'nt':
                # On Windows, create_subprocess_shell leaves orphan processes if only the shell is killed.
                # Use taskkill /T (tree) /F (force) to ensure everything dies.
                try:
                    proc = await asyncio.create_subprocess_exec(
                        "taskkill", "/F", "/T", "/PID", str(agent_proc.process.pid),
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE
                    )
                    await proc.wait()
                    return True
                except Exception as e:
                    logger.debug(f"Taskkill failed (maybe already dead): {e}")
            
            agent_proc.process.terminate()
            try:
                await asyncio.wait_for(agent_proc.process.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                agent_proc.process.kill()
                await agent_proc.process.wait()
            return True
        except Exception as e:
            logger.error(f"Failed to terminate subprocess for '{agent_proc.agent_id}': {e}")
            return False


class DockerAdapter(ExecutionAdapter):
    """Runs agents inside isolated Docker containers."""

    def __init__(self):
        self._docker_available = shutil.which("docker") is not None
        self._containers: dict[int, str] = {}  # card_id -> container_name

    async def create_process(self, agent_id, agent_config, card, env,
                             instance_dir=None):
        if not self._docker_available:
            logger.warning("CRITICAL SECURITY WARNING: Docker is not available. Falling back to SubprocessAdapter! Agents will execute code directly on the host OS. Proceed with extreme caution.")
            fallback = SubprocessAdapter()
            return await fallback.create_process(agent_id, agent_config, card, env, instance_dir)

        image = agent_config.get("docker_image", "python:3.11-slim")
        if not image:
            logger.error(f"No docker_image configured for agent '{agent_id}'")
            return None

        card_id = card.get("id", 0)
        container_name = f"aegis-{agent_id}-{card_id}"

        try:
            from main import CONFIG
            mcp_workspaces = CONFIG.get("mcp", {}).get("workspaces", [])
        except ImportError:
            mcp_workspaces = []

        volume_flags = []
        if instance_dir and instance_dir.exists():
            # Sync worker.py before mounting
            template_worker = TEMPLATES_DIR / agent_id / "worker.py"
            instance_worker = instance_dir / "worker.py"
            if template_worker.exists():
                try:
                    import shutil
                    shutil.copy2(str(template_worker), str(instance_worker))
                except Exception as e:
                    logger.warning(f"Failed to auto-sync worker.py: {e}")
            volume_flags.extend(["-v", f"{instance_dir.resolve()}:/workspace"])

        for ws in mcp_workspaces:
            path = ws.get("path", "")
            if path:
                volume_flags.extend(["-v", f"{path}:/workspace/mcp_{ws.get('name', 'ws')}:ro"])

        env_flags = []
        for k, v in env.items():
            if v:
                # Docker API requires host.docker.internal to route back to host localhost
                if k == "AEGIS_API_URL":
                    v = v.replace("localhost", "host.docker.internal").replace("127.0.0.1", "host.docker.internal")
                env_flags.extend(["-e", f"{k}={v}"])

        # Inject MCP Server URL so any MCP-aware agent can auto-discover Aegis tools
        api_url = env.get("AEGIS_API_URL", "http://localhost:42069")
        mcp_host = api_url.replace("localhost", "host.docker.internal").replace("127.0.0.1", "host.docker.internal")
        mcp_base = mcp_host.split("/api")[0].rstrip("/")
        env_flags.extend(["-e", f"AEGIS_MCP_URL={mcp_base}/mcp/sse"])

        cmd = [
            "docker", "run", "--rm",
            "--name", container_name,
            "--add-host", "host.docker.internal:host-gateway",  # Linux compat
            *env_flags,
            *volume_flags,
            image,
            "python", "-u", "/workspace/worker.py" # default command
        ]
        
        # If agent config specifies a custom command relative to workspace
        exec_cmd = agent_config.get("execution", {}).get("command", "")
        if exec_cmd:
             # Just replace python worker.py with their command
             cmd = cmd[:-3] + exec_cmd.split()

        # Enable stdin for interactive agents (claude-code, etc.)
        needs_stdin = agent_config.get("execution", {}).get("interactive", False)
        stdin_flag = asyncio.subprocess.PIPE if needs_stdin else asyncio.subprocess.DEVNULL

        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            stdin=stdin_flag,
        )
        self._containers[card_id] = container_name
        return process

    async def kill_process(self, agent_proc):
        card_id = agent_proc.card_id or 0
        container_name = self._containers.get(card_id)
        if container_name:
            try:
                proc = await asyncio.create_subprocess_exec(
                    "docker", "kill", container_name,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )
                await proc.wait()
                del self._containers[card_id]
                return True
            except Exception as e:
                logger.error(f"Failed to kill Docker container for '{agent_proc.agent_id}': {e}")
                return False
        # Fallback to process termination
        try:
            agent_proc.process.terminate()
            await agent_proc.process.wait()
            return True
        except Exception:
            return False


# ═══════════════════════════════════════════════════════════════════════════════════
# UNIFIED EXECUTION ENGINE
# ═══════════════════════════════════════════════════════════════════════════════════

class ExecutionEngine:
    """
    Unified execution engine with factory-pattern instance support.
    Keyed by instance_id so multiple instances of the same template can run.
    """

    def __init__(self, broadcaster=None, prompts_per_minute: int = 1):
        self.active: dict[str, AgentProcess] = {}  # instance_id -> AgentProcess
        self.broadcaster = broadcaster
        self._subprocess = SubprocessAdapter()
        self._docker = DockerAdapter()
        self._health_task: Optional[asyncio.Task] = None
        self._rate_limiter_last: float = 0.0
        self._rate_interval: float = 60.0 / prompts_per_minute
        self._running = False

    def _get_adapter(self, agent_config: dict) -> ExecutionAdapter:
        try:
            from main import CONFIG
            global_isolation = CONFIG.get("isolation_mode", "auto")
        except ImportError:
            global_isolation = "auto"
            
        isolation = agent_config.get("isolation", global_isolation)
        
        if isolation == "subprocess":
            return self._subprocess
        elif isolation == "docker":
            return self._docker
            
        # "auto" defaults to docker, but DockerAdapter gracefully falls back
        return self._docker

    @property
    def running_tasks(self) -> dict:
        """Returns all currently running agent processes."""
        return {
            aid: proc for aid, proc in self.active.items()
            if proc.status == "running"
        }

    # ─── Lifecycle ────────────────────────────────────────────────────────────

    async def start_health_polling(self):
        self._running = True
        self._health_task = asyncio.create_task(self._health_loop())
        logger.info("ExecutionEngine health polling started (5s interval)")

    async def stop_health_polling(self):
        self._running = False
        if self._health_task:
            self._health_task.cancel()
            try:
                await self._health_task
            except (asyncio.CancelledError, Exception):
                pass

    # ─── Run Agent (Instance-aware) ───────────────────────────────────────────

    async def run_agent(self, card_id: int, agent_id: str, agent_config: dict,
                        card: dict, store, registry_entry: Optional[dict] = None,
                        instance_id: Optional[str] = None,
                        instance_name: Optional[str] = None) -> dict:
        """
        Start an agent process. If instance_id is provided, uses the instance's
        isolated directory as cwd. Otherwise falls back to legacy behavior.
        """
        # Use instance_id as the key, fall back to agent_id for legacy
        key = instance_id or agent_id

        if key in self.active and self.active[key].status == "running":
            return {"error": f"'{key}' is already running", "status": "already_running"}

        # Merge execution config from registry if available
        merged_config = {**agent_config}
        if registry_entry:
            merged_config.setdefault("execution", registry_entry.get("execution", {}))
            # Propagate CLI agent flags from registry
            if registry_entry.get("cli_agent"):
                merged_config["cli_agent"] = True
                merged_config["api_key_env"] = registry_entry.get("api_key_env", "")

        # Determine color
        color = agent_config.get("color", "#6366f1")
        if registry_entry:
            color = registry_entry.get("color", color)

        # Rate limit
        await self._enforce_rate_limit()

        # Prepare env
        env = os.environ.copy()
        
        # Load per-instance env vars (API keys) from instances.json
        if instance_id:
            try:
                instances = load_instances()
                inst_meta = next((i for i in instances if i["instance_id"] == instance_id), None)
                if inst_meta:
                    inst_env = inst_meta.get("env_vars", {})
                    for k, v in inst_env.items():
                        if v:  # Only set if not empty
                            env[k] = str(v)

                    # For CLI agents: map user's generic api_key to the
                    # environment variable the CLI tool expects
                    if merged_config.get("cli_agent") and merged_config.get("api_key_env"):
                        target_env = merged_config["api_key_env"]
                        api_key = inst_env.get("api_key", "") or inst_env.get(target_env, "")
                        if api_key:
                            env[target_env] = api_key
                            logger.info(f"Mapped API key to {target_env} for CLI agent")
                        else:
                            logger.warning(f"CLI agent {instance_id} has no API key for {target_env}")
                        
                        # Map custom API Base URL if provided
                        api_base = inst_meta.get("config", {}).get("api_base_url", "")
                        if api_base:
                            if target_env == "GEMINI_API_KEY":
                                env["GOOGLE_GEMINI_BASE_URL"] = api_base
                                logger.info(f"Mapped custom base URL to GOOGLE_GEMINI_BASE_URL")
                            elif target_env == "ANTHROPIC_API_KEY":
                                env["ANTHROPIC_BASE_URL"] = api_base
                                logger.info(f"Mapped custom base URL to ANTHROPIC_BASE_URL")

                    # Also pass instance config (prompt, etc.) into merged_config
                    inst_config = inst_meta.get("config", {})
                    merged_config.setdefault("config", {}).update(inst_config)
            except Exception as e:
                logger.warning(f"Failed to load instance env_vars: {e}")

        # Set Aegis specific variables overriding everything else
        env["AEGIS_AGENT_ID"] = str(agent_id or "")
        env["AEGIS_CARD_ID"] = str(card_id or "")
        env["AEGIS_CARD_TITLE"] = str(card.get("title") or "")
        env["AEGIS_CARD_DESCRIPTION"] = str(card.get("description") or "")
        env["AEGIS_AGENT_PROFILE"] = str(agent_config.get("profile") or "")
        env["AEGIS_API_URL"] = str(os.environ.get("AEGIS_API_URL", "http://localhost:42069/api"))
        env["PYTHONUNBUFFERED"] = "1"
        env["PYTHONUTF8"] = "1"
        if instance_id:
            env["AEGIS_INSTANCE_ID"] = instance_id
            env["AEGIS_INSTANCE_NAME"] = instance_name or ""
            
            # Inject service and model if available in instance data
            try:
                instances = load_instances()
                inst_meta = next((i for i in instances if i["instance_id"] == instance_id), None)
                if inst_meta:
                    env["AEGIS_SERVICE"] = str(inst_meta.get("service") or "")
                    env["AEGIS_MODEL"] = str(inst_meta.get("model") or "")
                    # Inject config schema values as AEGIS_CONFIG_* env vars
                    inst_config = inst_meta.get("config", {})
                    for ck, cv in inst_config.items():
                        env_key = f"AEGIS_CONFIG_{ck.upper()}"
                        if isinstance(cv, list):
                            env[env_key] = ",".join(str(v) for v in cv)
                        else:
                            env[env_key] = str(cv or "")
            except Exception as e:
                logger.warning(f"Failed to load instance service/model: {e}")

        adapter = self._get_adapter(merged_config)

        # Resolve instance directory
        inst_dir = INSTANCES_DIR / instance_id if instance_id else None

        try:
            # Update card status
            store.update_card(card_id, status="running")
            if self.broadcaster:
                await self.broadcaster({"type": "card_updated", "card": store.get_card(card_id)})

            process = await adapter.create_process(agent_id, merged_config, card, env, inst_dir)
            if not process:
                store.update_card(card_id, status="error")
                return {"error": "Failed to create process", "status": "error"}

            # Track the process
            agent_proc = AgentProcess(
                agent_id, process.pid, process, card_id, color,
                instance_id=instance_id, instance_name=instance_name,
                icon=env.get("AEGIS_AGENT_ICON", "🤖")
            )
            agent_proc.is_cli = merged_config.get("cli_agent", False)
            self.active[key] = agent_proc

            # Start log streaming
            log_tag = instance_id or agent_id
            asyncio.create_task(self._stream_logs(agent_proc, process.stdout, "STDOUT", card_id, store))
            asyncio.create_task(self._stream_logs(agent_proc, process.stderr, "STDERR", card_id, store))

            logger.info(f"Started '{key}' (PID: {process.pid}) for card {card_id}")

            if self.broadcaster:
                await self.broadcaster({
                    "type": "agent_started",
                    "agent_id": agent_id,
                    "instance_id": instance_id,
                    "instance_name": instance_name,
                    "pid": process.pid,
                    "card_id": card_id,
                    "color": color
                })

            # Wait for completion in background
            asyncio.create_task(self._wait_for_completion(agent_proc, card_id, store, adapter))

            # --- CLI AGENT AUTONOMOUS PULSE LOOP ---
            # CLI agents (Claude Code, Gemini CLI) process stdin only on EOF,
            # so we can't inject prompts into a long-running REPL. Instead, we
            # spawn a new `cli -p "prompt"` one-shot process per pulse. Claude Code
            # maintains conversation history per working-directory, so subsequent
            # pulses use `--continue` to resume the conversation with full context.
            # Each individual invocation can do full multi-step reasoning with tools.
            if merged_config.get("cli_agent"):
                # Read config from the instance metadata
                _cli_config = {}
                try:
                    _instances = load_instances()
                    _inst = next((i for i in _instances if i["instance_id"] == instance_id), None)
                    if _inst:
                        _cli_config = _inst.get("config", {})
                except Exception:
                    pass

                _cli_goals = _cli_config.get("goals", "Process tasks from the Aegis board.")
                _cli_pulse = int(_cli_config.get("pulse_interval", 120))
                _cli_startup_delay = str(_cli_config.get("startup_delay", "false")).lower() == "true"
                _api_url = env.get("AEGIS_API_URL", "http://localhost:42069/api")

                # Resolve the CLI binary (e.g. claude, gemini)
                _base_command = merged_config.get("execution", {}).get("command", "")
                if os.name == "nt":
                    _cmd_base = _base_command.split()[0]
                    _cmd_path = shutil.which(_cmd_base) or shutil.which(_cmd_base + ".cmd")
                    if _cmd_path:
                        _base_command = _base_command.replace(_cmd_base, f'"{_cmd_path}"', 1)

                # Resolve working directory — use user config or instance dir
                _work_dir = _cli_config.get("work_dir", "")
                if _work_dir and Path(_work_dir).exists():
                    _cli_cwd = str(Path(_work_dir).resolve())
                elif inst_dir and inst_dir.exists():
                    _cli_cwd = str(inst_dir)
                else:
                    _cli_cwd = str(Path(".").resolve())

                # Determine if this is a Claude-based CLI
                _is_claude = "claude" in _base_command.lower()

                async def _cli_pulse_loop(_key, _proc, _goals, _pulse, _startup_delay,
                                          _api, _cmd, _cwd, _env, _is_claude_cli):
                    """Autonomous pulse loop: spawns one-shot CLI processes per pulse."""
                    import urllib.request, urllib.error
                    boot_wait = 5.0
                    if _startup_delay:
                        boot_wait += _pulse
                    await asyncio.sleep(boot_wait)

                    def _fetch_json(url):
                        try:
                            req = urllib.request.Request(url, headers={"Accept": "application/json"})
                            with urllib.request.urlopen(req, timeout=10) as resp:
                                return json.loads(resp.read().decode())
                        except Exception:
                            return None

                    robust_instruction = (
                        "You are an autonomous AI agent operating within the Aegis system. "
                        "Your primary objective is to continuously monitor the Aegis Kanban board for tasks and execute them to achieve your Goal. "
                        "You will receive periodic System Pulses containing the current board state. "
                        "When you receive a pulse, analyze the board, identify unassigned tasks relevant to your Goal, and use your tools to complete them. "
                        "CRITICAL: To update the board (e.g. creating, moving, or updating cards), you MUST make HTTP REST API requests to `http://localhost:42069/api`. "
                        "Do NOT modify the `aegis.db` SQLite database directly, as this bypasses the live UI updates. "
                        "If a user speaks to you directly in this terminal, prioritize their request, even if it alters your current focus. "
                        "Do not wait for user permission to act; use your tools to make progress independently."
                    )

                    pulse_count = 0
                    while _proc.status == "running":
                        pulse_count += 1
                        try:
                            # --- Stage 1: Fetch board state ---
                            async def _emit(_text):
                                _proc.logs.append(_text)
                                if self.broadcaster:
                                    await self.broadcaster({
                                        "type": "agent_log",
                                        "agent_id": _proc.agent_id,
                                        "instance_id": _proc.instance_id,
                                        "entry": _text + "\r\n"
                                    })

                            await _emit(f"📡 PULSE: Fetching board state (pulse #{pulse_count})...")

                            board_ctx = ""
                            try:
                                cards_data = await asyncio.to_thread(_fetch_json, f"{_api}/cards")
                                cols_data = await asyncio.to_thread(_fetch_json, f"{_api}/columns")
                                if cards_data and cols_data:
                                    col_names = ", ".join(c.get("name", "?") for c in cols_data)
                                    board_ctx = f"\n\nCurrent Board State:\nColumns: {col_names}\nCards:\n"
                                    for c in cards_data[:15]:
                                        board_ctx += f"  - [#{c.get('id')}] {c.get('title', '?')} | Col: {c.get('column', '?')} | Assignee: {c.get('assignee', 'None')}\n"
                                    await _emit(f"📋 Board loaded: {len(cards_data)} cards across {len(cols_data)} columns")
                                else:
                                    await _emit("⚠️ Could not fetch board state, proceeding with goal only")
                            except Exception as e:
                                logger.debug(f"CLI pulse: failed to fetch board state: {e}")
                                await _emit("⚠️ Board fetch failed, proceeding with goal only")

                            # --- Stage 2: Build the prompt ---
                            prompt_text = (
                                f"[Aegis System Pulse #{pulse_count}]\n"
                                f"Goal: {_goals}\n"
                                f"System Instructions: {robust_instruction}\n"
                            )
                            if pulse_count > 1:
                                prompt_text += "This is your autonomous pulse. Review the current board state, pick up any unassigned tasks, and continue working on your goal.\n"
                            prompt_text += board_ctx

                            # Escape the prompt for shell usage
                            safe_prompt = prompt_text.replace('"', '\\"').replace('\n', '\\n')

                            if _is_claude_cli:
                                one_shot_cmd = f'{_cmd} -p "{safe_prompt}"'
                                if pulse_count > 1:
                                    one_shot_cmd += " --continue"
                            else:
                                one_shot_cmd = f'{_cmd} "{safe_prompt}"'

                            # --- Stage 3: Spawn and stream ---
                            await _emit(f"🧠 THINKING: Consulting LLM (pulse #{pulse_count})...")

                            logger.info(f"CLI pulse #{pulse_count}: spawning one-shot for '{_key}'")

                            pulse_proc = await asyncio.create_subprocess_shell(
                                one_shot_cmd,
                                stdout=asyncio.subprocess.PIPE,
                                stderr=asyncio.subprocess.PIPE,
                                cwd=_cli_cwd,
                                env=_env
                            )

                            await _emit(f"⚡ WORKING: Agent processing task...")

                            # Stream output to the agent's terminal in real time
                            async def _stream_pulse_output(stream, proc_ref):
                                try:
                                    while True:
                                        chunk = await stream.read(4096)
                                        if not chunk:
                                            break
                                        decoded = chunk.decode(errors="replace")
                                        proc_ref.logs.append(decoded)
                                        if self.broadcaster:
                                            await self.broadcaster({
                                                "type": "agent_log",
                                                "agent_id": proc_ref.agent_id,
                                                "instance_id": proc_ref.instance_id,
                                                "entry": decoded
                                            })
                                except Exception:
                                    pass

                            await asyncio.gather(
                                _stream_pulse_output(pulse_proc.stdout, _proc),
                                _stream_pulse_output(pulse_proc.stderr, _proc),
                                pulse_proc.wait()
                            )

                            exit_code = pulse_proc.returncode
                            if exit_code == 0:
                                await _emit(f"✅ Action complete — pulse #{pulse_count} finished successfully")
                            else:
                                await _emit(f"⚠️ Pulse #{pulse_count} exited with code {exit_code}")

                            await _emit(f"💤 Waiting {_pulse}s until next pulse...")
                            
                            # Broadcast agent_pulse so the frontend starts the countdown timer
                            if self.broadcaster:
                                await self.broadcaster({
                                    "type": "agent_pulse",
                                    "agent_id": _proc.agent_id,
                                    "instance_id": _proc.instance_id,
                                    "interval": _pulse
                                })
                            logger.info(f"CLI pulse #{pulse_count} done for '{_key}' (exit: {exit_code})")

                        except Exception as e:
                            logger.error(f"CLI pulse error for '{_key}': {e}")

                        # Sleep until next pulse
                        await asyncio.sleep(_pulse)

                asyncio.create_task(_cli_pulse_loop(
                    key, agent_proc, _cli_goals,
                    _cli_pulse, _cli_startup_delay, _api_url,
                    _base_command, _cli_cwd, env, _is_claude
                ))

            return agent_proc.to_dict()

        except Exception as e:
            import traceback
            from datetime import datetime as _dt
            err_msg = traceback.format_exc()
            logs_dir = AEGIS_DATA / "logs"
            logs_dir.mkdir(exist_ok=True)
            crash_path = logs_dir / f"crash_{key}_{_dt.now().strftime('%Y%m%d_%H%M%S')}.log"
            with open(crash_path, "w", encoding="utf-8") as _f:
                _f.write(err_msg)
            logger.error(f"Failed to start '{key}': {e}\n{err_msg}")
            store.update_card(card_id, status="error")
            if self.broadcaster:
                await self.broadcaster({"type": "card_updated", "card": store.get_card(card_id)})
            return {"error": str(e) or "Unknown Error (see backend logs)", "status": "error"}

    async def _wait_for_completion(self, agent_proc: AgentProcess, card_id: int,
                                   store, adapter: ExecutionAdapter):
        """Waits for an agent process to finish and updates status."""
        try:
            return_code = await agent_proc.process.wait()
            if agent_proc.status == "stopped":
                status = "terminated"
            else:
                status = "completed" if return_code == 0 else "failed"

            agent_proc.status = status
            agent_proc.exit_code = return_code

            store.update_card(card_id, status=status)

            key = agent_proc.instance_id or agent_proc.agent_id

            if self.broadcaster:
                await self.broadcaster({"type": "card_updated", "card": store.get_card(card_id)})
                await self.broadcaster({
                    "type": "agent_status_changed",
                    "agent_id": agent_proc.agent_id,
                    "instance_id": agent_proc.instance_id,
                    "status": status,
                    "exit_code": return_code
                })

            logger.info(f"'{key}' finished with status '{status}' (code: {return_code})")

        except Exception as e:
            logger.error(f"Error waiting for agent '{agent_proc.agent_id}': {e}")

    # ─── Stop Agent ───────────────────────────────────────────────────────────

    async def stop_agent(self, agent_id: str) -> dict:
        """Stop a running agent process."""
        agent_proc = self.active.get(agent_id)
        if not agent_proc or agent_proc.status != "running":
            # If it's not active or running, it's effectively stopped already.
            # Return success to let the UI clear its "running" state
            return {"success": True, "status": "stopped", "message": f"Agent '{agent_id}' was already stopped."}

        adapter = self._get_adapter({"isolation": "subprocess"})  # Default
        agent_proc.status = "stopped"
        success = await adapter.kill_process(agent_proc)

        if success:
            agent_proc.exit_code = agent_proc.process.returncode
            logger.info(f"Stopped agent '{agent_id}' (PID: {agent_proc.pid})")

            if self.broadcaster:
                await self.broadcaster({
                    "type": "agent_stopped",
                    "agent_id": agent_id,
                    "pid": agent_proc.pid
                })

        return agent_proc.to_dict()

    async def stop_by_card(self, card_id: int) -> bool:
        """Stop the agent working on a specific card."""
        for agent_id, proc in self.active.items():
            if proc.card_id == card_id and proc.status == "running":
                result = await self.stop_agent(agent_id)
                return "error" not in result
        return False

    # ─── Intervention: Pause / Resume / Inject ────────────────────────────────

    async def pause_agent(self, agent_id: str) -> dict:
        """Pause (suspend) a running agent process."""
        agent_proc = self.active.get(agent_id)
        if not agent_proc or agent_proc.status != "running":
            return {"error": f"Agent '{agent_id}' is not running"}
        if agent_proc.paused:
            return {"error": f"Agent '{agent_id}' is already paused"}

        try:
            if os.name == 'nt':
                import ctypes
                kernel32 = ctypes.windll.kernel32
                handle = kernel32.OpenProcess(0x1F0FFF, False, agent_proc.pid)
                ntdll = ctypes.windll.ntdll
                ntdll.NtSuspendProcess(handle)
                kernel32.CloseHandle(handle)
            else:
                import signal
                os.kill(agent_proc.pid, signal.SIGSTOP)

            agent_proc.paused = True
            logger.info(f"Paused agent '{agent_id}' (PID: {agent_proc.pid})")

            if self.broadcaster:
                await self.broadcaster({
                    "type": "agent_paused",
                    "agent_id": agent_id,
                    "instance_id": agent_proc.instance_id
                })

            return {"success": True, "status": "paused"}
        except Exception as e:
            logger.error(f"Failed to pause '{agent_id}': {e}")
            return {"error": str(e)}

    async def resume_agent(self, agent_id: str) -> dict:
        """Resume a paused agent process."""
        agent_proc = self.active.get(agent_id)
        if not agent_proc or agent_proc.status != "running":
            return {"error": f"Agent '{agent_id}' is not running"}
        if not agent_proc.paused:
            return {"error": f"Agent '{agent_id}' is not paused"}

        try:
            if os.name == 'nt':
                import ctypes
                kernel32 = ctypes.windll.kernel32
                handle = kernel32.OpenProcess(0x1F0FFF, False, agent_proc.pid)
                ntdll = ctypes.windll.ntdll
                ntdll.NtResumeProcess(handle)
                kernel32.CloseHandle(handle)
            else:
                import signal
                os.kill(agent_proc.pid, signal.SIGCONT)

            agent_proc.paused = False
            logger.info(f"Resumed agent '{agent_id}' (PID: {agent_proc.pid})")

            if self.broadcaster:
                await self.broadcaster({
                    "type": "agent_resumed",
                    "agent_id": agent_id,
                    "instance_id": agent_proc.instance_id
                })

            return {"success": True, "status": "running"}
        except Exception as e:
            logger.error(f"Failed to resume '{agent_id}': {e}")
            return {"error": str(e)}

    async def inject_stdin(self, agent_id: str, text: str, newline: bool = False) -> dict:
        """Write text to a running agent's stdin pipe. 
        If newline is True, appends \\n and logs the injection as a discrete event."""
        agent_proc = self.active.get(agent_id)
        if not agent_proc or agent_proc.status != "running":
            return {"error": f"Agent '{agent_id}' is not running"}

        try:
            if agent_proc.process.stdin:
                payload = text + "\n" if newline else text
                agent_proc.process.stdin.write(payload.encode())
                await agent_proc.process.stdin.drain()

                if newline:
                    # Log the discrete injection
                    entry = f"[INJECT] {text}"
                    agent_proc.logs.append(entry)

                    if self.broadcaster:
                        await self.broadcaster({
                            "type": "log_entry",
                            "card_id": agent_proc.card_id,
                            "entry": entry
                        })
                    logger.info(f"Injected stdin to '{agent_id}': {text[:50]}")
                return {"success": True}
            else:
                return {"error": "Process stdin not available (pipe not open)"}
        except Exception as e:
            logger.error(f"Failed to inject stdin to '{agent_id}': {e}")
            return {"error": str(e)}

    # ─── Status Queries ───────────────────────────────────────────────────────

    def get_status(self, agent_id: str) -> Optional[dict]:
        agent_proc = self.active.get(agent_id)
        return agent_proc.to_dict() if agent_proc else None

    def get_all_active(self) -> list[dict]:
        return [proc.to_dict() for proc in self.active.values()]

    def get_logs(self, agent_id: str, tail: int = 100) -> list[str]:
        # agent_id here is actually the instance_id
        log_file = INSTANCES_DIR / agent_id / "logs.jsonl"
        if log_file.exists():
            try:
                with open(log_file, "r", encoding="utf-8") as f:
                    lines = f.readlines()[-tail:]
                    parsed = []
                    for line in lines:
                        try:
                            obj = json.loads(line)
                            parsed.append(obj.get('content', ''))
                        except:
                            parsed.append(line.strip())
                    return parsed
            except Exception as e:
                logger.error(f"Failed to read logs.jsonl for {agent_id}: {e}")
                
        agent_proc = self.active.get(agent_id)
        return agent_proc.logs[-tail:] if agent_proc else []

    # ─── Log Streaming ────────────────────────────────────────────────────────

    async def _stream_logs(self, agent_proc: AgentProcess, stream,
                           log_type: str, card_id: int, store):
        """Streams stdout/stderr to log buffer, card logs, and WebSocket."""
        is_cli = getattr(agent_proc, 'is_cli', False)
        try:
            while True:
                if is_cli:
                    # CLI agents (Claude Code, Gemini CLI) use interactive TUIs
                    # that don't emit clean newlines. Read raw byte chunks instead.
                    chunk = await stream.read(4096)
                    if not chunk:
                        break
                    decoded = chunk.decode(errors="replace")
                else:
                    line = await stream.readline()
                    if not line:
                        break
                    decoded = line.decode(errors="replace").strip()

                if not decoded:
                    continue

                entry = decoded
                agent_proc.logs.append(entry)

                # Persistent JSONL Disk Logging
                try:
                    if agent_proc.instance_id:
                        inst_dir = INSTANCES_DIR / agent_proc.instance_id
                        if inst_dir.exists():
                            lower_dec = decoded.lower()
                            tag = "error" if "error" in lower_dec or "fatal" in lower_dec or "traceback" in lower_dec else \
                                  ("thought" if "thought" in lower_dec else \
                                  ("action" if "action" in lower_dec or "tool" in lower_dec else "output"))
                                  
                            log_obj = {
                                "timestamp": datetime.now().isoformat(),
                                "stream": log_type.lower(),
                                "tag": tag,
                                "content": decoded
                            }
                            with open(inst_dir / "logs.jsonl", "a", encoding="utf-8") as lf:
                                lf.write(json.dumps(log_obj) + "\n")
                except Exception as disk_err:
                    logger.error(f"Failed to write JSONL log: {disk_err}")

                # Update card logs (only for non-CLI to avoid flooding with raw TUI data)
                if not is_cli:
                    current = store.get_card(card_id)
                    if current:
                        logs = current.get("logs", [])
                        logs.append(entry)
                        store.update_card(card_id, logs=json.dumps(logs))

                # Broadcast to clients
                if self.broadcaster:
                    await self.broadcaster({
                        "type": "log_entry",
                        "card_id": card_id,
                        "entry": entry
                    })
                    await self.broadcaster({
                        "type": "agent_log",
                        "agent_id": agent_proc.agent_id,
                        "instance_id": agent_proc.instance_id,
                        "entry": entry
                    })

        except Exception as e:
            logger.error(f"Log streaming error for {agent_proc.agent_id}: {e}")

    # ─── Health Polling ───────────────────────────────────────────────────────

    async def _health_loop(self):
        """Polls all running processes every 5 seconds for crashes."""
        while self._running:
            try:
                await asyncio.sleep(5)
                for agent_id, agent_proc in list(self.active.items()):
                    if agent_proc.status != "running":
                        continue
                    returncode = agent_proc.process.returncode
                    if returncode is not None:
                        agent_proc.status = "failed" if returncode != 0 else "completed"
                        agent_proc.exit_code = returncode
                        logger.warning(
                            f"Agent '{agent_id}' exited with code {returncode} "
                            f"(status: {agent_proc.status})"
                        )
                        if self.broadcaster:
                            await self.broadcaster({
                                "type": "agent_status_changed",
                                "agent_id": agent_id,
                                "status": agent_proc.status,
                                "exit_code": returncode
                            })
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Health polling error: {e}")

    # ─── Rate Limiting ────────────────────────────────────────────────────────

    async def _enforce_rate_limit(self):
        now = time.time()
        elapsed = now - self._rate_limiter_last
        if elapsed < self._rate_interval:
            wait = self._rate_interval - elapsed
            logger.info(f"Rate limit: waiting {wait:.1f}s before starting agent")
            await asyncio.sleep(wait)
        self._rate_limiter_last = time.time()

    # ─── Lifecycle Hook ───────────────────────────────────────────────────────

    async def lifecycle_hook(self, card_id: int, new_column: str, store, broadcaster):
        """Auto-kill agents when cards move to Review or Done."""
        if new_column in ("Review", "Done"):
            if await self.stop_by_card(card_id):
                logger.info(f"Lifecycle hook: Stopped agent for card {card_id} → {new_column}")


# ═══════════════════════════════════════════════════════════════════════════════════
# TEMPLATE INSTALLATION (Marketplace -> templates/)
# ═══════════════════════════════════════════════════════════════════════════════════

async def install_agent(agent_id: str, registry_entry: dict) -> dict:
    """Installs an agent template to aegis_data/templates/ (also keeps legacy agents/ compat)."""
    install_config = registry_entry.get("installation", {})
    method = install_config.get("method", "")
    github_url = registry_entry.get("github_url", "")
    setup_commands = install_config.get("setup_commands", [])

    template_dir = TEMPLATES_DIR / agent_id
    # Also update legacy dir
    legacy_dir = AGENTS_DIR / agent_id

    if template_dir.exists():
        return {"status": "already_installed", "path": str(template_dir)}

    try:
        if method == "git_clone" and github_url:
            proc = await asyncio.create_subprocess_exec(
                "git", "clone", github_url, str(template_dir),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await proc.communicate()

            if proc.returncode != 0:
                return {"status": "clone_failed", "error": stderr.decode(errors="replace")}

            results = []
            for cmd in setup_commands:
                setup_proc = await asyncio.create_subprocess_shell(
                    cmd, cwd=str(template_dir),
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )
                s_out, s_err = await setup_proc.communicate()
                results.append({
                    "command": cmd,
                    "exit_code": setup_proc.returncode,
                    "output": (s_out or s_err).decode(errors="replace")[:500]
                })
                if setup_proc.returncode != 0:
                    import shutil
                    shutil.rmtree(str(template_dir), ignore_errors=True)
                    return {"status": "setup_failed", "error": f"Command '{cmd}' failed.", "details": results}

            logger.info(f"Installed template '{agent_id}' to {template_dir}")
            return {"status": "installed", "path": str(template_dir), "setup_results": results}

        elif method == "npm_global":
            results = []
            for cmd in setup_commands:
                setup_proc = await asyncio.create_subprocess_shell(
                    cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )
                s_out, s_err = await setup_proc.communicate()
                results.append({
                    "command": cmd,
                    "exit_code": setup_proc.returncode,
                    "output": (s_out or s_err).decode(errors="replace")[:500]
                })
                if setup_proc.returncode != 0:
                    return {"status": "setup_failed", "error": f"Command '{cmd}' failed.", "details": results}

            template_dir.mkdir(parents=True, exist_ok=True)
            (template_dir / ".installed").write_text(datetime.now().isoformat(), encoding="utf-8")

            return {"status": "installed", "path": str(template_dir), "setup_results": results}

        else:
            return {"status": "unsupported_method", "method": method}

    except Exception as e:
        logger.error(f"Installation error for '{agent_id}': {e}")
        return {"status": "error", "error": str(e)}


# ═══════════════════════════════════════════════════════════════════════════════════
# INSTANCE MANAGEMENT (Factory Pattern)
# ═══════════════════════════════════════════════════════════════════════════════════

def load_instances() -> list[dict]:
    """Load persisted instance state from instances.json."""
    if INSTANCES_STATE_FILE.exists():
        try:
            return json.loads(INSTANCES_STATE_FILE.read_text(encoding="utf-8"))
        except Exception as e:
            logger.error(f"Failed to load instances.json: {e}")
    return []


def save_instances(instances: list[dict]):
    """Persist instance state to instances.json."""
    INSTANCES_STATE_FILE.write_text(json.dumps(instances, indent=2), encoding="utf-8")


def create_instance(template_id: str, instance_name: str,
                    registry_entry: Optional[dict] = None,
                    env_vars: Optional[dict] = None,
                    service: str = "",
                    model: str = "",
                    config: Optional[dict] = None,
                    icon: Optional[str] = None,
                    color: Optional[str] = None) -> dict:
    """
    Create a new instance from an installed template.
    Copies template files into a unique instance directory.
    """
    # Check template exists
    template_dir = TEMPLATES_DIR / template_id
    # Also check legacy agents/ dir
    if not template_dir.exists():
        template_dir = AGENTS_DIR / template_id
    if not template_dir.exists():
        return {"error": f"Template '{template_id}' is not installed"}

    # Generate unique instance id
    suffix = secrets.token_hex(2)  # 4 hex chars
    instance_id = f"{template_id}-{suffix}"
    instance_dir = INSTANCES_DIR / instance_id

    # Copy template → instance
    try:
        shutil.copytree(str(template_dir), str(instance_dir))
    except Exception as e:
        return {"error": f"Failed to copy template: {e}"}

    # Build instance metadata
    instance = {
        "instance_id": instance_id,
        "template_id": template_id,
        "instance_name": instance_name,
        "created_at": datetime.now().isoformat(),
        "path": str(instance_dir),
        "enabled": True,
        "icon": icon or (registry_entry.get("icon", "🤖") if registry_entry else "🤖"),
        "color": color or "#6366f1",
        "service": service,
        "model": model,
        "env_vars": env_vars or {},
        "config": config or {},
    }

    # Persist
    instances = load_instances()
    instances.append(instance)
    save_instances(instances)

    logger.info(f"Created instance '{instance_name}' ({instance_id}) from template '{template_id}'")
    return instance


def delete_instance(instance_id: str) -> dict:
    """Delete an instance and its files."""
    instances = load_instances()
    instance = next((i for i in instances if i["instance_id"] == instance_id), None)
    if not instance:
        return {"error": f"Instance '{instance_id}' not found"}

    # Remove files
    instance_dir = INSTANCES_DIR / instance_id
    if instance_dir.exists():
        shutil.rmtree(str(instance_dir), ignore_errors=True)

    # Remove from state
    instances = [i for i in instances if i["instance_id"] != instance_id]
    save_instances(instances)

    logger.info(f"Deleted instance '{instance_id}'")
    return {"success": True, "instance_id": instance_id}


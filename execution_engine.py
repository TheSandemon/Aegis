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
                 instance_name: Optional[str] = None):
        self.agent_id = agent_id          # template id (e.g. openclaw-core)
        self.instance_id = instance_id    # unique instance id (e.g. openclaw-core-a1b2)
        self.instance_name = instance_name  # user-chosen name (e.g. Frontend-Coder)
        self.pid = pid
        self.process = process
        self.status = "running"
        self.paused = False
        self.card_id = card_id
        self.color = color
        self.started_at = datetime.now().isoformat()
        self.exit_code: Optional[int] = None
        self.logs: list[str] = []

    def to_dict(self) -> dict:
        return {
            "agent_id": self.agent_id,
            "instance_id": self.instance_id,
            "instance_name": self.instance_name,
            "pid": self.pid,
            "status": self.status,
            "paused": self.paused,
            "card_id": self.card_id,
            "color": self.color,
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

        process = await asyncio.create_subprocess_shell(
            command,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(working_dir) if working_dir.exists() else None,
            env=env
        )
        return process

    async def kill_process(self, agent_proc):
        try:
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
            logger.warning("Docker not available — falling back to subprocess")
            fallback = SubprocessAdapter()
            return await fallback.create_process(agent_id, agent_config, card, env, instance_dir)

        image = agent_config.get("docker_image", "")
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
        for ws in mcp_workspaces:
            path = ws.get("path", "")
            if path:
                volume_flags.extend(["-v", f"{path}:/workspace/{ws.get('name', 'ws')}:ro"])

        cmd = [
            "docker", "run", "--rm",
            "--name", container_name,
            "--read-only",
            "-e", f"AEGIS_CARD_ID={card_id}",
            "-e", f"AEGIS_CARD_TITLE={card.get('title', '')}",
            "-e", f"AEGIS_CARD_DESCRIPTION={card.get('description', '')}",
            *volume_flags,
            image
        ]

        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
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
        isolation = agent_config.get("isolation", "subprocess")
        if isolation == "docker":
            return self._docker
        return self._subprocess

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
            except Exception as e:
                logger.warning(f"Failed to load instance env_vars: {e}")

        # Set Aegis specific variables overriding everything else
        env["AEGIS_AGENT_ID"] = agent_id
        env["AEGIS_CARD_ID"] = str(card_id)
        env["AEGIS_CARD_TITLE"] = card.get("title", "")
        env["AEGIS_CARD_DESCRIPTION"] = card.get("description", "")
        env["AEGIS_AGENT_PROFILE"] = agent_config.get("profile", "")
        env["AEGIS_API_URL"] = os.environ.get("AEGIS_API_URL", "http://localhost:8080/api")
        if instance_id:
            env["AEGIS_INSTANCE_ID"] = instance_id
            env["AEGIS_INSTANCE_NAME"] = instance_name or ""
            
            # Inject service and model if available in instance data
            try:
                instances = load_instances()
                inst_meta = next((i for i in instances if i["instance_id"] == instance_id), None)
                if inst_meta:
                    env["AEGIS_SERVICE"] = inst_meta.get("service", "")
                    env["AEGIS_MODEL"] = inst_meta.get("model", "")
                    # Inject config schema values as AEGIS_CONFIG_* env vars
                    inst_config = inst_meta.get("config", {})
                    for ck, cv in inst_config.items():
                        env_key = f"AEGIS_CONFIG_{ck.upper()}"
                        if isinstance(cv, list):
                            env[env_key] = ",".join(str(v) for v in cv)
                        else:
                            env[env_key] = str(cv)
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
                instance_id=instance_id, instance_name=instance_name
            )
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

            return agent_proc.to_dict()

        except Exception as e:
            logger.error(f"Failed to start '{key}': {e}")
            store.update_card(card_id, status="error")
            if self.broadcaster:
                await self.broadcaster({"type": "card_updated", "card": store.get_card(card_id)})
            return {"error": str(e), "status": "error"}

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
            return {"error": f"Agent '{agent_id}' is not running", "status": "not_running"}

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

    async def inject_stdin(self, agent_id: str, text: str) -> dict:
        """Write text to a running agent's stdin pipe."""
        agent_proc = self.active.get(agent_id)
        if not agent_proc or agent_proc.status != "running":
            return {"error": f"Agent '{agent_id}' is not running"}

        try:
            if agent_proc.process.stdin:
                agent_proc.process.stdin.write((text + "\n").encode())
                await agent_proc.process.stdin.drain()

                # Log the injection
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
        agent_proc = self.active.get(agent_id)
        return agent_proc.logs[-tail:] if agent_proc else []

    # ─── Log Streaming ────────────────────────────────────────────────────────

    async def _stream_logs(self, agent_proc: AgentProcess, stream,
                           log_type: str, card_id: int, store):
        """Streams stdout/stderr to log buffer, card logs, and WebSocket."""
        try:
            while True:
                line = await stream.readline()
                if not line:
                    break
                decoded = line.decode(errors="replace").strip()
                if decoded:
                    entry = f"[{log_type}] {decoded}"
                    agent_proc.logs.append(entry)

                    # Update card logs
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
            (template_dir / ".installed").write_text(datetime.now().isoformat())

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
            return json.loads(INSTANCES_STATE_FILE.read_text())
        except Exception as e:
            logger.error(f"Failed to load instances.json: {e}")
    return []


def save_instances(instances: list[dict]):
    """Persist instance state to instances.json."""
    INSTANCES_STATE_FILE.write_text(json.dumps(instances, indent=2))


def create_instance(template_id: str, instance_name: str,
                    registry_entry: Optional[dict] = None,
                    env_vars: Optional[dict] = None,
                    service: str = "",
                    model: str = "",
                    config: Optional[dict] = None) -> dict:
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
        "icon": registry_entry.get("icon", "🤖") if registry_entry else "🤖",
        "color": "#6366f1",
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


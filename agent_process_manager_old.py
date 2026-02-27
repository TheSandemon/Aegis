"""
Aegis AgentProcessManager — Full lifecycle management for installed agent bots.
Handles start, stop, status, health polling, non-blocking log streaming, and rate limiting.
"""

import os
import json
import asyncio
import time
import logging
import shutil
from pathlib import Path
from typing import Optional
from datetime import datetime
import uuid

logger = logging.getLogger("aegis.process_manager")

AGENTS_DIR = Path(__file__).parent / "agents"
AGENTS_DIR.mkdir(exist_ok=True)


class AgentProcess:
    """Tracks a single running agent process instance."""

    def __init__(self, agent_id: str, pid: int, process: asyncio.subprocess.Process):
        self.agent_id = agent_id
        # Generate a short unique ID for this instance (e.g. openclaw-core-a1b2)
        short_uuid = str(uuid.uuid4())[:4]
        self.instance_id = f"{agent_id}-{short_uuid}"
        self.pid = pid
        self.process = process
        self.status = "running"
        self.started_at = datetime.now().isoformat()
        self.exit_code: Optional[int] = None
        self.logs: list[str] = []
        self.log_queue: asyncio.Queue = asyncio.Queue()

    def to_dict(self):
        return {
            "instance_id": self.instance_id,
            "agent_id": self.agent_id,
            "pid": self.pid,
            "status": self.status,
            "started_at": self.started_at,
            "exit_code": self.exit_code,
            "log_count": len(self.logs),
        }


class AgentProcessManager:
    """
    Manages the full lifecycle of agent bot processes.
    - State tracking with PID, process object, instance ID, status
    - Lifecycle methods: start, stop, status
    - Non-blocking log streaming via asyncio queues -> WebSocket
    - Health polling every 5 seconds
    - Global rate limiting: 1 prompt/minute
    """

    def __init__(self, broadcaster=None, prompts_per_minute: int = 1):
        self.active: dict[str, AgentProcess] = {}  # instance_id -> AgentProcess
        self.broadcaster = broadcaster
        self._health_task: Optional[asyncio.Task] = None
        self._rate_limiter_last: float = 0.0
        self._rate_interval: float = 60.0 / prompts_per_minute
        self._running = False

    async def start_health_polling(self):
        """Start the background health polling loop."""
        self._running = True
        self._health_task = asyncio.create_task(self._health_loop())
        logger.info("AgentProcessManager health polling started (5s interval)")

    async def stop_health_polling(self):
        """Stop the health polling loop."""
        self._running = False
        if self._health_task:
            self._health_task.cancel()
            try:
                await self._health_task
            except asyncio.CancelledError:
                pass

    # ========== Lifecycle Methods ==========

    async def start_agent(self, agent_id: str, registry_entry: dict) -> dict:
        """Start an agent process from its registry definition."""
        # No longer blocking on agent_id; we allow multiple instances.

        exec_config = registry_entry.get("execution", {})
        working_dir = Path(exec_config.get("working_dir", ".")).resolve()
        command = exec_config.get("command", "")

        if not command:
            return {"error": "No command configured", "status": "error"}

        # ========== Rate Limiting ==========
        await self._enforce_rate_limit()

        env = os.environ.copy()
        env["AEGIS_AGENT_ID"] = agent_id
        for var in exec_config.get("env_vars_required", []):
            if var not in env:
                logger.warning(f"Missing env var '{var}' for agent '{agent_id}'")

        try:
            process = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(working_dir) if working_dir.exists() else None,
                env=env
            )

            agent_proc = AgentProcess(agent_id, process.pid, process)
            self.active[agent_proc.instance_id] = agent_proc

            # ========== Non-Blocking Log Streaming ==========
            asyncio.create_task(self._stream_logs(agent_proc, process.stdout, "STDOUT"))
            asyncio.create_task(self._stream_logs(agent_proc, process.stderr, "STDERR"))

            logger.info(f"Started instance '{agent_proc.instance_id}' of agent '{agent_id}' (PID: {process.pid})")

            if self.broadcaster:
                await self.broadcaster({
                    "type": "agent_started",
                    "instance_id": agent_proc.instance_id,
                    "agent_id": agent_id,
                    "pid": process.pid
                })

            return agent_proc.to_dict()

        except Exception as e:
            logger.error(f"Failed to start agent '{agent_id}': {e}")
            return {"error": str(e), "status": "error"}

    async def stop_agent(self, instance_id: str) -> dict:
        """Stop a running agent process instance."""
        agent_proc = self.active.get(instance_id)
        if not agent_proc or agent_proc.status != "running":
            return {"error": f"Instance '{instance_id}' is not running", "status": "not_running"}

        try:
            agent_proc.process.terminate()
            try:
                await asyncio.wait_for(agent_proc.process.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                agent_proc.process.kill()
                await agent_proc.process.wait()

            agent_proc.status = "stopped"
            agent_proc.exit_code = agent_proc.process.returncode
            logger.info(f"Stopped instance '{instance_id}' (PID: {agent_proc.pid})")

            if self.broadcaster:
                await self.broadcaster({
                    "type": "agent_stopped",
                    "instance_id": instance_id,
                    "agent_id": agent_proc.agent_id,
                    "pid": agent_proc.pid
                })

            return agent_proc.to_dict()

        except Exception as e:
            logger.error(f"Failed to stop instance '{instance_id}': {e}")
            return {"error": str(e), "status": "error"}

    def get_status(self, instance_id: str) -> Optional[dict]:
        """Get the current status of an agent instance."""
        agent_proc = self.active.get(instance_id)
        if not agent_proc:
            return None
        return agent_proc.to_dict()

    def get_all_active(self) -> list[dict]:
        """Get all active/recent agent process instances."""
        return [proc.to_dict() for proc in self.active.values()]

    def get_logs(self, instance_id: str, tail: int = 100) -> list[str]:
        """Get recent logs for an agent instance."""
        agent_proc = self.active.get(instance_id)
        if not agent_proc:
            return []
        return agent_proc.logs[-tail:]

    # ========== Non-Blocking Log Streaming ==========

    async def _stream_logs(self, agent_proc: AgentProcess, stream, log_type: str):
        """Streams stdout/stderr to the log buffer and broadcasts via WebSocket."""
        try:
            while True:
                line = await stream.readline()
                if not line:
                    break
                decoded = line.decode(errors="replace").strip()
                if decoded:
                    entry = f"[{log_type}] {decoded}"
                    agent_proc.logs.append(entry)

                    # Broadcast to connected clients
                    if self.broadcaster:
                        await self.broadcaster({
                            "type": "agent_log",
                            "instance_id": agent_proc.instance_id,
                            "agent_id": agent_proc.agent_id,
                            "entry": entry
                        })
        except Exception as e:
            logger.error(f"Log streaming error for {agent_proc.instance_id}: {e}")

    # ========== Health Polling ==========

    async def _health_loop(self):
        """Polls all running processes every 5 seconds for crashes."""
        while self._running:
            try:
                await asyncio.sleep(5)
                for instance_id, agent_proc in list(self.active.items()):
                    if agent_proc.status != "running":
                        continue

                    returncode = agent_proc.process.returncode
                    if returncode is not None:
                        agent_proc.status = "failed" if returncode != 0 else "completed"
                        agent_proc.exit_code = returncode
                        logger.warning(
                            f"Instance '{instance_id}' exited with code {returncode} "
                            f"(status: {agent_proc.status})"
                        )

                        if self.broadcaster:
                            await self.broadcaster({
                                "type": "agent_status_changed",
                                "instance_id": instance_id,
                                "agent_id": agent_proc.agent_id,
                                "status": agent_proc.status,
                                "exit_code": returncode
                            })

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Health polling error: {e}")

    # ========== Rate Limiting ==========

    async def _enforce_rate_limit(self):
        """Enforces 1 prompt/minute global throttle."""
        now = time.time()
        elapsed = now - self._rate_limiter_last
        if elapsed < self._rate_interval:
            wait = self._rate_interval - elapsed
            logger.info(f"Rate limit: waiting {wait:.1f}s before starting agent")
            await asyncio.sleep(wait)
        self._rate_limiter_last = time.time()


# ========== Installation Helper ==========

async def install_agent(agent_id: str, registry_entry: dict) -> dict:
    """Clones an agent repo and runs setup commands."""
    install_config = registry_entry.get("installation", {})
    method = install_config.get("method", "")
    github_url = registry_entry.get("github_url", "")
    setup_commands = install_config.get("setup_commands", [])

    agent_dir = AGENTS_DIR / agent_id

    if agent_dir.exists():
        return {"status": "already_installed", "path": str(agent_dir)}

    try:
        if method == "git_clone" and github_url:
            proc = await asyncio.create_subprocess_exec(
                "git", "clone", github_url, str(agent_dir),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await proc.communicate()

            if proc.returncode != 0:
                return {
                    "status": "clone_failed",
                    "error": stderr.decode(errors="replace")
                }

            # Run setup commands
            results = []
            for cmd in setup_commands:
                setup_proc = await asyncio.create_subprocess_shell(
                    cmd,
                    cwd=str(agent_dir),
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )
                s_out, s_err = await setup_proc.communicate()
                results.append({
                    "command": cmd,
                    "exit_code": setup_proc.returncode,
                    "output": s_out.decode(errors="replace")[:500]
                })

            logger.info(f"Installed agent '{agent_id}' to {agent_dir}")
            return {
                "status": "installed",
                "path": str(agent_dir),
                "setup_results": results
            }

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
                    "output": s_out.decode(errors="replace")[:500]
                })

            # Create a marker directory
            agent_dir.mkdir(parents=True, exist_ok=True)
            (agent_dir / ".installed").write_text(datetime.now().isoformat())

            return {
                "status": "installed",
                "path": str(agent_dir),
                "setup_results": results
            }

        elif method == "mock_local":
            # Generate local mock scripts for broken repos to ensure successful execution testing
            agent_dir.mkdir(parents=True, exist_ok=True)
            command = registry_entry.get("execution", {}).get("command", "")
            script_name = command.split()[-1] if " " in command else "mock.py"

            script_content = f"""import time
import sys
import os

print(f"Mock Agent '{{os.environ.get('AEGIS_AGENT_ID', 'unknown')}}' started.", flush=True)
print("Awaiting tasks in background...", flush=True)

try:
    while True:
        time.sleep(10)
        print("Polling... no new tasks found.", flush=True)
except KeyboardInterrupt:
    print("Agent shutting down.", flush=True)
    sys.exit(0)
"""
            (agent_dir / script_name).write_text(script_content)
            (agent_dir / ".installed").write_text(datetime.now().isoformat())

            return {
                "status": "installed",
                "path": str(agent_dir),
                "setup_results": [{"command": "generate_mock", "exit_code": 0, "output": "Mock script created"}]
            }
        else:
            return {"status": "unsupported_method", "method": method}

    except Exception as e:
        logger.error(f"Installation error for '{agent_id}': {e}")
        return {"status": "error", "error": str(e)}


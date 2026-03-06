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

logger = logging.getLogger("aegis.process_manager")

AGENTS_DIR = Path(__file__).parent / "agents"
AGENTS_DIR.mkdir(exist_ok=True)


class AgentProcess:
    """Tracks a single running agent process."""

    def __init__(self, agent_id: str, pid: int, process: asyncio.subprocess.Process, card_id: Optional[int] = None, color: str = "#6366f1"):
        self.agent_id = agent_id
        self.pid = pid
        self.process = process
        self.status = "running"
        self.card_id = card_id
        self.color = color
        self.started_at = datetime.now().isoformat()
        self.exit_code: Optional[int] = None
        self.logs: list[str] = []
        self.log_queue: asyncio.Queue = asyncio.Queue()

    def to_dict(self):
        return {
            "agent_id": self.agent_id,
            "pid": self.pid,
            "status": self.status,
            "card_id": self.card_id,
            "color": self.color,
            "started_at": self.started_at,
            "exit_code": self.exit_code,
            "log_count": len(self.logs),
        }


class AgentProcessManager:
    """
    Manages the full lifecycle of agent bot processes.
    - State tracking with PID, process object, agent ID, status
    - Lifecycle methods: start, stop, status
    - Non-blocking log streaming via asyncio queues -> WebSocket
    - Health polling every 5 seconds
    - Global rate limiting: 1 prompt/minute
    """

    def __init__(self, broadcaster=None, prompts_per_minute: int = 1):
        self.active: dict[str, AgentProcess] = {}  # agent_id -> AgentProcess
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
            except Exception as e:
                logger.error(f"Error stopping health polling: {e}")

    # ========== Lifecycle Methods ==========

    async def start_agent(self, agent_id: str, registry_entry: dict, card_id: Optional[int] = None) -> dict:
        """Start an agent process from its registry definition."""
        if agent_id in self.active and self.active[agent_id].status == "running":
            return {"error": f"Agent '{agent_id}' is already running", "status": "already_running"}

        exec_config = registry_entry.get("execution", {})
        working_dir = Path(exec_config.get("working_dir", ".")).resolve()
        command = exec_config.get("command", "")
        color = registry_entry.get("color", "#6366f1")

        if not command:
            return {"error": "No command configured", "status": "error"}

        # ========== Rate Limiting ==========
        await self._enforce_rate_limit()

        env = os.environ.copy()
        env["AEGIS_AGENT_ID"] = agent_id
        if card_id:
            env["AEGIS_CARD_ID"] = str(card_id)
            
        for var in exec_config.get("env_vars_required", []):
            if var not in env:
                logger.warning(f"Missing env var '{var}' for agent '{agent_id}'")

        try:
            process = await asyncio.create_subprocess_shell(
                command,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(working_dir) if working_dir.exists() else None,
                env=env
            )

            agent_proc = AgentProcess(agent_id, process.pid, process, card_id, color)
            self.active[agent_id] = agent_proc

            # ========== Non-Blocking Log Streaming ==========
            asyncio.create_task(self._stream_logs(agent_proc, process.stdout, "STDOUT"))
            asyncio.create_task(self._stream_logs(agent_proc, process.stderr, "STDERR"))

            logger.info(f"Started agent '{agent_id}' (PID: {process.pid})")

            if self.broadcaster:
                await self.broadcaster({
                    "type": "agent_started",
                    "agent_id": agent_id,
                    "pid": process.pid,
                    "card_id": card_id,
                    "color": color
                })

            return agent_proc.to_dict()

        except Exception as e:
            logger.error(f"Failed to start agent '{agent_id}': {e}")
            return {"error": str(e), "status": "error"}

    async def stop_agent(self, agent_id: str) -> dict:
        """Stop a running agent process."""
        agent_proc = self.active.get(agent_id)
        if not agent_proc or agent_proc.status != "running":
            return {"error": f"Agent '{agent_id}' is not running", "status": "not_running"}

        try:
            agent_proc.process.terminate()
            try:
                await asyncio.wait_for(agent_proc.process.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                agent_proc.process.kill()
                await agent_proc.process.wait()

            agent_proc.status = "stopped"
            agent_proc.exit_code = agent_proc.process.returncode
            logger.info(f"Stopped agent '{agent_id}' (PID: {agent_proc.pid})")

            if self.broadcaster:
                await self.broadcaster({
                    "type": "agent_stopped",
                    "agent_id": agent_id,
                    "pid": agent_proc.pid
                })

            return agent_proc.to_dict()

        except Exception as e:
            logger.error(f"Failed to stop agent '{agent_id}': {e}")
            return {"error": str(e), "status": "error"}

    async def send_input(self, agent_id: str, text: str) -> bool:
        """Sends arbitrary text to the agent's standard input."""
        agent_proc = self.active.get(agent_id)
        if not agent_proc or agent_proc.status != "running" or not agent_proc.process.stdin:
            return False
            
        try:
            agent_proc.process.stdin.write((text + "\n").encode("utf-8"))
            await agent_proc.process.stdin.drain()
            return True
        except Exception as e:
            logger.error(f"Failed to send input to agent '{agent_id}': {e}")
            return False

    def get_status(self, agent_id: str) -> Optional[dict]:
        """Get the current status of an agent."""
        agent_proc = self.active.get(agent_id)
        if not agent_proc:
            return None
        return agent_proc.to_dict()

    def get_all_active(self) -> list[dict]:
        """Get all active/recent agent processes."""
        return [proc.to_dict() for proc in self.active.values()]

    def get_logs(self, agent_id: str, tail: int = 100) -> list[str]:
        """Get recent logs for an agent."""
        agent_proc = self.active.get(agent_id)
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
                            "agent_id": agent_proc.agent_id,
                            "entry": entry
                        })
                        
                        # Detect critical agent errors / git conflicts
                        error_signals = ["❌ ERROR", "CONFLICT", "Merge failed", "fatal: "]
                        if any(sig in decoded for sig in error_signals):
                            await self.broadcaster({
                                "type": "agent_conflict",
                                "agent_id": agent_proc.agent_id,
                                "card_id": agent_proc.card_id,
                                "error": decoded
                            })
        except Exception as e:
            logger.error(f"Log streaming error for {agent_proc.agent_id}: {e}")

    # ========== Health Polling ==========

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

        else:
            return {"status": "unsupported_method", "method": method}

    except Exception as e:
        logger.error(f"Installation error for '{agent_id}': {e}")
        return {"status": "error", "error": str(e)}



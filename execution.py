"""
Aegis Execution Manager — Sandboxed Agent Execution
Supports Docker containers for heavy agents and bare-metal subprocess for light agents.
"""

import os
import json
import asyncio
import shutil
import logging
from typing import Optional
from abc import ABC, abstractmethod

logger = logging.getLogger("aegis.execution")


class ExecutionAdapter(ABC):
    """Base class for agent execution strategies."""

    @abstractmethod
    async def run(self, card_id: int, agent_name: str, agent_config: dict,
                  card: dict, store, broadcaster) -> None:
        ...

    @abstractmethod
    async def stop(self, card_id: int) -> bool:
        ...


class SubprocessAdapter(ExecutionAdapter):
    """Runs agents as bare-metal subprocesses. Best for lightweight, compiled bots."""

    def __init__(self):
        self.running: dict[int, asyncio.subprocess.Process] = {}

    async def run(self, card_id, agent_name, agent_config, card, store, broadcaster):
        command = agent_config.get("binary", "")
        if not command:
            logger.error(f"No binary configured for agent '{agent_name}'")
            return

        env = os.environ.copy()
        env["AEGIS_CARD_ID"] = str(card_id)
        env["AEGIS_CARD_TITLE"] = card.get("title", "")
        env["AEGIS_CARD_DESCRIPTION"] = card.get("description", "")
        env["AEGIS_AGENT_PROFILE"] = agent_config.get("profile", "")

        try:
            store.update_card(card_id, status="running")
            await broadcaster({"type": "card_updated", "card": store.get_card(card_id)})

            process = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env
            )
            self.running[card_id] = process

            async def stream(stream_obj, log_type):
                while True:
                    line = await stream_obj.readline()
                    if not line:
                        break
                    decoded = line.decode().strip()
                    if decoded:
                        entry = f"[{log_type}] {decoded}"
                        current = store.get_card(card_id)
                        if not current:
                            break
                        logs = current.get("logs", [])
                        logs.append(entry)
                        store.update_card(card_id, logs=json.dumps(logs))
                        await broadcaster({
                            "type": "log_entry",
                            "card_id": card_id,
                            "entry": entry
                        })

            await asyncio.gather(
                stream(process.stdout, "STDOUT"),
                stream(process.stderr, "STDERR")
            )

            return_code = await process.wait()

            if card_id not in self.running:
                status = "terminated"
            else:
                status = "completed" if return_code == 0 else "failed"

            store.update_card(card_id, status=status)
            await broadcaster({"type": "card_updated", "card": store.get_card(card_id)})

        except Exception as e:
            logger.error(f"Subprocess error for card {card_id}: {e}")
            store.update_card(card_id, status="error")
            await broadcaster({"type": "card_updated", "card": store.get_card(card_id)})
        finally:
            self.running.pop(card_id, None)

    async def stop(self, card_id):
        proc = self.running.get(card_id)
        if proc:
            try:
                proc.terminate()
                del self.running[card_id]
                logger.info(f"Subprocess terminated for card {card_id}")
                return True
            except Exception as e:
                logger.error(f"Failed to terminate subprocess for card {card_id}: {e}")
        return False


class DockerAdapter(ExecutionAdapter):
    """Runs agents inside isolated Docker containers. Best for autonomous heavy agents."""

    def __init__(self):
        self.running: dict[int, str] = {}  # card_id -> container_id
        self._docker_available = shutil.which("docker") is not None

    async def run(self, card_id, agent_name, agent_config, card, store, broadcaster):
        if not self._docker_available:
            logger.warning(f"Docker not available — falling back to subprocess for card {card_id}")
            fallback = SubprocessAdapter()
            await fallback.run(card_id, agent_name, agent_config, card, store, broadcaster)
            return

        image = agent_config.get("docker_image", "")
        if not image:
            logger.error(f"No docker_image configured for agent '{agent_name}'")
            store.update_card(card_id, status="error")
            return

        # Build workspace mounts from MCP config
        from main import CONFIG
        mcp_workspaces = CONFIG.get("mcp", {}).get("workspaces", [])
        volume_flags = []
        for ws in mcp_workspaces:
            path = ws.get("path", "")
            if path:
                volume_flags.extend(["-v", f"{path}:/workspace/{ws.get('name', 'ws')}:ro"])

        container_name = f"aegis-{agent_name}-{card_id}"
        cmd = [
            "docker", "run", "--rm",
            "--name", container_name,
            "--read-only",
            "-e", f"AEGIS_CARD_ID={card_id}",
            "-e", f"AEGIS_CARD_TITLE={card.get('title', '')}",
            "-e", f"AEGIS_CARD_DESCRIPTION={card.get('description', '')}",
            "-e", f"AEGIS_AGENT_PROFILE={agent_config.get('profile', '')}",
            *volume_flags,
            image
        ]

        try:
            store.update_card(card_id, status="running")
            await broadcaster({"type": "card_updated", "card": store.get_card(card_id)})

            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            self.running[card_id] = container_name

            async def stream(stream_obj, log_type):
                while True:
                    line = await stream_obj.readline()
                    if not line:
                        break
                    decoded = line.decode().strip()
                    if decoded:
                        entry = f"[{log_type}] {decoded}"
                        current = store.get_card(card_id)
                        if not current:
                            break
                        logs = current.get("logs", [])
                        logs.append(entry)
                        store.update_card(card_id, logs=json.dumps(logs))
                        await broadcaster({
                            "type": "log_entry",
                            "card_id": card_id,
                            "entry": entry
                        })

            await asyncio.gather(
                stream(process.stdout, "STDOUT"),
                stream(process.stderr, "STDERR")
            )

            return_code = await process.wait()

            if card_id not in self.running:
                status = "terminated"
            else:
                status = "completed" if return_code == 0 else "failed"

            store.update_card(card_id, status=status)
            await broadcaster({"type": "card_updated", "card": store.get_card(card_id)})

        except Exception as e:
            logger.error(f"Docker error for card {card_id}: {e}")
            store.update_card(card_id, status="error")
            await broadcaster({"type": "card_updated", "card": store.get_card(card_id)})
        finally:
            self.running.pop(card_id, None)

    async def stop(self, card_id):
        container_name = self.running.get(card_id)
        if container_name:
            try:
                proc = await asyncio.create_subprocess_exec(
                    "docker", "kill", container_name,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )
                await proc.wait()
                del self.running[card_id]
                logger.info(f"Docker container '{container_name}' killed for card {card_id}")
                return True
            except Exception as e:
                logger.error(f"Failed to kill Docker container for card {card_id}: {e}")
        return False


class ExecutionManager:
    """
    Routes agent execution to the correct adapter based on isolation config.
    Manages lifecycle hooks for container cleanup.
    """

    def __init__(self):
        self.subprocess_adapter = SubprocessAdapter()
        self.docker_adapter = DockerAdapter()

    def _get_adapter(self, agent_config: dict) -> ExecutionAdapter:
        isolation = agent_config.get("isolation", "subprocess")
        if isolation == "docker":
            return self.docker_adapter
        return self.subprocess_adapter

    @property
    def running_tasks(self) -> dict:
        """Combined view of all running tasks across adapters."""
        combined = {}
        combined.update(self.subprocess_adapter.running)
        combined.update(self.docker_adapter.running)
        return combined

    async def run_agent(self, card_id: int, agent_name: str, agent_config: dict,
                        card: dict, store, broadcaster):
        adapter = self._get_adapter(agent_config)
        logger.info(
            f"ExecutionManager: Running '{agent_name}' for card {card_id} "
            f"via {adapter.__class__.__name__}"
        )
        await adapter.run(card_id, agent_name, agent_config, card, store, broadcaster)

    async def stop_agent(self, card_id: int) -> bool:
        """Attempt to stop an agent on any adapter."""
        if card_id in self.subprocess_adapter.running:
            return await self.subprocess_adapter.stop(card_id)
        if card_id in self.docker_adapter.running:
            return await self.docker_adapter.stop(card_id)
        return False

    async def lifecycle_hook(self, card_id: int, new_column: str, store, broadcaster):
        """Auto-kill agents when cards move to Review or Done."""
        if new_column in ("Review", "Done"):
            if card_id in self.running_tasks:
                logger.info(f"Lifecycle hook: Stopping agent for card {card_id} → {new_column}")
                await self.stop_agent(card_id)

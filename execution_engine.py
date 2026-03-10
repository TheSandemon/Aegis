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

from core.models import AgentProcess
from core.adapters import ExecutionAdapter, SubprocessAdapter, DockerAdapter


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
            # Fetch wrapper preference early
            _show_wrap = True
            if agent_proc.is_cli and instance_id:
                try:
                    _t_inst = next((i for i in load_instances() if i["instance_id"] == instance_id), None)
                    if _t_inst:
                        _show_wrap = str(_t_inst.get("config", {}).get("show_cli_wrapper", "true")).lower() == "true"
                except Exception: pass
                
            # Set wrapper visibility for CLI agents
            agent_proc.show_wrapper = _show_wrap if agent_proc.is_cli else True
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
            #
            # SAFEGUARD: If someone sets `cli_agent: true` but uses `python -u worker.py`
            # as the command, skip the CLI pulse loop. The worker.py script has its own
            # internal pulse loop and running both causes dual-execution and crashes.
            _cmd_check = merged_config.get("execution", {}).get("command", "")
            _is_worker_cmd = "worker.py" in _cmd_check
            if merged_config.get("cli_agent") and not _is_worker_cmd:
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
                _show_cli_wrapper = agent_proc.show_wrapper
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
                                          _api, _cmd, _cwd, _env, _is_claude_cli, _show_wrapper=True):
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

                    # Aegis REST API cheat-sheet for CLI agents
                    api_reference = (
                        "\n\n=== AEGIS REST API REFERENCE (Base: http://localhost:42069/api) ===\n"
                        "All endpoints accept/return JSON. Use curl or your HTTP tools.\n\n"
                        "CARDS:\n"
                        "  GET    /api/cards                          - List all cards\n"
                        "  POST   /api/cards                          - Create card {title, column, description?, priority?, assignee?, tags?}\n"
                        '         Example: curl -X POST http://localhost:42069/api/cards -H "Content-Type: application/json" -d \'{"title":"Fix bug","column":"To-Do","priority":"high"}\'\n'
                        "  PATCH  /api/cards/{id}                     - Update card {column?, title?, description?, assignee?, priority?, status?, tags?}\n"
                        '         Example: curl -X PATCH http://localhost:42069/api/cards/5 -H "Content-Type: application/json" -H "X-Aegis-Agent: true" -d \'{"column":"In-Progress","assignee":"MyName"}\'\n'
                        "  DELETE /api/cards/{id}                     - Delete card\n"
                        "  GET    /api/cards/{id}/context              - Smart context (focus card + related cards + board directory)\n"
                        "  POST   /api/cards/{id}/comments            - Add comment {author, content}\n\n"
                        "BULK OPS:\n"
                        '  DELETE /api/cards/bulk                     - Bulk delete {card_ids: [1,2,3]}\n'
                        '  PATCH  /api/cards/bulk                     - Bulk update {updates: [{card_id:1, column:"Done"}, ...]}\n\n'
                        "COLUMNS:\n"
                        "  GET    /api/columns                        - List all columns\n"
                        "  POST   /api/columns                        - Create column {name}\n\n"
                        "IMPORTANT: Always include header 'X-Aegis-Agent: true' on PATCH/DELETE card requests.\n"
                        "IMPORTANT: Use column NAMES (not IDs) when setting a card's column.\n"
                        "=== END API REFERENCE ===\n"
                    )

                    pulse_count = 0
                    while _proc.status == "running":
                        pulse_count += 1
                        try:
                            # --- Stage 1: Fetch board state ---
                            async def _emit(_text, _wrapper=True):
                                if _wrapper and not _show_wrapper:
                                    return  # Skip wrapper messages when disabled
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
                            cards_data = None
                            cols_data = None
                            try:
                                cards_data = await asyncio.to_thread(_fetch_json, f"{_api}/cards")
                                cols_data = await asyncio.to_thread(_fetch_json, f"{_api}/columns")
                                if cards_data and cols_data:
                                    # Rich board context matching standard workers
                                    board_ctx = "\n\n--- BOARD STATE ---\n"

                                    # Column summary with guardrails
                                    board_ctx += "COLUMNS:\n"
                                    read_only_cols = set()
                                    for col in cols_data:
                                        col_line = f"  [{col.get('id')}] {col.get('name', '?')}"
                                        if col.get('is_locked'):
                                            col_line += " [LOCKED]"
                                        if col.get('integration_type') and col.get('integration_mode') == 'read':
                                            col_line += " [READ-ONLY]"
                                            read_only_cols.add(col.get('name', ''))
                                        board_ctx += col_line + "\n"
                                        # Column guardrails
                                        if col.get('function'):
                                            board_ctx += f"    Function: {col['function']}\n"
                                        if col.get('exit_pass'):
                                            board_ctx += f"    Exit [Pass]: {col['exit_pass']}\n"
                                        if col.get('exit_fail'):
                                            board_ctx += f"    Exit [Fail]: {col['exit_fail']}\n"

                                    if read_only_cols:
                                        board_ctx += f"\n⚠️ READ-ONLY: {', '.join(sorted(read_only_cols))} — do NOT create/update/delete cards in these columns.\n"

                                    board_ctx += f"\nCARDS ({len(cards_data)} total):\n"
                                    for c in cards_data:
                                        locked = " [LOCKED]" if c.get("is_locked") else ""
                                        board_ctx += (
                                            f"  [#{c.get('id')}]{locked} {c.get('title', '?')} | "
                                            f"Col: {c.get('column', '?')} | "
                                            f"Assignee: {c.get('assignee', 'None')} | "
                                            f"Priority: {c.get('priority', 'normal')}\n"
                                        )
                                        desc = c.get('description', '')
                                        if desc:
                                            board_ctx += f"    Desc: {desc[:200]}\n"
                                        comments = c.get('comments', [])
                                        if comments:
                                            last = comments[-1]
                                            board_ctx += f"    Last Comment [{last.get('author', '?')}]: {str(last.get('content', ''))[:100]}\n"

                                    board_ctx += "\n⚠️ LOCKED CARDS: If you see [LOCKED], do NOT edit, update, or delete that card.\n"

                                    await _emit(f"📋 Board loaded: {len(cards_data)} cards across {len(cols_data)} columns")
                                else:
                                    await _emit("⚠️ Could not fetch board state, proceeding with goal only")
                            except Exception as e:
                                logger.debug(f"CLI pulse: failed to fetch board state: {e}")
                                await _emit("⚠️ Board fetch failed, proceeding with goal only")

                            # --- Stage 2: Build the prompt ---
                            if _show_wrapper:
                                prompt_text = (
                                    f"[Aegis System Pulse #{pulse_count}]\n"
                                    f"Your Name: {_proc.instance_name or _proc.instance_id}\n"
                                    f"Goal: {_goals}\n"
                                    f"System Instructions: {robust_instruction}\n"
                                )
                                if pulse_count > 1:
                                    prompt_text += "This is your autonomous pulse. Review the current board state, pick up any unassigned tasks, and continue working on your goal.\n"
                            else:
                                prompt_text = f"{_goals}\n\n{robust_instruction}\n"
                            prompt_text += board_ctx
                            prompt_text += api_reference

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
                    _base_command, _cli_cwd, env, _is_claude, _show_cli_wrapper
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
        If newline is True, appends \\n and logs the injection as a discrete event.
        For CLI agents, non-TTY stdin buffers until EOF, so we instead spawn a discrete
        one-shot process with the `-p` flag."""
        agent_proc = self.active.get(agent_id)
        if not agent_proc or agent_proc.status != "running":
            return {"error": f"Agent '{agent_id}' is not running"}

        try:
            # Handle Node.js non-TTY pipe buffering for CLI agents
            if getattr(agent_proc, 'is_cli', False):
                logger.info(f"Routing stdin to CLI one-shot for '{agent_id}'")
                entry = f"[CHAT] {text}" if getattr(agent_proc, 'show_wrapper', True) else text
                agent_proc.logs.append(entry)
                if self.broadcaster:
                    await self.broadcaster({
                        "type": "log_entry",
                        "card_id": agent_proc.card_id,
                        "entry": entry
                    })

                # Fire off a background task to run the user query via CLI
                async def _run_cli_chat():
                    try:
                        # Build a lightweight direct-message prompt (no goal/system prompt)
                        chat_prompt = (
                            f"[Direct Message from User]\n"
                            f"The user sent you this message directly via the Aegis terminal. "
                            f"Respond to their request. You have access to the Aegis Kanban API at http://localhost:42069/api "
                            f"(GET /api/cards, POST /api/cards, PATCH /api/cards/{{id}}, DELETE /api/cards/{{id}}, "
                            f"POST /api/cards/{{id}}/comments, GET /api/columns). "
                            f"Include header 'X-Aegis-Agent: true' on PATCH/DELETE requests.\n\n"
                            f"User Message: {text}"
                        )
                        safe_prompt = chat_prompt.replace('"', '\\"').replace('\n', '\\n')
                        
                        # Resolve the proper CLI command (claude or gemini) directly from the registry template bounds
                        # rather than parsing the unpredictable transport args
                        from execution_engine import load_instances
                        _inst_md = next((i for i in load_instances() if i["instance_id"] == agent_id), {})
                        _tmp_id = _inst_md.get("template_id", "claude-code")
                        cmd_base = "gemini" if "gemini" in _tmp_id.lower() else "claude"
                        
                        if os.name == "nt":
                            cmd_path = __import__("shutil").which(cmd_base) or __import__("shutil").which(cmd_base + ".cmd")
                            if cmd_path: cmd_base = f'"{cmd_path}"'
                            
                        is_claude = "claude" in cmd_base.lower()
                        if is_claude:
                            cli_cmd = f'{cmd_base} -p "{safe_prompt}" --continue'
                        else:
                            cli_cmd = f'{cmd_base} "{safe_prompt}"'

                        # Get instance cwd if defined
                        from execution_engine import load_instances, INSTANCES_DIR
                        inst_meta = next((i for i in load_instances() if i["instance_id"] == agent_id), None)
                        
                        wk_dir = "."
                        if inst_meta:
                            wk_dir = inst_meta.get("config", {}).get("work_dir", ".")
                            if not Path(wk_dir).exists():
                                wk_dir = str(INSTANCES_DIR / agent_id)
                                
                        # Carry over environment mapping
                        cli_env = os.environ.copy()
                        if inst_meta:
                            for k, v in inst_meta.get("env_vars", {}).items():
                                if v: cli_env[k] = str(v)

                            # Handle dynamic API mapping
                            agent_registry = json.loads(Path("agent_registry.json").read_text(encoding="utf-8"))
                            reg_entry = next((a for a in agent_registry if a["id"] == inst_meta["template_id"]), None)
                            if reg_entry and reg_entry.get("cli_agent") and reg_entry.get("api_key_env"):
                                t_env = reg_entry["api_key_env"]
                                key = inst_meta["env_vars"].get("api_key", "")
                                if key: cli_env[t_env] = key

                        proc = await asyncio.create_subprocess_shell(
                            cli_cmd,
                            stdout=asyncio.subprocess.PIPE,
                            stderr=asyncio.subprocess.PIPE,
                            cwd=wk_dir,
                            env=cli_env
                        )

                        # Collect full response while streaming
                        chat_response_parts = []

                        async def _stream_chat(stream):
                            while True:
                                chunk = await stream.read(4096)
                                if not chunk: break
                                decoded = chunk.decode(errors="replace")
                                chat_response_parts.append(decoded)
                                agent_proc.logs.append(decoded)
                                if self.broadcaster:
                                    await self.broadcaster({
                                        "type": "agent_log",
                                        "agent_id": agent_proc.agent_id,
                                        "instance_id": agent_proc.instance_id,
                                        "entry": decoded
                                    })
                        await asyncio.gather(
                            _stream_chat(proc.stdout),
                            _stream_chat(proc.stderr),
                            proc.wait()
                        )

                        # Emit a NOTIFY entry so the UI triggers a chat bubble
                        full_response = "".join(chat_response_parts).strip()
                        if full_response:
                            # Clean up: take last meaningful paragraph as the bubble text
                            lines = [l.strip() for l in full_response.split("\n") if l.strip()]
                            # Filter out tool/thinking noise — grab the last substantial line
                            bubble_text = lines[-1] if lines else full_response[:200]
                            if len(bubble_text) > 200:
                                bubble_text = bubble_text[:197] + "..."
                            notify_entry = f"📢 NOTIFY: {bubble_text}"
                            agent_proc.logs.append(notify_entry)
                            if self.broadcaster:
                                await self.broadcaster({
                                    "type": "agent_log",
                                    "agent_id": agent_proc.agent_id,
                                    "instance_id": agent_proc.instance_id,
                                    "entry": notify_entry
                                })

                    except Exception as loop_e:
                        logger.error(f"Failed to proxy CLI chat: {loop_e}")

                asyncio.create_task(_run_cli_chat())
                return {"success": True}

            # Standard Python Agents
            if agent_proc.process.stdin:
                payload = text + "\n" if newline else text
                agent_proc.process.stdin.write(payload.encode())
                await agent_proc.process.stdin.drain()

                if newline:
                    # Log the discrete injection (skip prefix if wrapper disabled)
                    entry = f"[INJECT] {text}" if getattr(agent_proc, 'show_wrapper', True) else text
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

    async def update_presence(self, agent_id: str, card_id: Optional[int], activity: str) -> dict:
        """Update agent presence (card working on, activity status) and broadcast via WebSocket."""
        agent_proc = self.active.get(agent_id)
        if not agent_proc:
            return {"error": f"Agent '{agent_id}' not found", "status": "not_found"}

        # Update presence
        agent_proc.card_id = card_id
        presence_data = {
            "type": "agent_presence",
            "agent_id": agent_id,
            "card_id": card_id,
            "activity": activity,
            "timestamp": datetime.now().isoformat()
        }

        if self.broadcaster:
            await self.broadcaster(presence_data)

        return {"status": "updated", "presence": presence_data}

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

    # Build instance metadata — auto-equip core skills
    instance_config = config or {}
    if "skills" not in instance_config:
        instance_config["skills"] = []
    if "aegis-board-mastery" not in instance_config["skills"]:
        instance_config["skills"].append("aegis-board-mastery")

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
        "config": instance_config,
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


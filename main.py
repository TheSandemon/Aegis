#!/usr/bin/env python3
"""
Aegis - Multi-Agent Kanban & Orchestration Hub
Main entry point for the FastAPI backend

Architecture:
  Phase 1: A2A & MCP Protocol Layer
  Phase 2: Centralized Prompt Queue (PromptBroker)
  Phase 3: Sandboxed Execution (Docker + Subprocess)
  Phase 4: Firebase State Sync (optional)
  Phase 5: Human-in-the-Loop Validation
  Phase 6: Agent Registry & Process Manager
"""

import json
import os
import asyncio
import logging
import sqlite3
import httpx
import shutil
import secrets
from pathlib import Path
from datetime import datetime
import sys
from typing import Optional, List, Dict, Any
from contextlib import asynccontextmanager
import glob
from skill_manager import skill_manager

# Ensure UTF-8 output for Windows console
if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except AttributeError:
        pass

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Request, File, UploadFile
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field

# ─── Initialization & Config ─────────────────────────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("aegis")

# ─── Configuration ───────────────────────────────────────────────────────────────
CONFIG_PATH = Path(__file__).parent / "aegis.config.json"
if CONFIG_PATH.exists():
    with open(CONFIG_PATH, encoding="utf-8") as f:
        CONFIG = json.load(f)
else:
    CONFIG = {"port": 42069, "host": "0.0.0.0"}
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(CONFIG, f, indent=2)

# ─── Agent Registry ──────────────────────────────────────────────────────────────
REGISTRY_PATH = Path(__file__).parent / "agent_registry.json"
with open(REGISTRY_PATH, encoding="utf-8") as f:
    AGENT_REGISTRY = json.load(f)

# Default colors for agents if not specified
AGENT_COLORS = [
    "#6366f1", "#f59e0b", "#10b981", "#ef4444", "#8b5cf6", "#ec4899", "#06b6d4"
]

# ─── Data Directories ────────────────────────────────────────────────────────
PROFILES_DIR = Path(__file__).parent / "aegis_data" / "profiles"
ASSETS_DIR = Path(__file__).parent / "aegis_data" / "assets"

for d in [PROFILES_DIR, ASSETS_DIR]:
    d.mkdir(parents=True, exist_ok=True)

# ─── System Prompt ───────────────────────────────────────────────────────────────
SYSTEM_PROMPT_PATH = Path(__file__).parent / "aegis_data" / "system_prompt.txt"
DEFAULT_SYSTEM_PROMPT = """You are {agent_name}, an autonomous AI agent operating a Kanban board.
Your Goal: {goal}

━━━ BOARD STRUCTURE ━━━
• Columns are ordered stages (e.g. Inbox → Planned → In Progress → Review → Done).
• Cards are tasks. Each card has: id (int), title, description, column, assignee, priority, status, comments.
• You can only use column names that already exist on the board. Check the COLUMNS list before acting.

━━━ CORE RULES ━━━
1. ALWAYS act. Never respond with plain text — only use the JSON action format below.
2. Work on cards assigned to you OR unclaimed cards that match your goal.
3. When you finish a task, move the card to "Review" (not "Done" — a human approves final completion).
4. Use post_comment to leave notes, report progress, or ask questions on a card.
5. Reference other cards in comments/descriptions as @<id> (e.g. "@42") to link context.
6. NEVER duplicate work. Check existing cards before creating new ones.
7. If you see a 403 error, the action is not permitted — do not retry it.

━━━ AVAILABLE ACTIONS ━━━
create_card    — {{"title": str, "description": str, "column": str, "assignee": str|null}}
update_card    — {{"card_id": int, "title": str|null, "description": str|null, "column": str|null, "assignee": str|null, "status": str|null, "priority": "low"|"normal"|"high"|null}}
delete_card    — {{"card_id": int}}
post_comment   — {{"card_id": int, "content": str}}
create_column  — {{"name": str, "position": int}}
delete_column  — {{"column_id": int}}
list_dir       — {{"path": str}}  ← List files in a directory
read_file      — {{"path": str}}  ← Read a file
write_file     — {{"path": str, "content": str}}  ← Write/overwrite a file
wait           — {{"reason": str}}  ← Use ONLY when genuinely blocked; ends the pulse.
search_terminal — {{"query": str, "limit": int|null}}  ← Search your historical terminal logs

━━━ GIT & GITHUB ACTIONS ━━━
git_clone            — {{"repo_url": str, "dest": str}}  ← Clone a repo into your workspace
git_branch           — {{"branch_name": str, "checkout": bool, "cwd": str}}  ← Create a local branch
git_commit           — {{"message": str, "files": list|str, "cwd": str}}  ← Stage and commit (auto-attributed to you)
git_push             — {{"remote": str, "branch": str, "cwd": str}}  ← Push commits to remote
create_branch_remote — {{"branch_name": str, "base": str}}  ← Create a branch on GitHub (via API)
create_pr            — {{"title": str, "body": str, "head": str, "base": str}}  ← Open a Pull Request
merge_pr             — {{"pr_number": int, "merge_method": "squash"|"merge"|"rebase", "commit_message": str}}  ← Merge a PR
list_prs             — {{"state": "open"|"closed"|"all"}}  ← List Pull Requests
list_branches        — {{}}  ← List repo branches

⚠️ BRANCH SAFETY: Always create feature branches. Never push directly to main.
⚠️ COMMIT ATTRIBUTION: All commits are prefixed with [Aegis: {agent_name}] automatically.

━━━━━━━━ PERSONALITY ━━━━━━━━
• You are an autonomous entity with a distinct name ({agent_name}) and goal ({goal}).
• Express your personality in your "thought" field — be professional, quirky, cautious, or bold as appropriate for your name and goal.
• Use the thought field to reflect on your progress and plan your steps.

━━━ RESPONSE FORMAT (strict JSON array) ━━━
[
  {{
    "thought": "What I observed and why I'm taking this action.",
    "action": "action_name",
    "args": {{ ... }}
  }}
]

You may return multiple action objects in the array to batch several steps.
After each step you will receive an observation. Use observations to guide your next step.
If an action returns an error, adapt — do not repeat the same failing call.
End the pulse with "wait" once your current task sequence is complete."""

def load_system_prompt():
    if SYSTEM_PROMPT_PATH.exists():
        return SYSTEM_PROMPT_PATH.read_text(encoding="utf-8")
    SYSTEM_PROMPT_PATH.parent.mkdir(exist_ok=True)
    SYSTEM_PROMPT_PATH.write_text(DEFAULT_SYSTEM_PROMPT, encoding="utf-8")
    return DEFAULT_SYSTEM_PROMPT

SYSTEM_PROMPT = load_system_prompt()

def save_config():
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(CONFIG, f, indent=4)


# ═══════════════════════════════════════════════════════════════════════════════════
# ═══════════════════════════════════════════════════════════════════════════════════
# PYDANTIC MODELS (Now in models/schemas.py)
# ═══════════════════════════════════════════════════════════════════════════════════
from models.schemas import (
    CardCreate, CardUpdate, InstanceCreate, InstanceUpdate, CommentCreate,
    SkillInstallRequest, IntegrationConfig, ColumnCreate, SystemPromptUpdate,
    PromptSubmit, BrokerRateUpdate, ColumnUpdate, BranchCreate, PRCreate, PRMerge, ConnectionCreate, DevicePollRequest
)

# ═══════════════════════════════════════════════════════════════════════════════════
# PERSISTENCE (Now in services/db.py)
# ═══════════════════════════════════════════════════════════════════════════════════
from services.db import store

# ═══════════════════════════════════════════════════════════════════════════════════
# WEBSOCKET MANAGER (Now in websockets/manager.py)
# ═══════════════════════════════════════════════════════════════════════════════════
from ws.manager import manager
from services.dependencies import integration_manager

# ═══════════════════════════════════════════════════════════════════════════════════
# STATE SINGLETONS
# ═══════════════════════════════════════════════════════════════════════════════════
from services.dependencies import integration_manager, engine, broker, send_discord_webhook, get_costar_broker
from execution_engine import load_instances


# ═══════════════════════════════════════════════════════════════════════════════════
# APP LIFECYCLE
# ═══════════════════════════════════════════════════════════════════════════════════

async def polling_loop():
    """Polls for unassigned tasks in Planned column and routes to agents."""
    priority_order = {"high": 0, "normal": 1, "low": 2}

    while True:
        try:
            await asyncio.sleep(CONFIG.get("polling_rate_ms", 5000) / 1000)

            running_count = len(engine.running_tasks())
            max_agents = CONFIG.get("max_concurrent_agents", 4)

            if running_count < max_agents:
                planned_cards = [
                    c for c in store.get_cards(column="Planned")
                    if not c.get("assignee")
                ]

                # Sort by priority (high first)
                planned_cards.sort(key=lambda c: priority_order.get(c.get("priority", "normal"), 1))

                # Get all done card IDs for dependency checking
                done_ids = {c["id"] for c in store.get_cards(column="Done")}

                for card in planned_cards:
                    if len(engine.running_tasks()) >= max_agents:
                        break

                    # DAG check: skip if any dependency is not yet Done
                    deps = card.get("depends_on", [])
                    if deps and not all(d in done_ids for d in deps):
                        continue

                    instances = load_instances()
                    active_instances = [i for i in instances if i.get("enabled", True)]
                    
                    if not active_instances:
                        break # No workers available

                    # Pick the first available instance
                    for inst in active_instances:
                        instance_id = inst["instance_id"]
                        template_id = inst["template_id"]
                        
                        registry_entry = next((a for a in AGENT_REGISTRY if a["id"] == template_id), None)
                        if not registry_entry:
                            continue

                        # Merge configs
                        agent_config = CONFIG.get("agents", {}).get(template_id, {})
                        agent_config.setdefault("execution", registry_entry.get("execution", {}))

                        if instance_id in engine.active and engine.active[instance_id].status == "running":
                            continue

                        store.update_card(card["id"], assignee=inst["instance_name"], status="assigned")
                        logger.info(f"Routed card {card['id']} to instance '{inst['instance_name']}'")
                        
                        await manager.broadcast({
                            "type": "card_assigned",
                            "card_id": card["id"],
                            "agent": inst["instance_name"]
                        })

                        asyncio.create_task(
                            engine.run_agent(
                                card["id"], template_id, agent_config,
                                card, store, registry_entry,
                                instance_id=instance_id,
                                instance_name=inst["instance_name"]
                            )
                        )
                        break

        except Exception as e:
            logger.error(f"Polling error: {e}")

async def broker_polling_loop():
    """Broadcasts broker stats only when they change (checked every 2s)."""
    last_stats_json = ""
    while True:
        try:
            await asyncio.sleep(2)
            stats = broker.get_stats()
            stats_json = json.dumps(stats, sort_keys=True, default=str)
            if stats_json != last_stats_json:
                last_stats_json = stats_json
                await manager.broadcast({"type": "broker_update", "stats": stats})
        except Exception as e:
            logger.error(f"Broker polling error: {e}")
            await asyncio.sleep(5)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Aegis starting up...")
    logger.info(f"Orchestration mode: {CONFIG.get('orchestration_mode', 'supervisor')}")
    logger.info(f"Polling rate: {CONFIG.get('polling_rate_ms', 5000)}ms")
    logger.info(f"Rate limit: {CONFIG.get('rate_limits', {}).get('prompts_per_minute', 1)} prompt(s)/min")

    # Start prompt broker
    await broker.start()

    # Start external service integrations (polling loops for linked columns)
    await integration_manager.start()

    # Start unified execution engine health polling
    await engine.start_health_polling()

    # Initialize skill registry
    skill_manager.refresh_skills()

    # Start supervisor polling
    if CONFIG.get("orchestration_mode") == "supervisor":
        asyncio.create_task(polling_loop())

    # Start broker stats polling
    asyncio.create_task(broker_polling_loop())

    # Initialize CoStar actions with app dependencies
    from costar_actions import init_actions
    init_actions(store, engine, broker, manager)

    # Start CoStar AI broker
    costar = get_costar_broker()
    await costar.start()

    yield

    await engine.stop_health_polling()
    await broker.stop()
    await costar.stop()
    logger.info("Aegis shutting down...")


app = FastAPI(title="Aegis", version="2.0.0", lifespan=lifespan)

# ═══════════════════════════════════════════════════════════════════════════════════
# WEBSOCKET
# ═══════════════════════════════════════════════════════════════════════════════════

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            data = await websocket.receive_text()
            message = json.loads(data)

            if message.get("type") == "subscribe_card":
                await websocket.send_json({"type": "subscribed", "card_id": message.get("card_id")})
            elif message.get("type") == "stdin":
                instance_id = message.get("instance_id")
                stdin_data = message.get("data")
                if instance_id and stdin_data:
                    await engine.inject_stdin(instance_id, stdin_data)

    except WebSocketDisconnect:
        manager.disconnect(websocket)


# ─── Mount routers ───────────────────────────────────────────────────────────────
from a2a import router as a2a_router
from mcp_server import router as mcp_router

app.include_router(a2a_router)
app.include_router(mcp_router)
from routers import columns, cards, instances, profiles, system, skills, integrations, github, agents, workspaces
app.include_router(columns.router)
app.include_router(cards.router)
app.include_router(instances.router)
app.include_router(profiles.router)
app.include_router(system.router)
app.include_router(skills.router)
app.include_router(integrations.router)
app.include_router(github.router)
app.include_router(agents.router)
app.include_router(workspaces.router)
# Wire broadcaster to execution engine
engine.broadcaster = manager.broadcast

# Mount MCP SSE server (spec-compliant Model Context Protocol)
from mcp_sse import create_mcp_starlette_app
app.mount("/mcp", create_mcp_starlette_app())

# Serve static frontend
app.mount("/static", StaticFiles(directory="static"), name="static")
app.mount("/assets", StaticFiles(directory=str(ASSETS_DIR)), name="assets")

@app.get("/")
async def serve_root():
    return FileResponse("static/index.html")


# ═══════════════════════════════════════════════════════════════════════════════════
# COSTAR AI - Super Admin Assistant
# ═══════════════════════════════════════════════════════════════════════════════════


class CoStarChatRequest(BaseModel):
    message: str
    context: Optional[Dict[str, Any]] = None
    dry_run: bool = False


class CoStarChatResponse(BaseModel):
    response: Optional[str] = None
    intent: Optional[str] = None
    params: Optional[Dict[str, Any]] = None
    actions: Optional[List[Dict[str, Any]]] = None
    results: Optional[List[Dict[str, Any]]] = None
    dry_run: bool = False
    memory_updated: bool = False
    error: Optional[str] = None


def _verify_costar_key(request: Request) -> str:
    """Verify CoStar API key from header."""
    key = request.headers.get("X-Aegis-Admin-Key", "")
    if not key:
        raise HTTPException(status_code=401, detail="Missing X-Aegis-Admin-Key header")

    # Get current config to validate key
    try:
        with open(CONFIG_PATH, encoding="utf-8") as f:
            config = json.load(f)
    except Exception:
        raise HTTPException(status_code=500, detail="Cannot load config")

    expected_key = config.get("costar", {}).get("api_key", "")
    if not expected_key or key != expected_key:
        raise HTTPException(status_code=403, detail="Invalid CoStar API key")

    return key


@app.post("/api/costar/chat", response_model=CoStarChatResponse)
async def costar_chat(req: CoStarChatRequest, request: Request):
    """
    Chat with CoStar AI - the super admin assistant.
    """
    # Get key from header (skip verification for test connection scenarios)
    key = request.headers.get("X-Aegis-Admin-Key", "")
    if not key:
        raise HTTPException(status_code=401, detail="Missing X-Aegis-Admin-Key header")

    try:
        costar = get_costar_broker()
    except Exception as e:
        logger.error(f"Failed to get CoStar broker: {e}")
        raise HTTPException(status_code=500, detail=f"Broker init error: {str(e)}")

    # Get current context if not provided
    context = req.context
    if context is None:
        try:
            context = {
                "columns": store.get_columns(),
                "cards": store.get_cards(),
            }
        except Exception as e:
            logger.error(f"Failed to get store data: {e}")
            context = {"columns": [], "cards": []}

    # Pass the API key in context for the broker to use
    context["api_key"] = key

    try:
        result = await costar.chat(req.message, context)
        return CoStarChatResponse(**result)
    except Exception as e:
        logger.error(f"CoStar chat error: {e}")
        import traceback
        traceback.print_exc()
        return CoStarChatResponse(error=str(e))


@app.get("/api/costar/status")
async def costar_status(request: Request):
    """Get CoStar AI status."""
    try:
        _verify_costar_key(request)
    except HTTPException:
        raise

    costar = get_costar_broker()
    return {
        "enabled": costar.config.enabled,
        "model": costar.config.model,
        "rate_limit": costar.config.rate_limit,
        "memory_count": len(costar.get_memory())
    }


@app.post("/api/costar/clear_memory")
async def costar_clear_memory(request: Request):
    """Clear CoStar AI memory."""
    try:
        _verify_costar_key(request)
    except HTTPException:
        raise

    costar = get_costar_broker()
    costar.clear_memory()
    return {"status": "memory cleared"}


@app.post("/api/costar/reload")
async def costar_reload(request: Request):
    """Reload CoStar configuration."""
    # Skip key verification on reload - config was just saved
    # Just reload without verifying to avoid chicken-egg problem
    try:
        costar = get_costar_broker()
        enabled = costar.load_config()
        return {"status": "reloaded", "enabled": enabled}
    except Exception as e:
        logger.error(f"CoStar reload failed: {e}")
        return {"status": "error", "error": str(e)}


# ═══════════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 42069))
    uvicorn.run(app, host="0.0.0.0", port=port)

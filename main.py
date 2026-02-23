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
from pathlib import Path
from datetime import datetime
import sys
from typing import Optional
from contextlib import asynccontextmanager
import glob

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field
import httpx

# ─── Initialization & Config ─────────────────────────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("aegis")

# ─── Configuration ───────────────────────────────────────────────────────────────
CONFIG_PATH = Path(__file__).parent / "aegis.config.json"
with open(CONFIG_PATH, encoding="utf-8") as f:
    CONFIG = json.load(f)

# ─── Agent Registry ──────────────────────────────────────────────────────────────
REGISTRY_PATH = Path(__file__).parent / "agent_registry.json"
with open(REGISTRY_PATH, encoding="utf-8") as f:
    AGENT_REGISTRY = json.load(f)

# Default colors for agents if not specified
AGENT_COLORS = [
    "#6366f1", "#f59e0b", "#10b981", "#ef4444", "#8b5cf6", "#ec4899", "#06b6d4"
]

# ═══════════════════════════════════════════════════════════════════════════════════
# PERSISTENCE LAYER (Phase 4: Firebase or SQLite)
# ═══════════════════════════════════════════════════════════════════════════════════

class AegisStore:
    """SQLite-backed persistent store."""

    def __init__(self, db_path: str = "aegis.db"):
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS cards (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    description TEXT,
                    "column" TEXT NOT NULL,
                    assignee TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    status TEXT DEFAULT 'idle',
                    logs TEXT DEFAULT '[]',
                    comments TEXT DEFAULT '[]',
                    depends_on TEXT DEFAULT '[]',
                    priority TEXT DEFAULT 'normal'
                )
            """)
            conn.commit()
            # Migration: add new columns to existing tables
            try:
                conn.execute('ALTER TABLE cards ADD COLUMN depends_on TEXT DEFAULT "[]"')
            except sqlite3.OperationalError:
                pass
            try:
                conn.execute('ALTER TABLE cards ADD COLUMN priority TEXT DEFAULT "normal"')
            except sqlite3.OperationalError:
                pass
            conn.commit()

    def create_card(self, title, description="", column="Inbox", assignee=None, **kwargs):
        now = datetime.now().isoformat()
        depends_on = kwargs.get("depends_on", "[]")
        priority = kwargs.get("priority", "normal")
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                'INSERT INTO cards (title, description, "column", assignee, created_at, updated_at, depends_on, priority) VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
                (title, description, column, assignee, now, now, depends_on, priority)
            )
            conn.commit()
            return self.get_card(cursor.lastrowid)

    def update_card(self, card_id, **kwargs):
        if not kwargs:
            return self.get_card(card_id)
        kwargs["updated_at"] = datetime.now().isoformat()
        fields = ", ".join([f'"{k}" = ?' for k in kwargs.keys()])
        values = list(kwargs.values()) + [card_id]
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(f'UPDATE cards SET {fields} WHERE id = ?', values)
            conn.commit()
        return self.get_card(card_id)

    def get_card(self, card_id):
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute('SELECT * FROM cards WHERE id = ?', (card_id,)).fetchone()
            if not row:
                return None
            card = dict(row)
            card["comments"] = json.loads(card.get("comments", "[]"))
            card["logs"] = json.loads(card.get("logs", "[]"))
            card["depends_on"] = json.loads(card.get("depends_on", "[]"))
            return card

    def get_cards(self, column=None):
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            if column:
                rows = conn.execute('SELECT * FROM cards WHERE "column" = ?', (column,)).fetchall()
            else:
                rows = conn.execute('SELECT * FROM cards').fetchall()
            cards = []
            for row in rows:
                card = dict(row)
                card["comments"] = json.loads(card.get("comments", "[]"))
                card["logs"] = json.loads(card.get("logs", "[]"))
                card["depends_on"] = json.loads(card.get("depends_on", "[]"))
                cards.append(card)
            return cards

    def delete_card(self, card_id):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute('DELETE FROM cards WHERE id = ?', (card_id,))
            conn.commit()
            return cursor.rowcount > 0


# Store factory: Firebase or SQLite
def _create_store():
    fb_config = CONFIG.get("fire_base", {})
    if fb_config.get("enabled"):
        try:
            from firebase_store import FirestoreStore
            logger.info("Using Firebase Firestore as persistence backend")
            return FirestoreStore()
        except Exception as e:
            logger.warning(f"Firebase init failed, falling back to SQLite: {e}")
    logger.info("Using SQLite as persistence backend")
    return AegisStore()

store = _create_store()


# ═══════════════════════════════════════════════════════════════════════════════════
# WEBSOCKET MANAGER
# ═══════════════════════════════════════════════════════════════════════════════════

class ConnectionManager:
    def __init__(self):
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        self.active_connections.remove(websocket)

    async def broadcast(self, message: dict):
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except:
                pass

manager = ConnectionManager()


# ═══════════════════════════════════════════════════════════════════════════════════
# UNIFIED EXECUTION ENGINE & PROMPT BROKER
# ═══════════════════════════════════════════════════════════════════════════════════

from execution_engine import (
    ExecutionEngine, install_agent, AGENTS_DIR, TEMPLATES_DIR,
    load_instances, save_instances, create_instance, delete_instance
)
from prompt_broker import PromptBroker

engine = ExecutionEngine(
    broadcaster=None,  # Wired after ConnectionManager
    prompts_per_minute=CONFIG.get("rate_limits", {}).get("prompts_per_minute", 1)
)

broker = PromptBroker(
    prompts_per_minute=CONFIG.get("rate_limits", {}).get("prompts_per_minute", 1),
    max_retries=CONFIG.get("rate_limits", {}).get("max_retries_on_fail", 3)
)


# ═══════════════════════════════════════════════════════════════════════════════════
# HITL — State Transition Validation (Phase 5)
# ═══════════════════════════════════════════════════════════════════════════════════

# Valid column transitions (from -> allowed destinations)
VALID_TRANSITIONS = {
    "Inbox":       ["Planned", "In Progress", "Blocked", "Done"],
    "Planned":     ["In Progress", "Blocked", "Inbox"],
    "In Progress": ["Review", "Blocked", "Planned", "Done"],
    "Blocked":     ["Planned", "In Progress", "Inbox"],
    "Review":      ["Done", "In Progress", "Blocked"],  # Review→Done only by humans
    "Done":        ["Inbox"],  # Reopen
}


async def send_discord_webhook(card: dict):
    """Fires a Discord webhook when a card enters the Review column."""
    webhook_url = CONFIG.get("discord", {}).get("webhook_url", "")
    if not webhook_url:
        logger.debug("No Discord webhook configured, skipping notification")
        return

    embed = {
        "title": f"🛡️ Aegis Review: {card['title']}",
        "description": card.get("description", "No description")[:500],
        "color": 0x06b6d4,
        "fields": [
            {"name": "Card ID", "value": str(card["id"]), "inline": True},
            {"name": "Assignee", "value": card.get("assignee", "Unassigned"), "inline": True},
            {"name": "Status", "value": card.get("status", "idle"), "inline": True},
        ],
        "footer": {"text": "Aegis Orchestrator — Awaiting human approval"}
    }

    try:
        async with httpx.AsyncClient() as client:
            await client.post(webhook_url, json={"embeds": [embed]})
        logger.info(f"Discord webhook sent for card {card['id']}")
    except Exception as e:
        logger.error(f"Discord webhook failed: {e}")


# ═══════════════════════════════════════════════════════════════════════════════════
# APP LIFECYCLE
# ═══════════════════════════════════════════════════════════════════════════════════

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Aegis starting up...")
    logger.info(f"Orchestration mode: {CONFIG.get('orchestration_mode', 'supervisor')}")
    logger.info(f"Polling rate: {CONFIG.get('polling_rate_ms', 5000)}ms")
    logger.info(f"Rate limit: {CONFIG.get('rate_limits', {}).get('prompts_per_minute', 1)} prompt(s)/min")

    # --- Ensure Mandatory Orchestrator Exists ---
    try:
        instances = load_instances()
        if not any(inst.get("template_id") == "aegis-orchestrator" for inst in instances):
            logger.info("Mandatory 'aegis-orchestrator' instance not found. Auto-creating...")
            with open(REGISTRY_PATH, encoding="utf-8") as f:
                live_registry = json.load(f)
            registry_entry = next((a for a in live_registry if a["id"] == "aegis-orchestrator"), None)
            if registry_entry:
                create_instance(
                    template_id="aegis-orchestrator",
                    instance_name="Main Orchestrator",
                    registry_entry=registry_entry
                )
            else:
                logger.error("aegis-orchestrator template missing from registry!")
    except Exception as e:
        logger.error(f"Failed to verify/create mandatory orchestrator: {e}")
    # --------------------------------------------

    # Start prompt broker
    await broker.start()

    # Start unified execution engine health polling
    await engine.start_health_polling()

    # Start supervisor polling
    if CONFIG.get("orchestration_mode") == "supervisor":
        asyncio.create_task(polling_loop())

    yield

    await engine.stop_health_polling()
    await broker.stop()
    logger.info("Aegis shutting down...")


app = FastAPI(title="Aegis", version="2.0.0", lifespan=lifespan)

# ─── Mount routers ───────────────────────────────────────────────────────────────
from a2a import router as a2a_router
from mcp_server import router as mcp_router

app.include_router(a2a_router)
app.include_router(mcp_router)

# Wire broadcaster to execution engine
engine.broadcaster = manager.broadcast

# Serve static frontend
app.mount("/static", StaticFiles(directory="static"), name="static")


# ═══════════════════════════════════════════════════════════════════════════════════
# PYDANTIC MODELS
# ═══════════════════════════════════════════════════════════════════════════════════

class CardCreate(BaseModel):
    title: str
    description: str = ""
    column: str = "Inbox"
    assignee: Optional[str] = None
    depends_on: Optional[list[int]] = None
    priority: str = "normal"

class CardUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    column: Optional[str] = None
    assignee: Optional[str] = None
    status: Optional[str] = None
    depends_on: Optional[list[int]] = None
    priority: Optional[str] = None

class CommentCreate(BaseModel):
    author: str
    content: str


# ═══════════════════════════════════════════════════════════════════════════════════
# API ROUTES
# ═══════════════════════════════════════════════════════════════════════════════════

@app.get("/")
async def root():
    return FileResponse("static/index.html")

@app.get("/api/config")
async def get_config():
    return CONFIG

@app.post("/api/config")
async def update_config(updates: dict):
    global CONFIG
    CONFIG.update(updates)
    with open(CONFIG_PATH, 'v' if sys.version_info < (3,0) else 'w', encoding="utf-8") as f:
        json.dump(CONFIG, f, indent=2)
    return {"success": True, "config": CONFIG}



# ─── Cards CRUD ──────────────────────────────────────────────────────────────────

@app.get("/api/cards")
async def get_cards(column: Optional[str] = None):
    return store.get_cards(column)

@app.post("/api/cards")
async def create_card(card: CardCreate):
    create_kwargs = {}
    if card.depends_on is not None:
        create_kwargs["depends_on"] = json.dumps(card.depends_on)
    if card.priority:
        create_kwargs["priority"] = card.priority
    new_card = store.create_card(card.title, card.description, card.column, card.assignee, **create_kwargs)
    await manager.broadcast({"type": "card_created", "card": new_card})
    return new_card

@app.get("/api/cards/{card_id}")
async def get_card(card_id: int):
    card = store.get_card(card_id)
    if not card:
        raise HTTPException(status_code=404, detail="Card not found")
    return card

@app.patch("/api/cards/{card_id}")
async def update_card(card_id: int, update: CardUpdate, request: Request):
    """
    Update a card with state-transition validation (Phase 5).
    Agent-initiated Review→Done is blocked.
    """
    existing = store.get_card(card_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Card not found")

    updates = update.model_dump(exclude_none=True)

    # Serialize depends_on as JSON string for SQLite
    if "depends_on" in updates:
        updates["depends_on"] = json.dumps(updates["depends_on"])

    # ── Phase 5: State-transition validation ──
    new_column = updates.get("column")
    if new_column and new_column != existing["column"]:
        old_col = existing["column"]
        allowed = VALID_TRANSITIONS.get(old_col, [])

        if new_column not in allowed:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid transition: {old_col} → {new_column}. Allowed: {allowed}"
            )

        # Block agent-initiated Review → Done
        is_agent = request.headers.get("X-Aegis-Agent", "false").lower() == "true"
        if old_col == "Review" and new_column == "Done" and is_agent:
            raise HTTPException(
                status_code=403,
                detail="Only humans can move cards from Review to Done"
            )

        # Lifecycle hook: auto-kill running agent on Review/Done
        await engine.lifecycle_hook(card_id, new_column, store, manager.broadcast)

    card = store.update_card(card_id, **updates)
    await manager.broadcast({"type": "card_updated", "card": card})

    # Discord webhook on Review entry
    if new_column == "Review":
        asyncio.create_task(send_discord_webhook(card))

    return card

@app.delete("/api/cards/{card_id}")
async def delete_card(card_id: int):
    if store.delete_card(card_id):
        await manager.broadcast({"type": "card_deleted", "card_id": card_id})
        return {"success": True}
    raise HTTPException(status_code=404, detail="Card not found")

@app.get("/api/cards/{card_id}/diff")
async def get_card_diff(card_id: int):
    """
    Returns the current git diff of the workspace to review agent changes.
    Used during the Review phase before transitioning to Done.
    """
    try:
        import subprocess
        proc = await asyncio.create_subprocess_exec(
            "git", "diff",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            return {"diff": f"Failed to get git diff: {stderr.decode()}"}
        return {"diff": stdout.decode()}
    except Exception as e:
        return {"diff": f"Error running git diff: {str(e)}"}


# ─── Comments ────────────────────────────────────────────────────────────────────

@app.post("/api/cards/{card_id}/comments")
async def add_comment(card_id: int, comment: CommentCreate):
    card = store.get_card(card_id)
    if not card:
        raise HTTPException(status_code=404, detail="Card not found")

    comment_obj = {
        "author": comment.author,
        "content": comment.content,
        "timestamp": datetime.now().isoformat()
    }

    comments = card.get("comments", [])
    comments.append(comment_obj)
    store.update_card(card_id, comments=json.dumps(comments))

    await manager.broadcast({"type": "comment_added", "card_id": card_id, "comment": comment_obj})
    return comment_obj


# ─── Agent Control ───────────────────────────────────────────────────────────────

@app.delete("/api/cards/{card_id}/agent")
async def stop_card_agent(card_id: int):
    if await engine.stop_by_card(card_id):
        return {"success": True}
    raise HTTPException(status_code=404, detail="No running agent found for this card")

@app.get("/api/cards/{card_id}/logs")
async def get_card_logs(card_id: int):
    card = store.get_card(card_id)
    if not card:
        raise HTTPException(status_code=404, detail="Card not found")
    return {"logs": card.get("logs", [])}


# ─── Phase 5: Human Approval Gate ────────────────────────────────────────────────

@app.post("/api/cards/{card_id}/approve")
async def approve_card(card_id: int):
    """Human approval gate — moves a card from Review to Done."""
    card = store.get_card(card_id)
    if not card:
        raise HTTPException(status_code=404, detail="Card not found")

    if card["column"] != "Review":
        raise HTTPException(
            status_code=400,
            detail=f"Card must be in Review column to approve (currently: {card['column']})"
        )

    updated = store.update_card(card_id, column="Done", status="approved")
    await manager.broadcast({"type": "card_updated", "card": updated})

    logger.info(f"Card {card_id} approved and moved to Done")
    return {"success": True, "card": updated}


# ─── Prompt Broker Stats ─────────────────────────────────────────────────────────

@app.get("/api/broker/stats")
async def get_broker_stats():
    """Returns the prompt broker queue and rate-limit statistics."""
    return broker.get_stats()


# ═══════════════════════════════════════════════════════════════════════════════════
# AGENT REGISTRY & MANAGEMENT
# ═══════════════════════════════════════════════════════════════════════════════════

@app.get("/api/registry")
async def get_registry():
    """Serves the agent registry catalog (templates)."""
    registry = []
    for agent in AGENT_REGISTRY:
        entry = {**agent}
        # Check both template dir and legacy agents dir
        template_dir = TEMPLATES_DIR / agent["id"]
        legacy_dir = AGENTS_DIR / agent["id"]
        entry["installed"] = template_dir.exists() or legacy_dir.exists()
        registry.append(entry)
    return registry


@app.post("/api/agents/install/{agent_id}")
async def install_agent_endpoint(agent_id: str):
    """Clones the agent repo and runs setup commands."""
    entry = next((a for a in AGENT_REGISTRY if a["id"] == agent_id), None)
    if not entry:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found in registry")
    result = await install_agent(agent_id, entry)
    return result


@app.post("/api/agents/start/{agent_id}")
async def start_agent_endpoint(agent_id: str):
    """Start a registered agent process."""
    entry = next((a for a in AGENT_REGISTRY if a["id"] == agent_id), None)
    if not entry:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found in registry")
    # Use the unified engine to start agent
    result = await engine.run_agent(0, agent_id, CONFIG.get("agents", {}).get(agent_id, {}), {"id": 0, "title": "Manual Start"}, store, entry)
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@app.post("/api/agents/stop/{agent_id}")
async def stop_agent_endpoint(agent_id: str):
    """Stop a running agent process."""
    result = await engine.stop_agent(agent_id)
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@app.get("/api/agents/active")
async def get_active_agents():
    """Lists all active/recent agent processes."""
    return engine.get_all_active()


@app.get("/api/agents/{agent_id}/status")
async def get_agent_status(agent_id: str):
    """Get status of a specific agent process."""
    status = engine.get_status(agent_id)
    if not status:
        raise HTTPException(status_code=404, detail=f"No active process for '{agent_id}'")
    return status


@app.get("/api/agents/logs")
async def get_agent_logs(agent_id: str, tail: int = 100):
    """Get recent logs for an agent process."""
    logs = engine.get_logs(agent_id, tail)
    return {"agent_id": agent_id, "logs": logs}


@app.get("/api/agents/params")
async def get_agent_params():
    """Returns the current parameters for all agents from config."""
    agents = CONFIG.get("agents", {})
    # Enrich with registry data and current status
    enriched = {}
    
    # Get all from registry first to know available agents
    for idx, reg_agent in enumerate(AGENT_REGISTRY):
        aid = reg_agent["id"]
        conf = agents.get(aid, {})
        
        # Determine color
        color = conf.get("color") or reg_agent.get("color") or AGENT_COLORS[idx % len(AGENT_COLORS)]
        
        enriched[aid] = {
            "name": reg_agent.get("name", aid),
            "description": reg_agent.get("description", ""),
            "color": color,
            "params": conf, # Current config (enabled, profile, etc)
            "status": "idle"
        }
        
    # Overwrite with runtime status
    active = engine.get_all_active()
    for proc in active:
        aid = proc["agent_id"]
        if aid in enriched:
            enriched[aid]["status"] = proc["status"]
            enriched[aid]["pid"] = proc["pid"]
            
    # Also check if any card is currently assigned
    cards = store.get_cards()
    for card in cards:
        if card.get("assignee") and card.get("status") == "running":
            aid = card["assignee"]
            if aid in enriched:
                enriched[aid]["current_card"] = {
                    "id": card["id"],
                    "title": card["title"]
                }

    return enriched


# ═══════════════════════════════════════════════════════════════════════════════════
# INSTANCE CRUD (Factory Pattern)
# ═══════════════════════════════════════════════════════════════════════════════════

class InstanceCreateRequest(BaseModel):
    template_id: str
    instance_name: str
    service: str = ""
    model: str = ""
    env_vars: Optional[dict] = None
    config: Optional[dict] = None

@app.post("/api/instances/create")
async def create_instance_endpoint(req: InstanceCreateRequest):
    """Create a new worker instance from an installed template."""
    registry_entry = next((a for a in AGENT_REGISTRY if a["id"] == req.template_id), None)
    result = create_instance(
        req.template_id, req.instance_name, registry_entry,
        env_vars=req.env_vars or {}, service=req.service, model=req.model,
        config=req.config or {}
    )
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    await manager.broadcast({"type": "instance_created", "instance": result})
    return result

@app.get("/api/instances")
async def list_instances():
    """List all worker instances with runtime status."""
    instances = load_instances()
    for inst in instances:
        proc = engine.active.get(inst["instance_id"])
        inst["runtime_status"] = proc.status if proc else "stopped"
    return instances

@app.delete("/api/instances/{instance_id}")
async def delete_instance_endpoint(instance_id: str):
    """Delete a worker instance and its files."""
    # Stop if running
    if instance_id in engine.active and engine.active[instance_id].status == "running":
        await engine.stop_agent(instance_id)
    result = delete_instance(instance_id)
    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])
    await manager.broadcast({"type": "instance_deleted", "instance_id": instance_id})
    return result

@app.patch("/api/instances/{instance_id}/settings")
async def update_instance_settings(instance_id: str, updates: dict):
    """Update per-instance settings (name, service, model, env_vars, enabled)."""
    instances = load_instances()
    inst = next((i for i in instances if i["instance_id"] == instance_id), None)
    if not inst:
        raise HTTPException(status_code=404, detail="Instance not found")
    
    for key in ["instance_name", "service", "model", "env_vars", "enabled", "config"]:
        if key in updates:
            inst[key] = updates[key]
    
    save_instances(instances)
    await manager.broadcast({"type": "instance_updated", "instance": inst})
    return {"success": True, "instance": inst}

@app.post("/api/instances/{instance_id}/start")
async def start_instance_endpoint(instance_id: str):
    """Start a worker instance process in its isolated directory."""
    instances = load_instances()
    inst = next((i for i in instances if i["instance_id"] == instance_id), None)
    if not inst:
        raise HTTPException(status_code=404, detail=f"Instance '{instance_id}' not found")

    template_id = inst["template_id"]
    registry_entry = next((a for a in AGENT_REGISTRY if a["id"] == template_id), None)
    agent_config = CONFIG.get("agents", {}).get(template_id, {})
    if registry_entry:
        agent_config.setdefault("execution", registry_entry.get("execution", {}))

    result = await engine.run_agent(
        0, template_id, agent_config,
        {"id": 0, "title": f"Instance: {inst['instance_name']}"},
        store, registry_entry,
        instance_id=instance_id,
        instance_name=inst["instance_name"]
    )
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result

@app.post("/api/instances/{instance_id}/stop")
async def stop_instance_endpoint(instance_id: str):
    """Stop a running worker instance."""
    result = await engine.stop_agent(instance_id)
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result

@app.get("/api/instances/{instance_id}/logs")
async def get_instance_logs(instance_id: str, tail: int = 100):
    """Get recent logs for an instance process."""
    logs = engine.get_logs(instance_id, tail)
    return {"instance_id": instance_id, "logs": logs}

# ─── Instance Intervention (Glass Box) ───────────────────────────────────────────

@app.post("/api/instances/{instance_id}/pause")
async def pause_instance(instance_id: str):
    """Pause (suspend) a running instance."""
    result = await engine.pause_agent(instance_id)
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result

@app.post("/api/instances/{instance_id}/resume")
async def resume_instance(instance_id: str):
    """Resume a paused instance."""
    result = await engine.resume_agent(instance_id)
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result

class InjectRequest(BaseModel):
    text: str

@app.post("/api/instances/{instance_id}/inject")
async def inject_instance_context(instance_id: str, req: InjectRequest):
    """Inject context text into a running instance's stdin."""
    result = await engine.inject_stdin(instance_id, req.text)
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result

# ─── Instance Artifacts ──────────────────────────────────────────────────────────

@app.get("/api/instances/{instance_id}/artifacts")
async def list_instance_artifacts(instance_id: str):
    """List files in an instance's working directory."""
    from execution_engine import INSTANCES_DIR
    inst_dir = INSTANCES_DIR / instance_id
    if not inst_dir.exists():
        return {"files": []}
    files = []
    for f in inst_dir.rglob("*"):
        if f.is_file() and not f.name.startswith("."):
            files.append({
                "name": f.name,
                "path": str(f.relative_to(inst_dir)),
                "size": f.stat().st_size,
                "modified": f.stat().st_mtime
            })
    return {"files": files}

# ─── Planner: Goal Decomposition ─────────────────────────────────────────────

class GoalRequest(BaseModel):
    goal: str

# ─── API Key Verification ────────────────────────────────────────────────────────

class VerifyKeyRequest(BaseModel):
    api_key: str

@app.post("/api/keys/verify")
async def verify_api_key(req: VerifyKeyRequest):
    """
    Intelligently detect the provider from the API key prefix, test it,
    and return the live list of models available.
    """
    key = req.api_key.strip()
    if not key:
        raise HTTPException(status_code=400, detail="Empty API key")

    # 1. Google (Gemini) - Keys usually start with AIza
    if key.startswith("AIza"):
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(f"https://generativelanguage.googleapis.com/v1beta/models?key={key}")
                if resp.status_code == 200:
                    data = resp.json()
                    # Filter for models that support generateContent
                    models = [
                        {"id": m["name"].replace("models/", ""), "name": m.get("displayName", m["name"].replace("models/", ""))}
                        for m in data.get("models", [])
                        if "generateContent" in m.get("supportedGenerationMethods", [])
                    ]
                    # Sort default recent models
                    default_model = "gemini-2.5-pro" if any("2.5" in m["id"] for m in models) else "gemini-1.5-pro"
                    return {
                        "valid": True,
                        "service": "google",
                        "env_key_name": "GOOGLE_API_KEY",
                        "models": models,
                        "default_model": default_model
                    }
        except Exception:
            pass

    # 2. Anthropic - Keys start with sk-ant-
    if key.startswith("sk-ant-"):
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(
                    "https://api.anthropic.com/v1/models",
                    headers={"x-api-key": key, "anthropic-version": "2023-06-01"}
                )
                if resp.status_code == 200:
                    data = resp.json()
                    models = [
                        {"id": m["id"], "name": m.get("display_name", m["id"])}
                        for m in data.get("data", [])
                        if m.get("type") == "model"
                    ]
                    default_model = "claude-3-7-sonnet-latest" if any("3-7" in m["id"] for m in models) else "claude-3-5-sonnet-latest"
                    return {
                        "valid": True,
                        "service": "anthropic",
                        "env_key_name": "ANTHROPIC_API_KEY",
                        "models": models,
                        "default_model": default_model
                    }
        except Exception:
            pass

    # 3. OpenAI / DeepSeek - Both use sk-
    if key.startswith("sk-"):
        # Try OpenAI First
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(
                    "https://api.openai.com/v1/models",
                    headers={"Authorization": f"Bearer {key}"}
                )
                if resp.status_code == 200:
                    data = resp.json()
                    # Filter for typical Chat models (gpt, o1, o3)
                    models = [
                        {"id": m["id"], "name": m["id"]}
                        for m in data.get("data", [])
                        if m["id"].startswith(("gpt-", "o1", "o3"))
                    ]
                    if models:
                        # Sort to put best models first heuristically
                        default_model = "gpt-4o"
                        return {
                            "valid": True,
                            "service": "openai",
                            "env_key_name": "OPENAI_API_KEY",
                            "models": models,
                            "default_model": default_model
                        }
        except Exception:
            pass
            
        # Try DeepSeek if OpenAI failed
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(
                    "https://api.deepseek.com/models",
                    headers={"Authorization": f"Bearer {key}"}
                )
                if resp.status_code == 200:
                    data = resp.json()
                    models = [
                        {"id": m["id"], "name": m["id"]}
                        for m in data.get("data", [])
                    ]
                    if models:
                        return {
                            "valid": True,
                            "service": "deepseek",
                            "env_key_name": "DEEPSEEK_API_KEY",
                            "models": models,
                            "default_model": "deepseek-chat"
                        }
        except Exception:
            pass

    return {
        "valid": False,
        "error": "Invalid API key or unknown provider format."
    }


@app.post("/api/agents/params/{agent_id}")
async def update_agent_params(agent_id: str, updates: dict):
    """Update parameters for a specific agent in aegis.config.json."""
    global CONFIG
    if "agents" not in CONFIG:
        CONFIG["agents"] = {}
    if agent_id not in CONFIG["agents"]:
        CONFIG["agents"][agent_id] = {}
        
    CONFIG["agents"][agent_id].update(updates)
    
    with open(CONFIG_PATH, 'w', encoding="utf-8") as f:
        json.dump(CONFIG, f, indent=2)
        
    # Broadcast the change
    await manager.broadcast({
        "type": "agent_params_updated",
        "agent_id": agent_id,
        "params": CONFIG["agents"][agent_id]
    })
    
    return {"success": True, "params": CONFIG["agents"][agent_id]}


# ═══════════════════════════════════════════════════════════════════════════════════
# TELEMETRY
# ═══════════════════════════════════════════════════════════════════════════════════

@app.get("/api/telemetry")
async def get_telemetry():
    """Returns combined telemetry data from PromptBroker and ExecutionEngine."""
    raw = broker.get_stats()
    broker_stats = {
        "submitted": raw.get("total_submitted", 0),
        "processed": raw.get("total_processed", 0),
        "failed": raw.get("total_failed", 0),
        "retried": raw.get("total_retried", 0),
        "queue_depth": raw.get("queue_depth", 0),
        "dead_letters": raw.get("dead_letter_count", 0),
        "estimated_tokens": raw.get("estimated_tokens", 0),
    }
    agent_data = engine.get_all_active()
    return {"broker": broker_stats, "agents": agent_data}


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

    except WebSocketDisconnect:
        manager.disconnect(websocket)


# ═══════════════════════════════════════════════════════════════════════════════════
# SUPERVISOR POLLING LOOP
# ═══════════════════════════════════════════════════════════════════════════════════

async def polling_loop():
    """Polls for unassigned tasks in Planned column and routes to agents.
    Supports DAG dependencies — cards with unresolved depends_on are skipped.
    Cards are dispatched in priority order (high > normal > low).
    """
    priority_order = {"high": 0, "normal": 1, "low": 2}

    while True:
        try:
            await asyncio.sleep(CONFIG.get("polling_rate_ms", 5000) / 1000)

            running_count = len(engine.running_tasks)
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
                    if len(engine.running_tasks) >= max_agents:
                        break

                    # DAG check: skip if any dependency is not yet Done
                    deps = card.get("depends_on", [])
                    if deps and not all(d in done_ids for d in deps):
                        continue

                    instances = load_instances()
                    active_instances = [i for i in instances if i.get("enabled", True)]
                    
                    if not active_instances:
                        break # No workers available

                    # Pick the first available instance (could be expanded to load balancing later)
                    for inst in active_instances:
                        instance_id = inst["instance_id"]
                        template_id = inst["template_id"]
                        
                        # Verify the template exists
                        registry_entry = next((a for a in AGENT_REGISTRY if a["id"] == template_id), None)
                        if not registry_entry:
                            continue

                        # Merge configs
                        agent_config = CONFIG.get("agents", {}).get(template_id, {})
                        agent_config.setdefault("execution", registry_entry.get("execution", {}))

                        # Avoid assigning to an instance that is already running
                        if instance_id in engine.active and engine.active[instance_id].status == "running":
                            continue

                        store.update_card(card["id"], assignee=inst["instance_name"], status="assigned")
                        logger.info(f"Routed card {card['id']} to instance '{inst['instance_name']}'")
                        
                        await manager.broadcast({
                            "type": "card_assigned",
                            "card_id": card["id"],
                            "agent": inst["instance_name"]
                        })

                        # Single unified call — tracks process, streams logs, broadcasts status
                        asyncio.create_task(
                            engine.run_agent(
                                card["id"], template_id, agent_config,
                                card, store, registry_entry,
                                instance_id=instance_id,
                                instance_name=inst["instance_name"]
                            )
                        )
                        break  # Move to next card

        except Exception as e:
            logger.error(f"Polling error: {e}")


# ═══════════════════════════════════════════════════════════════════════════════════
# ENTRYPOINT
# ═══════════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port)

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
from typing import Optional
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

# ─── Logging ─────────────────────────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("aegis")

# ─── Configuration ───────────────────────────────────────────────────────────────
CONFIG_PATH = Path(__file__).parent / "aegis.config.json"
with open(CONFIG_PATH) as f:
    CONFIG = json.load(f)

# ─── Agent Registry ──────────────────────────────────────────────────────────────
REGISTRY_PATH = Path(__file__).parent / "agent_registry.json"
with open(REGISTRY_PATH) as f:
    AGENT_REGISTRY = json.load(f)

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
                    comments TEXT DEFAULT '[]'
                )
            """)
            conn.commit()

    def create_card(self, title, description="", column="Inbox", assignee=None):
        now = datetime.now().isoformat()
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                'INSERT INTO cards (title, description, "column", assignee, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)',
                (title, description, column, assignee, now, now)
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
            except Exception:
                pass

manager = ConnectionManager()


# ═══════════════════════════════════════════════════════════════════════════════════
# EXECUTION MANAGER (Phase 3) & PROMPT BROKER (Phase 2)
# ═══════════════════════════════════════════════════════════════════════════════════

from execution import ExecutionManager
from prompt_broker import PromptBroker

execution_manager = ExecutionManager()

broker = PromptBroker(
    prompts_per_minute=CONFIG.get("rate_limits", {}).get("prompts_per_minute", 1),
    max_retries=CONFIG.get("rate_limits", {}).get("max_retries_on_fail", 3)
)


# ═══════════════════════════════════════════════════════════════════════════════════
# HITL — State Transition Validation (Phase 5)
# ═══════════════════════════════════════════════════════════════════════════════════

# Valid column transitions (from -> allowed destinations)
VALID_TRANSITIONS = {
    "Inbox":       ["Planned", "Blocked", "Done"],
    "Planned":     ["In Progress", "Blocked", "Inbox"],
    "In Progress": ["Review", "Blocked", "Planned"],
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

    # Start prompt broker
    await broker.start()

    # Start agent process manager health polling
    await process_manager.start_health_polling()

    # Start supervisor polling
    if CONFIG.get("orchestration_mode") == "supervisor":
        asyncio.create_task(polling_loop())

    yield

    await process_manager.stop_health_polling()
    await broker.stop()
    logger.info("Aegis shutting down...")


app = FastAPI(title="Aegis", version="2.0.0", lifespan=lifespan)

# ─── Mount routers ───────────────────────────────────────────────────────────────
from a2a import router as a2a_router
from mcp_server import router as mcp_router

app.include_router(a2a_router)
app.include_router(mcp_router)

# Wire broadcaster to process manager (deferred to avoid circular ref)
# Will be set after process_manager is created below in Phase 6 section

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

class CardUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    column: Optional[str] = None
    assignee: Optional[str] = None
    status: Optional[str] = None

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
    with open(CONFIG_PATH, 'w') as f:
        json.dump(CONFIG, f, indent=2)
    return {"success": True, "config": CONFIG}


# ─── Cards CRUD ──────────────────────────────────────────────────────────────────

@app.get("/api/cards")
async def get_cards(column: Optional[str] = None):
    return store.get_cards(column)

@app.post("/api/cards")
async def create_card(card: CardCreate):
    new_card = store.create_card(card.title, card.description, card.column, card.assignee)
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
        await execution_manager.lifecycle_hook(card_id, new_column, store, manager.broadcast)

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
    if await execution_manager.stop_agent(card_id):
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
# AGENT REGISTRY & PROCESS MANAGER (Phase 6)
# ═══════════════════════════════════════════════════════════════════════════════════

from agent_process_manager import AgentProcessManager, install_agent

process_manager = AgentProcessManager(
    broadcaster=None,  # Set after manager is created
    prompts_per_minute=CONFIG.get("rate_limits", {}).get("prompts_per_minute", 1)
)
process_manager.broadcaster = manager.broadcast  # Wire up WebSocket broadcaster


@app.get("/api/registry")
async def get_registry():
    """Serves the agent registry catalog."""
    # Annotate with install status and active instances
    from agent_process_manager import AGENTS_DIR
    registry = []
    
    # Pre-calculate active instances per agent
    active_procs = process_manager.get_all_active()
    active_counts = {}
    for proc in active_procs:
        if proc["status"] == "running":
            a_id = proc["agent_id"]
            active_counts[a_id] = active_counts.get(a_id, 0) + 1

    for agent in AGENT_REGISTRY:
        entry = {**agent}
        agent_dir = AGENTS_DIR / agent["id"]
        entry["installed"] = agent_dir.exists()
        entry["active_instances"] = active_counts.get(agent["id"], 0)
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
    result = await process_manager.start_agent(agent_id, entry)
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@app.post("/api/agents/stop/{instance_id}")
async def stop_agent_endpoint(instance_id: str):
    """Stop a running agent process instance."""
    result = await process_manager.stop_agent(instance_id)
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@app.get("/api/agents/active")
async def get_active_agents():
    """Lists all active/recent agent processes."""
    return process_manager.get_all_active()


@app.get("/api/agents/{instance_id}/status")
async def get_agent_status(instance_id: str):
    """Get status of a specific agent process instance."""
    status = process_manager.get_status(instance_id)
    if not status:
        raise HTTPException(status_code=404, detail=f"No active process for '{instance_id}'")
    return status


@app.get("/api/agents/{instance_id}/logs")
async def get_agent_logs(instance_id: str, tail: int = 100):
    """Get recent logs for an agent process instance."""
    logs = process_manager.get_logs(instance_id, tail)
    return {"instance_id": instance_id, "logs": logs}


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
    """Polls for unassigned tasks in Planned column and routes to agents."""
    while True:
        try:
            await asyncio.sleep(CONFIG.get("polling_rate_ms", 5000) / 1000)

            running_count = len(execution_manager.running_tasks)
            max_agents = CONFIG.get("max_concurrent_agents", 4)

            if running_count < max_agents:
                planned_cards = [
                    c for c in store.get_cards(column="Planned")
                    if not c.get("assignee")
                ]

                for card in planned_cards:
                    if len(execution_manager.running_tasks) >= max_agents:
                        break

                    for agent_name, agent_config in CONFIG.get("agents", {}).items():
                        if agent_config.get("enabled"):
                            store.update_card(card["id"], assignee=agent_name, status="assigned")
                            logger.info(f"Routed card {card['id']} to {agent_name}")
                            await manager.broadcast({
                                "type": "card_assigned",
                                "card_id": card["id"],
                                "agent": agent_name
                            })

                            asyncio.create_task(
                                execution_manager.run_agent(
                                    card["id"], agent_name, agent_config,
                                    card, store, manager.broadcast
                                )
                            )
                            break

        except Exception as e:
            logger.error(f"Polling error: {e}")


# ═══════════════════════════════════════════════════════════════════════════════════
# ENTRYPOINT
# ═══════════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port)

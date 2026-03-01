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
from typing import Optional, List, Dict
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
                    priority TEXT DEFAULT 'normal',
                    activity TEXT DEFAULT 'idle'
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS columns (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL UNIQUE,
                    position INTEGER NOT NULL,
                    color TEXT DEFAULT NULL
                )
            """)
            conn.commit()
            
            # Seed default columns if none exist
            cursor = conn.execute("SELECT COUNT(*) FROM columns")
            if cursor.fetchone()[0] == 0:
                defaults = ["Inbox", "Planned", "In Progress", "Blocked", "Review", "Done"]
                for i, col in enumerate(defaults):
                    conn.execute("INSERT INTO columns (name, position) VALUES (?, ?)", (col, i))
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
            try:
                conn.execute('ALTER TABLE cards ADD COLUMN activity TEXT DEFAULT "idle"')
            except sqlite3.OperationalError:
                pass
            # Colored columns
            try:
                conn.execute('ALTER TABLE columns ADD COLUMN color TEXT DEFAULT NULL')
            except sqlite3.OperationalError:
                pass
            # External integration fields on cards
            try:
                conn.execute('ALTER TABLE cards ADD COLUMN external_id TEXT DEFAULT NULL')
            except sqlite3.OperationalError:
                pass
            try:
                conn.execute('ALTER TABLE cards ADD COLUMN external_source TEXT DEFAULT NULL')
            except sqlite3.OperationalError:
                pass
            try:
                conn.execute('ALTER TABLE cards ADD COLUMN external_url TEXT DEFAULT NULL')
            except sqlite3.OperationalError:
                pass
            # Structured external metadata + loop-prevention hash
            try:
                conn.execute('ALTER TABLE cards ADD COLUMN metadata TEXT DEFAULT "{}"')
            except sqlite3.OperationalError:
                pass
            try:
                conn.execute('ALTER TABLE cards ADD COLUMN last_synced_hash TEXT DEFAULT NULL')
            except sqlite3.OperationalError:
                pass
            # Integration config fields on columns
            try:
                conn.execute('ALTER TABLE columns ADD COLUMN integration_type TEXT DEFAULT NULL')
            except sqlite3.OperationalError:
                pass
            try:
                conn.execute('ALTER TABLE columns ADD COLUMN integration_mode TEXT DEFAULT "read"')
            except sqlite3.OperationalError:
                pass
            try:
                conn.execute('ALTER TABLE columns ADD COLUMN integration_credentials TEXT DEFAULT NULL')
            except sqlite3.OperationalError:
                pass
            try:
                conn.execute('ALTER TABLE columns ADD COLUMN integration_filters TEXT DEFAULT NULL')
            except sqlite3.OperationalError:
                pass
            try:
                conn.execute('ALTER TABLE columns ADD COLUMN sync_interval_ms INTEGER DEFAULT 60000')
            except sqlite3.OperationalError:
                pass
            try:
                conn.execute('ALTER TABLE columns ADD COLUMN webhook_secret TEXT DEFAULT NULL')
            except sqlite3.OperationalError:
                pass
            try:
                conn.execute('ALTER TABLE columns ADD COLUMN last_synced_at TEXT DEFAULT NULL')
            except sqlite3.OperationalError:
                pass
            try:
                conn.execute('ALTER TABLE columns ADD COLUMN integration_status TEXT DEFAULT NULL')
            except sqlite3.OperationalError:
                pass
            # Card groups (column-scoped swimlane labels) + global card tags
            try:
                conn.execute('ALTER TABLE cards ADD COLUMN card_group TEXT DEFAULT NULL')
            except sqlite3.OperationalError:
                pass
            try:
                conn.execute('ALTER TABLE cards ADD COLUMN card_tags TEXT DEFAULT "[]"')
            except sqlite3.OperationalError:
                pass
            conn.commit()

    def get_columns(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute('SELECT * FROM columns ORDER BY position ASC').fetchall()
            return [dict(r) for r in rows]

    def create_column(self, name: str, position: int, color: Optional[str] = None):
        with sqlite3.connect(self.db_path) as conn:
            try:
                cursor = conn.execute('INSERT INTO columns (name, position, color) VALUES (?, ?, ?)', (name, position, color))
                conn.commit()
                return {"id": cursor.lastrowid, "name": name, "position": position, "color": color}
            except sqlite3.IntegrityError:
                return None  # Already exists

    def delete_column(self, col_id: int):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute('DELETE FROM columns WHERE id = ?', (col_id,))
            conn.commit()
            return cursor.rowcount > 0

    def get_column_by_id(self, col_id: int):
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute('SELECT * FROM columns WHERE id = ?', (col_id,)).fetchone()
            return dict(row) if row else None

    def update_column(self, col_id: int, **kwargs):
        """Update non-integration column fields (name, position, color)."""
        if not kwargs:
            return self.get_column_by_id(col_id)
        fields = ", ".join([f'"{k}" = ?' for k in kwargs.keys()])
        values = list(kwargs.values()) + [col_id]
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(f'UPDATE columns SET {fields} WHERE id = ?', values)
            conn.commit()
        return self.get_column_by_id(col_id)

    def update_column_integration(self, col_id: int, **kwargs):
        if not kwargs:
            return
        fields = ", ".join([f'"{k}" = ?' for k in kwargs.keys()])
        values = list(kwargs.values()) + [col_id]
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(f'UPDATE columns SET {fields} WHERE id = ?', values)
            conn.commit()

    def find_card_by_external_id(self, external_id: str, external_source: str):
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                'SELECT * FROM cards WHERE external_id = ? AND external_source = ?',
                (external_id, external_source)
            ).fetchone()
            if not row:
                return None
            card = dict(row)
            card["comments"] = json.loads(card.get("comments") or "[]")
            card["logs"] = json.loads(card.get("logs") or "[]")
            card["depends_on"] = json.loads(card.get("depends_on") or "[]")
            card["metadata"] = json.loads(card.get("metadata") or "{}")
            card["card_tags"] = json.loads(card.get("card_tags") or "[]")
            return card

    def create_card(self, title, description="", column="Inbox", assignee=None, **kwargs):
        now = datetime.now().isoformat()
        depends_on = kwargs.get("depends_on", "[]")
        priority = kwargs.get("priority", "normal")
        external_id = kwargs.get("external_id")
        external_source = kwargs.get("external_source")
        external_url = kwargs.get("external_url")
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                'INSERT INTO cards (title, description, "column", assignee, created_at, updated_at, depends_on, priority, external_id, external_source, external_url) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
                (title, description, column, assignee, now, now, depends_on, priority, external_id, external_source, external_url)
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
            card["comments"] = json.loads(card.get("comments") or "[]")
            card["logs"] = json.loads(card.get("logs") or "[]")
            card["depends_on"] = json.loads(card.get("depends_on") or "[]")
            card["metadata"] = json.loads(card.get("metadata") or "{}")
            card["card_tags"] = json.loads(card.get("card_tags") or "[]")
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
                card["comments"] = json.loads(card.get("comments") or "[]")
                card["logs"] = json.loads(card.get("logs") or "[]")
                card["depends_on"] = json.loads(card.get("depends_on") or "[]")
                card["metadata"] = json.loads(card.get("metadata") or "{}")
                card["card_tags"] = json.loads(card.get("card_tags") or "[]")
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
        dead = []
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception:
                dead.append(connection)
        for connection in dead:
            self.disconnect(connection)

manager = ConnectionManager()

from integrations.manager import IntegrationManager
integration_manager = IntegrationManager(store=store, broadcaster=manager.broadcast)


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
# HITL — State Transition Hooks (Phase 5)
# ═══════════════════════════════════════════════════════════════════════════════════


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
app.mount("/assets", StaticFiles(directory=str(ASSETS_DIR)), name="assets")


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
    card_group: Optional[str] = None
    card_tags: Optional[list[str]] = None

class CardUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    column: Optional[str] = None
    assignee: Optional[str] = None
    status: Optional[str] = None
    depends_on: Optional[list[int]] = None
    priority: Optional[str] = None
    card_group: Optional[str] = None
    card_tags: Optional[list[str]] = None

class InstanceCreate(BaseModel):
    template_id: str
    instance_name: str
    service: Optional[str] = ""
    model: Optional[str] = ""
    env_vars: Optional[dict] = {}
    config: Optional[dict] = {}
    icon: Optional[str] = None
    color: Optional[str] = None

class InstanceUpdate(BaseModel):
    instance_name: Optional[str] = None
    enabled: Optional[bool] = None
    service: Optional[str] = None
    model: Optional[str] = None
    env_vars: Optional[dict] = None
    config: Optional[dict] = None
    icon: Optional[str] = None
    color: Optional[str] = None
    priority: Optional[str] = None

class CommentCreate(BaseModel):
    author: str
    content: str

class IntegrationConfig(BaseModel):
    type: str                             # "github" | "jira" | "linear" | "firestore"
    mode: str = "read"                    # "read" | "write" | "read_write"
    credentials: dict = {}
    filters: dict = {}
    sync_interval_ms: int = 60000
    webhook_secret: Optional[str] = None

class ColumnCreate(BaseModel):
    name: str
    position: Optional[int] = 0
    color: Optional[str] = None
    integration: Optional[IntegrationConfig] = None

class SystemPromptUpdate(BaseModel):
    prompt: str
class PromptSubmit(BaseModel):
    card_id: int
    agent_name: str
    prompt: str

class BrokerRateUpdate(BaseModel):
    prompts_per_minute: int

class ColumnUpdate(BaseModel):
    name: Optional[str] = None
    position: Optional[int] = None
    color: Optional[str] = None
    integration: Optional[IntegrationConfig] = None
    remove_integration: bool = False


# ═══════════════════════════════════════════════════════════════════════════════════
# API ROUTES
# ═══════════════════════════════════════════════════════════════════════════════════

@app.get("/api/columns")
async def get_columns():
    """Get all columns from the board."""
    return store.get_columns()

@app.post("/api/columns")
async def create_column(col: ColumnCreate):
    """Create a new column on the board."""
    new_col = store.create_column(col.name, col.position, col.color)
    if not new_col:
        raise HTTPException(status_code=400, detail="Column already exists")

    if col.integration:
        col_data = {
            "name": col.name,
            "integration_type": col.integration.type,
            "integration_mode": col.integration.mode,
            "integration_credentials": json.dumps(col.integration.credentials),
            "integration_filters": json.dumps(col.integration.filters),
            "sync_interval_ms": col.integration.sync_interval_ms,
            "webhook_secret": col.integration.webhook_secret,
        }
        await integration_manager.setup_integration(new_col["id"], col_data)
        # Immediately pull initial data so cards appear without waiting for first poll
        asyncio.create_task(integration_manager.initial_sync(new_col["id"]))

    await manager.broadcast({"type": "column_created", "column": new_col})
    return new_col

@app.delete("/api/columns/{col_id}")
async def delete_column(col_id: int, cascade: str = "block", force: bool = False):
    """Delete a column from the board."""
    col = next((c for c in store.get_columns() if c["id"] == col_id), None)
    if not col:
        raise HTTPException(status_code=404, detail="Column not found")

    cards_in_col = store.get_cards(column=col["name"])
    if cards_in_col:
        if force:
            # Force: delete all cards in the column
            for card in cards_in_col:
                store.delete_card(card["id"])
        elif cascade == "move":
            for card in cards_in_col:
                store.update_card(card["id"], column="Inbox")
        else:
            raise HTTPException(
                status_code=400,
                detail=f"Column '{col['name']}' has {len(cards_in_col)} card(s). "
                       "Use ?cascade=move to move them to Inbox first, or ?force=true to delete all."
            )

    await integration_manager.teardown_integration(col_id)

    if store.delete_column(col_id):
        await manager.broadcast({"type": "column_deleted", "column_id": col_id})
        return {"success": True}
    raise HTTPException(status_code=404, detail="Column not found")


@app.post("/api/assets/upload")
async def upload_asset(file: UploadFile = File(...)):
    """Upload a custom icon or asset."""
    ext = Path(file.filename).suffix.lower()
    if ext not in (".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg"):
        raise HTTPException(status_code=400, detail="Invalid file type")

    fname = f"icon_{secrets.token_hex(4)}{ext}"
    fpath = ASSETS_DIR / fname
    
    try:
        with open(fpath, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        return {"url": f"/assets/{fname}"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ─── Model Registry ──────────────────────────────────────────────────────────────

# Single source-of-truth for supported services + models.
# The frontend reads this at startup so both stay in sync.
SERVICE_MODELS: dict = {
    "anthropic": {
        "name": "Anthropic",
        "key_env": "ANTHROPIC_API_KEY",
        "models": [
            {"id": "claude-opus-4-6", "name": "Claude Opus 4.6"},
            {"id": "claude-sonnet-4-6", "name": "Claude Sonnet 4.6"},
            {"id": "claude-haiku-4-5-20251001", "name": "Claude Haiku 4.5"},
            {"id": "claude-3-7-sonnet-latest", "name": "Claude 3.7 Sonnet"},
            {"id": "claude-3-5-sonnet-latest", "name": "Claude 3.5 Sonnet"},
            {"id": "claude-3-5-haiku-latest", "name": "Claude 3.5 Haiku"},
            {"id": "claude-3-opus-latest", "name": "Claude 3 Opus"},
        ],
    },
    "google": {
        "name": "Google",
        "key_env": "GOOGLE_API_KEY",
        "models": [
            {"id": "gemini-2.5-pro", "name": "Gemini 2.5 Pro"},
            {"id": "gemini-2.5-flash", "name": "Gemini 2.5 Flash"},
            {"id": "gemini-2.0-flash", "name": "Gemini 2.0 Flash"},
            {"id": "gemini-2.0-pro-exp-02-05", "name": "Gemini 2.0 Pro Experimental"},
        ],
    },
    "openai": {
        "name": "OpenAI",
        "key_env": "OPENAI_API_KEY",
        "models": [
            {"id": "gpt-4o", "name": "GPT-4o"},
            {"id": "gpt-4o-mini", "name": "GPT-4o Mini"},
            {"id": "o3-mini", "name": "o3-mini"},
            {"id": "o1", "name": "o1"},
        ],
    },
    "deepseek": {
        "name": "DeepSeek",
        "key_env": "DEEPSEEK_API_KEY",
        "models": [
            {"id": "deepseek-reasoner", "name": "DeepSeek Reasoner (R1)"},
            {"id": "deepseek-chat", "name": "DeepSeek Chat (V3)"},
        ],
    },
    "minimax": {
        "name": "MiniMax",
        "key_env": "MINIMAX_API_KEY",
        "models": [
            {"id": "MiniMax-M2.5", "name": "MiniMax M2.5"},
            {"id": "MiniMax-Text-01", "name": "MiniMax Text-01"},
            {"id": "MiniMax-01", "name": "MiniMax-01"},
        ],
    },
    "custom": {
        "name": "Custom",
        "key_env": "",
        "models": [],
    },
}

@app.get("/api/models")
async def get_models():
    """Return the authoritative service/model registry used by all agents."""
    return SERVICE_MODELS

@app.get("/api/models/{service_id}")
async def get_service_models(service_id: str):
    """Return models for a specific service."""
    svc = SERVICE_MODELS.get(service_id)
    if not svc:
        raise HTTPException(status_code=404, detail=f"Unknown service '{service_id}'")
    return svc

# ─── Broker Control ──────────────────────────────────────────────────────────────

@app.post("/api/broker/pause")
async def pause_broker():
    """Pause the prompt broker."""
    await broker.pause()
    return {"status": "paused"}

@app.post("/api/broker/resume")
async def resume_broker():
    """Resume the prompt broker."""
    await broker.resume()
    return {"status": "resumed"}

@app.post("/api/broker/rate")
async def set_broker_rate(update: BrokerRateUpdate):
    """Update the broker's prompts-per-minute rate."""
    broker.set_rate(update.prompts_per_minute)
    return {"status": "updated", "prompts_per_minute": broker.prompts_per_minute, "interval": broker.interval}

@app.get("/api/broker/min_pulse")
async def get_min_pulse():
    """Returns the minimum safe pulse interval based on broker rate."""
    return {"min_pulse_seconds": int(broker.interval)}


@app.patch("/api/columns/{col_id}")
async def update_column(col_id: int, update: ColumnUpdate):
    """Update column name, position, color, or integration settings."""
    col = store.get_column_by_id(col_id)
    if not col:
        raise HTTPException(status_code=404, detail="Column not found")

    db_updates = {}
    old_name = col["name"]

    if update.name is not None and update.name.strip() and update.name.strip() != old_name:
        new_name = update.name.strip()
        db_updates["name"] = new_name
        # Rename all cards in this column
        for card in store.get_cards(column=old_name):
            store.update_card(card["id"], column=new_name)

    if update.position is not None:
        db_updates["position"] = update.position

    if update.color is not None:
        db_updates["color"] = update.color

    if db_updates:
        store.update_column(col_id, **db_updates)

    if update.remove_integration:
        await integration_manager.teardown_integration(col_id)
    elif update.integration:
        col_name = db_updates.get("name", old_name)
        col_data = {
            "name": col_name,
            "integration_type": update.integration.type,
            "integration_mode": update.integration.mode,
            "integration_credentials": json.dumps(update.integration.credentials),
            "integration_filters": json.dumps(update.integration.filters),
            "sync_interval_ms": update.integration.sync_interval_ms,
            "webhook_secret": update.integration.webhook_secret,
        }
        await integration_manager.setup_integration(col_id, col_data)
        asyncio.create_task(integration_manager.initial_sync(col_id))

    updated = store.get_column_by_id(col_id)
    await manager.broadcast({"type": "column_updated", "column": updated})
    return updated

@app.get("/")
async def root():
    """Root endpoint - serve the dashboard."""
    return FileResponse("static/index.html")

@app.get("/api/config")
async def get_config():
    """Get the current Aegis configuration."""
    return CONFIG

@app.post("/api/config")
async def update_config(updates: dict):
    """Update Aegis configuration."""
    global CONFIG
    CONFIG.update(updates)
    with open(CONFIG_PATH, 'w', encoding="utf-8") as f:
        json.dump(CONFIG, f, indent=2)
    return {"success": True, "config": CONFIG}

@app.get("/api/system_prompt")
async def get_system_prompt():
    """Get the current system prompt for agents."""
    return {"prompt": SYSTEM_PROMPT}

@app.put("/api/system_prompt")
async def update_system_prompt(update: SystemPromptUpdate):
    global SYSTEM_PROMPT
    SYSTEM_PROMPT = update.prompt
    SYSTEM_PROMPT_PATH.write_text(SYSTEM_PROMPT, encoding="utf-8")
    return {"success": True, "prompt": SYSTEM_PROMPT}


# ─── Cards CRUD ──────────────────────────────────────────────────────────────────

@app.get("/api/cards")
async def get_cards(column: Optional[str] = None):
    """Get all cards, optionally filtered by column."""
    return store.get_cards(column)

@app.post("/api/cards")
async def create_card(card: CardCreate):
    """Create a new card on the board."""
    create_kwargs = {}
    if card.depends_on is not None:
        create_kwargs["depends_on"] = json.dumps(card.depends_on)
    if card.priority:
        create_kwargs["priority"] = card.priority
    if card.card_group is not None:
        create_kwargs["card_group"] = card.card_group
    if card.card_tags is not None:
        create_kwargs["card_tags"] = json.dumps(card.card_tags)
    new_card = store.create_card(card.title, card.description, card.column, card.assignee, **create_kwargs)
    await manager.broadcast({"type": "card_created", "card": new_card})
    
    # Push change to external integration
    asyncio.create_task(integration_manager.notify_card_change(new_card, "card_created"))
    
    return new_card

@app.get("/api/cards/{card_id}")
async def get_card(card_id: int):
    """Get a specific card by ID."""
    card = store.get_card(card_id)
    if not card:
        raise HTTPException(status_code=404, detail="Card not found")
    return card

@app.get("/api/cards/{card_id}/context")
async def get_card_context(card_id: int):
    """
    Retrieve an optimized context bundle for an agent working on a specific card.
    Includes full details of the focus card and any explicitly @tagged cards,
    while returning a skinny directory of all other cards to save LLM context.
    """
    focus_card = store.get_card(card_id)
    if not focus_card:
        raise HTTPException(status_code=404, detail="Focus card not found")

    import re
    # Extract @ tags from description and comments
    text_to_search = focus_card.get("description", "")
    for comment in focus_card.get("comments", []):
        text_to_search += " " + comment.get("content", "")
    
    # Find all pattern instances of @<digits>
    tagged_ids = set()
    for match in re.finditer(r'@(\d+)', text_to_search):
        try:
            tagged_ids.add(int(match.group(1)))
        except ValueError:
            pass
            
    # Always include dependencies as well
    deps = focus_card.get("depends_on", [])
    if isinstance(deps, str):
        try:
            deps = json.loads(deps)
        except json.JSONDecodeError:
            deps = []
            
    for dep in deps:
        try:
            tagged_ids.add(int(dep))
        except ValueError:
            pass


    all_cards = store.get_cards()
    related_context = []
    board_directory = []
    
    for c in all_cards:
        if c["id"] == card_id:
            continue # already have focus_card
        
        if c["id"] in tagged_ids:
            # Full detail for tagged cards
            related_context.append(c)
        else:
            # Skinny detail for other cards
            board_directory.append({
                "id": c["id"],
                "title": c.get("title", ""),
                "column": c.get("column", ""),
                "assignee": c.get("assignee"),
                "priority": c.get("priority", "normal")
            })

    # Resolve @ColumnName and @AgentName mentions from description/comments
    all_columns = store.get_columns()
    all_instances = load_instances()
    col_names = {c["name"] for c in all_columns}
    agent_names = {inst.get("instance_name") or inst.get("agent_id") for inst in all_instances}

    mentioned_columns = []
    mentioned_agents = []
    for match in re.finditer(r'@([A-Za-z][^\s@]{0,49})', text_to_search):
        token = match.group(1)
        if token in col_names:
            col_obj = next((c for c in all_columns if c["name"] == token), None)
            if col_obj and col_obj not in mentioned_columns:
                mentioned_columns.append(col_obj)
        elif token in agent_names:
            inst = next((i for i in all_instances if (i.get("instance_name") or i.get("agent_id")) == token), None)
            if inst and inst not in mentioned_agents:
                mentioned_agents.append(inst)

    # Build column metadata for agent context
    focus_col_name = focus_card.get("column", "")
    focus_col_obj = next((c for c in all_columns if c["name"] == focus_col_name), {})
    column_meta = {
        "name": focus_col_name,
        "is_read_only": bool(focus_col_obj.get("integration_type") and focus_col_obj.get("integration_mode") == "read"),
        "integration_type": focus_col_obj.get("integration_type")
    }

    return {
        "focus_card": focus_card,
        "related_context": related_context,
        "board_directory": board_directory,
        "column_meta": column_meta,
        "mentioned_columns": mentioned_columns,
        "mentioned_agents": [{"instance_name": i.get("instance_name"), "agent_id": i.get("agent_id"), "goal": i.get("goal")} for i in mentioned_agents],
    }

@app.patch("/api/cards/{card_id}")
async def update_card(card_id: int, update: CardUpdate, request: Request):
    """Update a card. Arbitrary transitions are now allowed for Sandbox Agents."""
    existing = store.get_card(card_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Card not found")

    updates = update.model_dump(exclude_none=True)

    # Serialize JSON fields for SQLite
    if "depends_on" in updates:
        updates["depends_on"] = json.dumps(updates["depends_on"])
    if "card_tags" in updates:
        updates["card_tags"] = json.dumps(updates["card_tags"])

    new_column = updates.get("column")
    if new_column and new_column != existing["column"]:
        old_col = existing["column"]
        
        # Block agent-initiated Review → Done
        is_agent = request.headers.get("X-Aegis-Agent", "false").lower() == "true"
        if old_col == "Review" and new_column == "Done" and is_agent:
            raise HTTPException(
                status_code=403,
                detail="Only humans can move cards from Review to Done"
            )

        # Block agents from modifying cards in read-only integrated columns
        if is_agent:
            col_obj = next((c for c in store.get_columns() if c["name"] == old_col), {})
            if col_obj.get("integration_type") and col_obj.get("integration_mode") == "read":
                raise HTTPException(
                    status_code=403,
                    detail=f"Cannot modify cards in read-only integrated column '{old_col}'"
                )

        # Lifecycle hook: auto-kill running agent on Review/Done
        await engine.lifecycle_hook(card_id, new_column, store, manager.broadcast)

    card = store.update_card(card_id, **updates)
    await manager.broadcast({"type": "card_updated", "card": card})

    # Push change to external integration (write/read_write columns)
    event_type = "card_moved" if new_column else "card_updated"
    asyncio.create_task(integration_manager.notify_card_change(card, event_type))

    # Discord webhook on Review entry
    if new_column == "Review":
        asyncio.create_task(send_discord_webhook(card))

    return card

@app.delete("/api/cards/{card_id}")
async def delete_card(card_id: int, request: Request, close_external: bool = False):
    """Delete a card from the board."""
    card = store.get_card(card_id)
    if not card:
        raise HTTPException(status_code=404, detail="Card not found")

    # Block agents from deleting cards in read-only integrated columns
    is_agent = request.headers.get("X-Aegis-Agent", "false").lower() == "true"
    if is_agent:
        col_obj = next((c for c in store.get_columns() if c["name"] == card.get("column")), {})
        if col_obj.get("integration_type") and col_obj.get("integration_mode") == "read":
            raise HTTPException(
                status_code=403,
                detail=f"Cannot delete cards in read-only integrated column '{card.get('column')}'"
            )

    # Push change to external integration before deleting from DB
    asyncio.create_task(integration_manager.notify_card_change(card, "card_deleted"))

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

    # Push comment to external integration (write/read_write columns)
    updated_card = store.get_card(card_id)
    asyncio.create_task(integration_manager.notify_card_change(updated_card, "comment_added"))

    return comment_obj


# ─── Tools & Skills ──────────────────────────────────────────────────────────────

@app.get("/api/tools")
async def get_available_tools():
    """Lists all available tools (Core + Modular Skills)."""
    return skill_manager.get_all_tools()

@app.post("/api/tools/execute")
async def execute_tool(name: str, args: dict, request: Request):
    """Executes a specific tool."""
    agent_id = request.headers.get("X-Aegis-Agent", "unknown")
    context = {
        "agent_id": agent_id,
        "request_time": datetime.now().isoformat()
    }
    try:
        result = await skill_manager.execute_tool(name, args, context)
        return {"status": "success", "result": result}
    except Exception as e:
        logger.error(f"Tool execution failed ({name}): {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/tools/refresh")
async def refresh_skills():
    """Manually triggers a scan of the skills directory."""
    skill_manager.refresh_skills()
    return {"status": "refreshed", "count": len(skill_manager.skills)}


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
    
    # Push change to external integration
    asyncio.create_task(integration_manager.notify_card_change(updated, "card_moved"))

    logger.info(f"Card {card_id} approved and moved to Done")
    return {"success": True, "card": updated}


# ─── Prompt Broker Stats ─────────────────────────────────────────────────────────

@app.get("/api/broker/stats")
async def get_broker_stats():
    """Returns the prompt broker queue and rate-limit statistics."""
    return broker.get_stats()

@app.post("/api/broker/submit")
async def submit_prompt(req: PromptSubmit):
    """Submit a prompt for rate-limited processing using real credentials."""
    from prompt_broker import PromptRequest
    
    # 1. Resolve instance
    instance_id = None
    # Check active processes first
    for key, proc in engine.active.items():
        if proc.card_id == req.card_id:
            instance_id = proc.instance_id
            break
    
    # Fallback to store if not running
    if not instance_id:
        card = store.get_card(req.card_id)
        if card and card.get("assignee"):
            instances = load_instances()
            inst = next((i for i in instances if i["instance_name"] == card["assignee"]), None)
            if inst:
                instance_id = inst["instance_id"]

    if not instance_id:
        raise HTTPException(status_code=404, detail="Could not resolve worker instance for this card")

    # 2. Get credentials
    instances = load_instances()
    inst_meta = next((i for i in instances if i["instance_id"] == instance_id), None)
    if not inst_meta:
        raise HTTPException(status_code=404, detail="Worker instance metadata not found")

    api_key = inst_meta.get("env_vars", {}).get("OPENROUTER_API_KEY") 
    # Fallback to other possible keys
    if not api_key:
        api_key = inst_meta.get("env_vars", {}).get("ANTHROPIC_API_KEY") or inst_meta.get("env_vars", {}).get("OPENAI_API_KEY")
    
    model = inst_meta.get("model") or "anthropic/claude-3-haiku"

    if not api_key:
        raise HTTPException(status_code=400, detail="No API Key configured for this worker instance")

    future = asyncio.get_event_loop().create_future()
    
    async def callback(request):
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                headers = {
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                    "HTTP-Referer": "https://github.com/TheSandemon/Aegis",
                    "X-Title": "Aegis Orchestrator"
                }
                payload = {
                    "model": model,
                    "messages": [{"role": "user", "content": request.prompt}]
                }
                
                # Check for Gemini if using OpenRouter
                if "gemini" in model.lower() and "openrouter.ai" in os.environ.get("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"):
                     # specialized payload if needed, but usually standard OpenAI-compat works
                     pass

                response = await client.post(
                    "https://openrouter.ai/api/v1/chat/completions",
                    headers=headers,
                    json=payload
                )
                
                if response.status_code != 200:
                    err = f"LLM Error {response.status_code}: {response.text}"
                    logger.error(err)
                    future.set_exception(Exception(err))
                    return

                data = response.json()
                completion = data.get("choices", [{}])[0].get("message", {}).get("content", "No response content")
                future.set_result(completion)
                
        except Exception as e:
            logger.error(f"Broker callback error: {e}")
            future.set_exception(e)
        
    request = PromptRequest(
        card_id=req.card_id,
        agent_name=req.agent_name,
        prompt=req.prompt,
        callback=callback
    )
    
    await broker.submit(request)
    
    try:
        response_text = await future
        return {"status": "success", "response": response_text}
    except Exception as e:
        return {"status": "error", "message": str(e)}


# ═══════════════════════════════════════════════════════════════════════════════════
# GITHUB DEVOPS — Branch / PR / Merge Proxy (used by worker agents)
# ═══════════════════════════════════════════════════════════════════════════════════

def _resolve_github_integration(agent_column: str = None):
    """Find the first active GitHub integration adapter.

    If agent_column is provided, use the integration for that column.
    If agent_column is provided, use the integration for that column.
    Otherwise, finds the first write-capable integration.
    """
    # If agent specifies a column, try to use that column's integration first
    if agent_column:
        for col_id, integration in integration_manager._integrations.items():
            if getattr(integration, 'SOURCE', '') == 'github':
                col = store.get_columns()
                col_obj = next((c for c in col if c["id"] == col_id), None)
                if col_obj and col_obj.get("name") == agent_column:
                    return integration

    # Fall back to first write-capable integration
    for col_id, integration in integration_manager._integrations.items():
        if getattr(integration, 'SOURCE', '') == 'github':
            col = store.get_columns()
            col_obj = next((c for c in col if c["id"] == col_id), None)
            if col_obj and col_obj.get("integration_mode") in ("write", "read_write"):
                return integration

    # Last resort: any GitHub integration (for read operations)
    for col_id, integration in integration_manager._integrations.items():
        if getattr(integration, 'SOURCE', '') == 'github':
            return integration
    return None


def _check_github_write_access(gh_integration, agent_column: str = None) -> bool:
    """Check if an agent can write to the GitHub integration."""
    if not gh_integration:
        return False

    # If we have a column context, check that column's integration mode
    if agent_column:
        col = store.get_columns()
        col_obj = next((c for c in col if c.get("name") == agent_column), None)
        if col_obj and col_obj.get("integration_mode") in ("write", "read_write"):
            return True
        return False

    # Otherwise, check if ANY column has write access
    for col_id, integration in integration_manager._integrations.items():
        if integration is gh_integration:
            col = store.get_columns()
            col_obj = next((c for c in col if c["id"] == col_id), None)
            if col_obj and col_obj.get("integration_mode") in ("write", "read_write"):
                return True
    return False

class BranchCreate(BaseModel):
    branch_name: str
    base: str = "main"
    column: Optional[str] = None  # Optional column context for integration selection

class PRCreate(BaseModel):
    title: str
    body: str = ""
    head: str
    base: str = "main"
    column: Optional[str] = None  # Optional column context for integration selection

class PRMerge(BaseModel):
    pr_number: int
    merge_method: str = "squash"
    commit_message: str = ""


@app.get("/api/github/branches")
async def list_github_branches(column: Optional[str] = None):
    """List branches for the connected GitHub repo."""
    gh = _resolve_github_integration(column)
    if not gh:
        raise HTTPException(status_code=404, detail="No GitHub integration configured on any column")
    return await gh.list_branches()


@app.post("/api/github/branches")
async def create_github_branch(request: Request, req: BranchCreate):
    """Create a new branch on the connected GitHub repo."""
    is_agent = request.headers.get("X-Aegis-Agent", "false").lower() == "true"
    gh = _resolve_github_integration(req.column)
    if not gh:
        raise HTTPException(status_code=404, detail="No GitHub integration configured on any column")
    # Agents must have write access to use GitHub write operations
    if is_agent and not _check_github_write_access(gh, req.column):
        raise HTTPException(status_code=403, detail="No write-enabled GitHub integration found. Agents can only use GitHub integrations with 'write' or 'read_write' mode.")
    result = await gh.create_branch(req.branch_name, req.base)
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@app.get("/api/github/pulls")
async def list_github_prs(state: str = "open", column: Optional[str] = None):
    """List pull requests for the connected GitHub repo."""
    gh = _resolve_github_integration(column)
    if not gh:
        raise HTTPException(status_code=404, detail="No GitHub integration configured on any column")
    return await gh.list_pull_requests(state)


@app.post("/api/github/pulls")
async def create_github_pr(request: Request, req: PRCreate):
    """Open a pull request on the connected GitHub repo."""
    is_agent = request.headers.get("X-Aegis-Agent", "false").lower() == "true"
    gh = _resolve_github_integration(req.column)
    if not gh:
        raise HTTPException(status_code=404, detail="No GitHub integration configured on any column")
    # Agents must have write access to use GitHub write operations
    if is_agent and not _check_github_write_access(gh, req.column):
        raise HTTPException(status_code=403, detail="No write-enabled GitHub integration found. Agents can only use GitHub integrations with 'write' or 'read_write' mode.")
    result = await gh.create_pull_request(req.title, req.body, req.head, req.base)
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@app.post("/api/github/pulls/merge")
async def merge_github_pr(request: Request, req: PRMerge):
    """Merge a pull request on the connected GitHub repo."""
    is_agent = request.headers.get("X-Aegis-Agent", "false").lower() == "true"
    gh = _resolve_github_integration()
    if not gh:
        raise HTTPException(status_code=404, detail="No GitHub integration configured on any column")
    # Agents must have write access to use GitHub write operations
    if is_agent and not _check_github_write_access(gh):
        raise HTTPException(status_code=403, detail="No write-enabled GitHub integration found. Agents can only use GitHub integrations with 'write' or 'read_write' mode.")
    result = await gh.merge_pull_request(req.pr_number, req.merge_method, req.commit_message)
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


# ═══════════════════════════════════════════════════════════════════════════════════
# AGENT REGISTRY & MANAGEMENT
# ═══════════════════════════════════════════════════════════════════════════════════

@app.get("/api/registry")
async def get_registry():
    """Serves the unified agent worker template."""
    return AGENT_REGISTRY


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

@app.post("/api/instances/create")
async def create_instance_api(req: InstanceCreate):
    """Create a new agent instance."""
    registry_entry = next((a for a in AGENT_REGISTRY if a["id"] == req.template_id), None)
    instance = create_instance(
        req.template_id, req.instance_name,
        registry_entry=registry_entry,
        env_vars=req.env_vars,
        service=req.service,
        model=req.model,
        config=req.config,
        icon=req.icon,
        color=req.color
    )
    if "error" in instance:
        raise HTTPException(status_code=400, detail=instance["error"])
    await manager.broadcast({"type": "instance_created", "instance": instance})
    return instance

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
async def update_instance_settings(instance_id: str, req: InstanceUpdate):
    """Update per-instance settings (name, service, model, env_vars, enabled, icon, color)."""
    instances = load_instances()
    inst = next((i for i in instances if i["instance_id"] == instance_id), None)
    if not inst:
        raise HTTPException(status_code=404, detail="Instance not found")
    
    if req.instance_name is not None: inst["instance_name"] = req.instance_name
    if req.enabled is not None: inst["enabled"] = req.enabled
    if req.service is not None: inst["service"] = req.service
    if req.model is not None: inst["model"] = req.model
    if req.config is not None: inst["config"] = req.config
    if req.icon is not None: inst["icon"] = req.icon
    if req.color is not None: inst["color"] = req.color

    # Merge env_vars if provided
    if req.env_vars:
        inst.setdefault("env_vars", {}).update(req.env_vars)

    save_instances(instances)
    await manager.broadcast({"type": "instance_updated", "instance": inst})
    return {"success": True, "instance": inst}

@app.get("/api/instances/{instance_id}/config")
async def get_instance_config(instance_id: str):
    """Retrieve the live configuration (goals, interval) for a worker instance."""
    instances = load_instances()
    inst = next((i for i in instances if i["instance_id"] == instance_id), None)
    if not inst:
        raise HTTPException(status_code=404, detail="Instance not found")
    return {"config": inst.get("config", {})}

class PulseRequest(BaseModel):
    interval: int

@app.post("/api/instances/{instance_id}/pulse")
async def broadcast_pulse(instance_id: str, req: PulseRequest):
    """Broadcasts to the UI that a worker finished its action loop and is sleeping."""
    if not instance_id or instance_id == "/":
        return {"success": False, "error": "Empty instance_id"}
    await manager.broadcast({
        "type": "agent_pulse",
        "instance_id": instance_id,
        "interval": req.interval
    })
    return {"success": True}

@app.post("/api/instances//pulse")
async def broadcast_pulse_empty(req: PulseRequest):
    """Quietly handle orphaned pulse requests with empty IDs to stop 404 logs."""
    return {"success": False, "error": "orphaned_pulse_ignored"}

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

    # 4. MiniMax — no standard key prefix; try as a final fallback
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                "https://api.minimaxi.chat/v1/models",
                headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
            )
            if resp.status_code == 200:
                data = resp.json()
                raw_models = data.get("data", data.get("models", []))
                models = [
                    {"id": m.get("id", m.get("model", "")), "name": m.get("id", m.get("model", ""))}
                    for m in raw_models if m.get("id") or m.get("model")
                ]
                if not models:
                    models = SERVICE_MODELS["minimax"]["models"]
                return {
                    "valid": True,
                    "service": "minimax",
                    "env_key_name": "MINIMAX_API_KEY",
                    "models": models,
                    "default_model": "MiniMax-M2.5"
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

# ═══════════════════════════════════════════════════════════════════════════════════
# INTEGRATION ROUTES
# ─── Profile Management ──────────────────────────────────────────────────────────

@app.get("/api/profiles")
async def list_profiles():
    """List all saved agent profiles."""
    profiles = []
    for p in PROFILES_DIR.glob("*.json"):
        try:
            profiles.append(json.loads(p.read_text(encoding="utf-8")))
        except Exception:
            pass
    return profiles

@app.post("/api/profiles")
async def save_profile(profile: dict):
    """Save a new agent profile."""
    profile_id = profile.get("id") or f"profile_{secrets.token_hex(4)}"
    profile["id"] = profile_id
    path = PROFILES_DIR / f"{profile_id}.json"
    path.write_text(json.dumps(profile, indent=2), encoding="utf-8")
    return profile

@app.delete("/api/profiles/{profile_id}")
async def delete_profile(profile_id: str):
    """Delete a saved agent profile."""
    path = PROFILES_DIR / f"{profile_id}.json"
    if path.exists():
        path.unlink()
    return {"success": True}


# ═══════════════════════════════════════════════════════════════════════════════════

@app.get("/api/integrations")
async def list_integrations():
    """List all active column integrations with current status."""
    return integration_manager.get_status()

@app.post("/api/integrations/{column_id}/sync")
async def force_integration_sync(column_id: int):
    """Manually trigger a sync for a specific column's integration."""
    results = await integration_manager.force_sync(column_id)
    return {"status": "ok", "synced": len(results)}

@app.post("/api/webhooks/{column_id}")
async def receive_webhook(column_id: int, request: Request):
    """Entry point for all external service webhooks (GitHub, Jira, Linear, etc.)."""
    result = await integration_manager.handle_webhook(column_id, request)
    # Always return 200 to prevent webhook retry storms
    return {"status": "processed" if result else "ignored"}


# ═══════════════════════════════════════════════════════════════════════════════════
# BOARD WORKSPACES (Save / Load)
# ═══════════════════════════════════════════════════════════════════════════════════

WORKSPACES_DIR = Path(__file__).parent / "aegis_data" / "workspaces"
WORKSPACES_DIR.mkdir(parents=True, exist_ok=True)

def _export_board_snapshot() -> dict:
    """Serialize the current board + agent state to a portable dict (Workflowspace)."""
    from execution_engine import load_instances
    columns = store.get_columns()
    cards = store.get_cards()
    # Exclude integration-managed cards — they'll be re-synced from the external source on load
    cards = [c for c in cards if not c.get("external_source")]
    # Strip volatile runtime fields
    for card in cards:
        card.pop("status", None)
        card.pop("assignee", None)
    # Include agent instances without sensitive env_vars (API keys stay local)
    instances = load_instances()
    agents = [
        {k: v for k, v in inst.items() if k not in ("env_vars", "path")}
        for inst in instances
    ]
    return {
        "version": 2,
        "exported_at": datetime.now().isoformat(),
        "columns": columns,
        "cards": cards,
        "agents": agents,
    }

@app.get("/api/workspaces")
async def list_workspaces():
    """List all saved board workspaces."""
    workspaces = []
    for p in sorted(WORKSPACES_DIR.glob("*.json")):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            workspaces.append({
                "name": p.stem,
                "exported_at": data.get("exported_at"),
                "columns": len(data.get("columns", [])),
                "cards": len(data.get("cards", [])),
                "agents": len(data.get("agents", [])),
            })
        except Exception:
            pass
    return workspaces

@app.get("/api/workspaces/export")
async def export_workspace():
    """Download the current board as a JSON snapshot (no save)."""
    return _export_board_snapshot()

@app.post("/api/workspaces/{name}/save")
async def save_workspace(name: str):
    """Save current board state as a named workspace."""
    safe_name = "".join(c for c in name if c.isalnum() or c in "-_").strip() or "workspace"
    snapshot = _export_board_snapshot()
    path = WORKSPACES_DIR / f"{safe_name}.json"
    path.write_text(json.dumps(snapshot, indent=2, ensure_ascii=False), encoding="utf-8")
    return {"name": safe_name, "saved": True, "cards": len(snapshot["cards"]), "columns": len(snapshot["columns"]), "agents": len(snapshot.get("agents", []))}

@app.post("/api/workspaces/{name}/load")
async def load_workspace(name: str, merge: bool = False):
    """
    Restore a saved workspace.
    merge=false (default): clears the board first, then imports.
    merge=true: adds workspace cards/columns without clearing existing ones.
    """
    path = WORKSPACES_DIR / f"{name}.json"
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"Workspace '{name}' not found")

    snapshot = json.loads(path.read_text(encoding="utf-8"))

    if not merge:
        # Clear current board
        for card in store.get_cards():
            store.delete_card(card["id"])
        for col in store.get_columns():
            store.delete_column(col["id"])

    # Restore columns
    col_id_map = {}  # old_id → new_id
    for col in snapshot.get("columns", []):
        new_col = store.create_column(col["name"], col.get("position", 0), col.get("color"))
        if new_col:
            col_id_map[col["id"]] = new_col["id"]
            # Restore integration metadata without activating (user must re-authenticate)
            if col.get("integration_type"):
                store.update_column_integration(
                    new_col["id"],
                    integration_type=col.get("integration_type"),
                    integration_mode=col.get("integration_mode", "read"),
                    integration_status="inactive",
                )

    # Restore cards
    for card in snapshot.get("cards", []):
        store.create_card(
            title=card.get("title", ""),
            description=card.get("description", ""),
            column=card.get("column", "Inbox"),
            assignee=None,
            priority=card.get("priority", "normal"),
        )

    # Restore agents — add any from snapshot that don't already exist (matched by instance_name)
    from execution_engine import load_instances, create_instance
    existing_names = {i["instance_name"] for i in load_instances()}
    restored_agents = 0
    for agent in snapshot.get("agents", []):
        if agent.get("instance_name") and agent["instance_name"] not in existing_names:
            reg = next((r for r in AGENT_REGISTRY if r["id"] == agent.get("template_id", "")), None)
            result = create_instance(
                template_id=agent.get("template_id", "aegis-worker"),
                instance_name=agent["instance_name"],
                registry_entry=reg,
                service=agent.get("service", ""),
                model=agent.get("model", ""),
                config=agent.get("config", {}),
            )
            if "error" not in result:
                existing_names.add(agent["instance_name"])
                restored_agents += 1

    # Broadcast full refresh
    await manager.broadcast({"type": "board_loaded", "workspace": name})
    return {
        "loaded": name,
        "columns": len(snapshot.get("columns", [])),
        "cards": len(snapshot.get("cards", [])),
        "agents": restored_agents,
    }

@app.delete("/api/workspaces/{name}")
async def delete_workspace(name: str):
    """Delete a saved workspace."""
    path = WORKSPACES_DIR / f"{name}.json"
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"Workspace '{name}' not found")
    path.unlink()
    return {"deleted": name}

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
        "paused": raw.get("paused", False),
        "prompts_per_minute": raw.get("prompts_per_minute", 1),
        "broker_interval_seconds": raw.get("broker_interval_seconds", 60),
        "in_progress": raw.get("in_progress"),
    }
    agent_data = engine.get_all_active()

    # Gather per-instance data for telemetry
    try:
        instances_data = engine.list_instances()
    except Exception:
        instances_data = []

    return {"broker": broker_stats, "agents": agent_data, "instances": instances_data}


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


# ═══════════════════════════════════════════════════════════════════════════════════
# ENTRYPOINT
# ═══════════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 42069))
    uvicorn.run(app, host="0.0.0.0", port=port)

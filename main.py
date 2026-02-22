#!/usr/bin/env python3
"""
Aegis - Multi-Agent Kanban & Orchestration Hub
Main entry point for the FastAPI backend
"""

import json
import os
import asyncio
import logging
from pathlib import Path
from datetime import datetime
from typing import Optional
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("aegis")

# Load configuration
CONFIG_PATH = Path(__file__).parent / "aegis.config.json"
with open(CONFIG_PATH) as f:
    CONFIG = json.load(f)

import sqlite3

# Persistent data store (SQLite)
class AegisStore:
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

    def create_card(self, title: str, description: str = "", column: str = "Inbox", assignee: Optional[str] = None) -> dict:
        now = datetime.now().isoformat()
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                'INSERT INTO cards (title, description, "column", assignee, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)',
                (title, description, column, assignee, now, now)
            )
            card_id = cursor.lastrowid
            conn.commit()
            return self.get_card(card_id)
    
    def update_card(self, card_id: int, **kwargs) -> Optional[dict]:
        if not kwargs:
            return self.get_card(card_id)
            
        kwargs["updated_at"] = datetime.now().isoformat()
        fields = ", ".join([f'"{k}" = ?' for k in kwargs.keys()])
        values = list(kwargs.values()) + [card_id]
        
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(f'UPDATE cards SET {fields} WHERE id = ?', values)
            conn.commit()
            
        return self.get_card(card_id)
    
    def get_card(self, card_id: int) -> Optional[dict]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute('SELECT * FROM cards WHERE id = ?', (card_id,)).fetchone()
            if not row:
                return None
            card = dict(row)
            # Deserialize JSON fields
            card["comments"] = json.loads(card.get("comments", "[]"))
            card["logs"] = json.loads(card.get("logs", "[]"))
            return card

    def get_cards(self, column: Optional[str] = None) -> list:
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
    
    def delete_card(self, card_id: int) -> bool:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute('DELETE FROM cards WHERE id = ?', (card_id,))
            conn.commit()
            return cursor.rowcount > 0

# Global store instance
store = AegisStore()

# Sample cards removed - board starts empty for clean experience
# To add sample cards back, uncomment below:
# store.create_card("Welcome to Aegis", "Your multi-agent Kanban board is ready!", "Inbox")

# WebSocket connections
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

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Aegis starting up...")
    logger.info(f"Orchestration mode: {CONFIG['orchestration_mode']}")
    logger.info(f"Polling rate: {CONFIG['polling_rate_ms']}ms")
    
    # Start background task polling if supervisor mode
    if CONFIG.get("orchestration_mode") == "supervisor":
        asyncio.create_task(polling_loop())
    
    yield
    
    logger.info("Aegis shutting down...")

app = FastAPI(title="Aegis", lifespan=lifespan)

# Serve static frontend
app.mount("/static", StaticFiles(directory="static"), name="static")

# Pydantic models
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

# API Routes
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
    # Save to file
    with open(CONFIG_PATH, 'w') as f:
        json.dump(CONFIG, f, indent=2)
    return {"success": True, "config": CONFIG}

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
async def update_card(card_id: int, update: CardUpdate):
    card = store.update_card(card_id, **update.model_dump(exclude_none=True))
    if not card:
        raise HTTPException(status_code=404, detail="Card not found")
    await manager.broadcast({"type": "card_updated", "card": card})
    return card

@app.delete("/api/cards/{card_id}")
async def delete_card(card_id: int):
    if store.delete_card(card_id):
        await manager.broadcast({"type": "card_deleted", "card_id": card_id})
        return {"success": True}
    raise HTTPException(status_code=404, detail="Card not found")

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

class AgentManager:
    def __init__(self):
        self.running_tasks = {}

    async def run_agent(self, card_id: int, agent_name: str):
        agent_config = CONFIG.get("agents", {}).get(agent_name)
        if not agent_config:
            return

        command = agent_config.get("binary")
        # In a real scenario, we might want to pass task description as args
        # For now, we'll just run the binary
        
        try:
            store.update_card(card_id, status="running")
            await manager.broadcast({"type": "card_updated", "card": store.get_card(card_id)})
            
            process = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            self.running_tasks[card_id] = process
            
            # Stream logs
            async def stream_output(stream, log_type):
                while True:
                    line = await stream.readline()
                    if not line:
                        break
                    decoded_line = line.decode().strip()
                    if decoded_line:
                        log_entry = f"[{log_type}] {decoded_line}"
                        # Update DB logs
                        card = store.get_card(card_id)
                        logs = card.get("logs", [])
                        logs.append(log_entry)
                        store.update_card(card_id, logs=json.dumps(logs))
                        # Broadcast
                        await manager.broadcast({
                            "type": "log_entry", 
                            "card_id": card_id, 
                            "entry": log_entry
                        })

            await asyncio.gather(
                stream_output(process.stdout, "STDOUT"),
                stream_output(process.stderr, "STDERR")
            )
            
            return_code = await process.wait()
            status = "completed" if return_code == 0 else "failed"
            
            store.update_card(card_id, status=status)
            await manager.broadcast({"type": "card_updated", "card": store.get_card(card_id)})
            
        except Exception as e:
            logger.error(f"Agent execution error for card {card_id}: {e}")
            store.update_card(card_id, status="error")
            await manager.broadcast({"type": "card_updated", "card": store.get_card(card_id)})
        finally:
            if card_id in self.running_tasks:
                del self.running_tasks[card_id]

agent_manager = AgentManager()

@app.get("/api/cards/{card_id}/logs")
async def get_card_logs(card_id: int):
    card = store.get_card(card_id)
    if not card:
        raise HTTPException(status_code=404, detail="Card not found")
    return {"logs": card.get("logs", [])}

# WebSocket endpoint
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            data = await websocket.receive_text()
            message = json.loads(data)
            
            if message.get("type") == "subscribe_card":
                # Client subscribing to card updates
                await websocket.send_json({"type": "subscribed", "card_id": message.get("card_id")})
                
    except WebSocketDisconnect:
        manager.disconnect(websocket)

# Background polling loop (Supervisor Mode)
async def polling_loop():
    """Polls for unassigned tasks in Planned column and routes to agents"""
    while True:
        try:
            await asyncio.sleep(CONFIG["polling_rate_ms"] / 1000)
            
            # Find planned cards without assignees
            planned_cards = [c for c in store.get_cards(column="Planned") if not c.get("assignee")]
            
            for card in planned_cards:
                # Try to assign to an available agent
                for agent_name, agent_config in CONFIG.get("agents", {}).items():
                    if agent_config.get("enabled"):
                        store.update_card(card["id"], assignee=agent_name, status="assigned")
                        logger.info(f"Routed card {card['id']} to {agent_name}")
                        await manager.broadcast({
                            "type": "card_assigned",
                            "card_id": card["id"],
                            "agent": agent_name
                        })
                        
                        # Trigger actual agent execution
                        asyncio.create_task(agent_manager.run_agent(card["id"], agent_name))
                        break
                        
        except Exception as e:
            logger.error(f"Polling error: {e}")

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port)

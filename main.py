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

# In-memory data store (SQLite-like for now)
class AegisStore:
    def __init__(self):
        self.cards: dict = {}
        self.sessions: dict = {}
        self.next_card_id = 1
        
    def create_card(self, title: str, description: str = "", column: str = "Inbox", assignee: Optional[str] = None) -> dict:
        card_id = self.next_card_id
        self.next_card_id += 1
        card = {
            "id": card_id,
            "title": title,
            "description": description,
            "column": column,
            "assignee": assignee,
            "created_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat(),
            "comments": [],
            "logs": [],
            "status": "idle",
            "activity": [{"action": "created", "timestamp": datetime.now().isoformat()}]
        }
        self.cards[card_id] = card
        return card
    
    def update_card(self, card_id: int, **kwargs) -> Optional[dict]:
        if card_id not in self.cards:
            return None
        self.cards[card_id].update(kwargs)
        self.cards[card_id]["updated_at"] = datetime.now().isoformat()
        # Add activity log entry
        if "activity" not in self.cards[card_id]:
            self.cards[card_id]["activity"] = []
        self.cards[card_id]["activity"].append({
            "action": "updated",
            "timestamp": datetime.now().isoformat()
        })
        return self.cards[card_id]
    
    def get_cards(self, column: Optional[str] = None) -> list:
        cards = list(self.cards.values())
        if column:
            cards = [c for c in cards if c["column"] == column]
        return cards
    
    def delete_card(self, card_id: int) -> bool:
        if card_id in self.cards:
            del self.cards[card_id]
            return True
        return False

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
    card = store.cards.get(card_id)
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
    card = store.cards.get(card_id)
    if not card:
        raise HTTPException(status_code=404, detail="Card not found")
    comment_obj = {
        "author": comment.author,
        "content": comment.content,
        "timestamp": datetime.now().isoformat()
    }
    card["comments"].append(comment_obj)
    await manager.broadcast({"type": "comment_added", "card_id": card_id, "comment": comment_obj})
    return comment_obj

@app.get("/api/sessions")
async def get_sessions():
    return store.sessions

@app.get("/api/sessions/{session_id}/logs")
async def get_session_logs(session_id: int):
    session = store.sessions.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return {"logs": session.get("logs", [])}

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
            planned_cards = [c for c in store.cards.values() 
                           if c["column"] == "Planned" and not c.get("assignee")]
            
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
                        break
                        
        except Exception as e:
            logger.error(f"Polling error: {e}")

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port)

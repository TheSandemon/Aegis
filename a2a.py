"""
Aegis A2A (Agent-to-Agent) Protocol Layer
Implements the AgentCard discovery endpoint and A2A message ingestion.
"""

import json
import logging
from datetime import datetime
from typing import Optional, List

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

logger = logging.getLogger("aegis.a2a")

router = APIRouter()


# ─── AgentCard Schema ───────────────────────────────────────────────────────────

class AgentCapability(BaseModel):
    name: str
    description: str

class AgentCard(BaseModel):
    name: str = "Aegis Orchestrator"
    version: str = "2.0.0"
    description: str = "Multi-Agent Kanban & Orchestration Hub with A2A and MCP support"
    url: str = ""
    protocols: List[str] = ["a2a/1.0", "mcp/1.0"]
    capabilities: List[AgentCapability] = [
        AgentCapability(name="task_management", description="Create, update, and manage Kanban task cards"),
        AgentCapability(name="agent_orchestration", description="Route tasks to registered agents"),
        AgentCapability(name="log_streaming", description="Real-time agent output streaming via WebSocket"),
        AgentCapability(name="hitl_validation", description="Human-in-the-loop approval for completed work"),
    ]
    supported_content_types: List[str] = ["application/json"]


# ─── A2A Message Schema ─────────────────────────────────────────────────────────

class A2ATaskPayload(BaseModel):
    title: str
    description: str = ""
    priority: Optional[str] = "normal"
    metadata: Optional[dict] = None

class A2AMessage(BaseModel):
    sender: str                     # e.g. "openclaw", "picoclaw"
    type: str = "task.create"       # message type
    payload: A2ATaskPayload
    timestamp: Optional[str] = None


# ─── Endpoints ───────────────────────────────────────────────────────────────────

@router.get("/.well-known/agent.json")
async def get_agent_card(request: Request):
    """Publishes the Aegis AgentCard for A2A discovery."""
    card = AgentCard(url=str(request.base_url).rstrip("/"))
    return card.model_dump()


@router.post("/api/a2a/messages")
async def receive_a2a_message(message: A2AMessage):
    """
    Ingests standardized A2A messages from external agents.
    Currently supports 'task.create' to add cards to the Inbox.
    """
    # Lazy import to avoid circular dependency
    from main import store, manager

    if message.type == "task.create":
        description = message.payload.description
        if message.payload.metadata:
            description += f"\n\n---\nA2A Metadata: {json.dumps(message.payload.metadata)}"

        new_card = store.create_card(
            title=message.payload.title,
            description=description,
            column="Inbox",
            assignee=None,
            priority=message.payload.priority
        )

        await manager.broadcast({"type": "card_created", "card": new_card})

        logger.info(f"A2A: Created card {new_card['id']} from sender '{message.sender}'")
        return {
            "status": "accepted",
            "card_id": new_card["id"],
            "message": f"Task '{message.payload.title}' added to Inbox"
        }

    elif message.type == "task.status":
        # Allow agents to report their current status (Thinking, Acting, etc)
        from main import store, manager, engine
        
        # Determine the target (card or instance)
        card_id = message.payload.metadata.get("card_id") if message.payload.metadata else None
        instance_id = message.payload.metadata.get("instance_id") if message.payload.metadata else None
        
        status_text = message.payload.title # Using title as the status label
        
        # Broadcast the update
        await manager.broadcast({
            "type": "agent_activity",
            "sender": message.sender,
            "status": status_text,
            "card_id": card_id,
            "instance_id": instance_id,
            "timestamp": datetime.now().isoformat()
        })
        
        # If there's a card ID, persist the activity to the database
        if card_id:
            store.update_card(card_id, activity=status_text)
        
        # If there's a running process, update its activity state
        key = instance_id or message.sender
        if key in engine.active:
            # We'll need to add this attribute to AgentProcess in main.py/execution_engine.py
            setattr(engine.active[key], "activity", status_text)

        logger.info(f"A2A: Status update from '{message.sender}': {status_text}")
        return {"status": "accepted", "message": f"Status updated to '{status_text}'"}

    else:
        raise HTTPException(status_code=400, detail=f"Unknown A2A message type: {message.type}")


@router.get("/api/a2a/agents")
async def list_registered_agents():
    """Lists all agents registered in the Aegis config."""
    from main import CONFIG
    agents = CONFIG.get("agents", {})
    return {
        name: {
            "profile": cfg.get("profile", ""),
            "enabled": cfg.get("enabled", False),
            "isolation": cfg.get("isolation", "subprocess")
        }
        for name, cfg in agents.items()
    }

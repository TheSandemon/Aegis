"""
Aegis MCP (Model Context Protocol) Server
Exposes local workspace directories as discoverable resources and tools.
"""

import os
import json
import logging
from pathlib import Path
from typing import Optional, List

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

logger = logging.getLogger("aegis.mcp")

router = APIRouter(prefix="/api/mcp", tags=["MCP"])


# ─── Models ──────────────────────────────────────────────────────────────────────

class MCPResource(BaseModel):
    uri: str
    name: str
    description: str
    mime_type: str = "application/octet-stream"

class MCPToolCall(BaseModel):
    path: str
    content: Optional[str] = None  # For write operations


# ─── Resource Discovery ─────────────────────────────────────────────────────────

@router.get("/resources")
async def list_resources():
    """Lists all workspace directories exposed as MCP resources."""
    from main import CONFIG

    mcp_config = CONFIG.get("mcp", {})
    workspaces = mcp_config.get("workspaces", [])

    resources = []
    for ws in workspaces:
        ws_path = Path(ws.get("path", ""))
        if ws_path.exists() and ws_path.is_dir():
            resources.append(MCPResource(
                uri=f"file://{ws_path.resolve()}",
                name=ws.get("name", ws_path.name),
                description=ws.get("description", f"Workspace at {ws_path}"),
                mime_type="inode/directory"
            ))

    return {"resources": [r.model_dump() for r in resources]}


# ─── Tool Endpoints ──────────────────────────────────────────────────────────────

@router.post("/tools/read_file")
async def read_file(call: MCPToolCall, request: Request):
    """Reads a file from a permitted MCP workspace."""
    _check_permission(request, "read_file")
    resolved = _validate_path(call.path)
    if not resolved.is_file():
        raise HTTPException(status_code=404, detail=f"File not found: {call.path}")

    try:
        content = resolved.read_text(encoding="utf-8", errors="replace")
        return {
            "path": str(resolved),
            "content": content,
            "size_bytes": resolved.stat().st_size
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/tools/write_file")
async def write_file(call: MCPToolCall, request: Request):
    """Writes content to a file within a permitted MCP workspace."""
    _check_permission(request, "write_file")
    if call.content is None:
        raise HTTPException(status_code=400, detail="Content is required for write operations")

    resolved = _validate_path(call.path)
    resolved.parent.mkdir(parents=True, exist_ok=True)

    try:
        resolved.write_text(call.content, encoding="utf-8")
        logger.info(f"MCP: Wrote {len(call.content)} bytes to {resolved}")
        return {
            "path": str(resolved),
            "size_bytes": len(call.content),
            "status": "written"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/tools/list_dir")
async def list_directory(call: MCPToolCall, request: Request):
    """Lists directory contents within a permitted MCP workspace."""
    _check_permission(request, "list_dir")
    resolved = _validate_path(call.path)
    if not resolved.is_dir():
        raise HTTPException(status_code=404, detail=f"Directory not found: {call.path}")

    entries = []
    try:
        for entry in sorted(resolved.iterdir()):
            entries.append({
                "name": entry.name,
                "type": "directory" if entry.is_dir() else "file",
                "size_bytes": entry.stat().st_size if entry.is_file() else None
            })
    except PermissionError:
        raise HTTPException(status_code=403, detail="Permission denied")

    return {"path": str(resolved), "entries": entries}


# ─── Path Validation & RBAC ──────────────────────────────────────────────────────

def _check_permission(request: Request, required_perm: str):
    """Verifies that the calling agent has the required permission."""
    from main import AGENT_REGISTRY
    
    agent_id = request.headers.get("x-aegis-agent")
    if not agent_id:
        return  # Allow if no agent header is provided (e.g. human/UI)
        
    entry = next((a for a in AGENT_REGISTRY if a["id"] == agent_id), None)
    if entry:
        perms = entry.get("permissions", [])
        if required_perm not in perms:
            raise HTTPException(
                status_code=403, 
                detail=f"Agent '{agent_id}' lacks permission: {required_perm}"
            )

def _validate_path(requested_path: str) -> Path:
    """Ensures the requested path falls within a permitted MCP workspace."""
    from main import CONFIG

    mcp_config = CONFIG.get("mcp", {})
    workspaces = mcp_config.get("workspaces", [])
    permitted_roots = [Path(ws["path"]).resolve() for ws in workspaces if "path" in ws]

    resolved = Path(requested_path).resolve()

    for root in permitted_roots:
        if str(resolved).startswith(str(root)):
            return resolved

    raise HTTPException(
        status_code=403,
        detail=f"Path '{requested_path}' is outside permitted MCP workspaces"
    )

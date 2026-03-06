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
from services.dependencies import integration_manager, engine, broker, send_discord_webhook


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
from routers import columns, cards, instances, profiles
app.include_router(columns.router)
app.include_router(cards.router)
app.include_router(instances.router)
app.include_router(profiles.router)

# Wire broadcaster to execution engine
engine.broadcaster = manager.broadcast

# Mount MCP SSE server (spec-compliant Model Context Protocol)
from mcp_sse import create_mcp_starlette_app
app.mount("/mcp", create_mcp_starlette_app())

# Serve static frontend
app.mount("/static", StaticFiles(directory="static"), name="static")
app.mount("/assets", StaticFiles(directory=str(ASSETS_DIR)), name="assets")


# ═══════════════════════════════════════════════════════════════════════════════════
# PYDANTIC MODELS
# ═══════════════════════════════════════════════════════════════════════════════════

# ═══════════════════════════════════════════════════════════════════════════════════
# API ROUTES
# ═══════════════════════════════════════════════════════════════════════════════════

@app.get("/api/system/status")
async def get_system_status():
    """Return core system state, including whether this is the first run."""
    from execution_engine import load_instances
    from services.db import store
    instances = load_instances()
    cards = store.get_cards()
    profiles = store.get_profiles()
    is_first_run = len(instances) == 0 and len(cards) == 0 and len(profiles) == 0
    return {"is_first_run": is_first_run}

@app.get("/api/browse-folder")
async def browse_folder():
    """Open a native OS folder picker dialog and return the selected path."""
    import asyncio
    from concurrent.futures import ThreadPoolExecutor

    def _pick_folder():
        try:
            import tkinter as tk
            from tkinter import filedialog
            root = tk.Tk()
            root.withdraw()
            root.attributes("-topmost", True)
            folder = filedialog.askdirectory(title="Select Workspace Folder")
            root.destroy()
            return folder or ""
        except Exception:
            return ""

    loop = asyncio.get_event_loop()
    with ThreadPoolExecutor(max_workers=1) as pool:
        result = await loop.run_in_executor(pool, _pick_folder)
    return {"path": result}

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
async def get_system_prompt(request: Request):
    """Get the current system prompt, injecting agent-specific skills if configured."""
    prompt = SYSTEM_PROMPT
    
    # Try to identify which instance is requesting the prompt
    instance_id = request.headers.get("X-Aegis-Instance")
    agent_id = request.headers.get("X-Aegis-Agent")
    
    if instance_id or agent_id:
        instances = load_instances()
        matcher = instance_id or agent_id
        inst = next((i for i in instances if i.get("instance_id") == matcher or i.get("instance_name") == matcher or i.get("agent_id") == matcher), None)
        
        if inst and inst.get("config", {}).get("skills"):
            enabled_skills = inst["config"]["skills"]
            prompt += "\n\n# Your Equipped Skills:\n"
            prompt += "You have been granted access to the following specialized skills.\n"
            prompt += "To use them, perform an HTTP POST request to `/api/tools/execute?name=<skill_name>`.\n"
            prompt += "Pass the required parameters as a JSON payload in the request body.\n\n"
            
            all_tools = skill_manager.get_all_tools()
            for t in all_tools:
                if t["name"] in enabled_skills:
                    prompt += f"## {t['name']}\n"
                    prompt += f"- **Description**: {t['description']}\n"
                    prompt += f"- **Parameters Schema**: {json.dumps(t.get('parameters', {}))}\n\n"
                    
    return {"prompt": prompt}

@app.put("/api/system_prompt")
async def update_system_prompt(update: SystemPromptUpdate):
    global SYSTEM_PROMPT
    SYSTEM_PROMPT = update.prompt
    SYSTEM_PROMPT_PATH.write_text(SYSTEM_PROMPT, encoding="utf-8")
    return {"success": True, "prompt": SYSTEM_PROMPT}



# ─── Cards CRUD ──────────────────────────────────────────────────────────────────

# ─── Comments ────────────────────────────────────────────────────────────────────

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

@app.get("/api/skills/marketplace")
async def get_marketplace_skills(q: Optional[str] = None, cursor: Optional[str] = None):
    """Returns a paginated list of port-ready ClawHub skills."""
    url = "https://clawhub.ai/api/v1/skills"
    
    params = {}
    if q:
        url = "https://clawhub.ai/api/v1/search"
        params["q"] = q
    if cursor:
        params["cursor"] = cursor
        
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(url, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()
            skills = data.get("items", data.get("results", []))
            
            # Map Clawhub skills to the format expected by the frontend
            formatted_skills = []
            for skill in skills:
                formatted_skills.append({
                    "id": skill.get("slug"),
                    "name": skill.get("displayName"),
                    "description": skill.get("summary", ""),
                    "github_url": f"https://clawhub.ai/api/v1/download?slug={skill.get('slug')}"
                })
                
            return {
                "items": formatted_skills,
                "nextCursor": data.get("nextCursor")
            }
    except Exception as e:
        logger.error(f"Failed to fetch Clawhub skills: {e}")
        # Fallback to the old hardcoded list if the API fails
        return {
            "items": [
                {
                    "id": "skills-security-audit",
                    "name": "Security Auditor",
                    "description": "Static code analysis and vulnerability scanning tool suite.",
                    "github_url": "https://github.com/clawhub/skills-security-audit.git"
                },
                {
                    "id": "agentic-devops",
                    "name": "Agentic DevOps",
                    "description": "CI/CD and infrastructure management abilities for agents.",
                    "github_url": "https://github.com/clawhub/agentic-devops.git"
                }
            ],
            "nextCursor": None
        }

@app.post("/api/skills/install")
async def install_skill(req: SkillInstallRequest):
    """Downloads/clones a skill into aegis_data/skills/ and refreshes."""
    import asyncio
    from pathlib import Path
    import zipfile
    import io
    import urllib.parse
    
    # Parse the repo name differently depending on if it's a clawhub download URL or a git URL
    if "clawhub.ai/api/v1/download" in req.github_url:
        parsed_url = urllib.parse.urlparse(req.github_url)
        query_params = urllib.parse.parse_qs(parsed_url.query)
        repo_name = query_params.get('slug', ['unknown'])[0]
    else:
        repo_name = req.github_url.rstrip("/").split("/")[-1].replace(".git", "")
        
    # Find the skill data dir from existing skill manager
    from skill_manager import SKILLS_DIR
    target_dir = SKILLS_DIR / repo_name
    
    if target_dir.exists():
        return {"status": "already_installed", "skill_id": repo_name}
        
    if "clawhub.ai/api/v1/download" in req.github_url:
        try:
            async with httpx.AsyncClient() as client:
                headers = {"User-Agent": "Aegis/2.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko)"}
                response = await client.get(req.github_url, timeout=30, follow_redirects=True, headers=headers)
                response.raise_for_status()
                
                # Extract zip file
                with zipfile.ZipFile(io.BytesIO(response.content)) as zip_ref:
                    # Clawhub zips usually have the contents at the root, unlike github zips
                    zip_ref.extractall(target_dir)
        except Exception as e:
            logger.error(f"Failed to download/extract skill from {req.github_url}: {e}")
            if target_dir.exists():
                shutil.rmtree(target_dir, ignore_errors=True)
            raise HTTPException(status_code=400, detail=f"Failed to download skill: {e}")
    else:
        # Legacy git clone
        proc = await asyncio.create_subprocess_exec(
            "git", "clone", req.github_url, str(target_dir),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await proc.communicate()
        
        if proc.returncode != 0:
            raise HTTPException(status_code=400, detail=stderr.decode(errors="replace"))
        
    skill_manager.refresh_skills()
    return {"status": "success", "skill_id": repo_name, "message": f"Successfully installed {repo_name}"}

@app.delete("/api/skills/uninstall/{skill_id}")
async def uninstall_skill(skill_id: str):
    """Uninstalls a skill and removes it from all active workers."""
    import shutil
    from skill_manager import SKILLS_DIR
    target_dir = SKILLS_DIR / skill_id
    
    if not target_dir.exists():
        raise HTTPException(status_code=404, detail=f"Skill '{skill_id}' is not installed.")
        
    try:
        shutil.rmtree(target_dir, ignore_errors=True)
    except Exception as e:
        logger.error(f"Error removing skill directory for {skill_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to remove skill files: {e}")
        
    # Remove from instances to prevent ghost skills
    try:
        instances = load_instances()
        changed = False
        for inst in instances:
            skills = inst.get("config", {}).get("skills", [])
            if skill_id in skills:
                skills.remove(skill_id)
                changed = True
        
        if changed:
            save_instances(instances)
    except Exception as e:
        logger.error(f"Error removing skill {skill_id} from instances: {e}")
        
    skill_manager.refresh_skills()
    return {"status": "success", "skill_id": skill_id, "message": f"Successfully uninstalled {skill_id}"}

# ─── Agent Control ───────────────────────────────────────────────────────────────

# ─── Phase 5: Human Approval Gate ────────────────────────────────────────────────

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

# ─── Instance Intervention (Glass Box) ───────────────────────────────────────────
# ─── Instance Artifacts ──────────────────────────────────────────────────────────

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


# ─── Integration Connections ─────────────────────────────────────────────────────

_GH_BASE = "https://api.github.com"

@app.get("/api/connections")
async def list_connections():
    """List all saved integration connections (tokens redacted)."""
    conns = CONFIG.get("integration_connections", [])
    return [
        {
            "id": c["id"],
            "type": c["type"],
            "name": c["name"],
            "user_info": c.get("user_info", {}),
            "scopes": c.get("scopes", []),
            "created_at": c.get("created_at"),
        }
        for c in conns
    ]

@app.post("/api/connections")
async def create_connection(req: ConnectionCreate):
    """Validate credentials and save a new integration connection."""
    if req.type != "github":
        raise HTTPException(status_code=400, detail=f"Unsupported connection type: {req.type}")

    if req.token.startswith("github_pat_"):
        raise HTTPException(status_code=400, detail="Fine-grained tokens are no longer supported. Please use a Classic PAT or OAuth login.")

    # Validate the GitHub token
    headers = {
        "Authorization": f"Bearer {req.token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(f"{_GH_BASE}/user", headers=headers)
        
        if resp.status_code == 401:
            raise HTTPException(status_code=401, detail="Invalid token — authentication failed")
        elif resp.status_code == 403:
            raise HTTPException(status_code=403, detail="Token lacks required permissions (or might be a restricted token)")
        elif resp.status_code != 200:
            raise HTTPException(status_code=resp.status_code, detail=f"GitHub API error: {resp.status_code}")
        
        user = resp.json()

        scopes = resp.headers.get("x-oauth-scopes", "")
        scope_list = [s.strip() for s in scopes.split(",") if s.strip()]

    conn_id = f"conn_{secrets.token_hex(6)}"
    connection = {
        "id": conn_id,
        "type": req.type,
        "name": req.name,
        "credentials": {"token": req.token},
        "user_info": {
            "login": user["login"],
            "avatar_url": user.get("avatar_url", ""),
            "name": user.get("name") or user["login"],
        },
        "scopes": scope_list,
        "created_at": datetime.now().isoformat(),
    }

    CONFIG.setdefault("integration_connections", [])
    CONFIG["integration_connections"].append(connection)
    with open(CONFIG_PATH, 'w', encoding="utf-8") as f:
        json.dump(CONFIG, f, indent=2)

    # Return without the raw token
    return {
        "id": conn_id,
        "type": req.type,
        "name": req.name,
        "user_info": connection["user_info"],
        "scopes": scope_list,
        "created_at": connection["created_at"],
    }

@app.delete("/api/connections/{conn_id}")
async def delete_connection(conn_id: str):
    """Remove a saved integration connection."""
    conns = CONFIG.get("integration_connections", [])
    CONFIG["integration_connections"] = [c for c in conns if c["id"] != conn_id]
    with open(CONFIG_PATH, 'w', encoding="utf-8") as f:
        json.dump(CONFIG, f, indent=2)
    return {"success": True}


def _get_connection(conn_id: str) -> dict:
    """Helper to find a connection by ID, raises HTTPException if not found."""
    conns = CONFIG.get("integration_connections", [])
    conn = next((c for c in conns if c["id"] == conn_id), None)
    if not conn:
        raise HTTPException(status_code=404, detail="Connection not found")
    return conn


@app.get("/api/connections/{conn_id}/repos")
async def list_connection_repos(conn_id: str, search: Optional[str] = None):
    """List repos accessible to a saved connection."""
    conn = _get_connection(conn_id)
    token = conn.get("credentials", {}).get("token")
    if not token:
        raise HTTPException(status_code=400, detail="Connection has no token")

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    repos = []
    page = 1
    async with httpx.AsyncClient(timeout=15) as client:
        while True:
            params = {"per_page": 100, "page": page, "sort": "updated", "direction": "desc"}
            resp = await client.get(f"{_GH_BASE}/user/repos", headers=headers, params=params)
            if resp.status_code in (401, 403):
                # If strictly scoped, /user/repos might fail. Return empty list so frontend can fallback.
                break
            if resp.status_code != 200:
                raise HTTPException(status_code=resp.status_code, detail="Failed to fetch repos")
            batch = resp.json()
            if not batch:
                break
            repos.extend(batch)
            if len(batch) < 100:
                break
            page += 1

    if search:
        search_lower = search.lower()
        repos = [r for r in repos if search_lower in r["full_name"].lower()]

    return [
        {
            "full_name": r["full_name"],
            "name": r["name"],
            "owner": r["owner"]["login"],
            "private": r["private"],
            "description": r.get("description") or "",
            "has_issues": r.get("has_issues", True),
            "permissions": r.get("permissions", {}),
            "updated_at": r.get("updated_at"),
        }
        for r in repos[:100]
    ]


@app.get("/api/connections/{conn_id}/repos/{owner}/{repo}/permissions")
async def check_connection_repo_permissions(conn_id: str, owner: str, repo: str):
    """Check permissions for a specific repo on a saved connection."""
    conn = _get_connection(conn_id)
    token = conn.get("credentials", {}).get("token")
    if not token:
        raise HTTPException(status_code=400, detail="Connection has no token")

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(f"{_GH_BASE}/repos/{owner}/{repo}", headers=headers)
        if resp.status_code == 404:
            raise HTTPException(status_code=404, detail="Repository not found or not accessible")
        if resp.status_code != 200:
            raise HTTPException(status_code=resp.status_code, detail=f"GitHub API error: {resp.status_code}")

        repo_data = resp.json()
        perms = repo_data.get("permissions", {})

        return {
            "full_name": repo_data["full_name"],
            "private": repo_data["private"],
            "permissions": {
                "can_read_issues": perms.get("pull", False) or perms.get("push", False) or perms.get("admin", False),
                "can_write_issues": perms.get("push", False) or perms.get("admin", False),
                "can_read_prs": perms.get("pull", False) or perms.get("push", False) or perms.get("admin", False),
                "can_write_prs": perms.get("push", False) or perms.get("admin", False),
                "can_manage_webhooks": perms.get("admin", False),
                "can_push": perms.get("push", False),
                "is_admin": perms.get("admin", False),
            },
            "has_issues": repo_data.get("has_issues", True),
        }

# ═══════════════════════════════════════════════════════════════════════════════════
# GITHUB DEVICE FLOW (OAuth)
# ═══════════════════════════════════════════════════════════════════════════════════

# Open-source public Client ID for Aegis on GitHub
# TODO: Replace with your actual GitHub OAuth App Client ID that has Device Flow enabled.
GITHUB_CLIENT_ID = "Ov23ctf2YCfapE8ClL8s"

@app.post("/api/github/device/start")
async def github_device_start():
    """Start the GitHub Device Flow to get user and device codes."""
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(
            "https://github.com/login/device/code",
            headers={"Accept": "application/json"},
            data={
                "client_id": GITHUB_CLIENT_ID,
                "scope": "repo,workflow"
            }
        )
        if resp.status_code != 200:
            print(f"GitHub Device Flow Start Error ({resp.status_code}): {resp.text}")
            raise HTTPException(status_code=400, detail="Failed to initialize GitHub login.")
        return resp.json()

@app.post("/api/github/device/poll")
async def github_device_poll(req: DevicePollRequest):
    """Poll GitHub to see if the user authenticated yet."""
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(
            "https://github.com/login/oauth/access_token",
            headers={"Accept": "application/json"},
            data={
                "client_id": GITHUB_CLIENT_ID,
                "device_code": req.device_code,
                "grant_type": "urn:ietf:params:oauth:grant-type:device_code"
            }
        )
        
        data = resp.json()
        
        if "error" in data:
            err = data["error"]
            if err == "authorization_pending":
                return {"status": "pending"}
            elif err == "slow_down":
                return {"status": "slow_down", "interval": data.get("interval", 5)}
            elif err == "expired_token":
                return {"status": "expired"}
            else:
                return {"status": "error", "message": data.get("error_description", err)}
                
        # Success!
        access_token = data.get("access_token")
        if not access_token:
            return {"status": "error", "message": "No access token received"}

        # Fetch User Profile
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        user_resp = await client.get(f"{_GH_BASE}/user", headers=headers)
        if user_resp.status_code != 200:
            return {"status": "error", "message": "Failed to fetch GitHub profile"}
            
        user = user_resp.json()
        scopes = user_resp.headers.get("x-oauth-scopes", "")
        scope_list = [s.strip() for s in scopes.split(",") if s.strip()]

        # Save Connection
        conn_id = f"conn_{secrets.token_hex(6)}"
        connection = {
            "id": conn_id,
            "type": "github",
            "name": f"OAuth @{user['login']}",
            "credentials": {"token": access_token},
            "user_info": {
                "login": user["login"],
                "avatar_url": user.get("avatar_url", ""),
                "name": user.get("name") or user["login"],
            },
            "scopes": scope_list,
            "created_at": datetime.now().isoformat(),
        }

        CONFIG.setdefault("integration_connections", [])
        CONFIG["integration_connections"].append(connection)
        with open(CONFIG_PATH, 'w', encoding="utf-8") as f:
            json.dump(CONFIG, f, indent=2)

        return {"status": "success", "connection": connection}
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
            elif message.get("type") == "stdin":
                instance_id = message.get("instance_id")
                stdin_data = message.get("data")
                if instance_id and stdin_data:
                    await engine.inject_stdin(instance_id, stdin_data)

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

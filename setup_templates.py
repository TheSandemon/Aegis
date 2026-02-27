import json
import os
from pathlib import Path
import sys
import logging
import shutil

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger(__name__)

# Ensure UTF-8 output for Windows console
if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except AttributeError:
        pass

REGISTRY_PATH = Path("agent_registry.json")
with open(REGISTRY_PATH, "r", encoding="utf-8") as f:
    registry = json.load(f)

TEMPLATES_DIR = Path("aegis_data/templates")
TEMPLATES_DIR.mkdir(parents=True, exist_ok=True)

# Read worker code from canonical source file instead of inline string.
# The canonical worker.py lives in the aegis-worker template directory.
CANONICAL_WORKER = TEMPLATES_DIR / "aegis-worker" / "worker.py"
if CANONICAL_WORKER.exists():
    worker_code = CANONICAL_WORKER.read_text(encoding="utf-8")
    print(f"Loaded canonical worker.py ({len(worker_code)} bytes)")
else:
    print("WARNING: Canonical worker.py not found! Skipping worker sync.")
    worker_code = None

for agent in registry:
    # 1. Update execution to use Python worker
    agent["execution"] = {
        "working_dir": f"./agents/{agent['id']}",
        "command": "python -u worker.py",
        "env_vars_required": []
    }
    
    # 2. Add 'goals' to config schema
    if "config_schema" not in agent:
        agent["config_schema"] = {}
        
    # We remove system_prompt if it exists and replace with goals
    if "system_prompt" in agent["config_schema"]:
        default_prompt = agent["config_schema"]["system_prompt"].get("default", "")
        del agent["config_schema"]["system_prompt"]
        agent["config_schema"]["goals"] = {
            "type": "textarea",
            "label": "Agent Goals",
            "default": default_prompt
        }
    elif "goals" not in agent["config_schema"]:
        agent["config_schema"]["goals"] = {
            "type": "textarea",
            "label": "Agent Goals",
            "default": f"You are {agent.get('name')}. Complete tasks efficiently."
        }
        
    # Move goals to the top of the dict
    if "goals" in agent["config_schema"]:
        goals = agent["config_schema"].pop("goals")
        new_schema = {"goals": goals}
        new_schema.update(agent["config_schema"])
        agent["config_schema"] = new_schema
        new_schema = agent["config_schema"]
    else:
        new_schema = agent["config_schema"]
    
    # 2.5 Add work_dir and pulse_interval to the schema if missing
    if "work_dir" not in new_schema and not agent.get("is_orchestrator"):
        new_schema["work_dir"] = {
            "type": "text",
            "label": "Workspace Path (Local or URL)",
            "default": "./"
        }
    if "pulse_interval" not in new_schema:
        new_schema["pulse_interval"] = {
            "type": "number",
            "label": "Pulse Interval (Seconds)",
            "default": 30 if agent.get("is_orchestrator") else 60
        }
    if "startup_delay" not in new_schema:
        new_schema["startup_delay"] = {
            "type": "boolean",
            "label": "Delay First Action",
            "default": False,
            "description": "Wait one pulse interval before taking the first action."
        }
        
    agent["config_schema"] = new_schema

    # 3. Pre-create the local template to bypass git clone
    agent_dir = TEMPLATES_DIR / agent["id"]
    agent_dir.mkdir(parents=True, exist_ok=True)
    
    # Write worker.py from canonical source
    if worker_code:
        try:
            (agent_dir / "worker.py").write_text(worker_code, encoding="utf-8")
            # Write requirements.txt
            (agent_dir / "requirements.txt").write_text("requests==2.31.0\n", encoding="utf-8")
        except Exception as e:
            print(f"Warning: Could not write to template directory for {agent['id']}: {e}")

# Bulk sync latest worker.py to ALL existing templates and instances once
if worker_code and TEMPLATES_DIR.exists():
    for t_dir in TEMPLATES_DIR.iterdir():
        if t_dir.is_dir() and (t_dir / "worker.py").exists():
            try:
                (t_dir / "worker.py").write_text(worker_code, encoding='utf-8')
                print(f"Synced latest worker.py to template {t_dir.name}")
            except Exception as e:
                print(f"Warning: Could not sync template {t_dir.name}: {e}")
            
INSTANCES_DIR = Path("aegis_data/instances")
if worker_code and INSTANCES_DIR.exists():
    for i_dir in INSTANCES_DIR.iterdir():
        if i_dir.is_dir() and (i_dir / "worker.py").exists():
            try:
                (i_dir / "worker.py").write_text(worker_code, encoding='utf-8')
                print(f"Synced latest worker.py to instance {i_dir.name}")
            except Exception as e:
                print(f"Warning: Could not sync instance {i_dir.name}: {e}")

with open(REGISTRY_PATH, "w", encoding="utf-8") as f:
    json.dump(registry, f, indent=4)

print("Registry updated and local templates generated successfully.")


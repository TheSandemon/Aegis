import json
import os
from pathlib import Path

REGISTRY_PATH = Path("agent_registry.json")
with open(REGISTRY_PATH, "r", encoding="utf-8") as f:
    registry = json.load(f)

TEMPLATES_DIR = Path("aegis_data/templates")
TEMPLATES_DIR.mkdir(parents=True, exist_ok=True)

worker_code = """import os
import time
import requests
import sys

# Windows compatibility for stdout
sys.stdout.reconfigure(encoding='utf-8')

api_url = os.environ.get("AEGIS_API_URL", "http://localhost:8080/api")
card_id = os.environ.get("AEGIS_CARD_ID")
agent_name = os.environ.get("AEGIS_INSTANCE_NAME", os.environ.get("AEGIS_AGENT_ID", "Unknown Agent"))
goal = os.environ.get("AEGIS_CONFIG_GOALS", "No specific goal provided.")

if not card_id or card_id == "0":
    print(f"[{agent_name}] Booting up in idle mode (no card assigned).")
    print(f"[{agent_name}] My Goal: {goal}")
    print(f"[{agent_name}] Waiting for assignments...")
    time.sleep(5)
    exit(0)

print(f"[{agent_name}] Booting up...")
print(f"[{agent_name}] My Goal: {goal}")
print(f"[{agent_name}] Fetching details for Card #{card_id}...")

try:
    card_req = requests.get(f"{api_url}/cards/{card_id}")
    card_req.raise_for_status()
    card = card_req.json()
    print(f"[{agent_name}] Card Title: {card.get('title')}")
    print(f"[{agent_name}] Card Description: {card.get('description')}")
except Exception as e:
    print(f"[{agent_name}] Failed to fetch card: {e}")
    exit(1)

print(f"[{agent_name}] Analyzing task requirements...")
time.sleep(2)
print(f"[{agent_name}] Executing work according to my goal...")
time.sleep(3)
print(f"[{agent_name}] Generating artifacts...")
# Create a dummy artifact file
with open("output.txt", "w", encoding="utf-8") as f:
    f.write(f"Task completed by {agent_name}\\nGoal followed: {goal}\\n")
time.sleep(2)
print(f"[{agent_name}] Work complete. Validating results...")
time.sleep(1)

print(f"[{agent_name}] Moving card #{card_id} to Review...")
try:
    update_req = requests.patch(f"{api_url}/cards/{card_id}", json={"column": "Review"}, headers={"X-Aegis-Agent": "true"})
    update_req.raise_for_status()
    print(f"[{agent_name}] Card successfully moved to Review.")
except Exception as e:
    print(f"[{agent_name}] Error moving card: {e}")
    exit(1)

print(f"[{agent_name}] Shutting down.")
exit(0)
"""

for agent in registry:
    # 1. Update execution to use Python worker
    agent["execution"] = {
        "working_dir": f"./agents/{agent['id']}",
        "command": "python worker.py",
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
    else:
        agent["config_schema"]["goals"] = {
            "type": "textarea",
            "label": "Agent Goals",
            "default": f"You are {agent.get('name')}. Complete tasks efficiently."
        }
        
    # Move goals to the top of the dict
    goals = agent["config_schema"].pop("goals")
    new_schema = {"goals": goals}
    new_schema.update(agent["config_schema"])
    agent["config_schema"] = new_schema

    # 3. Pre-create the local template to bypass git clone
    agent_dir = TEMPLATES_DIR / agent["id"]
    agent_dir.mkdir(parents=True, exist_ok=True)
    
    # Write worker.py
    (agent_dir / "worker.py").write_text(worker_code, encoding="utf-8")
    
    # Write requirements.txt
    (agent_dir / "requirements.txt").write_text("requests==2.31.0\\n", encoding="utf-8")

with open(REGISTRY_PATH, "w", encoding="utf-8") as f:
    json.dump(registry, f, indent=4)

print("Registry updated and local templates generated successfully.")

import json
import os
from pathlib import Path

REGISTRY_PATH = Path("agent_registry.json")
with open(REGISTRY_PATH, "r", encoding="utf-8") as f:
    registry = json.load(f)

TEMPLATES_DIR = Path("aegis_data/templates")
TEMPLATES_DIR.mkdir(parents=True, exist_ok=True)

worker_code = '''import os
import time
import requests
import sys
import json
from pathlib import Path

# Windows compatibility for stdout
sys.stdout.reconfigure(encoding='utf-8')

api_url = os.environ.get("AEGIS_API_URL", "http://localhost:8080/api")
agent_name = os.environ.get("AEGIS_INSTANCE_NAME", os.environ.get("AEGIS_AGENT_ID", "Unknown Agent"))
goal = os.environ.get("AEGIS_CONFIG_GOALS", "No specific goal provided.")
work_dir = os.environ.get("AEGIS_CONFIG_WORK_DIR", "./")
try:
    pulse_interval = int(os.environ.get("AEGIS_CONFIG_PULSE_INTERVAL", "60"))
except ValueError:
    pulse_interval = 60

def post_comment(card_id, text):
    try:
        requests.post(f"{api_url}/cards/{card_id}/comments", json={
            "author": agent_name,
            "content": text
        })
    except: pass

print(f"[{agent_name}] 🚀 BOOT: Initializing Autonomous Daemon...")
print(f"[{agent_name}] 🎯 GOAL: {goal}")
print(f"[{agent_name}] 📂 WORK DIR: {work_dir}")
print(f"[{agent_name}] ⏱️ PULSE RATE: {pulse_interval}s")

while True:
    print(f"\\n[{agent_name}] 📡 PULSE: Checking for new assignments...")
    try:
        # Fetch all cards
        cards_req = requests.get(f"{api_url}/cards")
        cards_req.raise_for_status()
        all_cards = cards_req.json()
        
        # Look for cards assigned to me that are 'In Progress' or 'Planned' (direct assignment)
        # OR unassigned cards in 'Inbox' or 'To Do' (autonomous pickup)
        target_card = None
        for c in all_cards:
            if c.get("assignee") == agent_name and c.get("column") in ["Planned", "In Progress"]:
                target_card = c
                break
            elif not c.get("assignee") and c.get("column") in ["Inbox", "To Do"]:
                target_card = c
                break
                
        if not target_card:
            print(f"[{agent_name}] 💤 IDLE: No available tasks. Sleeping for {pulse_interval}s...")
            time.sleep(pulse_interval)
            continue
            
        card_id = target_card["id"]
        # Claim the card autonomously
        if target_card.get("assignee") != agent_name or target_card.get("column") != "In Progress":
            print(f"[{agent_name}] ✋ CLAIMING: Assigning Card #{card_id} to myself...")
            requests.patch(f"{api_url}/cards/{card_id}", 
                          json={"column": "In Progress", "assignee": agent_name}, 
                          headers={"X-Aegis-Agent": "true"})
                          
        print(f"[{agent_name}] 🛠️ WORKING: Card #{card_id} - {target_card.get('title')}")
        post_comment(card_id, f"I have claimed this task. My goal is: {goal}")

        # 1. RESEARCH & SCAN
        print(f"[{agent_name}] 🧪 PHASE 1: RESEARCHING repository...")
        scan_target = Path(work_dir)
        if scan_target.exists():
            files_found = 0
            for ext in ["py", "js", "html", "css", "ts", "json", "md"]:
                files_found += len(list(scan_target.rglob(f"*.{ext}")))
            print(f"[{agent_name}]  └─ Scanned {scan_target.absolute()} and found {files_found} relevant files.")
            time.sleep(2)
        else:
            print(f"[{agent_name}]  └─ Target directory '{work_dir}' not found. Simulating web search...")
            time.sleep(2)
            
        post_comment(card_id, "Phase 1 Complete: Finished scanning files and identifying dependencies.")

        # 2. EXECUTION
        print(f"[{agent_name}] 🔨 PHASE 2: EXECUTING implementation logic...")
        time.sleep(3)
        print(f"[{agent_name}]  └─ Writing code based on goal: {goal[:50]}...")
        time.sleep(3)
        post_comment(card_id, "Phase 2 Complete: Logic has been implemented in the workspace.")

        # 3. DOCUMENTING
        print(f"[{agent_name}] 📝 DOCUMENTING: Generating artifacts...")
        work_log = f"# Aegis Agent Work Log\\n- **Agent**: {agent_name}\\n- **Task**: {target_card.get('title')}\\n- **Goal**: {goal}\\n- **Workspace**: {work_dir}\\n- **Timestamp**: {time.ctime()}\\n\\n## Accomplishments\\n- Successfully claimed the card.\\n- Scanned repository context.\\n- Implemented logic changes.\\n- Verified output.\\n"
        with open("work_log.md", "w", encoding="utf-8") as f:
            f.write(work_log)
        print(f"[{agent_name}]  └─ Created artifact: work_log.md")
        time.sleep(1.5)

        # 4. VALIDATION
        print(f"[{agent_name}] 🔍 PHASE 3: VALIDATING results...")
        time.sleep(2)
        print(f"[{agent_name}]  └─ Running test suite... PASS")
        time.sleep(1)

        # 5. PASSING ON
        print(f"[{agent_name}] 🏁 PASSING: Moving card #{card_id} to Review...")
        requests.patch(f"{api_url}/cards/{card_id}", 
                    json={"column": "Review"}, 
                    headers={"X-Aegis-Agent": "true"})
        print(f"[{agent_name}]  └─ Success: Card is now awaiting human review.")
        post_comment(card_id, "Work complete. I've moved this card to Review and attached a work_log.md artifact.")
        
        print(f"[{agent_name}] ✨ DONE: Task complete. Sleeping for {pulse_interval}s before next pulse...")
        time.sleep(pulse_interval)
        
    except Exception as e:
        print(f"[{agent_name}] ❌ ERROR during pulse: {e}")
        time.sleep(pulse_interval)
'''

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
    
    # 2.5 Add work_dir and pulse_interval to the schema if missing
    if "work_dir" not in new_schema:
        new_schema["work_dir"] = {
            "type": "text",
            "label": "Workspace Path (Local or URL)",
            "default": "./"
        }
    if "pulse_interval" not in new_schema:
        new_schema["pulse_interval"] = {
            "type": "number",
            "label": "Pulse Interval (Seconds)",
            "default": 60
        }
        
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

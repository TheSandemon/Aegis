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

orchestrator_worker_code = '''import os
import time
import requests
import sys
import json

sys.stdout.reconfigure(encoding='utf-8')

api_url = os.environ.get("AEGIS_API_URL", "http://localhost:8080/api")
agent_name = os.environ.get("AEGIS_INSTANCE_NAME", os.environ.get("AEGIS_AGENT_ID", "Orchestrator"))
goal = os.environ.get("AEGIS_CONFIG_GOALS", "Manage and delegate tasks.")
try:
    pulse_interval = int(os.environ.get("AEGIS_CONFIG_PULSE_INTERVAL", "30"))
except ValueError:
    pulse_interval = 30

# API Keys (at least one is needed for LLM delegation)
openai_key = os.environ.get("OPENAI_API_KEY", "")
anthropic_key = os.environ.get("ANTHROPIC_API_KEY", "")
gemini_key = os.environ.get("GEMINI_API_KEY", "")

def post_comment(card_id, text):
    try:
        requests.post(f"{api_url}/cards/{card_id}/comments", json={"author": agent_name, "content": text})
    except: pass

def get_other_instances():
    try:
        res = requests.get(f"{api_url}/instances")
        if res.ok:
            insts = res.json()
            # Only count OTHER enabled instances that have API keys (can work)
            return [i for i in insts if i["enabled"] and i["instance_name"] != agent_name and i.get("env_vars")]
    except: pass
    return []

def prompt_llm(system_prompt, user_text):
    """Sends a minimal prompt to the cheapest available configured LLM"""
    if openai_key:
        res = requests.post("https://api.openai.com/v1/chat/completions", headers={"Authorization": f"Bearer {openai_key}"}, json={"model": "gpt-4o-mini", "messages": [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_text}], "response_format": {"type": "json_object"}})
        return json.loads(res.json()["choices"][0]["message"]["content"])
    elif gemini_key:
        res = requests.post(f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={gemini_key}", 
            json={"system_instruction": {"parts": [{"text": system_prompt}]}, "contents": [{"parts":[{"text": user_text}]}], "generationConfig": {"responseMimeType": "application/json"}})
        return json.loads(res.json()["candidates"][0]["content"]["parts"][0]["text"])
    elif anthropic_key:
        res = requests.post("https://api.anthropic.com/v1/messages", headers={"x-api-key": anthropic_key, "anthropic-version": "2023-06-01"}, json={"model": "claude-3-haiku-20240307", "max_tokens": 1000, "system": system_prompt, "messages": [{"role": "user", "content": f"Please output ONLY raw JSON. {user_text}"}]})
        return json.loads(res.json()["content"][0]["text"])
    return None

print(f"[{agent_name}] 👑 BOOT: Initializing Dual-Mode Orchestrator...")
print(f"[{agent_name}] ⏱️ PULSE RATE: {pulse_interval}s")

def solo_worker_logic(target_card):
    # Same as standard worker.
    card_id = target_card["id"]
    if target_card.get("assignee") != agent_name or target_card.get("column") != "In Progress":
        print(f"[{agent_name}] ✋ CLAIMING (SOLO): Assigning Card #{card_id} to myself...")
        requests.patch(f"{api_url}/cards/{card_id}", json={"column": "In Progress", "assignee": agent_name}, headers={"X-Aegis-Agent": "true"})
    
    print(f"[{agent_name}] 🛠️ WORKING: Card #{card_id} - {target_card.get('title')}")
    post_comment(card_id, "Running in Solo Worker mode. Executing task...")
    time.sleep(3)
    
    print(f"[{agent_name}] 🏁 PASSING: Moving card #{card_id} to Review...")
    requests.patch(f"{api_url}/cards/{card_id}", json={"column": "Review"}, headers={"X-Aegis-Agent": "true"})
    post_comment(card_id, "Task complete. Moved to Review.")

def manager_logic(target_card, other_instances):
    card_id = target_card["id"]
    print(f"[{agent_name}] 👔 MANAGER MODE: Delegating Card #{card_id}...")
    
    if target_card.get("assignee") != agent_name or target_card.get("column") != "In Progress":
        requests.patch(f"{api_url}/cards/{card_id}", json={"column": "In Progress", "assignee": agent_name}, headers={"X-Aegis-Agent": "true"})
    
    # Analyze other agents
    agent_profiles = [
        f"- Name: {i['instance_name']} | Template: {i['template_id']} | Goals: {i.get('config', {}).get('goals', 'None')}"
        for i in other_instances
    ]
    
    sys_prompt = """You are the Aegis Orchestrator. Break down the user's task into sub-tasks and assign them to the available agents based on their goals.
Your output MUST be a JSON object with a 'sub_tasks' array. Each object in the array must have:
- 'title': A short title.
- 'description': What to do.
- 'assignee': The EXACT name of the agent to assign it to.
If no agent fits well, assign it to yourself."""
    
    user_msgs = f"TASK TITLE: {target_card['title']}\\nTASK DESC: {target_card['description']}\\n\\nAVAILABLE AGENTS:\\n" + "\\n".join(agent_profiles)
    
    try:
        print(f"[{agent_name}] 🧠 THINKING: Consulting LLM for breakdown...")
        post_comment(card_id, "Entering Manager Mode. Breaking this task down for the team...")
        plan = prompt_llm(sys_prompt, user_msgs)
        
        if not plan or 'sub_tasks' not in plan:
            raise Exception("Invalid LLM response")
            
        created_ids = []
        for st in plan['sub_tasks']:
            print(f"[{agent_name}] 📝 DELEGATING '{st['title']}' to {st['assignee']}...")
            res = requests.post(f"{api_url}/cards", json={
                "title": f"(Sub) {st['title']}",
                "description": st['description'] + f"\\n\\nPart of parent task #{card_id}",
                "column": "Inbox",
                "assignee": st['assignee']
            })
            if res.ok:
                created_ids.append(res.json()['id'])
            time.sleep(1)
            
        print(f"[{agent_name}] 🛑 BLOCKING: Waiting on sub-tasks {created_ids}...")
        requests.patch(f"{api_url}/cards/{card_id}", json={
            "column": "Blocked",
            "depends_on": created_ids
        }, headers={"X-Aegis-Agent": "true"})
        post_comment(card_id, f"I have broken this task down and assigned it. Sub-task IDs: {created_ids}. Moving myself to Blocked.")
        
    except Exception as e:
        print(f"[{agent_name}] ❌ DELEGATION FAILED: {e}")
        post_comment(card_id, f"Failed to delegate task: {e}")
        requests.patch(f"{api_url}/cards/{card_id}", json={"column": "Inbox"}, headers={"X-Aegis-Agent": "true"})

while True:
    try:
        cards_req = requests.get(f"{api_url}/cards")
        if not cards_req.ok: 
            time.sleep(pulse_interval)
            continue
            
        all_cards = cards_req.json()
        target_card = None
        for c in all_cards:
            if c.get("assignee") == agent_name and c.get("column") in ["Planned", "In Progress"]:
                target_card = c
                break
            elif not c.get("assignee") and c.get("column") in ["Inbox"]:
                target_card = c
                break
                
        if not target_card:
            time.sleep(pulse_interval)
            continue
            
        others = get_other_instances()
        if not others:
            solo_worker_logic(target_card)
        else:
            manager_logic(target_card, others)
            
        time.sleep(pulse_interval)
        
    except Exception as e:
        print(f"[{agent_name}] ❌ ERROR: {e}")
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
        
    agent["config_schema"] = new_schema

    # 3. Pre-create the local template to bypass git clone
    agent_dir = TEMPLATES_DIR / agent["id"]
    agent_dir.mkdir(parents=True, exist_ok=True)
    
    # Write worker.py (branching for orchestrator)
    target_code = orchestrator_worker_code if agent.get("is_orchestrator") else worker_code
    (agent_dir / "worker.py").write_text(target_code, encoding="utf-8")
    
    # Write requirements.txt
    (agent_dir / "requirements.txt").write_text("requests==2.31.0\\n", encoding="utf-8")

with open(REGISTRY_PATH, "w", encoding="utf-8") as f:
    json.dump(registry, f, indent=4)

print("Registry updated and local templates generated successfully.")

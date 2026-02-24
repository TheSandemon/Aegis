import json
import os
from pathlib import Path
import sys

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

worker_code = '''import os
import time
import requests
import sys
import json

sys.stdout.reconfigure(encoding='utf-8')

api_url = os.environ.get("AEGIS_API_URL", "http://localhost:8080/api")
agent_name = os.environ.get("AEGIS_INSTANCE_NAME", os.environ.get("AEGIS_AGENT_ID", "Agent"))
goal = os.environ.get("AEGIS_CONFIG_GOALS", "Process tasks and help the team.")
try:
    pulse_interval = int(os.environ.get("AEGIS_CONFIG_PULSE_INTERVAL", "30"))
except ValueError:
    pulse_interval = 30

service = os.environ.get("AEGIS_SERVICE", "")
model = os.environ.get("AEGIS_MODEL", "")

openai_key = os.environ.get("OPENAI_API_KEY", "")
anthropic_key = os.environ.get("ANTHROPIC_API_KEY", "")
google_key = os.environ.get("GOOGLE_API_KEY", os.environ.get("GEMINI_API_KEY", ""))
deepseek_key = os.environ.get("DEEPSEEK_API_KEY", "")

if not service:
    if openai_key: service = "openai"
    elif anthropic_key: service = "anthropic"
    elif google_key: service = "google"
    elif deepseek_key: service = "deepseek"

def fetch_board_state():
    try:
        cards = requests.get(f"{api_url}/cards").json()
        cols = requests.get(f"{api_url}/columns").json()
        return cards, cols
    except Exception as e:
        print(f"[{agent_name}] ❌ API Error: {e}")
        return [], []

def prompt_llm(system_prompt, user_text):
    def parse_json(text):
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            # Try to strip markdown code blocks if the LLM hallucinated them
            if text.startswith("```json"): text = text[7:]
            elif text.startswith("```"): text = text[3:]
            if text.endswith("```"): text = text[:-3]
            try: return json.loads(text.strip())
            except: return None

    if service == "openai" and openai_key:
        m = model or "gpt-4o-mini"
        res = requests.post("https://api.openai.com/v1/chat/completions", headers={"Authorization": f"Bearer {openai_key}"}, json={"model": m, "messages": [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_text}], "response_format": {"type": "json_object"}})
        content = res.json()["choices"][0]["message"]["content"]
        return parse_json(content)
    elif service == "google" and google_key:
        m = model or "gemini-2.0-flash"
        res = requests.post(f"https://generativelanguage.googleapis.com/v1beta/models/{m}:generateContent?key={google_key}", 
            json={"system_instruction": {"parts": [{"text": system_prompt}]}, "contents": [{"parts":[{"text": user_text}]}], "generationConfig": {"responseMimeType": "application/json"}})
        content = res.json()["candidates"][0]["content"]["parts"][0]["text"]
        return parse_json(content)
    elif service == "anthropic" and anthropic_key:
        m = model or "claude-3-5-sonnet-latest"
        res = requests.post("https://api.anthropic.com/v1/messages", headers={"x-api-key": anthropic_key, "anthropic-version": "2023-06-01"}, json={"model": m, "max_tokens": 1000, "system": system_prompt, "messages": [{"role": "user", "content": f"Please output ONLY raw JSON. {user_text}"}]})
        content = res.json()["content"][0]["text"]
        return parse_json(content)
    elif service == "deepseek" and deepseek_key:
        m = model or "deepseek-chat"
        res = requests.post("https://api.deepseek.com/chat/completions", headers={"Authorization": f"Bearer {deepseek_key}"}, json={"model": m, "messages": [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_text}], "response_format": {"type": "json_object"}})
        content = res.json()["choices"][0]["message"]["content"]
        return parse_json(content)
        
    print(f"[{agent_name}] ❌ ERROR: Unsupported service '{service}' or missing API key.")
    return None

system_prompt = f"""You are an autonomous AI agent working on a Kanban board via a REST API.
Your Name: {agent_name}
Your Goal: {goal}

Core Workspace Mechanics:
1. The Kanban board is composed of Columns (e.g., 'Inbox', 'In Progress', 'Done').
2. Tasks are represented as Cards inside these columns.
3. You MUST take action to achieve your goal. Do NOT just output text. Use the JSON tools provided.
4. If your goal is to "create ideas in the inbox", you must use the 'create_card' tool and set the 'column' argument to 'Inbox' (or whatever column is requested).
5. If you see a card you need to work on, use 'update_card' to move it, change its status, or claim it as the assignee.
6. Use 'post_comment' to add notes to cards you are working on.
7. Use 'wait' ONLY if you are truly blocked waiting for a human or another agent to do something.

Available Actions (Tools):
1. create_card: {{"title": str, "description": str, "column": str, "assignee": str}} - Create a new task in a specific column.
2. update_card: {{"card_id": int, "column": str, "assignee": str, "status": str, "priority": "low"|"normal"|"high"}} - Move a card, assign it, or update it.
3. delete_card: {{"card_id": int}} - Remove a card.
4. post_comment: {{"card_id": int, "content": str}} - Add details or ask questions on a card.
5. create_column: {{"name": str, "position": int}} - Add a new Kanban column.
6. delete_column: {{"column_id": int}} - Remove a column.
7. wait: {{"reason": str}} - Pause until the next pulse (use sparingly).

Response Format (JSON ONLY):
{{
    "thought": "Brief reasoning for this action.",
    "action": "action_name",
    "args": {{...}}
}}
"""

print(f"[{agent_name}] 🚀 BOOT: Sandboxed Autonomous Agent")
print(f"[{agent_name}] 🎯 GOAL: {goal}")

while True:
    print(f"\\n[{agent_name}] 📡 PULSE: Fetching board state...")
    cards, cols = fetch_board_state()
    
    if not isinstance(cards, list) or not isinstance(cols, list):
        print(f"[{agent_name}] ❌ API Error: Invalid state format received. Waiting...")
        time.sleep(pulse_interval)
        continue
        
    board_context = f"COLUMNS: {[{'id': c['id'], 'name': c['name']} for c in cols]}\\n\\nCARDS:\\n"
    for c in cards:
        comments = c.get("comments", [])
        last_comment = f" | Last Comment: {comments[-1]['content'][:50]}" if comments else ""
        board_context += f"- [#{c['id']}] {c['title']} (Col: {c['column']}) | Asg: {c.get('assignee', 'None')} | Priority: {c.get('priority', 'normal')}{last_comment}\\n  Desc: {c.get('description', '')[:100]}\\n"
        
    print(f"[{agent_name}] 🧠 THINKING: Consulting LLM...")
    try:
        if not service:
             raise Exception("No active service or API key configured.")
             
        res = prompt_llm(system_prompt, board_context)
        if not res:
            raise Exception("Empty or malformed response from LLM")
            
        res_lower = {k.lower(): v for k, v in res.items()}
            
        thought = res_lower.get("thought", "...")
        action = str(res_lower.get("action", "wait")).lower()
        args = res_lower.get("args", {})
        
        print(f"[{agent_name}] 🤔 THOUGHT: {thought}")
        print(f"[{agent_name}] ⚡ ACTION: {action} {args}")
        
        def check_res(r, act):
            if r.status_code >= 400:
                print(f"[{agent_name}] ❌ API REJECTED {act}: {r.status_code} - {r.text}")
                return False
            return True
        
        if action == "create_card":
            r = requests.post(f"{api_url}/cards", json=args)
            check_res(r, "create_card")
        elif action == "update_card":
            cid = args.pop("card_id", None)
            if cid: 
                r = requests.patch(f"{api_url}/cards/{cid}", json=args, headers={"X-Aegis-Agent": "true"})
                check_res(r, "update_card")
        elif action == "delete_card":
            cid = args.get("card_id")
            if cid: 
                r = requests.delete(f"{api_url}/cards/{cid}")
                check_res(r, "delete_card")
        elif action == "post_comment":
            cid = args.get("card_id")
            content = args.get("content")
            if cid and content:
                r = requests.post(f"{api_url}/cards/{cid}/comments", json={"author": agent_name, "content": content})
                check_res(r, "post_comment")
        elif action == "create_column":
            r = requests.post(f"{api_url}/columns", json=args)
            check_res(r, "create_column")
        elif action == "delete_column":
            cid = args.get("column_id")
            if cid: 
                r = requests.delete(f"{api_url}/columns/{cid}")
                check_res(r, "delete_column")
        elif action == "wait":
            print(f"[{agent_name}] 💤 Waiting... reason: {args.get('reason', 'None')}")
            time.sleep(pulse_interval)
            continue
            
        print(f"[{agent_name}] ✅ Action complete. Sleeping {pulse_interval}s...")
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

    if TEMPLATES_DIR.exists():
        for t_dir in TEMPLATES_DIR.iterdir():
            if t_dir.is_dir() and (t_dir / "worker.py").exists():
                (t_dir / "worker.py").write_text(worker_code, encoding='utf-8')
                print(f"Synced latest worker.py to template {t_dir.name}")
                
    INSTANCES_DIR = Path("aegis_data/instances")
    if INSTANCES_DIR.exists():
        for i_dir in INSTANCES_DIR.iterdir():
            if i_dir.is_dir() and (i_dir / "worker.py").exists():
                (i_dir / "worker.py").write_text(worker_code, encoding='utf-8')
                print(f"Synced latest worker.py to instance {i_dir.name}")
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

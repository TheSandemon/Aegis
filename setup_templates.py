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

sys.stdout.reconfigure(encoding='utf-8')

api_url = os.environ.get("AEGIS_API_URL", "http://localhost:8080/api")
agent_name = os.environ.get("AEGIS_INSTANCE_NAME", os.environ.get("AEGIS_AGENT_ID", "Agent"))
goal = os.environ.get("AEGIS_CONFIG_GOALS", "Process tasks and help the team.")
try:
    pulse_interval = int(os.environ.get("AEGIS_CONFIG_PULSE_INTERVAL", "30"))
except ValueError:
    pulse_interval = 30

openai_key = os.environ.get("OPENAI_API_KEY", "")
anthropic_key = os.environ.get("ANTHROPIC_API_KEY", "")
gemini_key = os.environ.get("GEMINI_API_KEY", "")

def fetch_board_state():
    try:
        cards = requests.get(f"{api_url}/cards").json()
        cols = requests.get(f"{api_url}/columns").json()
        return cards, cols
    except Exception as e:
        print(f"[{agent_name}] ❌ API Error: {e}")
        return [], []

def prompt_llm(system_prompt, user_text):
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

system_prompt = f"""You are an autonomous AI agent working on a Kanban board via REST API.
Your Name: {agent_name}
Your Goal: {goal}

Available Actions:
1. create_card: {{"title": str, "description": str, "column": str, "assignee": str}}
2. update_card: {{"card_id": int, "column": str, "assignee": str, "status": str}} 
3. post_comment: {{"card_id": int, "content": str}}
4. wait: {{"reason": str}} - use this if no action is needed right now or you are blocked.

Response Format (JSON ONLY):
{{
    "thought": "Your reasoning for the next action based on the board state and your goal.",
    "action": "action_name",
    "args": {{"key": "value"}}
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
        
    board_context = f"COLUMNS: {[c['name'] for c in cols]}\\n\\nCARDS:\\n"
    for c in cards:
        board_context += f"- [#{c['id']}] {c['title']} (Col: {c['column']}) | Asg: {c.get('assignee', 'None')}\\n  Desc: {c.get('description', '')[:100]}\\n"
        
    print(f"[{agent_name}] 🧠 THINKING: Consulting LLM...")
    try:
        if not (openai_key or anthropic_key or gemini_key):
             raise Exception("No API key configured. Set OPENAI_API_KEY, ANTHROPIC_API_KEY, or GEMINI_API_KEY.")
             
        res = prompt_llm(system_prompt, board_context)
        if not res:
            raise Exception("Empty response from LLM")
            
        thought = res.get("thought", "...")
        action = res.get("action", "wait")
        args = res.get("args", {})
        
        print(f"[{agent_name}] 🤔 THOUGHT: {thought}")
        print(f"[{agent_name}] ⚡ ACTION: {action} {args}")
        
        if action == "create_card":
            requests.post(f"{api_url}/cards", json=args)
        elif action == "update_card":
            cid = args.pop("card_id", None)
            if cid: requests.patch(f"{api_url}/cards/{cid}", json=args, headers={"X-Aegis-Agent": "true"})
        elif action == "post_comment":
            cid = args.get("card_id")
            content = args.get("content")
            if cid and content:
                requests.post(f"{api_url}/cards/{cid}/comments", json={"author": agent_name, "content": content})
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

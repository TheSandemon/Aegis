import json
import os
from pathlib import Path
import sys
import logging

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
    
# Unique token used to fetch live configs
instance_id = os.environ.get("AEGIS_INSTANCE_ID", "")

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

def prompt_llm(system_prompt, user_text):
    """Call the LLM with a system prompt and user text.
    
    Returns:
        str: The LLM response text.
    """
    def parse_json(text):
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            # Try to strip markdown code blocks if the LLM hallucinated them
            if text.startswith("```json"): text = text[7:]
            elif text.startswith("```"): text = text[3:]
            if text.endswith("```"): text = text[:-3]
            try: return json.loads(text.strip())
            except Exception:
                return None

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



print(f"[{agent_name}] 🚀 BOOT: Sandboxed Autonomous Agent")
print(f"[{agent_name}] 🎯 GOAL: {goal}")

# Startup delay block
try:
    if os.environ.get("AEGIS_CONFIG_STARTUP_DELAY", "False").lower() == "true":
        print(f"[{agent_name}] ⏳ Startup delay enabled. Waiting {pulse_interval}s...")
        time.sleep(pulse_interval)
except Exception as e:
    pass

while True:
    try:
        # Fetch live configuration updates
        if instance_id:
            try:
                conf = requests.get(f"{api_url}/instances/{instance_id}/config").json().get("config", {})
                if "goals" in conf: goal = conf["goals"]
                if "pulse_interval" in conf: pulse_interval = int(conf["pulse_interval"])
            except Exception:
                pass

        print(f"\\n[{agent_name}] 📡 PULSE: Fetching board state & instructions...")
        cards = requests.get(f"{api_url}/cards").json()
        cols = requests.get(f"{api_url}/columns").json()
        raw_prompt = requests.get(f"{api_url}/system_prompt").json().get("prompt", "")
    except Exception as e:
        print(f"[{agent_name}] ❌ API Error: {e}")
        time.sleep(pulse_interval)
        continue
        
    system_prompt = raw_prompt.replace("{agent_name}", agent_name).replace("{goal}", goal)
    
    if not isinstance(cards, list) or not isinstance(cols, list) or not system_prompt:
        print(f"[{agent_name}] ❌ API Error: Invalid state format received. Waiting...")
        time.sleep(pulse_interval)
        continue
        
        # Check if agent is assigned to a specific card
        my_card_id = None
        for c in cards:
            if c.get("assignee") == agent_name and c.get("status") in ["assigned", "running"]:
                my_card_id = c["id"]
                break
                
        if my_card_id:
            print(f"\\n[{agent_name}] 🎯 FOCUS: Fetching smart context for Card #{my_card_id}...")
            ctx = requests.get(f"{api_url}/cards/{my_card_id}/context").json()
            focus = ctx.get("focus_card", {})
            related = ctx.get("related_context", [])
            directory = ctx.get("board_directory", [])
            
            board_context = f"--- FOCUS CARD ---\\n[#{focus.get('id')}] {focus.get('title')}\\n"
            board_context += f"Priority: {focus.get('priority', 'normal')} | Column: {focus.get('column')}\\n"
            board_context += f"Description: {focus.get('description', '')}\\n"
            if focus.get('comments'):
                board_context += "Comments:\\n"
                for cmt in focus.get('comments', []):
                    board_context += f"  - [{cmt.get('author')}]: {cmt.get('content')}\\n"
            
            if related:
                board_context += "\\n--- RELATED CONTEXT (From @ Tags & Dependencies) ---\\n"
                for rc in related:
                    board_context += f"[#{rc.get('id')}] {rc.get('title')} (Col: {rc.get('column')})\\n"
                    board_context += f"Description: {rc.get('description', '')[:200]}...\\n"
                    if rc.get('comments'):
                        last = rc['comments'][-1]
                        board_context += f"Last Comment: [{last.get('author')}]: {last.get('content')[:100]}...\\n"
            
            board_context += "\\n--- BOARD DIRECTORY (Other Cards) ---\\n"
            for dc in directory:
                board_context += f"- [#{dc.get('id')}] {dc.get('title')} (Col: {dc.get('column')}) | Asg: {dc.get('assignee', 'None')}\\n"
                
        else:
            # Fallback to full board if no specific assignment
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
            
        if not isinstance(res, list):
            res = [res] # Normalize single dict to list

        for action_block in res:
            res_lower = {k.lower(): v for k, v in action_block.items()}
            action = str(res_lower.get("action", "wait")).lower()
            args = res_lower.get("args", {})
            thought = res_lower.get("thought", "")
            
            if thought:
                print(f"[{agent_name}] 💡 THOUGHT: {thought}")
            
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
                    if isinstance(cid, str): cid = cid.strip("# ")
                    r = requests.patch(f"{api_url}/cards/{cid}", json=args, headers={"X-Aegis-Agent": "true"})
                    check_res(r, "update_card")
            elif action == "delete_card":
                cid = args.get("card_id")
                if cid: 
                    if isinstance(cid, str): cid = cid.strip("# ")
                    r = requests.delete(f"{api_url}/cards/{cid}")
                    check_res(r, "delete_card")
            elif action == "post_comment":
                cid = args.get("card_id")
                content = args.get("content")
                if cid and content:
                    if isinstance(cid, str): cid = cid.strip("# ")
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
            elif action == "list_dir":
                p = args.get("path", ".")
                try:
                    res = os.listdir(p)
                    print(f"[{agent_name}] 📁 LIST_DIR: {res}")
                except Exception as e:
                    print(f"[{agent_name}] ❌ LIST_DIR ERROR: {e}")
            elif action == "read_file":
                p = args.get("path")
                if p:
                    try:
                        with open(p, "r", encoding="utf-8") as rf:
                            res = rf.read()
                        print(f"[{agent_name}] 📄 READ_FILE: read {len(res)} characters")
                    except Exception as e:
                        print(f"[{agent_name}] ❌ READ_FILE ERROR: {e}")
            elif action == "write_file":
                p = args.get("path")
                c = args.get("content")
                if p and c is not None:
                    try:
                        with open(p, "w", encoding="utf-8") as wf:
                            wf.write(c)
                        print(f"[{agent_name}] 💾 WRITE_FILE: Saved {p}")
                    except Exception as e:
                        print(f"[{agent_name}] ❌ WRITE_FILE ERROR: {e}")
            elif action == "wait":
                print(f"[{agent_name}] 💤 Waiting... reason: {args.get('reason', 'None')}")
                break # Stop processing further actions if wait is called
                
        # Send pulse websocket event so UI can show countdown
        try:
            requests.post(f"{api_url}/instances/{instance_id}/pulse", json={"interval": pulse_interval})
        except Exception:
            pass
            
        print(f"[{agent_name}] ✅ Pulse complete. Sleeping {pulse_interval}s...")
        time.sleep(pulse_interval)
        
    except Exception as e:
        print(f"[{agent_name}] ❌ ERROR: {e}")
        time.sleep(pulse_interval)
'''

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
    
    # Write worker.py
    try:
        (agent_dir / "worker.py").write_text(worker_code, encoding="utf-8")
        # Write requirements.txt
        (agent_dir / "requirements.txt").write_text("requests==2.31.0\n", encoding="utf-8")
    except Exception as e:
        print(f"Warning: Could not write to template directory for {agent['id']}: {e}")

# Bulk sync latest worker.py to ALL existing templates and instances once
if TEMPLATES_DIR.exists():
    for t_dir in TEMPLATES_DIR.iterdir():
        if t_dir.is_dir() and (t_dir / "worker.py").exists():
            try:
                (t_dir / "worker.py").write_text(worker_code, encoding='utf-8')
                print(f"Synced latest worker.py to template {t_dir.name}")
            except Exception as e:
                print(f"Warning: Could not sync template {t_dir.name}: {e}")
            
INSTANCES_DIR = Path("aegis_data/instances")
if INSTANCES_DIR.exists():
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


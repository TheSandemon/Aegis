import os
import time
import requests
import sys
import json
import threading
import queue

try:
    from rich.console import Console
    from rich.prompt import Prompt
    from rich.panel import Panel
    from rich.markdown import Markdown
    from rich.syntax import Syntax
    console = Console(force_terminal=True, color_system="standard")
except ImportError:
    # Fallback if rich is not installed
    class DummyConsole:
        def print(self, *args, **kwargs): print(*args)
    class DummyPrompt:
        @classmethod
        def ask(cls, *args, **kwargs): return input(args[0] if args else "")
    console = DummyConsole()
    Prompt = DummyPrompt
    Panel = lambda x, **kw: str(x)
    Markdown = lambda x, **kw: str(x)

sys.stdout.reconfigure(encoding='utf-8')

api_url = os.environ.get("AEGIS_API_URL", "http://localhost:42069/api")
agent_name = os.environ.get("AEGIS_INSTANCE_NAME", os.environ.get("AEGIS_AGENT_ID", "Agent"))
goal = os.environ.get("AEGIS_CONFIG_GOALS", "Process tasks and help the team.")
try:
    pulse_interval = int(os.environ.get("AEGIS_CONFIG_PULSE_INTERVAL", "60"))
except ValueError:
    pulse_interval = 60

mode = os.environ.get("AEGIS_CONFIG_MODE", "continuous")  # "continuous" | "one-shot"

# Unique token used to fetch live configs
instance_id = os.environ.get("AEGIS_INSTANCE_ID", "")

# ─── Presence Reporting Helper ─────────────────────────────────────────────────
def _report_presence(card_id: int = None, activity: str = "idle"):
    """Report agent presence (card working on, activity status) for character animation."""
    if not instance_id:
        return
    try:
        requests.patch(
            f"{api_url}/agents/{instance_id}/presence",
            json={"card_id": card_id, "activity": activity},
            timeout=3
        )
    except Exception:
        pass  # Silently fail - presence is non-critical

service = os.environ.get("AEGIS_SERVICE", "")
model = os.environ.get("AEGIS_MODEL", "")

openai_key = os.environ.get("OPENAI_API_KEY", "")
anthropic_key = os.environ.get("ANTHROPIC_API_KEY", "")
google_key = os.environ.get("GOOGLE_API_KEY", os.environ.get("GEMINI_API_KEY", ""))
deepseek_key = os.environ.get("DEEPSEEK_API_KEY", "")
minimax_key = os.environ.get("MINIMAX_API_KEY", "")

if not service:
    if openai_key: service = "openai"
    elif anthropic_key: service = "anthropic"
    elif google_key: service = "google"
    elif deepseek_key: service = "deepseek"
    elif minimax_key: service = "minimax"

# Enforce minimum pulse interval from broker rate limit
try:
    _min_resp = requests.get(f"{api_url}/broker/min_pulse", timeout=5)
    _min_pulse = int(_min_resp.json().get("min_pulse_seconds", 0))
    if _min_pulse > pulse_interval:
        print(f"[{agent_name}] ⚠️ Pulse {pulse_interval}s < broker minimum {_min_pulse}s — clamping to {_min_pulse}s.")
        pulse_interval = _min_pulse
except Exception:
    pass


# ─── AEGIS TOOL DEFINITIONS (native function-calling schema) ──────────────────
AEGIS_TOOLS = [
    {
        "name": "create_card",
        "description": "Create a new card on the Kanban board.",
        "parameters": {"type": "object", "properties": {
            "title": {"type": "string"},
            "description": {"type": "string"},
            "column": {"type": "string", "description": "Must be an existing column name."},
            "assignee": {"type": "string"},
            "priority": {"type": "string", "enum": ["low", "normal", "high"]},
            "card_group": {"type": "string"},
            "card_tags": {"type": "array", "items": {"type": "string"}}
        }, "required": ["title", "column"]}
    },
    {
        "name": "update_card",
        "description": "Update an existing card (move it, change priority, assignee, description, etc.).",
        "parameters": {"type": "object", "properties": {
            "card_id": {"type": "integer"},
            "title": {"type": "string"},
            "description": {"type": "string"},
            "column": {"type": "string"},
            "assignee": {"type": "string"},
            "status": {"type": "string"},
            "priority": {"type": "string", "enum": ["low", "normal", "high"]},
            "card_group": {"type": "string"},
            "card_tags": {"type": "array", "items": {"type": "string"}}
        }, "required": ["card_id"]}
    },
    {
        "name": "delete_card",
        "description": "Delete a card from the board.",
        "parameters": {"type": "object", "properties": {
            "card_id": {"type": "integer"}
        }, "required": ["card_id"]}
    },
    {
        "name": "post_comment",
        "description": "Post a comment on a card.",
        "parameters": {"type": "object", "properties": {
            "card_id": {"type": "integer"},
            "content": {"type": "string"}
        }, "required": ["card_id", "content"]}
    },
    {
        "name": "bulk_update_cards",
        "description": "Update multiple cards at once (preferred for batch moves).",
        "parameters": {"type": "object", "properties": {
            "updates": {"type": "array", "items": {
                "type": "object", "properties": {
                    "card_id": {"type": "integer"},
                    "column": {"type": "string"},
                    "assignee": {"type": "string"},
                    "priority": {"type": "string"}
                }, "required": ["card_id"]
            }}
        }, "required": ["updates"]}
    },
    {
        "name": "bulk_delete_cards",
        "description": "Delete multiple cards at once.",
        "parameters": {"type": "object", "properties": {
            "card_ids": {"type": "array", "items": {"type": "integer"}}
        }, "required": ["card_ids"]}
    },
    {
        "name": "create_column",
        "description": "Create a new column on the board.",
        "parameters": {"type": "object", "properties": {
            "name": {"type": "string"},
            "position": {"type": "integer"}
        }, "required": ["name"]}
    },
    {
        "name": "delete_column",
        "description": "Delete a column from the board.",
        "parameters": {"type": "object", "properties": {
            "column_id": {"type": "integer"}
        }, "required": ["column_id"]}
    },
    {
        "name": "notify",
        "description": "Send a notification message bubble to the user.",
        "parameters": {"type": "object", "properties": {
            "message": {"type": "string"},
            "mood": {"type": "string", "enum": ["info", "warning", "error"]}
        }, "required": ["message"]}
    },
    {
        "name": "list_dir",
        "description": "List files and folders in a directory. Use '.' for current directory.",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string"}
        }, "required": ["path"]}
    },
    {
        "name": "read_file",
        "description": "Read the contents of a file. Returns the first 4000 characters. Use search_file for targeted lookups in large files.",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string"}
        }, "required": ["path"]}
    },
    {
        "name": "search_file",
        "description": "Search for a keyword or pattern within a file. Returns matching lines with line numbers.",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string"},
            "query": {"type": "string"}
        }, "required": ["path", "query"]}
    },
    {
        "name": "write_file",
        "description": "Write (or overwrite) a file with the given content.",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string"},
            "content": {"type": "string"}
        }, "required": ["path", "content"]}
    },
    {
        "name": "git_commit",
        "description": "Stage and commit files with a message.",
        "parameters": {"type": "object", "properties": {
            "message": {"type": "string"},
            "files": {"type": "array", "items": {"type": "string"}}
        }, "required": ["message"]}
    },
    {
        "name": "git_push",
        "description": "Push committed changes to a remote.",
        "parameters": {"type": "object", "properties": {
            "remote": {"type": "string"},
            "branch": {"type": "string"}
        }, "required": []}
    },
    {
        "name": "done",
        "description": "Signal that all work for this pulse is complete. Always call this when finished.",
        "parameters": {"type": "object", "properties": {
            "reason": {"type": "string", "description": "Summary of what was accomplished."}
        }, "required": ["reason"]}
    },
    {
        "name": "wait",
        "description": "Signal that work is blocked and the agent should sleep until the next pulse.",
        "parameters": {"type": "object", "properties": {
            "reason": {"type": "string"}
        }, "required": ["reason"]}
    },
]

def _tool_schema_openai(tools):
    """Convert tool list to OpenAI/DeepSeek function calling format."""
    return [{"type": "function", "function": {
        "name": t["name"],
        "description": t["description"],
        "parameters": t["parameters"]
    }} for t in tools]

def _tool_schema_google(tools):
    """Convert tool list to Google Gemini function declaration format."""
    def clean_schema(schema):
        """Google doesn't support 'enum' inside properties directly — embed as description."""
        if not isinstance(schema, dict):
            return schema
        out = {}
        for k, v in schema.items():
            if k == "enum":
                continue  # handled by adding to description
            out[k] = clean_schema(v)
        return out

    declarations = []
    for t in tools:
        params = t["parameters"].copy()
        declarations.append({
            "name": t["name"],
            "description": t["description"],
            "parameters": clean_schema(params)
        })
    return [{"functionDeclarations": declarations}]


def execute_tool(name, args, cards, cols, read_only_columns, my_card_column):
    """Execute an Aegis tool call and return the result string."""
    def check_r(r, label):
        if r.status_code >= 400:
            return f"❌ {label} FAILED: HTTP {r.status_code} — {r.text[:250]}"
        return f"✅ {label} OK"

    if name == "create_card":
        col = args.get("column", "")
        if col in read_only_columns:
            return f"❌ BLOCKED: '{col}' is read-only."
        r = requests.post(f"{api_url}/cards", json=args, headers={"X-Aegis-Agent": "true"})
        if r.status_code < 400:
            new_id = r.json().get("id", "?")
            return f"✅ Card #{new_id} created in '{col}'."
        return f"❌ create_card failed: {r.status_code} — {r.text[:200]}"

    elif name == "update_card":
        cid = args.get("card_id")
        target = next((c for c in cards if c.get("id") == cid), None)
        if target and target.get("column") in read_only_columns:
            return f"❌ BLOCKED: Card #{cid} is in a read-only column."
        r = requests.patch(f"{api_url}/cards/{cid}", json=args, headers={"X-Aegis-Agent": "true"})

        # Report presence when agent claims/assigns a card
        if r.status_code < 400:
            assignee = args.get("assignee")
            column = args.get("column")
            if assignee or column:
                _report_presence(card_id=cid, activity="working")

        return check_r(r, f"update_card #{cid}")

    elif name == "delete_card":
        cid = args.get("card_id")
        target = next((c for c in cards if c.get("id") == cid), None)
        if target and target.get("column") in read_only_columns:
            return f"❌ BLOCKED: Card #{cid} is in a read-only column."
        r = requests.delete(f"{api_url}/cards/{cid}", headers={"X-Aegis-Agent": "true"})
        return check_r(r, f"delete_card #{cid}")

    elif name == "post_comment":
        cid = args.get("card_id")
        r = requests.post(f"{api_url}/cards/{cid}/comments",
                          json={"author": agent_name, "content": args.get("content", "")})
        return check_r(r, f"post_comment on #{cid}")

    elif name == "bulk_update_cards":
        updates = args.get("updates", [])
        valid = [u for u in updates if not next((c for c in cards if c.get("id") == u.get("card_id") and c.get("column") in read_only_columns), None)]
        blocked = len(updates) - len(valid)
        if not valid:
            return "❌ All updates blocked (read-only)."
        r = requests.patch(f"{api_url}/cards/bulk", json={"updates": valid}, headers={"X-Aegis-Agent": "true"})
        if r.status_code < 400:
            updated = r.json().get("updated", [])
            return f"✅ Bulk updated {len(updated)} cards." + (f" ({blocked} blocked.)" if blocked else "")
        return f"❌ bulk_update_cards failed: {r.status_code}"

    elif name == "bulk_delete_cards":
        ids = args.get("card_ids", [])
        r = requests.delete(f"{api_url}/cards/bulk", json={"card_ids": ids}, headers={"X-Aegis-Agent": "true"})
        if r.status_code < 400:
            return f"✅ Bulk deleted {len(ids)} cards."
        return f"❌ bulk_delete_cards failed: {r.status_code}"

    elif name == "create_column":
        r = requests.post(f"{api_url}/columns", json=args)
        return check_r(r, "create_column")

    elif name == "delete_column":
        r = requests.delete(f"{api_url}/columns/{args.get('column_id')}")
        return check_r(r, "delete_column")

    elif name == "notify":
        msg = args.get("message", "")
        mood = args.get("mood", "info")
        prefix = {"info": "📢", "warning": "⚠️", "error": "🛑"}.get(mood, "📢")
        print(f"[{agent_name}] {prefix} NOTIFY: {msg}")
        return f"Notification sent: {msg}"

    elif name in ("list_dir", "list_files"):
        try:
            return f"DIR {args.get('path', '.')}: {os.listdir(args.get('path', '.'))}"
        except Exception as e:
            return f"❌ list_dir error: {e}"

    elif name == "read_file":
        p = args.get("path", "")
        try:
            content = open(p, "r", encoding="utf-8").read()
            out = content[:4000]
            if len(content) > 4000:
                out += f"\n... [TRUNCATED — {len(content)} chars total. Use search_file for targeted lookups.]"
            return f"FILE {p} ({len(content)} chars):\n{out}"
        except Exception as e:
            return f"❌ read_file error: {e}"

    elif name == "search_file":
        p = args.get("path", "")
        q = args.get("query", "")
        try:
            matches = [f"L{i}: {ln.rstrip()[:200]}" for i, ln in enumerate(open(p, encoding="utf-8"), 1) if q.lower() in ln.lower()]
            if matches:
                return f"SEARCH '{q}' in {p}: {len(matches)} hits\n" + "\n".join(matches[:40])
            return f"SEARCH '{q}' in {p}: no matches."
        except Exception as e:
            return f"❌ search_file error: {e}"

    elif name == "write_file":
        p = args.get("path", "")
        try:
            open(p, "w", encoding="utf-8").write(args.get("content", ""))
            return f"✅ Wrote {p}"
        except Exception as e:
            return f"❌ write_file error: {e}"

    elif name == "git_commit":
        import subprocess
        msg = args.get("message", "Automated commit")
        files = args.get("files", ["."])
        for f in (files if isinstance(files, list) else [files]):
            subprocess.run(["git", "add", f], capture_output=True)
        r = subprocess.run(["git", "commit", "-m", f"[Aegis: {agent_name}] {msg}"],
                           capture_output=True, text=True)
        return f"✅ COMMIT: {r.stdout.strip()}" if r.returncode == 0 else f"❌ git_commit: {r.stderr[:200]}"

    elif name == "git_push":
        import subprocess
        remote = args.get("remote", "origin")
        branch = args.get("branch", "")
        cmd = ["git", "push", remote] + ([branch] if branch else [])
        r = subprocess.run(cmd, capture_output=True, text=True)
        return f"✅ PUSH OK" if r.returncode == 0 else f"❌ git_push: {r.stderr[:200]}"

    elif name in ("done", "wait"):
        return f"{name.upper()}: {args.get('reason', '')}"

    return f"⚠️ Unknown tool: {name}"


def run_agentic_loop(system_prompt, board_context, cards, cols, read_only_columns,
                     my_card_column, max_steps=50):
    """
    Native tool-calling agentic loop.
    Sends system_prompt + board_context once, then enters a multi-turn
    conversation where the LLM natively calls tools until it signals done/wait.
    Returns (observations, terminal_action) where terminal_action is 'done'|'wait'|None.
    """
    if not service:
        print(f"[{agent_name}] ❌ No LLM service configured.")
        return [], None

    observations = []
    terminal_action = None
    step = 0

    # ── ANTHROPIC ────────────────────────────────────────────────────────────
    if service == "anthropic" and anthropic_key:
        m = model or "claude-sonnet-4-5"
        headers = {
            "x-api-key": anthropic_key,
            "anthropic-version": "2023-06-01",
            "anthropic-beta": "interleaved-thinking-2025-05-14",
            "content-type": "application/json"
        }
        # Convert tool schema to Anthropic format
        ant_tools = [{"name": t["name"], "description": t["description"],
                      "input_schema": t["parameters"]} for t in AEGIS_TOOLS]

        messages = [{"role": "user", "content": board_context}]

        while step < max_steps:
            payload = {
                "model": m,
                "max_tokens": 16384,
                "system": system_prompt,
                "tools": ant_tools,
                "messages": messages,
                "temperature": 1,  # Required for extended thinking
                "thinking": {
                    "type": "enabled",
                    "budget_tokens": 10000  # Gives the model room to reason before each tool call
                }
            }
            try:
                resp = requests.post("https://api.anthropic.com/v1/messages",
                                     headers=headers, json=payload, timeout=180)
                if resp.status_code != 200:
                    print(f"[{agent_name}] ❌ Anthropic API {resp.status_code}: {resp.text[:300]}")
                    break
                data = resp.json()
            except Exception as e:
                print(f"[{agent_name}] ❌ Anthropic request failed: {e}")
                break

            # Append assistant message to thread (includes thinking blocks)
            messages.append({"role": "assistant", "content": data.get("content", [])})

            # Process content blocks
            tool_results = []
            has_tool_use = False
            stop_reason = data.get("stop_reason", "")

            for block in data.get("content", []):
                if block.get("type") == "thinking" and block.get("thinking"):
                    # Extended thinking — show the model's reasoning
                    thinking_text = block["thinking"][:300]
                    print(f"[{agent_name}] 🧠 THINKING: {thinking_text}")
                elif block.get("type") == "text" and block.get("text"):
                    print(f"[{agent_name}] 💡 THOUGHT: {block['text'][:200]}")
                elif block.get("type") == "tool_use":
                    has_tool_use = True
                    tool_name = block["name"]
                    tool_args = block.get("input", {})
                    tool_id = block["id"]
                    step += 1
                    print(f"[{agent_name}] ⚡ TOOL ({step}): {tool_name} {json.dumps(tool_args)[:120]}")

                    if tool_name in ("done", "wait"):
                        terminal_action = tool_name
                        reason = tool_args.get("reason", "")
                        print(f"[{agent_name}] {'✅ DONE' if tool_name == 'done' else '💤 WAIT'}: {reason}")
                        observations.append(f"{tool_name.upper()}: {reason}")
                        tool_results.append({"type": "tool_result", "tool_use_id": tool_id,
                                             "content": f"{tool_name.upper()}: {reason}"})
                        break
                    else:
                        result = execute_tool(tool_name, tool_args, cards, cols,
                                              read_only_columns, my_card_column)
                        print(f"[{agent_name}] 📤 RESULT: {result[:150]}")
                        observations.append(f"{tool_name}: {result}")
                        tool_results.append({"type": "tool_result", "tool_use_id": tool_id,
                                             "content": result})

            if tool_results:
                messages.append({"role": "user", "content": tool_results})

            if terminal_action or not has_tool_use or stop_reason == "end_turn":
                break


        return observations, terminal_action

    # ── OPENAI / DEEPSEEK ─────────────────────────────────────────────────────
    elif service in ("openai", "deepseek"):
        key = openai_key if service == "openai" else deepseek_key
        base = "https://api.openai.com/v1" if service == "openai" else "https://api.deepseek.com"
        m = model or ("gpt-4o" if service == "openai" else "deepseek-chat")
        oai_tools = _tool_schema_openai(AEGIS_TOOLS)

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": board_context}
        ]

        while step < max_steps:
            try:
                resp = requests.post(f"{base}/chat/completions",
                    headers={"Authorization": f"Bearer {key}"},
                    json={"model": m, "tools": oai_tools, "tool_choice": "auto",
                          "messages": messages, "max_tokens": 16384},
                    timeout=120)
                if resp.status_code != 200:
                    print(f"[{agent_name}] ❌ API {resp.status_code}: {resp.text[:300]}")
                    break
                data = resp.json()
            except Exception as e:
                print(f"[{agent_name}] ❌ Request failed: {e}")
                break

            choice = data["choices"][0]
            msg = choice["message"]
            messages.append(msg)

            if msg.get("content"):
                print(f"[{agent_name}] 💡 THOUGHT: {msg['content'][:200]}")

            tool_calls = msg.get("tool_calls") or []
            if not tool_calls:
                break  # No more tool calls — LLM is done

            for tc in tool_calls:
                fn = tc["function"]
                tool_name = fn["name"]
                try:
                    tool_args = json.loads(fn.get("arguments", "{}"))
                except Exception:
                    tool_args = {}
                step += 1
                print(f"[{agent_name}] ⚡ TOOL ({step}): {tool_name} {json.dumps(tool_args)[:120]}")

                if tool_name in ("done", "wait"):
                    terminal_action = tool_name
                    reason = tool_args.get("reason", "")
                    print(f"[{agent_name}] {'✅ DONE' if tool_name == 'done' else '💤 WAIT'}: {reason}")
                    observations.append(f"{tool_name.upper()}: {reason}")
                    messages.append({"role": "tool", "tool_call_id": tc["id"],
                                     "content": f"{tool_name.upper()}: {reason}"})
                else:
                    result = execute_tool(tool_name, tool_args, cards, cols,
                                         read_only_columns, my_card_column)
                    print(f"[{agent_name}] 📤 RESULT: {result[:150]}")
                    observations.append(f"{tool_name}: {result}")
                    messages.append({"role": "tool", "tool_call_id": tc["id"], "content": result})

            if terminal_action:
                break

        return observations, terminal_action

    # ── GOOGLE GEMINI ─────────────────────────────────────────────────────────
    elif service == "google" and google_key:
        m = model or "gemini-2.0-flash"
        g_tools = _tool_schema_google(AEGIS_TOOLS)

        contents = [{"role": "user", "parts": [{"text": board_context}]}]

        while step < max_steps:
            payload = {
                "system_instruction": {"parts": [{"text": system_prompt}]},
                "contents": contents,
                "tools": g_tools,
                "generationConfig": {"maxOutputTokens": 16384}
            }
            try:
                resp = requests.post(
                    f"https://generativelanguage.googleapis.com/v1beta/models/{m}:generateContent?key={google_key}",
                    json=payload, timeout=120)
                if resp.status_code != 200:
                    print(f"[{agent_name}] ❌ Gemini API {resp.status_code}: {resp.text[:300]}")
                    break
                data = resp.json()
            except Exception as e:
                print(f"[{agent_name}] ❌ Gemini request failed: {e}")
                break

            candidate = data.get("candidates", [{}])[0]
            content = candidate.get("content", {})
            parts = content.get("parts", [])
            contents.append({"role": "model", "parts": parts})

            function_calls = [p for p in parts if "functionCall" in p]
            text_parts = [p for p in parts if "text" in p]

            for tp in text_parts:
                print(f"[{agent_name}] 💡 THOUGHT: {tp['text'][:200]}")

            if not function_calls:
                break  # Model done

            tool_responses = []
            for fc_part in function_calls:
                fc = fc_part["functionCall"]
                tool_name = fc["name"]
                tool_args = fc.get("args", {})
                step += 1
                print(f"[{agent_name}] ⚡ TOOL ({step}): {tool_name} {json.dumps(tool_args)[:120]}")

                if tool_name in ("done", "wait"):
                    terminal_action = tool_name
                    reason = tool_args.get("reason", "")
                    print(f"[{agent_name}] {'✅ DONE' if tool_name == 'done' else '💤 WAIT'}: {reason}")
                    observations.append(f"{tool_name.upper()}: {reason}")
                    tool_responses.append({"functionResponse": {"name": tool_name,
                                           "response": {"result": f"{tool_name.upper()}: {reason}"}}})
                else:
                    result = execute_tool(tool_name, tool_args, cards, cols,
                                         read_only_columns, my_card_column)
                    print(f"[{agent_name}] 📤 RESULT: {result[:150]}")
                    observations.append(f"{tool_name}: {result}")
                    tool_responses.append({"functionResponse": {"name": tool_name,
                                           "response": {"result": result}}})

            contents.append({"role": "user", "parts": tool_responses})

            if terminal_action:
                break

        return observations, terminal_action

    # ── MINIMAX (chat fallback — no native tool calling) ─────────────────────
    elif service == "minimax" and minimax_key:
        # MiniMax doesn't support native tool calling — use JSON fallback
        m = model or "MiniMax-Text-01"
        tool_docs = "\n".join(f"- {t['name']}: {t['description']}" for t in AEGIS_TOOLS)
        full_prompt = f"{system_prompt}\n\nAvailable tools:\n{tool_docs}\n\nRespond with JSON: {{\"tool\": \"name\", \"args\": {{...}}}}"
        obs = []
        for step in range(max_steps):
            resp = requests.post("https://api.minimaxi.chat/v1/chat/completions",
                headers={"Authorization": f"Bearer {minimax_key}"},
                json={"model": m, "messages": [
                    {"role": "system", "content": full_prompt},
                    {"role": "user", "content": board_context + ("\n\nPrevious: " + str(obs[-3:]) if obs else "")}
                ]})
            if resp.status_code != 200:
                print(f"[{agent_name}] ❌ MiniMax {resp.status_code}")
                break
            content = resp.json()["choices"][0]["message"]["content"]
            try:
                parsed = json.loads(content.strip().strip("```json").strip("```"))
                tool_name = parsed.get("tool", "done")
                tool_args = parsed.get("args", {})
            except Exception:
                break
            result = execute_tool(tool_name, tool_args, cards, cols, read_only_columns, my_card_column)
            obs.append(f"{tool_name}: {result}")
            if tool_name in ("done", "wait"):
                return obs, tool_name
        return obs, None

    print(f"[{agent_name}] ❌ No supported service configured.")
    return [], None






if mode != "one-shot":
    console.print(Panel(f"🎯 [bold cyan]GOAL:[/bold cyan] {goal}", title=f"🚀 {agent_name} BOOT", border_style="blue"))

# Startup delay block
try:
    if os.environ.get("AEGIS_CONFIG_STARTUP_DELAY", "False").lower() == "true":
        console.print(f"[{agent_name}] ⏳ Startup delay enabled. Waiting {pulse_interval}s...")
        time.sleep(pulse_interval)
except Exception as e:
    pass

# Setup non-blocking stdin reader for terminal chat so we can timeout on pulses
chat_queue = queue.Queue()

def stdin_reader():
    for line in sys.stdin:
        if line.strip():
            chat_queue.put(line.strip())
        else:
            chat_queue.put("") # Empty string if they just press Enter

reader_thread = threading.Thread(target=stdin_reader, daemon=True)
reader_thread.start()

# Store original root to revert context if card changes
# On startup, fetch the configured work_dir and change to it
original_cwd = os.getcwd()
if instance_id:
    try:
        _startup_conf = requests.get(f"{api_url}/instances/{instance_id}/config", timeout=5).json().get("config", {})
        _work_dir = _startup_conf.get("work_dir", "")
        if _work_dir and os.path.isdir(_work_dir):
            os.chdir(_work_dir)
            original_cwd = _work_dir
            print(f"[{agent_name}] 📂 Working directory: {_work_dir}")
    except Exception:
        pass

# Track consecutive re-pulses to prevent infinite continue loops
consecutive_repulses = 0
MAX_CONSECUTIVE_REPULSES = 2

# Module-level skill cache — fetched once per session, cached here
_skill_cache = None

while True:
    try:
        # Fetch live configuration updates
        if instance_id:
            try:
                conf = requests.get(f"{api_url}/instances/{instance_id}/config").json().get("config", {})
                if "goals" in conf: goal = conf["goals"]
                if "pulse_interval" in conf: pulse_interval = int(conf["pulse_interval"])
                if "work_dir" in conf:
                    wd = conf["work_dir"]
                    if wd and os.path.isdir(wd) and os.path.abspath(wd) != os.path.abspath(original_cwd):
                        os.chdir(wd)
                        original_cwd = wd
                # Configurable step and repulse limits
                if "max_steps" in conf:
                    try: MAX_STEPS_CFG = int(conf["max_steps"])
                    except: MAX_STEPS_CFG = 50
                else:
                    MAX_STEPS_CFG = 50
                if "max_repulse_tries" in conf:
                    try: MAX_CONSECUTIVE_REPULSES = int(conf["max_repulse_tries"])
                    except: MAX_CONSECUTIVE_REPULSES = 5
                else:
                    MAX_CONSECUTIVE_REPULSES = 5
            except Exception:
                MAX_STEPS_CFG = 50
                MAX_CONSECUTIVE_REPULSES = 5
        else:
            MAX_STEPS_CFG = 50
            MAX_CONSECUTIVE_REPULSES = 5

        print(f"\n[{agent_name}] 📡 PULSE: Fetching board state & instructions...")
        cards = requests.get(f"{api_url}/cards").json()
        cols = requests.get(f"{api_url}/columns").json()
        raw_prompt = requests.get(f"{api_url}/system_prompt").json().get("prompt", "")
    except Exception as e:
        print(f"[{agent_name}] ❌ API Error: {e}")
        time.sleep(pulse_interval)
        continue
        
    system_prompt = raw_prompt.replace("{agent_name}", agent_name).replace("{goal}", goal)

    # ─── INJECT EQUIPPED SKILLS (knowledge injection) ───
    if _skill_cache is None:
        equipped_skills = []
        try:
            if instance_id:
                conf = requests.get(f"{api_url}/instances/{instance_id}/config", timeout=5).json().get("config", {})
                equipped_skills = conf.get("skills", [])
            if not equipped_skills:
                equipped_skills = ["aegis-board-mastery"]  # Default core skill
        except Exception:
            equipped_skills = ["aegis-board-mastery"]

        skill_texts = []
        for skill_id in equipped_skills:
            try:
                skill_resp = requests.get(f"{api_url}/skills/{skill_id}/content", timeout=5)
                if skill_resp.status_code == 200:
                    skill_content = skill_resp.json().get("content", "")
                    if skill_content:
                        skill_texts.append(f"\n━━━ EQUIPPED SKILL: {skill_id} ━━━\n{skill_content}")
                        print(f"[{agent_name}] 🧩 SKILL LOADED: {skill_id}")
            except Exception as e:
                print(f"[{agent_name}] ⚠️ Failed to load skill {skill_id}: {e}")
        _skill_cache = "\n".join(skill_texts)
    
    if _skill_cache:
        system_prompt += _skill_cache

    if not isinstance(cards, list) or not isinstance(cols, list) or not system_prompt:
        print(f"[{agent_name}] ❌ API Error: Invalid state format received. Waiting...")
        time.sleep(pulse_interval)
        continue

    # Build read-only column set — agents must not write to these
    read_only_columns = set()
    github_columns = {}  # column_name -> {mode, resource_type}
    for col in cols:
        if col.get("integration_type") and col.get("integration_mode") == "read":
            read_only_columns.add(col["name"])
        if col.get("integration_type") == "github":
            # Parse integration_filters to get resource_type
            filters_str = col.get("integration_filters")
            resource_type = "issue"
            if filters_str:
                try:
                    if isinstance(filters_str, str):
                        filters = json.loads(filters_str)
                    else:
                        filters = filters_str
                    resource_type = filters.get("resource_type", "issue")
                except (json.JSONDecodeError, TypeError):
                    pass
            github_columns[col["name"]] = {
                "mode": col.get("integration_mode", "read"),
                "resource_type": resource_type
            }
    if read_only_columns:
        ro_note = (
            f"\n\n⚠️ READ-ONLY COLUMNS: {', '.join(sorted(read_only_columns))} "
            f"are synced from external services and are READ-ONLY. "
            f"Do NOT use delete_card or update_card on cards in these columns. "
            f"post_comment is still allowed."
        )
        system_prompt += ro_note

    system_prompt += "\n\n⚠️ LOCKED CARDS: If you see a card marked [LOCKED], you MUST NOT edit it, update it, or delete it under any circumstances."

    # Warn if no GitHub integration exists
    if not github_columns:
        gh_note = (
            "\n\n⚠️ GITHUB NOT AVAILABLE: No GitHub integration is configured on any column. "
            "Do not attempt GitHub operations (create_pr, merge_pr, create_branch, etc.) "
            "as they will fail."
        )
        system_prompt += gh_note
    else:
        # List available GitHub-integrated columns with their resource types
        writeable_gh = [c for c, info in github_columns.items() if info.get("mode") in ("write", "read_write")]
        pr_columns = [c for c, info in github_columns.items() if info.get("resource_type") == "pull_request"]
        issue_columns = [c for c, info in github_columns.items() if info.get("resource_type") == "issue"]

        # Build column description
        col_descriptions = []
        for col_name, info in github_columns.items():
            rt = info.get("resource_type", "issue")
            mode = info.get("mode", "read")
            col_descriptions.append(f"{col_name} ({rt}, {mode})")

        if writeable_gh:
            gh_note = (
                f"\n\n📥 GITHUB INTEGRATIONS: The following columns have GitHub integration: "
                f"{', '.join(sorted(github_columns.keys()))}. "
                f"Details: {', '.join(col_descriptions)}. "
            )
            if pr_columns:
                gh_note += f"PR columns: {', '.join(sorted(pr_columns))} support merge, approve, and branch operations. "
            if issue_columns:
                gh_note += f"Issue columns: {', '.join(sorted(issue_columns))} support issue creation and comment operations. "
            gh_note += "When using GitHub tools, specify the column via the 'column' parameter to use the correct integration."
        else:
            gh_note = (
                f"\n\n⚠️ GITHUB READ-ONLY: GitHub integrations exist but are read-only: "
                f"{', '.join(sorted(github_columns.keys()))}. "
                f"GitHub write operations (create_pr, merge_pr, create_branch) will be blocked."
            )
        system_prompt += gh_note

    # Check if agent is assigned to a specific card
    my_card_id = None
    my_card_column = None
    for c in cards:
        if c.get("assignee") == agent_name and c.get("status") in ["assigned", "running"]:
            my_card_id = c["id"]
            my_card_column = c.get("column")
    target_dir = original_cwd
    if my_card_id:
        for col in cols:
            if col.get("name") == my_card_column and col.get("integration_type") == "local_folder":
                creds = col.get("integration_credentials", {})
                if isinstance(creds, str):
                    try: creds = json.loads(creds)
                    except: pass
                local_path = creds.get("local_path")
                if local_path and os.path.exists(local_path):
                    import pathlib
                    target_dir = str(pathlib.Path(local_path).resolve())
                break
                
    if os.getcwd() != target_dir:
        try:
            os.chdir(target_dir)
            if target_dir != original_cwd:
                print(f"[{agent_name}] 📂 Switched working directory to: {target_dir}")
        except Exception as e:
            print(f"[{agent_name}] ⚠️ Failed to switch working directory to {target_dir}: {e}")

    if my_card_id:
        print(f"\n[{agent_name}] 🎯 FOCUS: Fetching smart context for Card #{my_card_id}...")
        ctx = requests.get(f"{api_url}/cards/{my_card_id}/context").json()
        focus = ctx.get("focus_card", {})
        related = ctx.get("related_context", [])
        directory = ctx.get("board_directory", [])
        
        board_context = f"--- FOCUS CARD ---\n[#{focus.get('id')}] {focus.get('title')}\n"
        board_context += f"Priority: {focus.get('priority', 'normal')} | Column: {focus.get('column')}\n"
        
        # Inject Column Guardrails & Context
        for col in cols:
            if col.get("name") == focus.get("column"):
                if col.get("function"): board_context += f"Column Function (Your objective here): {col.get('function')}\n"
                if col.get("exit_pass"): board_context += f"Exit Condition [Pass] (When done): {col.get('exit_pass')}\n"
                if col.get("exit_fail"): board_context += f"Exit Condition [Fail] (If errors): {col.get('exit_fail')}\n"
                break
        
        # Surface structured external metadata (GitHub labels, assignees, etc.)
        meta = focus.get("metadata") or {}
        if meta.get("source"):
            src_line = f"[Source: {meta['source'].upper()}"
            # Show resource_type (issue vs pull_request)
            if meta.get("resource_type"):
                src_line += f" | Type: {meta['resource_type'].replace('_', ' ').title()}"
            if meta.get("github_number"):
                src_line += f" #{meta['github_number']}"
            if meta.get("action_required"):
                src_line += " | ACTION REQUIRED"
            src_line += f" | State: {meta.get('state', 'open')}]"
            board_context += src_line + "\n"

            # Show PR-specific metadata
            if meta.get("resource_type") == "pull_request":
                if meta.get("head_branch") and meta.get("base_branch"):
                    board_context += f"PR: {meta['head_branch']} → {meta['base_branch']}\n"
                if meta.get("draft"):
                    board_context += "PR: DRAFT\n"
                if meta.get("mergeable"):
                    board_context += "PR: MERGEABLE\n"

            if meta.get("labels"):
                board_context += f"Labels: {', '.join(meta['labels'])}\n"
            if meta.get("assignees"):
                board_context += f"Assignees: {', '.join(meta['assignees'])}\n"
            if meta.get("milestone"):
                board_context += f"Milestone: {meta['milestone']}\n"
            if meta.get("external_url"):
                board_context += f"External: {meta['external_url']}\n"
        board_context += f"Description: {focus.get('description', '')}\n"
        if focus.get('comments'):
            board_context += "Comments:\n"
            for cmt in focus.get('comments', []):
                board_context += f"  - [{cmt.get('author')}]: {cmt.get('content')}\n"
        
        if related:
            board_context += "\n--- RELATED CONTEXT (From @ Tags & Dependencies) ---\n"
            for rc in related:
                board_context += f"[#{rc.get('id')}] {rc.get('title')} (Col: {rc.get('column')})\n"
                board_context += f"Description: {rc.get('description', '')[:200]}...\n"
                if rc.get('comments'):
                    last = rc['comments'][-1]
                    board_context += f"Last Comment: [{last.get('author')}]: {last.get('content')[:100]}...\n"
        
        board_context += "\n--- BOARD DIRECTORY (Other Cards) ---\n"
        for dc in directory:
            board_context += f"- [#{dc.get('id')}] {dc.get('title')} (Col: {dc.get('column')}) | Asg: {dc.get('assignee', 'None')}\n"
            
    else:
        # Fallback to full board if no specific assignment
        col_summary = ", ".join([f"{c['name']} (id:{c['id']})" for c in cols])
        board_context = f"COLUMNS: {col_summary}\n\nCARDS:\n"
        for c in cards:
            comments = c.get("comments", [])
            last_comment = f" | Last Comment: {comments[-1]['content'][:60]}" if comments else ""
            locked_tag = " [LOCKED]" if c.get("is_locked") else ""
            board_context += (
                f"- [#{c['id']}]{locked_tag} {c['title']} | Col: {c['column']} | "
                f"Asg: {c.get('assignee', 'None')} | Priority: {c.get('priority', 'normal')}"
                f"{last_comment}\n  Desc: {c.get('description', '')[:120]}\n"
            )

    # ─── INJECT WORKING DIRECTORY INFO ───
    board_context += f"\n\n--- WORKSPACE ---\nWorking Directory: {os.getcwd()}\n(File tools like read_file, list_dir, search_file operate relative to this path.)\n"

    # ─── INJECT SCRATCHPAD MEMORY ───
    if os.path.exists("scratchpad.md"):
        try:
            with open("scratchpad.md", "r", encoding="utf-8") as rf:
                scratchpad_content = rf.read()
            if scratchpad_content.strip():
                board_context += f"\n\n--- SCRATCHPAD (Working Memory) ---\n{scratchpad_content}\n"
        except Exception:
            pass

    # ─── INJECT TERMINAL CHAT MESSAGES ───
    chat_messages = []
    while not chat_queue.empty():
        try:
            chat_messages.append(chat_queue.get_nowait())
        except queue.Empty:
            break
            
    if chat_messages:
        board_context += "\n\n--- NEW TERMINAL CHAT MESSAGES FROM USER ---\n"
        for msg in chat_messages:
            board_context += f"- {msg}\n"
        board_context += (
            "IMPORTANT INSTRUCTION: You have received a direct chat message from the user. "
            "For this current pulse, your ONLY objective is to respond to the user or execute "
            "the specific command they just requested. DO NOT proactively work on your general "
            "goal, pick up new cards, or assign yourself to things unless the user explicitly "
            "asked you to do so in the chat. Use the `notify` action to reply directly to the user.\n"
        )

    print(f"[{agent_name}] 🧠 THINKING: Consulting LLM (native tool-calling)...")

    # Report presence: agent is thinking/working
    _report_presence(activity="thinking")

    # ─── NATIVE TOOL-CALLING AGENTIC LOOP ───
    # Board state + system prompt sent once. LLM natively calls tools in a
    # multi-turn conversation thread until it signals done() or wait().
    observations, terminal_action = run_agentic_loop(
        system_prompt=system_prompt,
        board_context=board_context,
        cards=cards,
        cols=cols,
        read_only_columns=read_only_columns,
        my_card_column=my_card_column,
        max_steps=MAX_STEPS_CFG,
    )



    # ─── AUTO-SAVE SCRATCHPAD (Persistent Memory) ───
    if observations:
        try:
            scratchpad = ""
            if os.path.exists("scratchpad.md"):
                with open("scratchpad.md", "r", encoding="utf-8") as rf:
                    scratchpad = rf.read()
            # Append a timestamped session block
            import datetime
            session_block = f"\n\n## Pulse @ {datetime.datetime.now().isoformat()}\n"
            for i, obs in enumerate(observations):
                session_block += f"- Step {i+1}: {obs}\n"
            # Keep scratchpad from growing unbounded (last 5000 chars)
            scratchpad = (scratchpad + session_block)[-5000:]
            with open("scratchpad.md", "w", encoding="utf-8") as wf:
                wf.write(scratchpad)
        except Exception as e:
            print(f"[{agent_name}] ⚠️ Failed to save scratchpad: {e}")

    # ─── SELF-EVALUATION: Should I keep working or sleep? ───
    if observations and not any("DONE:" in o or "WAITING:" in o for o in observations):
        # Hard cap: prevent infinite re-pulse loops
        if consecutive_repulses >= MAX_CONSECUTIVE_REPULSES:
            print(f"[{agent_name}] 🛑 Self-eval: Hit max consecutive re-pulses ({MAX_CONSECUTIVE_REPULSES}). Forcing sleep.")
            consecutive_repulses = 0
        else:
            try:
                # Build a concise summary of what was just done
                actions_taken = "\n".join(f"- {o}" for o in observations[-8:])
                # Re-fetch a quick card count so the eval knows the current state
                try:
                    current_cards = requests.get(f"{api_url}/cards").json()
                    card_count = len(current_cards) if isinstance(current_cards, list) else "unknown"
                except Exception:
                    card_count = "unknown"

                eval_prompt = (
                    f"You are evaluating whether an AI worker should CONTINUE working or SLEEP.\n\n"
                    f"WORKER GOAL: {goal}\n\n"
                    f"ACTIONS JUST COMPLETED THIS PULSE:\n{actions_taken}\n\n"
                    f"CURRENT BOARD STATE: {card_count} cards exist on the board.\n\n"
                    f"RULES — You must respond SLEEP unless ALL of these are true:\n"
                    f"1. There are SPECIFIC, CONCRETE tasks remaining that were NOT already done above.\n"
                    f"2. The actions above did NOT already fulfill the worker's goal.\n"
                    f"3. There are cards with status 'assigned' or 'running' that still need work.\n\n"
                    f"If the worker just created cards, organized the board, or completed its instructions, it is DONE. Respond SLEEP.\n"
                    f"DO NOT say continue just because the goal sounds ongoing (e.g., 'help the team'). "
                    f"Only continue if there is an explicit, unfinished action item.\n\n"
                    f'Respond with ONLY one of: {{"action": "continue", "reason": "..."}} or {{"action": "sleep", "reason": "..."}}'
                )
                eval_res = prompt_llm("You are a strict work evaluator. Default to sleep. Respond in JSON only.", eval_prompt)
                if eval_res and isinstance(eval_res, dict) and eval_res.get("action") == "continue":
                    consecutive_repulses += 1
                    print(f"[{agent_name}] 🔄 Self-eval: MORE WORK — {eval_res.get('reason', '')} (re-pulse {consecutive_repulses}/{MAX_CONSECUTIVE_REPULSES})")
                    # ─── FLUSH CONTEXT TO SCRATCHPAD BEFORE RE-PULSE ───
                    # Observations reset when we loop back to the top — save them now so the
                    # next pulse picks them up via scratchpad injection and doesn't start over.
                    try:
                        import datetime
                        scratchpad = ""
                        if os.path.exists("scratchpad.md"):
                            with open("scratchpad.md", "r", encoding="utf-8") as rf:
                                scratchpad = rf.read()
                        carry_block = f"\n\n## CONTINUING WORK @ {datetime.datetime.now().isoformat()}\n"
                        carry_block += f"**Reason:** {eval_res.get('reason', '')}\n"
                        carry_block += f"### What I already did this session:\n"
                        for i, obs in enumerate(observations):
                            carry_block += f"- {obs[:200]}\n"
                        carry_block += f"\n⚠️ Do NOT redo the above. Continue from where I left off.\n"
                        scratchpad = (scratchpad + carry_block)[-8000:]
                        with open("scratchpad.md", "w", encoding="utf-8") as wf:
                            wf.write(scratchpad)
                        print(f"[{agent_name}] 💾 Flushed {len(observations)} observations to scratchpad for next pulse.")
                    except Exception as se:
                        print(f"[{agent_name}] ⚠️ Failed to flush context: {se}")
                    continue  # Skip the sleep and loop back to the top
                else:
                    reason = eval_res.get("reason", "No pending work") if eval_res else "Eval failed"
                    print(f"[{agent_name}] 😴 Self-eval: SLEEP — {reason}")
                    consecutive_repulses = 0
            except Exception:
                consecutive_repulses = 0
    else:
        consecutive_repulses = 0

    # Report presence: agent is idle/sleeping
    _report_presence(activity="idle")

    # Send pulse websocket event so UI can show countdown
    clean_id = (instance_id or "").strip()
    if clean_id:
        try:
            requests.post(f"{api_url}/instances/{clean_id}/pulse", json={"interval": pulse_interval})
        except Exception:
            pass

    console.print(f"\n[bold green][{agent_name}] ✅ Pulse complete.[/bold green]")
    
    if mode == "one-shot":
        console.print(f"[{agent_name}] 🏁 One-shot mode: task complete. Exiting.")
        break
        
    # Interactive TUI: Yield control to user instead of sleeping
    console.print(f"[bold cyan]{agent_name}[/bold cyan] (Type a command and hit Enter, or hit Enter to pulse early)")
    try:
        user_input = chat_queue.get(timeout=pulse_interval)
        if user_input and user_input.strip():
            chat_queue.put(user_input.strip())
    except queue.Empty:
        pass
    except (KeyboardInterrupt, EOFError):
        console.print(f"\n[{agent_name}] 🛑 Interrupted by user. Exiting.")
        break

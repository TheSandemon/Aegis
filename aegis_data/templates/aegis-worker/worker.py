import os
import time
import requests
import sys
import json

sys.stdout.reconfigure(encoding='utf-8')

api_url = os.environ.get("AEGIS_API_URL", "http://localhost:8080/api")
agent_name = os.environ.get("AEGIS_INSTANCE_NAME", os.environ.get("AEGIS_AGENT_ID", "Agent"))
goal = os.environ.get("AEGIS_CONFIG_GOALS", "Process tasks and help the team.")
try:
    pulse_interval = int(os.environ.get("AEGIS_CONFIG_PULSE_INTERVAL", "60"))
except ValueError:
    pulse_interval = 60

mode = os.environ.get("AEGIS_CONFIG_MODE", "continuous")  # "continuous" | "one-shot"

# Unique token used to fetch live configs
instance_id = os.environ.get("AEGIS_INSTANCE_ID", "")

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

def prompt_llm(system_prompt, user_text):
    """Call the LLM with a system prompt and user text.
    
    Returns:
        dict or list: The parsed JSON response from the LLM.
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
        try:
            res = requests.post(f"https://generativelanguage.googleapis.com/v1beta/models/{m}:generateContent?key={google_key}", 
                json={"system_instruction": {"parts": [{"text": system_prompt}]}, "contents": [{"parts":[{"text": user_text}]}], "generationConfig": {"responseMimeType": "application/json"}})
            
            if res.status_code != 200:
                print(f"[{agent_name}] Google API Error {res.status_code}: {res.text[:200]}")
                return None
                
            data = res.json()
            if "candidates" not in data:
                print(f"[{agent_name}] Google API response missing 'candidates': {json.dumps(data)[:200]}")
                return None
                
            content = data["candidates"][0]["content"]["parts"][0]["text"]
            return parse_json(content)
        except Exception as e:
            print(f"[{agent_name}] Google API Request Failed: {e}")
            return None
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
    elif service == "minimax" and minimax_key:
        m = model or "MiniMax-Text-01"
        res = requests.post(
            "https://api.minimaxi.chat/v1/chat/completions",
            headers={"Authorization": f"Bearer {minimax_key}", "Content-Type": "application/json"},
            json={"model": m, "messages": [{"role": "system", "content": system_prompt}, {"role": "user", "content": f"Please output ONLY raw JSON. {user_text}"}]}
        )
        if res.status_code != 200:
            print(f"[{agent_name}] MiniMax API Error {res.status_code}: {res.text[:200]}")
            return None
        content = res.json()["choices"][0]["message"]["content"]
        return parse_json(content)

    print(f"[{agent_name}] ERROR: Unsupported service '{service}' or missing API key.")
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

        print(f"\n[{agent_name}] 📡 PULSE: Fetching board state & instructions...")
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

    # Build read-only column set — agents must not write to these
    read_only_columns = set()
    github_columns = {}  # column_name -> mode (write, read_write, read)
    for col in cols:
        if col.get("integration_type") and col.get("integration_mode") == "read":
            read_only_columns.add(col["name"])
        if col.get("integration_type") == "github":
            github_columns[col["name"]] = col.get("integration_mode", "read")
    if read_only_columns:
        ro_note = (
            f"\n\n⚠️ READ-ONLY COLUMNS: {', '.join(sorted(read_only_columns))} "
            f"are synced from external services and are READ-ONLY. "
            f"Do NOT use delete_card or update_card on cards in these columns. "
            f"post_comment is still allowed."
        )
        system_prompt += ro_note

    # Warn if no GitHub integration exists
    if not github_columns:
        gh_note = (
            "\n\n⚠️ GITHUB NOT AVAILABLE: No GitHub integration is configured on any column. "
            "Do not attempt GitHub operations (create_pr, merge_pr, create_branch, etc.) "
            "as they will fail."
        )
        system_prompt += gh_note
    else:
        # List available GitHub-integrated columns
        writeable_gh = [c for c, m in github_columns.items() if m in ("write", "read_write")]
        if writeable_gh:
            gh_note = (
                f"\n\n📥 GITHUB INTEGRATIONS: The following columns have GitHub integration: "
                f"{', '.join(sorted(github_columns.keys()))}. "
                f"Write-enabled columns: {', '.join(sorted(writeable_gh))}. "
                f"When using GitHub tools, specify the column via the 'column' parameter to use the correct integration."
            )
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
            break

    if my_card_id:
        print(f"\n[{agent_name}] 🎯 FOCUS: Fetching smart context for Card #{my_card_id}...")
        ctx = requests.get(f"{api_url}/cards/{my_card_id}/context").json()
        focus = ctx.get("focus_card", {})
        related = ctx.get("related_context", [])
        directory = ctx.get("board_directory", [])
        
        board_context = f"--- FOCUS CARD ---\n[#{focus.get('id')}] {focus.get('title')}\n"
        board_context += f"Priority: {focus.get('priority', 'normal')} | Column: {focus.get('column')}\n"
        # Surface structured external metadata (GitHub labels, assignees, etc.)
        meta = focus.get("metadata") or {}
        if meta.get("source"):
            src_line = f"[Source: {meta['source'].upper()}"
            if meta.get("github_number"):
                src_line += f" #{meta['github_number']}"
            if meta.get("action_required"):
                src_line += " | ACTION REQUIRED"
            src_line += f" | State: {meta.get('state', 'open')}]"
            board_context += src_line + "\n"
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
            board_context += (
                f"- [#{c['id']}] {c['title']} | Col: {c['column']} | "
                f"Asg: {c.get('assignee', 'None')} | Priority: {c.get('priority', 'normal')}"
                f"{last_comment}\n  Desc: {c.get('description', '')[:120]}\n"
            )

    print(f"[{agent_name}] 🧠 THINKING: Consulting LLM...")

    # Internal ReAct Loop (Max 20 steps per pulse — agents exit early via done/wait)
    observations = []
    MAX_STEPS = 20

    for step in range(MAX_STEPS):
        try:
            if not service:
                 raise Exception("No active service or API key configured.")

            # Build the cumulative context for this pulse
            current_context = board_context
            if observations:
                current_context += "\n\n--- OBSERVATIONS FROM PREVIOUS STEPS ---\n"
                for i, obs in enumerate(observations):
                    current_context += f"Step {i+1}: {obs}\n"
            
            res = prompt_llm(system_prompt, current_context)
            if not res:
                raise Exception("Empty or malformed response from LLM")
                
            if not isinstance(res, list):
                res = [res] # Normalize single dict to list

            step_observations = []
            should_break = False

            for action_block in res:
                res_lower = {k.lower(): v for k, v in action_block.items()}
                action = str(res_lower.get("action", "wait")).lower()
                args = res_lower.get("args", {})
                thought = res_lower.get("thought", "")
                
                if thought:
                    print(f"[{agent_name}] 💡 THOUGHT: {thought}")
                
                print(f"[{agent_name}] ⚡ ACTION (Step {step+1}): {action} {args}")
                
                def check_res(r, act):
                    if r.status_code >= 400:
                        msg = f"❌ API REJECTED {act}: {r.status_code} - {r.text[:200]}"
                        print(f"[{agent_name}] {msg}")
                        return msg
                    return f"✅ SUCCESS: {act}"

                obs = ""
                if action == "create_card":
                    # Validate column exists
                    col_name = args.get("column", "")
                    valid_cols = [c["name"] for c in cols]
                    if col_name and col_name not in valid_cols:
                        obs = f"❌ INVALID COLUMN '{col_name}'. Valid columns: {valid_cols}"
                        print(f"[{agent_name}] {obs}")
                    else:
                        r = requests.post(f"{api_url}/cards", json=args)
                        obs = check_res(r, "create_card")
                        if r.status_code < 400:
                            try: obs += f" (Card #{r.json().get('id')})"
                            except: pass
                elif action == "update_card":
                    cid = args.pop("card_id", None)
                    if not cid:
                        obs = "❌ update_card requires card_id"
                    else:
                        if isinstance(cid, str): cid = cid.strip("# ")
                        # Pre-flight: block writes to read-only columns
                        target = next((c for c in cards if c.get("id") == int(cid)), None)
                        if target and target.get("column") in read_only_columns:
                            obs = f"❌ BLOCKED: Card #{cid} is in read-only column '{target['column']}'"
                            print(f"[{agent_name}] {obs}")
                        else:
                            r = requests.patch(f"{api_url}/cards/{cid}", json=args, headers={"X-Aegis-Agent": "true"})
                            obs = check_res(r, "update_card")
                elif action == "delete_card":
                    cid = args.get("card_id")
                    if not cid:
                        obs = "❌ delete_card requires card_id"
                    else:
                        if isinstance(cid, str): cid = cid.strip("# ")
                        # Pre-flight: block deletes on read-only columns
                        target = next((c for c in cards if c.get("id") == int(cid)), None)
                        if target and target.get("column") in read_only_columns:
                            obs = f"❌ BLOCKED: Card #{cid} is in read-only column '{target['column']}'"
                            print(f"[{agent_name}] {obs}")
                        else:
                            r = requests.delete(f"{api_url}/cards/{cid}", headers={"X-Aegis-Agent": "true"})
                            obs = check_res(r, "delete_card")
                elif action == "post_comment":
                    cid = args.get("card_id")
                    content = args.get("content")
                    if cid and content:
                        if isinstance(cid, str): cid = cid.strip("# ")
                        r = requests.post(f"{api_url}/cards/{cid}/comments", json={"author": agent_name, "content": content})
                        obs = check_res(r, "post_comment")
                elif action == "create_column":
                    r = requests.post(f"{api_url}/columns", json=args)
                    obs = check_res(r, "create_column")
                elif action == "delete_column":
                    cid = args.get("column_id")
                    if cid: 
                        r = requests.delete(f"{api_url}/columns/{cid}")
                        obs = check_res(r, "delete_column")
                elif action == "list_dir":
                    p = args.get("path", ".")
                    try:
                        dir_res = os.listdir(p)
                        obs = f"FILE LIST: {dir_res}"
                        print(f"[{agent_name}] 📁 LIST_DIR: {dir_res}")
                    except Exception as e:
                        obs = f"❌ LIST_DIR ERROR: {e}"
                        print(f"[{agent_name}] {obs}")
                elif action == "read_file":
                    p = args.get("path")
                    if p:
                        try:
                            with open(p, "r", encoding="utf-8") as rf:
                                file_content = rf.read()
                            obs = f"READ {p}: {file_content[:500]}..."
                            print(f"[{agent_name}] 📄 READ_FILE: read {len(file_content)} characters")
                        except Exception as e:
                            obs = f"❌ READ_FILE ERROR: {e}"
                            print(f"[{agent_name}] {obs}")
                elif action == "write_file":
                    p = args.get("path")
                    c = args.get("content")
                    if p and c is not None:
                        try:
                            with open(p, "w", encoding="utf-8") as wf:
                                wf.write(c)
                            obs = f"✅ SAVED FILE: {p}"
                            print(f"[{agent_name}] 💾 WRITE_FILE: Saved {p}")
                        except Exception as e:
                            obs = f"❌ WRITE_FILE ERROR: {e}"
                            print(f"[{agent_name}] {obs}")

                # --- GitHub API Tools (via Aegis proxy) ---
                # ─── Git CLI Tools ────────────────────────────────────────────
                elif action == "git_clone":
                    repo_url = args.get("repo_url", "")
                    dest = args.get("dest", "repo")
                    try:
                        import subprocess
                        result = subprocess.run(
                            ["git", "clone", "--depth", "1", repo_url, dest],
                            capture_output=True, text=True, timeout=120
                        )
                        if result.returncode == 0:
                            obs = f"✅ CLONED {repo_url} → {dest}"
                            print(f"[{agent_name}] 📥 GIT_CLONE: {obs}")
                        else:
                            obs = f"❌ GIT_CLONE ERROR: {result.stderr[:300]}"
                            print(f"[{agent_name}] {obs}")
                    except Exception as e:
                        obs = f"❌ GIT_CLONE ERROR: {e}"
                        print(f"[{agent_name}] {obs}")

                elif action == "git_branch":
                    branch_name = args.get("branch_name", "")
                    checkout = args.get("checkout", True)
                    cwd = args.get("cwd", ".")
                    try:
                        import subprocess
                        cmd = ["git", "checkout", "-b", branch_name] if checkout else ["git", "branch", branch_name]
                        result = subprocess.run(cmd, capture_output=True, text=True, cwd=cwd, timeout=30)
                        if result.returncode == 0:
                            obs = f"✅ BRANCH CREATED: {branch_name}"
                            print(f"[{agent_name}] 🌿 GIT_BRANCH: {obs}")
                        else:
                            obs = f"❌ GIT_BRANCH ERROR: {result.stderr[:300]}"
                            print(f"[{agent_name}] {obs}")
                    except Exception as e:
                        obs = f"❌ GIT_BRANCH ERROR: {e}"
                        print(f"[{agent_name}] {obs}")

                elif action == "git_commit":
                    message = args.get("message", "Automated commit")
                    files = args.get("files", ["."])
                    cwd = args.get("cwd", ".")
                    try:
                        import subprocess
                        # Stage files
                        for f in (files if isinstance(files, list) else [files]):
                            subprocess.run(["git", "add", f], cwd=cwd, capture_output=True, timeout=15)
                        # Commit with agent attribution
                        commit_msg = f"[Aegis: {agent_name}] {message}"
                        result = subprocess.run(
                            ["git", "commit", "-m", commit_msg],
                            capture_output=True, text=True, cwd=cwd, timeout=30
                        )
                        if result.returncode == 0:
                            obs = f"✅ COMMITTED: {commit_msg}"
                            print(f"[{agent_name}] 📝 GIT_COMMIT: {obs}")
                        else:
                            obs = f"❌ GIT_COMMIT ERROR: {result.stderr[:300]}"
                            print(f"[{agent_name}] {obs}")
                    except Exception as e:
                        obs = f"❌ GIT_COMMIT ERROR: {e}"
                        print(f"[{agent_name}] {obs}")

                elif action == "git_push":
                    remote = args.get("remote", "origin")
                    branch = args.get("branch", "")
                    cwd = args.get("cwd", ".")
                    try:
                        import subprocess
                        cmd = ["git", "push", remote]
                        if branch:
                            cmd.append(branch)
                        result = subprocess.run(cmd, capture_output=True, text=True, cwd=cwd, timeout=60)
                        if result.returncode == 0:
                            obs = f"✅ PUSHED to {remote}/{branch or 'HEAD'}"
                            print(f"[{agent_name}] 🚀 GIT_PUSH: {obs}")
                        else:
                            obs = f"❌ GIT_PUSH ERROR: {result.stderr[:300]}"
                            print(f"[{agent_name}] {obs}")
                    except Exception as e:
                        obs = f"❌ GIT_PUSH ERROR: {e}"
                        print(f"[{agent_name}] {obs}")

                # ─── GitHub API Tools (via Aegis proxy) ───────────────────────
                elif action == "create_pr":
                    title = args.get("title", "")
                    body = args.get("body", "")
                    head = args.get("head", "")
                    base = args.get("base", "main")
                    gh_column = args.get("column", my_card_column)
                    gh_column = args.get("column", my_card_column)  # Use agent's card column if not specified
                    try:
                        r = requests.post(f"{api_url}/github/pulls",
                            headers={"X-Aegis-Agent": "true"},
                            json={"title": title, "body": body, "head": head, "base": base, "column": gh_column})
                        if r.status_code < 400:
                            data = r.json()
                            obs = f"✅ PR CREATED: #{data.get('pr_number')} — {data.get('url', '')}"
                            print(f"[{agent_name}] 🔀 CREATE_PR: {obs}")
                        else:
                            obs = f"❌ CREATE_PR ERROR: {r.text[:300]}"
                            print(f"[{agent_name}] {obs}")
                    except Exception as e:
                        obs = f"❌ CREATE_PR ERROR: {e}"
                        print(f"[{agent_name}] {obs}")

                elif action == "merge_pr":
                    pr_number = args.get("pr_number")
                    merge_method = args.get("merge_method", "squash")
                    commit_message = args.get("commit_message", "")
                    try:
                        r = requests.post(f"{api_url}/github/pulls/merge",
                            headers={"X-Aegis-Agent": "true"},
                            json={"pr_number": pr_number, "merge_method": merge_method, "commit_message": commit_message})
                        if r.status_code < 400:
                            obs = f"✅ PR #{pr_number} MERGED ({merge_method})"
                            print(f"[{agent_name}] ✅ MERGE_PR: {obs}")
                        else:
                            obs = f"❌ MERGE_PR ERROR: {r.text[:300]}"
                            print(f"[{agent_name}] {obs}")
                    except Exception as e:
                        obs = f"❌ MERGE_PR ERROR: {e}"
                        print(f"[{agent_name}] {obs}")

                elif action == "list_prs":
                    state = args.get("state", "open")
                    gh_column = args.get("column", my_card_column)
                    try:
                        r = requests.get(f"{api_url}/github/pulls", params={"state": state, "column": gh_column})
                        prs = r.json() if r.status_code < 400 else []
                        obs = f"PULL REQUESTS ({state}): " + json.dumps(prs[:10], indent=2)
                        print(f"[{agent_name}] 📋 LIST_PRS: {len(prs)} PRs found")
                    except Exception as e:
                        obs = f"❌ LIST_PRS ERROR: {e}"
                        print(f"[{agent_name}] {obs}")

                elif action == "list_branches":
                    gh_column = args.get("column", my_card_column)
                    try:
                        r = requests.get(f"{api_url}/github/branches", params={"column": gh_column})
                        branches = r.json() if r.status_code < 400 else []
                        obs = f"BRANCHES: " + json.dumps(branches[:20], indent=2)
                        print(f"[{agent_name}] 🌿 LIST_BRANCHES: {len(branches)} branches found")
                    except Exception as e:
                        obs = f"❌ LIST_BRANCHES ERROR: {e}"
                        print(f"[{agent_name}] {obs}")

                elif action == "create_branch_remote":
                    branch_name = args.get("branch_name", "")
                    base = args.get("base", "main")
                    gh_column = args.get("column", my_card_column)
                    try:
                        r = requests.post(f"{api_url}/github/branches",
                            headers={"X-Aegis-Agent": "true"},
                            json={"branch_name": branch_name, "base": base, "column": gh_column})
                        if r.status_code < 400:
                            obs = f"✅ REMOTE BRANCH CREATED: {branch_name} (from {base})"
                            print(f"[{agent_name}] 🌿 CREATE_BRANCH_REMOTE: {obs}")
                        else:
                            obs = f"❌ CREATE_BRANCH_REMOTE ERROR: {r.text[:300]}"
                            print(f"[{agent_name}] {obs}")
                    except Exception as e:
                        obs = f"❌ CREATE_BRANCH_REMOTE ERROR: {e}"
                        print(f"[{agent_name}] {obs}")

                elif action == "done":
                    reason = args.get('reason', 'Task complete')
                    print(f"[{agent_name}] ✅ DONE: {reason}")
                    obs = f"DONE: {reason}"
                    should_break = True
                elif action == "wait":
                    reason = args.get('reason', 'None')
                    print(f"[{agent_name}] 💤 WAIT: {reason}")
                    obs = f"WAITING: {reason}"
                    should_break = True
                elif action == "notify":
                    msg = args.get("message", "")
                    mood = args.get("mood", "info")
                    prefix = {"info": "📢", "warning": "⚠️", "error": "🛑"}.get(mood, "📢")
                    print(f"[{agent_name}] {prefix} NOTIFY: {msg}")
                    obs = f"NOTIFIED: {msg}"

                if obs:
                    step_observations.append(obs)

            if should_break:
                break

            observations.extend(step_observations)

            # Small delay between ReAct steps to be nice to the API
            if step < MAX_STEPS - 1:
                time.sleep(1)

        except Exception as e:
            print(f"[{agent_name}] ❌ ERROR (Step {step+1}): {e}")
            break

    # Send pulse websocket event so UI can show countdown
    clean_id = (instance_id or "").strip()
    if clean_id:
        try:
            requests.post(f"{api_url}/instances/{clean_id}/pulse", json={"interval": pulse_interval})
        except Exception:
            pass
        
    print(f"[{agent_name}] ✅ Pulse complete. Sleeping {pulse_interval}s...")
    time.sleep(pulse_interval)

    if mode == "one-shot":
        print(f"[{agent_name}] 🏁 One-shot mode: task complete. Exiting.")
        break

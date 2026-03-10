import os
import re
import json
import logging
import asyncio
from pathlib import Path
from typing import Dict, List, Any, Optional

logger = logging.getLogger("aegis.skills")

SKILLS_DIR = Path(__file__).parent / "aegis_data" / "skills"
SKILLS_DIR.mkdir(parents=True, exist_ok=True)

class SkillManager:
    def __init__(self):
        self.skills: Dict[str, Any] = {}
        self.core_tools: Dict[str, Any] = self._init_core_tools()

    def _init_core_tools(self) -> Dict[str, Any]:
        """Initialize the built-in core tools."""
        return {
            "search_web": {
                "name": "search_web",
                "description": "Performs a web search for a given query.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "The search term."}
                    },
                    "required": ["query"]
                }
            },
            "read_url": {
                "name": "read_url",
                "description": "Fetches content from a URL via HTTP request.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "url": {"type": "string", "description": "The URL to read."}
                    },
                    "required": ["url"]
                }
            },
            "shell_command": {
                "name": "shell_command",
                "description": "Executes a shell command on the host (CAUTION: Restricted).",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "command": {"type": "string", "description": "The command to run."}
                    },
                    "required": ["command"]
                }
            },
            "github_create_branch": {
                "name": "github_create_branch",
                "description": "Creates a new branch in a GitHub repository using the native API.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "repo": {"type": "string", "description": "The target repository in owner/repo format (e.g., 'TheSandemon/Aegis')."},
                        "branch_name": {"type": "string", "description": "Name of the new branch to create."},
                        "base_branch": {"type": "string", "description": "Name of the base branch to branch from (default 'main')."}
                    },
                    "required": ["repo", "branch_name"]
                }
            },
            "github_create_pr": {
                "name": "github_create_pr",
                "description": "Opens a Pull Request in a GitHub repository using the native API.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "repo": {"type": "string", "description": "The target repository in owner/repo format."},
                        "title": {"type": "string", "description": "PR title."},
                        "body": {"type": "string", "description": "PR description."},
                        "head_branch": {"type": "string", "description": "The name of the branch where your changes are implemented."},
                        "base_branch": {"type": "string", "description": "The name of the branch you want the changes pulled into. Default usually 'main'."}
                    },
                    "required": ["repo", "title", "body", "head_branch"]
                }
            },
            "github_list_prs": {
                "name": "github_list_prs",
                "description": "Lists open Pull Requests for a specific GitHub repository.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "repo": {"type": "string", "description": "The target repository in owner/repo format."},
                        "state": {"type": "string", "description": "State of the PR to list: 'open', 'closed', or 'all'. default 'open'."}
                    },
                    "required": ["repo"]
                }
            },
            "github_merge_pr": {
                "name": "github_merge_pr",
                "description": "Merges an open Pull Request using the native API.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "repo": {"type": "string", "description": "The target repository in owner/repo format."},
                        "pr_number": {"type": "integer", "description": "The integer ID of the Pull Request."},
                        "merge_method": {"type": "string", "description": "The merge method: 'merge', 'squash', or 'rebase'. default 'squash'."}
                    },
                    "required": ["repo", "pr_number"]
                }
            }
        }

    def refresh_skills(self):
        """Scans the skills directory for SKILL.md files and parses them."""
        self.skills = {}
        if not SKILLS_DIR.exists():
            return

        for skill_folder in SKILLS_DIR.iterdir():
            if skill_folder.is_dir():
                skill_file = skill_folder / "SKILL.md"
                if skill_file.exists():
                    try:
                        skill_data = self._parse_skill_file(skill_file)
                        if skill_data:
                            # Use folder name as skill ID if not provided
                            skill_id = skill_data.get("id", skill_folder.name)
                            self.skills[skill_id] = skill_data
                            logger.info(f"Loaded skill: {skill_id} from {skill_file}")
                    except Exception as e:
                        logger.error(f"Failed to parse skill at {skill_file}: {e}")

    def _parse_skill_file(self, path: Path) -> Optional[Dict[str, Any]]:
        """Parses a SKILL.md file into a tool definition."""
        content = path.read_text(encoding="utf-8")
        
        # Simple regex-based parsing for ClawHub format
        # This is a bit naive but works for standard SKILL.md
        name_match = re.search(r"^#\s+(.+)$", content, re.MULTILINE)
        desc_match = re.search(r"^Description:\s*(.+)$", content, re.MULTILINE)
        
        if not name_match:
            return None
            
        name = name_match.group(1).strip()
        description = desc_match.group(1).strip() if desc_match else ""
        
        # Look for the JSON schema if it exists in the file (often in a code block)
        schema_match = re.search(r"```json\s*(\{.*?\})\s*```", content, re.DOTALL)
        parameters = {}
        if schema_match:
            try:
                parameters = json.loads(schema_match.group(1))
            except json.JSONDecodeError:
                pass

        return {
            "name": name,
            "description": description,
            "parameters": parameters,
            "path": str(path.parent)
        }

    def get_all_tools(self) -> List[Dict[str, Any]]:
        """Returns all available tools (core + loaded skills)."""
        all_tools = []
        for core_tool in self.core_tools.values():
            tool_data = dict(core_tool)
            tool_data["is_core"] = True
            all_tools.append(tool_data)
            
        for skill_id, skill in self.skills.items():
            skill_name = skill["name"]
            is_core = False
            
            # Label core knowledge skills dynamically for UI
            if skill_name.lower() == "calculator" or skill_id == "aegis-board-mastery":
                is_core = True
                
            all_tools.append({
                "id": skill_id,
                "name": skill_name,
                "description": skill["description"],
                "parameters": skill["parameters"],
                "is_core": is_core
            })
        return all_tools

    async def execute_tool(self, name: str, args: Dict[str, Any], agent_context: Dict[str, Any]) -> Any:
        """Dispatches tool execution to the appropriate handler."""
        if name in self.core_tools:
            return await self._execute_core_tool(name, args, agent_context)
        elif name in self.skills:
            return await self._execute_modular_tool(name, args, agent_context)
        else:
            raise ValueError(f"Unknown tool: {name}")

    async def _execute_core_tool(self, name: str, args: Dict[str, Any], context: Dict[str, Any]) -> Any:
        """Handles execution of built-in core tools."""
        if name == "search_web":
            query = args.get("query")
            # In a real app, this would call a search API. 
            # For now, we'll return a mock and suggest how to implement.
            logger.info(f"CoreTool: search_web query='{query}'")
            return f"Search result for '{query}': No results found (Mock implementation)."
        
        elif name == "read_url":
            url = args.get("url")
            import httpx
            async with httpx.AsyncClient() as client:
                r = await client.get(url)
                return r.text[:2000] # Return first 2k chars
                
        elif name == "shell_command":
            cmd = args.get("command")
            # Restricted execution
            allowed_cmds = ["ls", "dir", "pwd", "date", "whoami"]
            base_cmd = cmd.split()[0]
            if base_cmd not in allowed_cmds:
                return f"Error: Command '{base_cmd}' is not allowed for safety."
            
            proc = await asyncio.create_subprocess_shell(
                cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await proc.communicate()
            return (stdout or stderr).decode().strip()

        elif name.startswith("github_"):
            token = os.environ.get("GITHUB_TOKEN")
            if not token:
                config_path = Path("aegis.config.json")
                if config_path.exists():
                    try:
                        conf = json.loads(config_path.read_text())
                        for c in conf.get("integration_connections", []):
                            if c.get("type") == "github" and c.get("credentials", {}).get("token"):
                                token = c["credentials"]["token"]
                                break
                    except Exception:
                        pass
            if not token:
                return "Error: No GitHub token configured in aegis.config.json or GITHUB_TOKEN environment variable."
            
            repo = args.get("repo")
            if not repo:
                return "Error: 'repo' parameter is required for GitHub operations."
                
            import httpx
            headers = {
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            }
            base_url = "https://api.github.com"
            
            async with httpx.AsyncClient(timeout=20) as client:
                if name == "github_create_branch":
                    base = args.get("base_branch", "main")
                    branch_name = args.get("branch_name")
                    ref_resp = await client.get(f"{base_url}/repos/{repo}/git/ref/heads/{base}", headers=headers)
                    if ref_resp.status_code != 200:
                        return f"Error: Base branch '{base}' not found: {ref_resp.status_code} - {ref_resp.text}"
                    sha = ref_resp.json()["object"]["sha"]
                    create_resp = await client.post(f"{base_url}/repos/{repo}/git/refs", headers=headers, json={"ref": f"refs/heads/{branch_name}", "sha": sha})
                    if create_resp.status_code == 201:
                        return f"Success: Created branch {branch_name} from {base} (SHA: {sha})"
                    return f"Error: Failed to create branch: {create_resp.status_code} - {create_resp.text}"

                elif name == "github_create_pr":
                    title = args.get("title")
                    body = args.get("body", "")
                    head = args.get("head_branch")
                    base = args.get("base_branch", "main")
                    resp = await client.post(f"{base_url}/repos/{repo}/pulls", headers=headers, json={"title": title, "body": body, "head": head, "base": base})
                    if resp.status_code == 201:
                        data = resp.json()
                        return f"Success: Created Pull Request #{data['number']} at {data['html_url']}"
                    return f"Error: Failed to create PR: {resp.status_code} - {resp.text}"

                elif name == "github_list_prs":
                    state = args.get("state", "open")
                    resp = await client.get(f"{base_url}/repos/{repo}/pulls", headers=headers, params={"state": state, "per_page": 30})
                    if resp.status_code == 200:
                        prs = resp.json()
                        return json.dumps([{"number": pr["number"], "title": pr["title"], "state": pr["state"], "url": pr["html_url"], "head": pr.get("head", {}).get("ref", ""), "base": pr.get("base", {}).get("ref", "")} for pr in prs])
                    return f"Error: Failed to list PRs: {resp.status_code} - {resp.text}"

                elif name == "github_merge_pr":
                    pr_number = args.get("pr_number")
                    merge_method = args.get("merge_method", "squash")
                    resp = await client.put(f"{base_url}/repos/{repo}/pulls/{pr_number}/merge", headers=headers, json={"merge_method": merge_method})
                    if resp.status_code == 200:
                        return f"Success: Merged PR #{pr_number} using {merge_method}."
                    return f"Error: Merge failed: {resp.status_code} - {resp.text}"

    async def _execute_modular_tool(self, name: str, args: Dict[str, Any], context: Dict[str, Any]) -> Any:
        """Handles execution of ported ClawHub skills."""
        skill = self.skills[name]
        skill_path = Path(skill["path"])
        
        # Look for an entrypoint script (often main.py or logic.py)
        entrypoint = skill_path / "logic.py"
        if not entrypoint.exists():
            entrypoint = skill_path / "main.py"
            
        if not entrypoint.exists():
            return f"Error: No entrypoint (logic.py or main.py) found for skill '{name}'"

        # Execute the skill logic as a subprocess
        # We pass arguments as JSON via env or stdin
        env = os.environ.copy()
        env["SKILL_ARGS"] = json.dumps(args)
        env["AEGIS_CONTEXT"] = json.dumps(context)
        
        proc = await asyncio.create_subprocess_exec(
            "python", str(entrypoint),
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await proc.communicate()
        
        if proc.returncode != 0:
            return f"Skill Execution Error: {stderr.decode()}"
            
        return stdout.decode().strip()

skill_manager = SkillManager()

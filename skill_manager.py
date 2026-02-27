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
        all_tools = list(self.core_tools.values())
        for skill in self.skills.values():
            all_tools.append({
                "name": skill["name"],
                "description": skill["description"],
                "parameters": skill["parameters"]
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

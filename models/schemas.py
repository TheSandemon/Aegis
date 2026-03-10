from typing import Optional
from pydantic import BaseModel

class CardCreate(BaseModel):
    title: str
    description: str = ""
    column: str = "Inbox"
    assignee: Optional[str] = None
    depends_on: Optional[list[int]] = None
    priority: str = "normal"
    card_group: Optional[str] = None
    card_tags: Optional[list[str]] = None

class CardUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    column: Optional[str] = None
    assignee: Optional[str] = None
    status: Optional[str] = None
    depends_on: Optional[list[int]] = None
    priority: Optional[str] = None
    card_group: Optional[str] = None
    card_tags: Optional[list[str]] = None
    is_locked: Optional[bool] = None

class InstanceCreate(BaseModel):
    template_id: str
    instance_name: str
    service: Optional[str] = ""
    model: Optional[str] = ""
    env_vars: Optional[dict] = {}
    config: Optional[dict] = {}
    skills: Optional[list[str]] = []
    icon: Optional[str] = None
    color: Optional[str] = None
    character_type: Optional[str] = "robot"

class InstanceUpdate(BaseModel):
    instance_name: Optional[str] = None
    enabled: Optional[bool] = None
    service: Optional[str] = None
    model: Optional[str] = None
    env_vars: Optional[dict] = None
    config: Optional[dict] = None
    skills: Optional[list[str]] = None
    icon: Optional[str] = None
    color: Optional[str] = None
    priority: Optional[str] = None
    character_type: Optional[str] = None

class CommentCreate(BaseModel):
    author: str
    content: str

class SkillInstallRequest(BaseModel):
    github_url: str

class IntegrationConfig(BaseModel):
    type: str                             # "github" | "jira" | "linear" | "firestore"
    mode: str = "read"                    # "read" | "write" | "read_write"
    credentials: dict = {}
    filters: dict = {}
    sync_interval_ms: int = 60000
    webhook_secret: Optional[str] = None

class ColumnCreate(BaseModel):
    name: str
    position: Optional[int] = 0
    color: Optional[str] = None
    integration: Optional[IntegrationConfig] = None
    function: Optional[str] = ""
    exit_pass: Optional[str] = ""
    exit_fail: Optional[str] = ""

class SystemPromptUpdate(BaseModel):
    prompt: str

class PromptSubmit(BaseModel):
    card_id: int
    agent_name: str
    prompt: str

class BrokerRateUpdate(BaseModel):
    prompts_per_minute: int

class ColumnUpdate(BaseModel):
    name: Optional[str] = None
    position: Optional[int] = None
    color: Optional[str] = None
    is_locked: Optional[bool] = None
    integration: Optional[IntegrationConfig] = None
    remove_integration: bool = False
    function: Optional[str] = None
    exit_pass: Optional[str] = None
    exit_fail: Optional[str] = None
class PulseRequest(BaseModel):
    interval: float

class BranchCreate(BaseModel):
    column: Optional[str] = None
    branch_name: str
    base: str = "main"

class PRCreate(BaseModel):
    column: Optional[str] = None
    title: str
    body: str
    head: str
    base: str = "main"

class PRMerge(BaseModel):
    column: Optional[str] = None
    pr_number: int
    merge_method: str = "squash"
    commit_message: Optional[str] = None

class ConnectionCreate(BaseModel):
    provider_id: str
    connection_name: str
    credentials: dict

class DevicePollRequest(BaseModel):
    device_code: str


class CoStarConfig(BaseModel):
    """Configuration for CoStar AI super admin assistant."""
    enabled: bool = False
    api_key: str = ""
    model: str = "claude-sonnet-4-6"
    service: str = "anthropic"
    rate_limit: int = 10  # prompts per minute
    max_retries: int = 3
    auto_memory_compress: bool = True
    memory_compress_threshold: float = 0.5

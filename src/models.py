from typing import Any, Literal

from pydantic import BaseModel, Field

AgentStatus = Literal["idle", "busy", "disabled"]
TaskStatus = Literal["queued", "running", "completed", "failed", "cancelled"]
AgentRunner = Literal["api", "cli"]
MemoryScope = Literal["user", "project", "local"]


class AgentCreate(BaseModel):
    name: str
    role: str = ""
    system_prompt: str = ""
    model_preference: str = "claude-sonnet-4-6"
    memory: MemoryScope | None = None
    config: dict[str, Any] = Field(default_factory=dict)


class AgentUpdate(BaseModel):
    name: str | None = None
    role: str | None = None
    system_prompt: str | None = None
    model_preference: str | None = None
    status: AgentStatus | None = None
    memory: MemoryScope | None = None
    config: dict[str, Any] | None = None


class AgentResponse(BaseModel):
    id: str
    name: str
    role: str
    status: AgentStatus
    system_prompt: str
    model_preference: str
    runner: AgentRunner
    skills: list[str]
    memory: MemoryScope | None = None
    config: dict[str, Any]
    created_at: str
    updated_at: str


class TaskCreate(BaseModel):
    agent_id: str
    description: str
    input_context: dict[str, Any] = Field(default_factory=dict)
    priority: int = Field(default=3, ge=1, le=5)
    max_retries: int = Field(default=0, ge=0)


class TaskResponse(BaseModel):
    id: str
    agent_id: str
    description: str
    status: TaskStatus
    priority: int
    input_context: dict[str, Any]
    output: dict[str, Any] | None
    error: str | None
    max_retries: int
    retry_count: int
    created_at: str
    started_at: str | None
    completed_at: str | None


class SkillCreate(BaseModel):
    name: str
    description: str = ""
    content: str
    version: str = "1.0.0"
    assign_to: list[str] = Field(default_factory=list)


class SkillResponse(BaseModel):
    id: str
    name: str
    description: str
    file_path: str
    version: str
    installed_at: str


class DashboardStats(BaseModel):
    total_agents: int
    active_agents: int
    queued_tasks: int
    total_skills: int
    tasks_today: int
    queue_depth: int

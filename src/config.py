from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    port: int = 8100
    mcp_auth_token: str = ""
    mcp_auth_disabled: bool = False
    ide_target: Literal["claude", "cursor"] = "claude"
    max_concurrent_agents: int = 3
    task_queue_size: int = 20
    anthropic_api_key: str = ""
    data_dir: str = "/data"
    workspace_dir: str = "/workspace"
    skills_dir: str = "/skills"
    project_dir: str = "/project"
    # Comma-separated list of allowed Host header values for DNS rebinding protection.
    # Leave empty to disable the protection (e.g. when behind a trusted reverse proxy).
    mcp_allowed_hosts: str = ""
    # When True, CLI-runner agents get the orcai-mcp delegate endpoint registered
    # as an MCP server so they can delegate tasks to sibling agents.
    enable_agent_delegation: bool = True


settings = Settings()

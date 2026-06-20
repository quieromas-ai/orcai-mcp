from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    port: int = 8100
    # Instance identity: used as the FastMCP server name AND as the frontmatter
    # boolean key that an agent must set to `true` to be discoverable by this instance.
    mcp_name: str = "orcai-mcp"
    mcp_auth_token: str = ""
    mcp_auth_disabled: bool = False
    ide_target: Literal["claude", "cursor", "orcai"] = "claude"
    max_concurrent_agents: int = 3
    task_queue_size: int = 20
    anthropic_api_key: str = ""
    data_dir: str = "/data"
    claude_dir: str = "/project/.claude"
    project_dir: str = "/project"
    mcp_allowed_hosts: str = ""
    enable_agent_delegation: bool = True
    wakeup_poll_seconds: int = 30
    wakeup_max_delay_seconds: int = 86400


settings = Settings()

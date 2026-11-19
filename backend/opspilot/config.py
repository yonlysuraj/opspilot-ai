from pathlib import Path
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEMO_USER = "maya-chen"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="OPSPILOT_", env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    db_path: Path = Path("data/opspilot.sqlite3")
    ollama_url: str = "http://127.0.0.1:11434"
    ollama_model: str = Field(default="qwen3:1.7b", pattern=r"^[a-zA-Z0-9_.:/-]+$")
    embedding_model: str = Field(default="nomic-embed-text", pattern=r"^[a-zA-Z0-9_.:/-]+$")
    approver_token: SecretStr = SecretStr("")
    model_timeout_seconds: float = Field(default=180, gt=0)
    tool_timeout_seconds: float = Field(default=10, gt=0)
    mcp_start_timeout_seconds: float = Field(default=60, gt=0)
    run_timeout_seconds: float = Field(default=600, gt=0)
    max_tool_calls: int = Field(default=12, ge=1, le=24)

    @property
    def checkpoints_path(self) -> Path:
        return self.db_path.resolve().with_suffix(".checkpoints.sqlite3")

    @property
    def vector_path(self) -> Path:
        return self.db_path.resolve().with_suffix(".vectors")

    @field_validator("ollama_url")
    @classmethod
    def local_ollama_only(cls, value: str) -> str:
        url = urlsplit(value)
        if (
            url.scheme != "http"
            or url.hostname not in {"localhost", "127.0.0.1", "::1"}
            or url.username is not None
            or url.path not in {"", "/"}
            or url.query
            or url.fragment
        ):
            raise ValueError("Use a loopback Ollama URL such as http://127.0.0.1:11434")
        return value.rstrip("/")

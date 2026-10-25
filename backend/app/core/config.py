"""应用配置。所有密钥只从环境变量 / .env 读取。"""

from __future__ import annotations

from pathlib import Path

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(PROJECT_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_name: str = "AI 群友"
    app_env: str = "development"
    app_version: str = "0.1.0"
    app_host: str = "127.0.0.1"
    app_port: int = 8000
    log_level: str = "INFO"
    default_timezone: str = "Asia/Shanghai"
    api_prefix: str = "/api"

    data_dir: str = ""
    database_url: str = ""
    auto_migrate: bool = True

    app_secret_key: str = ""
    credential_encryption_key: str = ""

    allow_remote_admin: bool = False
    admin_api_token: str = ""
    cors_origins: str = "http://127.0.0.1:5173,http://localhost:5173"

    llm_max_retries: int = 2
    llm_timeout_seconds: float = 45.0
    max_tool_rounds: int = 2
    outbox_max_attempts: int = 3
    outbox_failure_pause_threshold: int = 3
    context_message_limit: int = 20
    memory_max_items: int = 6
    memory_max_chars: int = 1600
    memory_extraction_max_messages: int = 40
    memory_extraction_max_candidates: int = 6
    memory_extraction_min_confidence: float = 0.6
    memory_auto_extraction_interval_seconds: int = Field(default=300, ge=30, le=86400)
    max_reply_chars: int = 500
    max_tool_calls_per_turn: int = 3
    max_media_bytes: int = 10 * 1024 * 1024

    default_llm_provider: str = "openai_compatible"
    default_llm_base_url: str = ""
    default_llm_model: str = ""
    default_llm_api_key: str = ""

    log_retention_days: int = 30
    message_retention_days: int = 90
    media_retention_days: int = 30

    frontend_dist: str = ""

    @model_validator(mode="after")
    def _fill_defaults(self) -> Settings:
        if not self.data_dir:
            self.data_dir = str(PROJECT_ROOT / "data")
        data_path = Path(self.data_dir)
        if not data_path.is_absolute():
            self.data_dir = str(PROJECT_ROOT / data_path)
        if not self.database_url:
            db_path = Path(self.data_dir) / "ai_group_friend.db"
            self.database_url = f"sqlite+aiosqlite:///{db_path.as_posix()}"
        if not self.frontend_dist:
            self.frontend_dist = str(PROJECT_ROOT / "frontend" / "dist")
        return self

    @property
    def data_path(self) -> Path:
        return Path(self.data_dir)

    @property
    def logs_path(self) -> Path:
        return self.data_path / "logs"

    @property
    def media_path(self) -> Path:
        return self.data_path / "media"

    @property
    def backups_path(self) -> Path:
        return self.data_path / "backups"

    @property
    def plugins_path(self) -> Path:
        return self.data_path / "plugins"

    @property
    def frontend_dist_path(self) -> Path:
        return Path(self.frontend_dist)

    @property
    def database_sync_url(self) -> str:
        return self.database_url.replace("sqlite+aiosqlite", "sqlite")

    @property
    def cors_origin_list(self) -> list[str]:
        return [item.strip() for item in self.cors_origins.split(",") if item.strip()]

    @property
    def has_credential_key(self) -> bool:
        return bool(self.credential_encryption_key.strip())

    @property
    def allowed_hosts(self) -> set[str]:
        return {"127.0.0.1", "::1", "localhost", "testclient", "testserver"}

    def ensure_directories(self) -> None:
        for path in (self.data_path, self.logs_path, self.media_path, self.backups_path, self.plugins_path):
            path.mkdir(parents=True, exist_ok=True)

    def masked_runtime_info(self) -> dict[str, object]:
        return {
            "app_env": self.app_env,
            "app_version": self.app_version,
            "database": "sqlite",
            "data_dir": str(self.data_path),
            "default_timezone": self.default_timezone,
            "credential_key_configured": self.has_credential_key,
            "allow_remote_admin": self.allow_remote_admin,
        }


def get_settings() -> Settings:
    return Settings()


__all__ = ["PROJECT_ROOT", "Settings", "get_settings", "Field"]

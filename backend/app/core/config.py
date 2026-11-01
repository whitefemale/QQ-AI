"""应用配置。所有密钥只从环境变量 / .env 读取。"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from urllib.parse import urlparse

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app import __version__


def is_frozen() -> bool:
    """是否运行在 PyInstaller 打包产物中。"""
    return bool(getattr(sys, "frozen", False))


def _resource_root() -> Path:
    """应用资源根。

    源码运行时是仓库根；冻结后优先使用 ``AI_GROUP_FRIEND_RESOURCE_ROOT``
    （桌面壳显式传入），否则使用 PyInstaller 的 ``_MEIPASS``。
    """
    override = os.environ.get("AI_GROUP_FRIEND_RESOURCE_ROOT", "").strip()
    if override:
        return Path(override).expanduser().resolve()
    if is_frozen():
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent)).resolve()
    return Path(__file__).resolve().parents[3]


def _default_data_dir(root: Path) -> Path:
    """打包版默认写入用户目录，避免尝试写安装目录（Program Files）。"""
    if is_frozen():
        return Path.home() / ".ai-group-friend" / "data"
    return root / "data"


def _default_frontend_dist(root: Path) -> Path:
    if is_frozen():
        # 安装布局：resources/backend/aiqf-backend.exe + resources/frontend/dist。
        return Path(sys.executable).resolve().parent.parent / "frontend" / "dist"
    return root / "frontend" / "dist"


def _env_file(root: Path) -> Path:
    override = os.environ.get("AI_GROUP_FRIEND_ENV_FILE", "").strip()
    return Path(override).expanduser().resolve() if override else root / ".env"


PROJECT_ROOT = _resource_root()


def resolve_backend_root(root: Path | None = None) -> Path:
    """返回包含 ``alembic.ini`` 的目录。

    源码布局为 ``<repo>/backend``；PyInstaller 把迁移文件放到资源根。
    """
    base = root or PROJECT_ROOT
    return base / "backend" if (base / "backend" / "alembic").is_dir() else base


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(_env_file(PROJECT_ROOT)),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_name: str = "AI 群友"
    app_env: str = "development"
    app_version: str = __version__
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
    # 允许的 Host 头（逗号分隔，不含端口）；默认只允许本机访问。
    allowed_hosts: str = ""

    llm_max_retries: int = 2
    llm_timeout_seconds: float = 45.0
    # 单进程内的 Provider 保护：并发上限与最小请求间隔。不是分布式限流。
    llm_max_concurrency_per_provider: int = Field(default=2, ge=1, le=32)
    llm_min_interval_ms: int = Field(default=200, ge=0, le=60000)
    llm_model_list_timeout_seconds: float = Field(default=20.0, gt=0, le=300)
    llm_retry_base_seconds: float = Field(default=0.5, ge=0, le=60)
    llm_retry_max_seconds: float = Field(default=8.0, ge=0, le=300)
    llm_retry_jitter_seconds: float = Field(default=0.25, ge=0, le=10)
    llm_retry_after_max_seconds: float = Field(default=30.0, ge=0, le=600)
    # 读/写超时可能已使服务商计费；默认不自动重试，避免重复费用。
    llm_retry_ambiguous_timeouts: bool = False
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
    media_worker_enabled: bool = True
    media_worker_interval_seconds: float = Field(default=2.0, ge=0.5, le=300)
    media_worker_batch_size: int = Field(default=10, ge=1, le=100)

    default_llm_provider: str = "openai_compatible"
    default_llm_base_url: str = ""
    default_llm_model: str = ""
    default_llm_api_key: str = ""

    log_retention_days: int = 30
    message_retention_days: int = 90
    media_retention_days: int = 30
    # 自动清理默认关闭，避免升级后未经确认永久删除数据；管理员可在设置页显式开启。
    retention_enabled: bool = False
    retention_interval_seconds: int = Field(default=3600, ge=60, le=86400)
    retention_batch_size: int = Field(default=100, ge=1, le=1000)
    retention_max_batches_per_run: int = Field(default=20, ge=1, le=1000)
    retention_run_on_start: bool = False

    frontend_dist: str = ""
    # 受管连接器根目录。API 不接受任意路径；仅本机设置/桌面壳可覆盖。
    connectors_dir: str = ""

    @model_validator(mode="after")
    def _fill_defaults(self) -> Settings:
        if not self.data_dir:
            self.data_dir = str(_default_data_dir(PROJECT_ROOT))
        data_path = Path(self.data_dir)
        if not data_path.is_absolute():
            self.data_dir = str(PROJECT_ROOT / data_path)
        if not self.database_url:
            db_path = Path(self.data_dir) / "ai_group_friend.db"
            self.database_url = f"sqlite+aiosqlite:///{db_path.as_posix()}"
        if not self.frontend_dist:
            self.frontend_dist = str(_default_frontend_dist(PROJECT_ROOT))
        if not self.connectors_dir:
            if is_frozen():
                # 打包版安装目录通常不可写；受管连接器默认放在用户数据目录。
                self.connectors_dir = str(Path(self.data_dir) / "connectors" / "napcat")
            else:
                self.connectors_dir = str(PROJECT_ROOT / "connectors" / "napcat")
        connectors_path = Path(self.connectors_dir)
        if not connectors_path.is_absolute():
            self.connectors_dir = str(PROJECT_ROOT / connectors_path)
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
    def connectors_path(self) -> Path:
        return Path(self.connectors_dir)

    @property
    def database_sync_url(self) -> str:
        return self.database_url.replace("sqlite+aiosqlite", "sqlite")

    @property
    def cors_origin_list(self) -> list[str]:
        """CORS 只接受明确的 http(s) 来源；通配符或非法来源在启动时直接失败。"""
        raw = self.cors_origins.strip()
        if not raw:
            return []
        items = [item.strip() for item in raw.split(",")]
        if any(not item for item in items):
            raise RuntimeError("CORS_ORIGINS 含有空项；请使用逗号分隔的明确来源，或留空表示不启用跨域。")
        origins: list[str] = []
        for item in items:
            if item == "*" or "*" in item:
                raise RuntimeError("CORS_ORIGINS 不允许通配符；请填写明确的 http:// 或 https:// 来源。")
            parsed = urlparse(item)
            if (
                parsed.scheme not in {"http", "https"}
                or not parsed.hostname
                or parsed.username is not None
                or parsed.password is not None
                or parsed.path not in {"", "/"}
                or parsed.query
                or parsed.fragment
            ):
                raise RuntimeError(f"CORS_ORIGINS 来源无效：{item!r}；只允许 scheme://host[:port]。")
            origins.append(item.rstrip("/"))
        return origins

    @property
    def has_credential_key(self) -> bool:
        return bool(self.credential_encryption_key.strip())

    @property
    def allowed_host_list(self) -> list[str]:
        """TrustedHost 白名单；显式 * 表示关闭校验（仅限受控环境）。"""
        defaults = ["127.0.0.1", "::1", "localhost", "testclient", "testserver"]
        extra = [item.strip().lower() for item in self.allowed_hosts.split(",") if item.strip()]
        if "*" in extra:
            return ["*"]
        result: list[str] = []
        for host in [*defaults, *extra]:
            value = host.strip().strip("[]")
            if value and value not in result:
                result.append(value)
        return result

    def ensure_directories(self) -> None:
        for path in (self.data_path, self.logs_path, self.media_path, self.backups_path, self.plugins_path):
            path.mkdir(parents=True, exist_ok=True)

    def masked_runtime_info(self) -> dict[str, object]:
        return {
            "app_env": self.app_env,
            "app_version": self.app_version,
            "runtime_mode": "packaged" if is_frozen() else "source",
            "database": "sqlite",
            "data_dir": str(self.data_path),
            "connectors_dir": str(self.connectors_path),
            "default_timezone": self.default_timezone,
            "credential_key_configured": self.has_credential_key,
            "allow_remote_admin": self.allow_remote_admin,
        }


def get_settings() -> Settings:
    return Settings()


__all__ = [
    "PROJECT_ROOT",
    "Settings",
    "get_settings",
    "Field",
    "is_frozen",
    "resolve_backend_root",
]

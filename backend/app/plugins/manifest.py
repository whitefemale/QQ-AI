"""插件清单（Manifest）校验与目录加载。

P0 只登记清单和权限，不加载或执行第三方代码。
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from app.core.errors import AppError, ErrorCode

ALLOWED_PERMISSIONS: set[str] = {
    "messages:read",
    "messages:send",
    "media:read",
    "memory:read",
    "memory:write",
    "llm:invoke",
    "tools:invoke",
    "network:http",
    "settings:read",
}

HIGH_RISK_PERMISSIONS: set[str] = {
    "messages:send",
    "memory:write",
    "llm:invoke",
    "network:http",
}

_PLUGIN_ID = re.compile(r"^[a-z][a-z0-9_.-]{1,63}$")
_VERSION = re.compile(r"^(\d+)\.(\d+)\.(\d+)(?:[-+][0-9A-Za-z.-]+)?$")


def parse_version(value: str) -> tuple[int, int, int]:
    match = _VERSION.match(value.strip())
    if not match:
        raise AppError(ErrorCode.PLUGIN_INVALID, "插件版本号必须为 x.y.z 格式。", status_code=400)
    return int(match.group(1)), int(match.group(2)), int(match.group(3))


def version_at_least(current: str, minimum: str) -> bool:
    return parse_version(current) >= parse_version(minimum)


class PluginHealthcheck(BaseModel):
    """健康检查声明：只保存声明，本版本不执行第三方检查或任意网络请求。"""

    type: Literal["builtin", "http"] = "builtin"
    path: str = Field(default="", max_length=256)
    interval_seconds: int = Field(default=300, ge=30, le=86400)
    timeout_seconds: int = Field(default=5, ge=1, le=30)

    @field_validator("path")
    @classmethod
    def _validate_path(cls, value: str) -> str:
        path = value.strip()
        if not path:
            return ""
        if not path.startswith("/") or path.startswith("//"):
            raise ValueError("健康检查路径必须为空或以 / 开头的站内相对路径。")
        if any(marker in path for marker in ("://", "@", "?", "#", "..", "\\")):
            raise ValueError("健康检查路径不能包含协议、凭据、查询、片段或目录穿越。")
        return path


class PluginManifest(BaseModel):
    id: str
    name: str = Field(min_length=1, max_length=128)
    version: str = "0.1.0"
    description: str = Field(default="", max_length=2000)
    plugin_type: Literal["builtin", "manifest", "http"] = "manifest"
    entrypoint: str = Field(default="", max_length=256)
    capabilities: list[str] = Field(default_factory=list)
    permissions: list[str] = Field(default_factory=list)
    config_schema: dict[str, Any] = Field(default_factory=dict)
    dependencies: list[str] = Field(default_factory=list)
    min_app_version: str = "0.1.0"
    author: str = Field(default="", max_length=128)
    homepage: str = Field(default="", max_length=256)
    healthcheck: PluginHealthcheck | None = None

    @field_validator("id")
    @classmethod
    def _validate_id(cls, value: str) -> str:
        if not _PLUGIN_ID.match(value):
            raise ValueError("插件 id 只能包含小写字母、数字、点、下划线和短横线，且以字母开头。")
        return value

    @field_validator("version", "min_app_version")
    @classmethod
    def _validate_version(cls, value: str) -> str:
        parse_version(value)
        return value

    @field_validator("permissions")
    @classmethod
    def _validate_permissions(cls, value: list[str]) -> list[str]:
        unknown = sorted(set(value) - ALLOWED_PERMISSIONS)
        if unknown:
            raise ValueError(f"包含未知权限：{', '.join(unknown)}")
        return sorted(set(value))

    @field_validator("capabilities")
    @classmethod
    def _dedupe_capabilities(cls, value: list[str]) -> list[str]:
        return sorted({item.strip() for item in value if item.strip()})

    @field_validator("entrypoint")
    @classmethod
    def _validate_entrypoint(cls, value: str) -> str:
        if value and not (value.startswith("builtin:") or value.startswith("https://")):
            raise ValueError("entrypoint 只能是内置实现（builtin:xxx）或 https 地址；本版本不执行本地任意代码。")
        return value

    def requires_approval(self) -> bool:
        return bool(set(self.permissions) & HIGH_RISK_PERMISSIONS)

    def public(self) -> dict[str, Any]:
        return self.model_dump()


class ManifestLoadError(BaseModel):
    path: str
    message: str


class ManifestLoadResult(BaseModel):
    manifests: list[PluginManifest] = Field(default_factory=list)
    errors: list[ManifestLoadError] = Field(default_factory=list)


def parse_manifest(raw: dict[str, Any]) -> PluginManifest:
    try:
        return PluginManifest.model_validate(raw)
    except Exception as exc:  # pydantic ValidationError 的细节不适合直接外露
        message = str(exc)
        if len(message) > 500:
            message = message[:500] + "…"
        raise AppError(ErrorCode.PLUGIN_INVALID, f"插件清单无效：{message}", status_code=400) from exc


def load_manifests(root: Path) -> ManifestLoadResult:
    """从数据目录加载插件清单；单个清单损坏不影响其他插件。"""
    result = ManifestLoadResult()
    if not root.exists():
        return result
    candidates: list[Path] = []
    for entry in sorted(root.iterdir()):
        if entry.is_dir() and (entry / "manifest.json").is_file():
            candidates.append(entry / "manifest.json")
        elif entry.name == "manifest.json" and entry.is_file():
            candidates.append(entry)
    for path in candidates:
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                raise ValueError("清单根节点必须是 JSON 对象。")
            result.manifests.append(parse_manifest(raw))
        except AppError as exc:
            result.errors.append(ManifestLoadError(path=str(path), message=exc.message))
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            result.errors.append(ManifestLoadError(path=str(path), message=f"读取或解析失败：{exc}"))
    return result


BUILTIN_MANIFESTS: list[PluginManifest] = [
    PluginManifest(
        id="builtin.core-tools",
        name="内置安全工具",
        version="1.0.0",
        description="计算器与时间工具。不执行 Shell、不读写任意文件、不访问任意网络。",
        plugin_type="builtin",
        entrypoint="builtin:core_tools",
        capabilities=["tool.calculator", "tool.datetime"],
        permissions=[],
        min_app_version="0.1.0",
        author="AI 群友内置",
    ),
]

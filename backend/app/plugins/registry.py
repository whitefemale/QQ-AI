"""插件注册表服务。

安全边界：本版本只登记清单、校验权限、展示健康状态，不加载第三方代码。
内置插件（如内置工具模块）可启停；第三方 manifest 仅登记，启用时明确提示尚未实现运行时。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import AppError, ErrorCode, planned
from app.core.time import iso_utc, utcnow
from app.db.session import Database
from app.models.governance import PluginRegistry
from app.plugins.manifest import (
    BUILTIN_MANIFESTS,
    HIGH_RISK_PERMISSIONS,
    ManifestLoadResult,
    PluginManifest,
    load_manifests,
    version_at_least,
)


class PluginService:
    def __init__(self, database: Database, settings: Settings) -> None:
        self.database = database
        self.settings = settings
        self.load_errors: list[dict[str, str]] = []

    async def sync(self) -> ManifestLoadResult:
        """扫描插件目录与内置模块并持久化；单个插件错误不影响其他插件。"""
        loaded = load_manifests(self.settings.plugins_path)
        self.load_errors = [error.model_dump() for error in loaded.errors]
        manifests: list[PluginManifest] = list(BUILTIN_MANIFESTS) + loaded.manifests
        async with self.database.session() as session:
            for manifest in manifests:
                await self._upsert(session, manifest)
            await session.commit()
        return loaded

    async def _upsert(self, session: AsyncSession, manifest: PluginManifest) -> PluginRegistry:
        record = await session.get(PluginRegistry, manifest.id)
        compatible = version_at_least(self.settings.app_version, manifest.min_app_version)
        if record is None:
            record = PluginRegistry(
                id=manifest.id,
                name=manifest.name,
                version=manifest.version,
                description=manifest.description,
                entrypoint=manifest.entrypoint,
                plugin_type=manifest.plugin_type,
                capabilities_json=list(manifest.capabilities),
                permissions_json=list(manifest.permissions),
                config_schema_json=manifest.config_schema,
                dependencies_json=list(manifest.dependencies),
                healthcheck_json=manifest.healthcheck.model_dump() if manifest.healthcheck else None,
                min_app_version=manifest.min_app_version,
                enabled=manifest.plugin_type == "builtin" and compatible,
                permission_approved=not manifest.requires_approval(),
                health_status="healthy" if manifest.plugin_type == "builtin" and compatible else "registered",
                manifest_path=str(self.settings.plugins_path / manifest.id / "manifest.json")
                if manifest.plugin_type != "builtin"
                else None,
                is_builtin=manifest.plugin_type == "builtin",
                last_error=None
                if compatible
                else f"需要应用版本 ≥ {manifest.min_app_version}，当前 {self.settings.app_version}。",
            )
            session.add(record)
        else:
            record.name = manifest.name
            record.version = manifest.version
            record.description = manifest.description
            record.entrypoint = manifest.entrypoint
            record.plugin_type = manifest.plugin_type
            record.capabilities_json = list(manifest.capabilities)
            record.permissions_json = list(manifest.permissions)
            record.config_schema_json = manifest.config_schema
            record.dependencies_json = list(manifest.dependencies)
            record.healthcheck_json = manifest.healthcheck.model_dump() if manifest.healthcheck else None
            record.min_app_version = manifest.min_app_version
            record.is_builtin = manifest.plugin_type == "builtin"
            if manifest.requires_approval():
                record.permission_approved = bool(record.permission_approved)
            else:
                record.permission_approved = True
            if not compatible:
                record.enabled = False
                record.health_status = "incompatible"
                record.last_error = f"需要应用版本 ≥ {manifest.min_app_version}，当前 {self.settings.app_version}。"
        await session.flush()
        return record

    async def list_plugins(self) -> list[dict[str, Any]]:
        async with self.database.session() as session:
            result = await session.execute(select(PluginRegistry).order_by(PluginRegistry.id))
            records = list(result.scalars())
        return [self._public(record) for record in records]

    async def get(self, plugin_id: str) -> dict[str, Any]:
        async with self.database.session() as session:
            record = await session.get(PluginRegistry, plugin_id)
        if record is None:
            raise AppError(ErrorCode.PLUGIN_NOT_FOUND, "插件不存在或尚未登记。", status_code=404)
        return self._public(record)

    def _runtime_status(self, record: PluginRegistry) -> str:
        if record.health_status == "incompatible":
            return "incompatible"
        if record.is_builtin:
            return "builtin_active" if record.enabled else "disabled"
        return "runtime_planned"

    def _public(self, record: PluginRegistry) -> dict[str, Any]:
        approved = set(record.permissions_json) & HIGH_RISK_PERMISSIONS
        return {
            "id": record.id,
            "name": record.name,
            "version": record.version,
            "description": record.description,
            "plugin_type": record.plugin_type,
            "entrypoint": record.entrypoint,
            "capabilities": record.capabilities_json,
            "permissions": record.permissions_json,
            "high_risk_permissions": sorted(approved),
            "config_schema": record.config_schema_json,
            "dependencies": record.dependencies_json,
            "min_app_version": record.min_app_version,
            "enabled": record.enabled,
            "permission_approved": record.permission_approved,
            "healthcheck": record.healthcheck_json,
            "healthcheck_note": "健康检查仅为清单声明；本版本不执行第三方健康检查或任意网络请求。",
            "health_status": record.health_status,
            "runtime_status": self._runtime_status(record),
            "runtime_note": (
                "内置模块，由应用自身实现。"
                if record.is_builtin
                else "当前版本仅登记清单，不加载或执行第三方代码；运行时插件将在后续版本提供。"
            ),
            "last_error": record.last_error,
            "is_builtin": record.is_builtin,
            "manifest_path": record.manifest_path,
            "created_at": iso_utc(record.created_at),
            "updated_at": iso_utc(record.updated_at),
        }

    async def set_enabled(self, plugin_id: str, enabled: bool) -> dict[str, Any]:
        async with self.database.session() as session:
            record = await session.get(PluginRegistry, plugin_id)
            if record is None:
                raise AppError(ErrorCode.PLUGIN_NOT_FOUND, "插件不存在或尚未登记。", status_code=404)
            if record.health_status == "incompatible":
                raise AppError(
                    ErrorCode.PLUGIN_INCOMPATIBLE,
                    record.last_error or "插件与应用版本不兼容。",
                    status_code=400,
                )
            if not record.is_builtin:
                raise planned("第三方插件运行时")
            if enabled and not record.permission_approved:
                raise AppError(
                    ErrorCode.PLUGIN_PERMISSION_DENIED,
                    "插件申请的高风险权限尚未批准，不能启用。",
                    status_code=403,
                )
            record.enabled = enabled
            record.health_status = "healthy" if enabled else "disabled"
            await session.commit()
            await session.refresh(record)
            return self._public(record)

    async def approve_permissions(self, plugin_id: str, approved: bool = True) -> dict[str, Any]:
        async with self.database.session() as session:
            record = await session.get(PluginRegistry, plugin_id)
            if record is None:
                raise AppError(ErrorCode.PLUGIN_NOT_FOUND, "插件不存在或尚未登记。", status_code=404)
            record.permission_approved = approved
            if not approved:
                record.enabled = False
                record.health_status = "disabled"
            await session.commit()
            await session.refresh(record)
            return self._public(record)

    async def health(self, plugin_id: str) -> dict[str, Any]:
        data = await self.get(plugin_id)
        if data["health_status"] == "incompatible":
            return data
        if data["is_builtin"]:
            data["health_status"] = "healthy" if data["enabled"] else "disabled"
            data["checked_at"] = iso_utc(utcnow())
        else:
            data["health_status"] = "runtime_planned"
            data["checked_at"] = iso_utc(utcnow())
        return data

    async def is_core_tools_enabled(self) -> bool:
        async with self.database.session() as session:
            record = await session.get(PluginRegistry, "builtin.core-tools")
        return True if record is None else bool(record.enabled)

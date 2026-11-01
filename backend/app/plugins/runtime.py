"""第三方插件运行时契约（当前不提供实现）。

本版本仍只登记清单，绝不加载或执行第三方代码。未来开放执行前，下列条件必须同时满足；
缺任何一项都不得把插件标记为可执行。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from app.core.errors import planned

# 固定顺序，前端可直接按列表展示。state 只用于表达“要求存在/尚未实现”，不是运行时开关。
PLUGIN_RUNTIME_REQUIREMENTS: dict[str, dict[str, str]] = {
    "sandbox": {
        "state": "planned",
        "note": "第三方代码必须在独立进程或容器中执行，与后端主进程隔离。",
    },
    "permission_manifest": {
        "state": "required",
        "note": "清单必须声明最小权限；未声明权限一律拒绝。",
    },
    "user_confirmation": {
        "state": "required",
        "note": "首次启用与每次高风险执行都需要管理员明确确认。",
    },
    "signature_verification": {
        "state": "planned",
        "note": "必须验证来源与签名；未签名或校验失败的插件不得执行。",
    },
    "timeout": {
        "state": "planned",
        "note": "每次调用必须设置超时并强制终止，不能无限等待。",
    },
    "resource_limits": {
        "state": "planned",
        "note": "必须限制内存、CPU、文件与网络资源，并禁止任意路径访问。",
    },
    "audit": {
        "state": "required",
        "note": "启用、授权、执行与停用都必须写审计（不含敏感载荷）。",
    },
    "disable": {
        "state": "planned",
        "note": "管理员停用后必须立即停止该插件的新任务并取消其运行中任务。",
    },
}


@dataclass(frozen=True)
class PluginExecutionRequest:
    plugin_id: str
    capability: str
    payload: dict[str, Any] = field(default_factory=dict)
    timeout_seconds: float = 5.0
    granted_permissions: tuple[str, ...] = ()


@dataclass(frozen=True)
class PluginExecutionResult:
    ok: bool
    content: str = ""
    error_code: str | None = None
    error_message: str | None = None


@runtime_checkable
class PluginRuntime(Protocol):
    async def execute(self, request: PluginExecutionRequest) -> PluginExecutionResult: ...


class UnavailablePluginRuntime:
    """显式不可用：调用会返回 OPERATION_PLANNED，而不是伪造执行结果。"""

    async def execute(self, request: PluginExecutionRequest) -> PluginExecutionResult:
        raise planned("第三方插件运行时")


def get_plugin_runtime() -> PluginRuntime:
    """未来替换为沙箱实现；当前始终返回诚实拒绝的占位。"""
    return UnavailablePluginRuntime()


def runtime_requirements() -> list[dict[str, str]]:
    return [
        {"key": key, "state": value["state"], "note": value["note"]}
        for key, value in PLUGIN_RUNTIME_REQUIREMENTS.items()
    ]

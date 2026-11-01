"""接入向导接口：状态只读聚合；唯一写操作需显式确认词并写审计。"""

from __future__ import annotations

from typing import Any

from app.api.deps import as_payload, get_actor, get_runtime
from app.core.errors import AppError, ErrorCode
from app.core.response import ok
from app.runtime import AppRuntime
from fastapi import APIRouter, Body, Depends

router = APIRouter()


@router.get("/onboarding")
async def onboarding(runtime: AppRuntime = Depends(get_runtime)) -> dict[str, Any]:
    return ok(await runtime.onboarding.build())


@router.post("/onboarding/actions/auto-configure-connector")
async def auto_configure_connector(
    payload: dict[str, Any] | None = Body(default=None),
    actor: str = Depends(get_actor),
    runtime: AppRuntime = Depends(get_runtime),
) -> dict[str, Any]:
    """为受管、可自动配置的连接器分配本地端口与随机 Token，并创建受管账号。

    不启动连接器、不登录 QQ、不连接实例；仅写入固定受管配置文件与加密凭证。
    """
    data = as_payload(payload)
    if str(data.get("confirm_text") or "").strip() != "AUTO CONFIG":
        raise AppError(
            ErrorCode.CONNECTOR_CONFIRMATION_REQUIRED,
            "自动配置需要输入确认词「AUTO CONFIG」；未执行任何动作。",
            status_code=400,
        )
    requested_id = data.get("installation_id")
    if requested_id is not None and not isinstance(requested_id, str):
        raise AppError(ErrorCode.VALIDATION_ERROR, "连接器安装标识必须为字符串。", status_code=400)

    installations = await runtime.connectors.list_installations(rescan=False)
    candidates = [
        item
        for item in installations
        if item.get("managed") is True
        and item.get("shell_installed") is True
        and item.get("auto_configure_allowed") is True
        and item.get("active_job") is None
    ]
    if requested_id:
        selected = next((item for item in candidates if item.get("id") == requested_id), None)
        if selected is None:
            raise AppError(
                ErrorCode.CONNECTOR_CONFIG_INVALID,
                "指定的连接器不存在、不可自动配置或当前正忙；请刷新连接器页后重试。",
                status_code=409,
            )
    elif len(candidates) == 1:
        selected = candidates[0]
    elif not candidates:
        raise AppError(
            ErrorCode.CONNECTOR_NOT_INSTALLED,
            "没有可自动配置的受管连接器；请先在连接器页下载并安装。",
            status_code=409,
        )
    else:
        raise AppError(
            ErrorCode.CONNECTOR_CONFIG_AMBIGUOUS,
            "检测到多个可自动配置的连接器；请在连接器页选择目标后重试。",
            status_code=409,
            details={"count": len(candidates)},
        )

    result = await runtime.connectors.apply_config(
        str(selected["id"]),
        actor=actor,
    )
    return ok(
        {
            **result,
            "installation_id": str(selected["id"]),
            "note": (
                "已写入受管连接器配置并创建关联账号；实例默认不自动连接。"
                "请由你在 NapCat 中完成 QQ 登录，再显式启动并确认身份。"
            ),
        }
    )

"""连接诊断编排：逐项收集证据，区分「连接/身份已验证」与「真实收发未验证」。"""

from __future__ import annotations

import time
from datetime import datetime
from typing import Any

from app.adapters.qq.base import BaseQQAdapter
from app.adapters.qq.mock import MockQQAdapter
from app.core.errors import AppError, ErrorCode
from app.core.time import utcnow
from app.schemas.connection import ConnectionDiagnostics, DiagnosticCheck

_REQUIRED_CHECK_IDS = {"config", "websocket", "auth", "identity", "action"}
_MAX_DISPLAY_GROUPS = 50
_IDENTITY_TIMEOUT_SECONDS = 8.0


def _elapsed_ms(started: float) -> int:
    return int((time.monotonic() - started) * 1000)


def _check(
    check_id: str,
    label: str,
    state: str,
    detail: str,
    *,
    error_code: str | None = None,
    duration_ms: int | None = None,
    next_step: str | None = None,
) -> DiagnosticCheck:
    return DiagnosticCheck(
        id=check_id,
        label=label,
        state=state,  # type: ignore[arg-type]
        detail=detail,
        error_code=error_code,
        duration_ms=duration_ms,
        next_step=next_step,
    )


def _sanitize_login(info: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(info, dict):
        return None
    user_id = info.get("user_id")
    nickname = info.get("nickname")
    if user_id is None and not nickname:
        return None
    result: dict[str, Any] = {}
    if user_id is not None:
        result["user_id"] = str(user_id)
    if isinstance(nickname, str) and nickname.strip():
        result["nickname"] = nickname.strip()[:64]
    return result or None


def _sanitize_groups(groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for item in groups[:_MAX_DISPLAY_GROUPS]:
        if not isinstance(item, dict) or item.get("group_id") is None:
            continue
        name = item.get("group_name")
        result.append(
            {
                "group_id": str(item["group_id"]),
                "group_name": name.strip()[:128] if isinstance(name, str) and name.strip() else None,
            }
        )
    return result


def _next_step_for_error(error_code: str | None) -> str:
    if error_code == ErrorCode.ADAPTER_AUTH_FAILED:
        return "检查连接器 Token 是否与控制台填写的一致，然后重新测试。"
    if error_code == ErrorCode.ADAPTER_REMOTE_FORBIDDEN:
        return "地址不是本机或私网。若确需公网连接，请显式开启「允许远程连接」并自行承担风险。"
    if error_code == ErrorCode.ADAPTER_IDENTITY_UNVERIFIED:
        return "确认连接器内的 QQ 已登录，并在 NapCat 中开启 get_login_info 相关接口后重新测试。"
    if error_code == ErrorCode.ADAPTER_CONNECT_FAILED:
        return "确认 NapCat 已启动、正向 WebSocket 已开启，并检查地址与端口。"
    return "修正配置后重新测试；如仍失败，请查看连接器日志。"


def failed_report(
    *,
    connection_mode: str,
    started_at: datetime,
    error_code: str | None,
    error_message: str,
    config_error: bool = False,
) -> ConnectionDiagnostics:
    """构建失败报告；配置错误不会尝试网络，连接错误会把失败落在对应检查项上。"""
    checks: list[DiagnosticCheck] = []
    if config_error:
        checks.append(
            _check(
                "config",
                "配置校验",
                "failed",
                error_message,
                error_code=error_code,
                next_step=_next_step_for_error(error_code),
            )
        )
        checks.append(_check("websocket", "WebSocket 握手", "skipped", "配置无效，未尝试连接。"))
    else:
        checks.append(_check("config", "配置校验", "ok", "地址格式与访问范围有效。"))
        checks.append(
            _check(
                "websocket",
                "WebSocket 握手",
                "failed",
                error_message,
                error_code=error_code,
                next_step=_next_step_for_error(error_code),
            )
        )
    checks.append(
        _check(
            "auth",
            "OneBot 鉴权",
            "failed" if error_code == ErrorCode.ADAPTER_AUTH_FAILED else "skipped",
            "鉴权失败，请检查 Token。" if error_code == ErrorCode.ADAPTER_AUTH_FAILED else "握手未完成，未测试鉴权。",
            error_code=ErrorCode.ADAPTER_AUTH_FAILED if error_code == ErrorCode.ADAPTER_AUTH_FAILED else None,
        )
    )
    for check_id, label in (
        ("identity", "QQ 登录身份"),
        ("action", "动作通道"),
        ("groups", "群列表读取"),
        ("event_stream", "事件流/心跳"),
    ):
        checks.append(_check(check_id, label, "skipped", "握手未完成，未执行该项。"))
    checks.append(_check("real_inbound", "真实入站消息", "not_verified", "连接失败，未观察到真实消息。"))
    checks.append(_check("real_outbound", "真实发送", "not_verified", "本测试不发送任何消息。"))
    return ConnectionDiagnostics(
        ok=False,
        state="failed",
        connection_mode=connection_mode,
        tested_at=started_at.isoformat(),
        latency_ms=int((utcnow() - started_at).total_seconds() * 1000),
        checks=checks,
        error_code=error_code,
        error_message=error_message,
        next_step=_next_step_for_error(error_code),
        unverified_scope=["connector_runtime", "real_inbound", "real_outbound"],
    )


async def run_connection_diagnostics(
    adapter: BaseQQAdapter,
    *,
    connection_mode: str,
    started_at: datetime,
    token_configured: bool,
) -> ConnectionDiagnostics:
    """对已连接的适配器执行诊断；不发送任何消息。"""
    is_mock = isinstance(adapter, MockQQAdapter)
    checks: list[DiagnosticCheck] = [
        _check("config", "配置校验", "ok", "连接方式与地址已通过本地校验。"),
    ]
    login: dict[str, Any] | None = None
    groups: list[dict[str, Any]] = []
    group_count = 0
    identity_ok = False
    action_ok = False
    groups_ok = False
    event_seen = False
    inbound_seen = False

    if is_mock:
        mock_info = _sanitize_login(await adapter.get_login_info())
        mock_groups = await adapter.get_group_list()
        login = {**(mock_info or {}), "source": "mock"}
        groups = _sanitize_groups(mock_groups)
        group_count = len(mock_groups)
        checks.extend(
            [
                _check("websocket", "WebSocket 握手", "skipped", "Mock 模式不建立真实 WebSocket。"),
                _check("auth", "OneBot 鉴权", "skipped", "Mock 模式没有真实鉴权。"),
                _check("identity", "QQ 登录身份", "ok", "Mock 本地身份，不连接真实 QQ。"),
                _check("action", "动作通道", "skipped", "Mock 模式没有真实动作通道。"),
                _check("groups", "群列表读取", "ok", f"Mock 演示群 {group_count} 个，不代表真实群。"),
                _check("event_stream", "事件流/心跳", "skipped", "Mock 模式不接收真实事件。"),
                _check("real_inbound", "真实入站消息", "not_verified", "Mock 模式没有真实 QQ 消息。"),
                _check("real_outbound", "真实发送", "not_verified", "Mock 模式不发送真实消息。"),
            ]
        )
        return ConnectionDiagnostics(
            ok=True,
            state="mock_only",
            connection_mode=connection_mode,
            is_mock=True,
            tested_at=started_at.isoformat(),
            latency_ms=int((utcnow() - started_at).total_seconds() * 1000),
            checks=checks,
            login=login,
            groups=groups,
            group_count=group_count,
            identity_verified=False,
            action_path_verified=False,
            group_list_verified=False,
            real_inbound_verified=False,
            real_outbound_verified=False,
            message_send_attempted=False,
            verified_scope=["mock_local"],
            unverified_scope=["real_qq", "connector_runtime", "real_inbound", "real_outbound"],
            next_step="Mock 测试不连接真实 QQ；请安装并登录连接器后填写 OneBot 地址。",
            note="Mock 测试通过不代表真实 QQ 能力可用，也不代表真实消息收发已验证。",
        )

    # 1. WebSocket 握手（能进入本函数说明 connect() 成功）
    checks.append(_check("websocket", "WebSocket 握手", "ok", "WebSocket 握手成功。"))

    # 2. 身份验证
    identity_started = time.monotonic()
    identity_error: str | None = None
    if adapter.status == "error" and adapter.last_error_code == ErrorCode.ADAPTER_AUTH_FAILED:
        identity_error = adapter.last_error_message or "身份查询鉴权失败。"
        checks.append(
            _check(
                "identity",
                "QQ 登录身份",
                "failed",
                identity_error,
                error_code=ErrorCode.ADAPTER_AUTH_FAILED,
                duration_ms=_elapsed_ms(identity_started),
                next_step=_next_step_for_error(ErrorCode.ADAPTER_AUTH_FAILED),
            )
        )
    else:
        try:
            info = await adapter.get_login_info()
        except AppError as exc:
            identity_error = exc.message
            checks.append(
                _check(
                    "identity",
                    "QQ 登录身份",
                    "failed",
                    exc.message,
                    error_code=exc.code,
                    duration_ms=_elapsed_ms(identity_started),
                    next_step=_next_step_for_error(exc.code),
                )
            )
        except Exception as exc:
            identity_error = f"身份查询异常（{type(exc).__name__}）。"
            checks.append(
                _check(
                    "identity",
                    "QQ 登录身份",
                    "failed",
                    identity_error,
                    error_code=ErrorCode.ADAPTER_IDENTITY_UNVERIFIED,
                    duration_ms=_elapsed_ms(identity_started),
                    next_step=_next_step_for_error(ErrorCode.ADAPTER_IDENTITY_UNVERIFIED),
                )
            )
        else:
            login = _sanitize_login(info)
            if login and login.get("user_id"):
                identity_ok = True
                checks.append(
                    _check(
                        "identity",
                        "QQ 登录身份",
                        "ok",
                        f"已读取登录账号 {login['user_id']}。",
                        duration_ms=_elapsed_ms(identity_started),
                    )
                )
            else:
                identity_error = "连接器未返回 QQ 账号，无法确认机器人身份。"
                checks.append(
                    _check(
                        "identity",
                        "QQ 登录身份",
                        "failed",
                        identity_error,
                        error_code=ErrorCode.ADAPTER_IDENTITY_UNVERIFIED,
                        duration_ms=_elapsed_ms(identity_started),
                        next_step=_next_step_for_error(ErrorCode.ADAPTER_IDENTITY_UNVERIFIED),
                    )
                )

    # 3. 鉴权（握手成功但无 Token 时只能给出警告）
    if not token_configured:
        checks.append(
            _check(
                "auth",
                "OneBot 鉴权",
                "warning",
                "未配置 Token，无法确认连接器是否强制鉴权。仅建议用于本机回环测试。",
                next_step="为连接器设置独立 Token，并在控制台填写。",
            )
        )
    elif identity_error and not identity_ok and adapter.last_error_code == ErrorCode.ADAPTER_AUTH_FAILED:
        checks.append(
            _check(
                "auth",
                "OneBot 鉴权",
                "failed",
                "连接器拒绝鉴权，请检查 Token。",
                error_code=ErrorCode.ADAPTER_AUTH_FAILED,
                next_step=_next_step_for_error(ErrorCode.ADAPTER_AUTH_FAILED),
            )
        )
    else:
        checks.append(_check("auth", "OneBot 鉴权", "ok", "Bearer Token 已被动作通道接受。"))

    # 4. 动作通道：无害探测，不发送消息
    if adapter.status == "error" and adapter.last_error_code == ErrorCode.ADAPTER_AUTH_FAILED:
        checks.append(
            _check(
                "action",
                "动作通道",
                "failed",
                "鉴权失败，未执行动作探测。",
                error_code=ErrorCode.ADAPTER_AUTH_FAILED,
                next_step=_next_step_for_error(ErrorCode.ADAPTER_AUTH_FAILED),
            )
        )
    else:
        action_started = time.monotonic()
        try:
            await adapter.probe_action()
        except AppError as exc:
            if identity_ok:
                checks.append(
                    _check(
                        "action",
                        "动作通道",
                        "warning",
                        f"无害动作探测未成功（{exc.code}），但身份查询已通过。",
                        error_code=exc.code,
                        duration_ms=_elapsed_ms(action_started),
                        next_step="连接器可能不支持 get_status；不影响发送，但建议确认动作接口版本。",
                    )
                )
            else:
                checks.append(
                    _check(
                        "action",
                        "动作通道",
                        "failed",
                        exc.message,
                        error_code=exc.code,
                        duration_ms=_elapsed_ms(action_started),
                        next_step=_next_step_for_error(exc.code),
                    )
                )
        except Exception as exc:
            checks.append(
                _check(
                    "action",
                    "动作通道",
                    "warning" if identity_ok else "failed",
                    f"动作探测异常（{type(exc).__name__}）。",
                    error_code=ErrorCode.ADAPTER_IDENTITY_UNVERIFIED,
                    duration_ms=_elapsed_ms(action_started),
                )
            )
        else:
            action_ok = True
            checks.append(
                _check(
                    "action",
                    "动作通道",
                    "ok",
                    "无害动作 get_status 已通过。",
                    duration_ms=_elapsed_ms(action_started),
                )
            )

    # 5. 群列表：失败降为 warning，不让整次诊断失败
    if identity_ok:
        groups_started = time.monotonic()
        try:
            raw_groups = await adapter.get_group_list()
        except AppError as exc:
            checks.append(
                _check(
                    "groups",
                    "群列表读取",
                    "warning",
                    f"群列表读取失败（{exc.code}），但身份已验证。",
                    error_code=exc.code,
                    duration_ms=_elapsed_ms(groups_started),
                    next_step="检查连接器是否允许读取群列表；不影响连接状态。",
                )
            )
        except Exception as exc:
            checks.append(
                _check(
                    "groups",
                    "群列表读取",
                    "warning",
                    f"群列表读取异常（{type(exc).__name__}），但身份已验证。",
                    duration_ms=_elapsed_ms(groups_started),
                )
            )
        else:
            groups = _sanitize_groups(raw_groups)
            group_count = len(raw_groups)
            groups_ok = True
            checks.append(
                _check(
                    "groups",
                    "群列表读取",
                    "ok",
                    f"读取到 {group_count} 个群。",
                    duration_ms=_elapsed_ms(groups_started),
                )
            )
    else:
        checks.append(_check("groups", "群列表读取", "skipped", "身份未验证，未尝试读取群列表。"))

    # 6. 事件流：只证明收到过连接器主动推送的事件，不证明真实消息
    last_event = getattr(adapter, "last_event_at", None)
    event_seen = last_event is not None and last_event >= started_at
    checks.append(
        _check(
            "event_stream",
            "事件流/心跳",
            "ok" if event_seen else "warning",
            "测试期间收到连接器事件帧。" if event_seen else "测试期间未收到心跳或事件帧。",
            next_step=None if event_seen else "确认连接器已开启心跳上报；这通常不影响动作调用。",
        )
    )

    # 7. 真实消息与发送：不得伪造
    inbound_seen = adapter.last_received_at is not None and adapter.last_received_at >= started_at
    checks.append(
        _check(
            "real_inbound",
            "真实入站消息",
            "ok" if inbound_seen else "not_verified",
            "测试期间收到真实消息。" if inbound_seen else "测试不等待真实群消息，未观察到入站消息。",
            next_step=None if inbound_seen else "在受控测试群发送一条消息，观察是否被记录。",
        )
    )
    checks.append(
        _check(
            "real_outbound",
            "真实发送",
            "not_verified",
            "本测试不发送任何消息。",
            next_step="在受控测试群完成一次人工确认的发送验收。",
        )
    )

    failed = any(c.state == "failed" and c.id in _REQUIRED_CHECK_IDS for c in checks)
    verified = identity_ok and not failed
    state = "identity_verified" if verified else "failed"
    first_problem = next((c for c in checks if c.state == "failed"), None)
    first_warning = next((c for c in checks if c.state == "warning"), None)
    verified_scope = [c.id for c in checks if c.state == "ok" and c.id in _REQUIRED_CHECK_IDS]
    if groups_ok:
        verified_scope.append("groups")
    if event_seen:
        verified_scope.append("event_stream")
    next_step = (
        first_problem.next_step
        if first_problem is not None and first_problem.next_step
        else first_warning.next_step
        if first_warning is not None and first_warning.next_step
        else "在真实环境中完成受控消息收发验收；自动化诊断不能代替该步骤。"
    )
    return ConnectionDiagnostics(
        ok=verified,
        state=state,  # type: ignore[arg-type]
        connection_mode=connection_mode,
        tested_at=started_at.isoformat(),
        latency_ms=int((utcnow() - started_at).total_seconds() * 1000),
        checks=checks,
        login=login,
        groups=groups,
        group_count=group_count,
        identity_verified=identity_ok,
        action_path_verified=action_ok,
        group_list_verified=groups_ok,
        real_inbound_verified=inbound_seen,
        real_outbound_verified=False,
        message_send_attempted=False,
        verified_scope=verified_scope,
        unverified_scope=["connector_runtime", "real_inbound", "real_outbound"],
        error_code=first_problem.error_code if first_problem is not None else None,
        error_message=first_problem.detail if first_problem is not None else None,
        next_step=next_step,
    )

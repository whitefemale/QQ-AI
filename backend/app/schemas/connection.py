"""连接诊断的数据结构：分项证据，明确「已验证范围」与「未验证范围」。"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

ConnectionCheckState = Literal["ok", "warning", "failed", "skipped", "not_verified"]
DiagnosticsState = Literal["failed", "identity_verified", "mock_only"]


class DiagnosticCheck(BaseModel):
    id: str
    label: str
    state: ConnectionCheckState
    detail: str
    error_code: str | None = None
    duration_ms: int | None = None
    next_step: str | None = None
    source: str = "live_diagnostic"


class ConnectionDiagnostics(BaseModel):
    """一次连接诊断的完整结果。

    ``ok`` 只代表配置文件、握手、鉴权、身份与动作通道检查通过；
    它不代表真实 QQ 入站消息或出站发送已验证。
    """

    ok: bool
    state: DiagnosticsState
    connection_mode: str
    is_mock: bool = False
    tested_at: str
    latency_ms: int
    checks: list[DiagnosticCheck] = Field(default_factory=list)
    login: dict[str, Any] | None = None
    groups: list[dict[str, Any]] = Field(default_factory=list)
    group_count: int = 0
    identity_verified: bool = False
    action_path_verified: bool = False
    group_list_verified: bool = False
    real_inbound_verified: bool = False
    real_outbound_verified: bool = False
    message_send_attempted: bool = False
    verified_scope: list[str] = Field(default_factory=list)
    unverified_scope: list[str] = Field(default_factory=lambda: ["connector_runtime", "real_inbound", "real_outbound"])
    error_code: str | None = None
    error_message: str | None = None
    next_step: str | None = None
    note: str = "连接与身份检查不等于真实 QQ 群消息收发验证；本测试不发送任何消息。"

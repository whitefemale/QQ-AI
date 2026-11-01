"""QQ 适配器工厂注册表。

新增连接方式只需实现 BaseQQAdapter 并在此注册，不需要修改消息流水线。
工厂只负责构造对象；连接、身份确认、收发与审计仍由运行时服务负责。
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from app.adapters.qq.base import BaseQQAdapter
from app.adapters.qq.mock import MockQQAdapter
from app.adapters.qq.onebot11 import OneBot11Adapter
from app.core.errors import AppError, ErrorCode


@dataclass(frozen=True)
class QQAdapterRequest:
    instance_id: str
    account_id: str
    endpoint: str | None = None
    api_endpoint: str | None = None
    token: str | None = None
    allow_remote: bool = False
    self_id: str | None = None


@dataclass(frozen=True)
class QQAdapterSpec:
    mode: str
    label: str
    builder: Callable[[QQAdapterRequest], BaseQQAdapter]
    available: bool = True
    state: str = "available"
    note: str = ""

    def public(self) -> dict[str, object]:
        return {
            "value": self.mode,
            "label": self.label,
            "available": self.available,
            "state": self.state,
            "note": self.note,
        }


class QQAdapterFactory:
    def __init__(self) -> None:
        self._specs: dict[str, QQAdapterSpec] = {}

    def register(self, spec: QQAdapterSpec) -> None:
        if not spec.mode:
            raise ValueError("适配器连接方式不能为空。")
        self._specs[spec.mode] = spec

    def get(self, mode: str) -> QQAdapterSpec | None:
        return self._specs.get(mode)

    def modes(self) -> list[dict[str, object]]:
        return [spec.public() for spec in self._specs.values()]

    def build(self, mode: str, request: QQAdapterRequest) -> BaseQQAdapter:
        spec = self.get(mode)
        if spec is None:
            raise AppError(
                ErrorCode.ADAPTER_CONNECT_FAILED,
                f"未知的连接方式「{mode}」。",
                status_code=400,
            )
        if not spec.available:
            raise AppError(
                ErrorCode.OPERATION_PLANNED,
                spec.note or "该连接方式尚未实现。",
                status_code=501,
            )
        return spec.builder(request)


def _build_mock(request: QQAdapterRequest) -> BaseQQAdapter:
    return MockQQAdapter(
        instance_id=request.instance_id,
        account_id=request.account_id,
        endpoint=request.endpoint,
        self_id=request.self_id or "10000",
    )


def _build_onebot11(request: QQAdapterRequest) -> BaseQQAdapter:
    if not request.endpoint:
        raise AppError(
            ErrorCode.ADAPTER_CONNECT_FAILED,
            "请填写 OneBot 11 WebSocket 地址（例如 ws://127.0.0.1:3001）。",
            status_code=400,
        )
    return OneBot11Adapter(
        instance_id=request.instance_id,
        account_id=request.account_id,
        endpoint=request.endpoint,
        api_endpoint=request.api_endpoint,
        token=request.token,
        allow_remote=request.allow_remote,
    )


def _build_planned(request: QQAdapterRequest) -> BaseQQAdapter:
    raise AppError(
        ErrorCode.OPERATION_PLANNED,
        "官方 QQ 机器人接入尚未实现，当前版本仅预留接口。",
        status_code=501,
    )


def build_default_qq_adapter_factory() -> QQAdapterFactory:
    factory = QQAdapterFactory()
    factory.register(
        QQAdapterSpec(
            mode="mock",
            label="Mock 连接器（本地演示）",
            builder=_build_mock,
            note="不会连接真实 QQ。",
        )
    )
    factory.register(
        QQAdapterSpec(
            mode="onebot11",
            label="OneBot 11（NapCat 等）",
            builder=_build_onebot11,
            note="需用户自行安装并登录连接器；默认只允许本机/内网地址。",
        )
    )
    factory.register(
        QQAdapterSpec(
            mode="official",
            label="官方 QQ 机器人",
            builder=_build_planned,
            available=False,
            state="planned",
            note="尚未实现，仅为规划占位。",
        )
    )
    return factory

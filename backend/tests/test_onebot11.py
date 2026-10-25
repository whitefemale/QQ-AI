"""OneBot 11 适配器测试：消息段解析、地址安全、进程内假 WS/HTTP 服务器收发。

全部使用本机回环地址与假服务器，不接触真实 QQ 或真实连接器。
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
import pytest_asyncio
from app.adapters.qq.onebot11 import (
    OneBot11Adapter,
    parse_onebot_segments,
    validate_onebot_endpoints,
)
from app.core.errors import AppError, ErrorCode
from websockets.asyncio.server import ServerConnection, serve

GROUP_EVENT: dict[str, Any] = {
    "post_type": "message",
    "message_type": "group",
    "message_id": 9001,
    "group_id": 100001,
    "user_id": 20001,
    "self_id": 10000,
    "time": int(datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC).timestamp()),
    "sender": {"user_id": 20001, "nickname": "测试群友", "card": "群名片"},
    "message": [
        {"type": "reply", "data": {"id": "8000"}},
        {"type": "at", "data": {"qq": "10000", "name": "AI 群友"}},
        {"type": "text", "data": {"text": " 你好"}},
        {"type": "image", "data": {"file": "abc.jpg", "url": "http://127.0.0.1/x.jpg"}},
    ],
    "raw_message": "[CQ:at,qq=10000] 你好",
}


class FakeOneBotServer:
    """最小 OneBot 11 假服务器：连接后推送事件，并对动作返回 echo 响应。"""

    def __init__(self, *, initial_events: list[dict[str, Any]] | None = None) -> None:
        self.initial_events = list(initial_events or [])
        self.actions: list[dict[str, Any]] = []
        self.authorization: str | None = None
        self.port: int | None = None

    async def handler(self, connection: ServerConnection) -> None:
        self.authorization = connection.request.headers.get("Authorization")
        for event in self.initial_events:
            await connection.send(json.dumps(event, ensure_ascii=False))
        async for raw in connection:
            payload = json.loads(raw)
            self.actions.append(payload)
            action = payload.get("action")
            if action == "get_login_info":
                data: Any = {"user_id": 10000, "nickname": "Fake Bot"}
            elif action == "get_group_list":
                data = [{"group_id": 100001, "group_name": "假服务器群"}]
            else:
                data = {"message_id": 777}
            await connection.send(
                json.dumps(
                    {
                        "status": "ok",
                        "retcode": 0,
                        "data": data,
                        "echo": payload.get("echo"),
                    }
                )
            )

    @property
    def ws_url(self) -> str:
        assert self.port is not None
        return f"ws://127.0.0.1:{self.port}"


@pytest_asyncio.fixture
async def fake_server() -> AsyncIterator[FakeOneBotServer]:
    fake = FakeOneBotServer(
        initial_events=[
            {
                "post_type": "meta_event",
                "meta_event_type": "heartbeat",
                "self_id": 10000,
                "interval": 5000,
            },
            GROUP_EVENT,
        ]
    )
    async with serve(fake.handler, "127.0.0.1", 0, ping_interval=None) as server:
        sockets = server.sockets
        assert sockets
        fake.port = sockets[0].getsockname()[1]
        yield fake


# ---------------------------------------------------------------- 纯解析逻辑


def test_parse_segments_maps_protocol_types() -> None:
    segments, mentions, reply_to = parse_onebot_segments(GROUP_EVENT["message"])
    types = [segment.type for segment in segments]
    assert types == ["reply", "mention", "text", "image"]
    assert mentions == ["10000"]
    assert reply_to == "8000"
    assert segments[2].text == " 你好"
    assert segments[3].metadata["media_type"] == "image"
    assert segments[3].media_ref is None


def test_parse_segments_keeps_unknown_types() -> None:
    segments, mentions, _ = parse_onebot_segments(
        [{"type": "face", "data": {"id": "14", "raw": "微笑"}}, {"type": "mystery", "data": {}}]
    )
    assert segments[0].type == "sticker"
    assert segments[0].metadata["face_id"] == "14"
    assert segments[1].type == "unknown"
    assert segments[1].metadata["onebot_type"] == "mystery"
    assert mentions == []


def test_parse_segments_never_returns_empty() -> None:
    segments, _, _ = parse_onebot_segments([])
    assert len(segments) == 1
    assert segments[0].type == "unknown"


def test_public_endpoint_requires_explicit_consent() -> None:
    with pytest.raises(AppError) as excinfo:
        validate_onebot_endpoints("ws://8.8.8.8:3001", None, allow_remote=False)
    assert excinfo.value.code == ErrorCode.ADAPTER_REMOTE_FORBIDDEN

    ws_url, _ = validate_onebot_endpoints("ws://8.8.8.8:3001", "https://8.8.8.8:3000", allow_remote=True)
    assert ws_url == "ws://8.8.8.8:3001"


def test_localhost_http_endpoint_is_converted_to_ws() -> None:
    ws_url, http_url = validate_onebot_endpoints("http://127.0.0.1:3001", "http://127.0.0.1:3000", allow_remote=False)
    assert ws_url == "ws://127.0.0.1:3001"
    assert http_url == "http://127.0.0.1:3000"


def test_invalid_scheme_is_rejected() -> None:
    with pytest.raises(AppError) as excinfo:
        validate_onebot_endpoints("ftp://127.0.0.1:3001", None, allow_remote=False)
    assert excinfo.value.code == ErrorCode.ADAPTER_CONNECT_FAILED


# ---------------------------------------------------------------- WS 收发


@pytest.mark.asyncio
async def test_ws_receives_event_and_sends_reply(fake_server: FakeOneBotServer) -> None:
    adapter = OneBot11Adapter(
        instance_id="onebot-test",
        account_id="account-test",
        endpoint=fake_server.ws_url,
        token="secret-token",
    )
    try:
        await adapter.connect()
        assert adapter.status == "online"
        assert fake_server.authorization == "Bearer secret-token"

        message = await asyncio.wait_for(adapter.next_event(), timeout=5)
        assert message.message_id == "9001"
        assert message.conversation_id == "100001"
        assert message.conversation_type == "group"
        assert message.sender_id == "20001"
        assert message.sender_name == "群名片"
        assert message.mentions == ["10000"]
        assert message.reply_to_message_id == "8000"
        assert message.is_self_message is False
        assert message.segments[-1].type == "image"
        assert message.segments[-1].media_ref is None

        sent = await adapter.send_text("100001", "你好呀", conversation_type="group", reply_to_message_id="9001")
        assert sent.platform_message_id == "777"
        assert sent.status == "sent"

        action = next(item for item in fake_server.actions if item["action"] == "send_group_msg")
        assert action["params"]["group_id"] == 100001
        assert action["params"]["message"] == [
            {"type": "reply", "data": {"id": "9001"}},
            {"type": "text", "data": {"text": "你好呀"}},
        ]
        assert adapter.last_sent_at is not None
    finally:
        await adapter.disconnect()
    assert adapter.status == "disconnected"


@pytest.mark.asyncio
async def test_ws_connect_failure_raises_clear_error() -> None:
    adapter = OneBot11Adapter(
        instance_id="onebot-fail",
        account_id="account-test",
        endpoint="ws://127.0.0.1:9",
    )
    with pytest.raises(AppError) as excinfo:
        await adapter.connect()
    assert excinfo.value.code == ErrorCode.ADAPTER_CONNECT_FAILED
    assert adapter.status == "error"
    await adapter.disconnect()


# ---------------------------------------------------------------- HTTP 动作


def _http_adapter(handler: Any) -> tuple[OneBot11Adapter, httpx.AsyncClient]:
    adapter = OneBot11Adapter(
        instance_id="onebot-http",
        account_id="account-test",
        endpoint="ws://127.0.0.1:3001",
        api_endpoint="http://127.0.0.1:3000",
        token="api-token",
    )
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    adapter._http = client
    return adapter, client


@pytest.mark.asyncio
async def test_http_send_group_message() -> None:
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, json={"status": "ok", "retcode": 0, "data": {"message_id": 12345}})

    adapter, client = _http_adapter(handler)
    try:
        sent = await adapter.send_text("100001", "HTTP 回复")
        assert sent.platform_message_id == "12345"
        request = captured[0]
        assert str(request.url) == "http://127.0.0.1:3000/send_group_msg"
        assert request.headers["Authorization"] == "Bearer api-token"
        body = json.loads(request.content)
        assert body["group_id"] == 100001
        assert body["message"] == [{"type": "text", "data": {"text": "HTTP 回复"}}]
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_http_retcode_failure_is_classified() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"status": "failed", "retcode": 1404, "data": None})

    adapter, client = _http_adapter(handler)
    try:
        with pytest.raises(AppError) as excinfo:
            await adapter.send_text("100001", "不会成功")
        assert excinfo.value.code == ErrorCode.SEND_FAILED
        assert excinfo.value.retryable is False
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_http_timeout_marks_send_status_unknown() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timeout", request=request)

    adapter, client = _http_adapter(handler)
    try:
        with pytest.raises(AppError) as excinfo:
            await adapter.send_text("100001", "超时")
        assert excinfo.value.code == ErrorCode.SEND_STATUS_UNKNOWN
        assert excinfo.value.retryable is False
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_http_auth_failure_sets_error_status() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"status": "failed", "retcode": 100})

    adapter, client = _http_adapter(handler)
    try:
        with pytest.raises(AppError) as excinfo:
            await adapter.get_login_info()
        assert excinfo.value.code == ErrorCode.ADAPTER_AUTH_FAILED
        assert adapter.status == "error"
    finally:
        await client.aclose()

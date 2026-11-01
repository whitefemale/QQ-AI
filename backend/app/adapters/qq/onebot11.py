"""OneBot 11 适配器：WebSocket 接收事件，HTTP / WS action 发送消息。

安全边界：
- 软件不登录 QQ、不接触 QQ 密码；账号由用户自行在连接器（如 NapCat）中登录。
- 连接地址默认只允许回环或私网；公网地址必须显式开启 allow_remote。
- Token 只保存在内存与加密字段中，不写入日志、不回显。
- 收到的事件一律视为不可信数据，只做结构解析，不执行其中任何内容。
"""

from __future__ import annotations

import asyncio
import ipaddress
import json
import logging
import time
import uuid
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlparse

import httpx
import websockets
from websockets.asyncio.client import ClientConnection
from websockets.exceptions import (
    ConnectionClosed,
    InvalidStatus,
    InvalidURI,
    WebSocketException,
)

from app.adapters.qq.base import AdapterCapabilities, BaseQQAdapter
from app.core.errors import AppError, ErrorCode
from app.core.time import iso_utc, utcnow
from app.schemas.message import CanonicalMessage, MessageSegment, SentMessage

logger = logging.getLogger(__name__)

_RECONNECT_MIN_SECONDS = 1.0
_RECONNECT_MAX_SECONDS = 30.0
_ACTION_TIMEOUT_SECONDS = 15.0
_IDENTITY_TIMEOUT_SECONDS = 8.0
_IDENTITY_RETRY_SECONDS = 10.0
_MAX_PAYLOAD_BYTES = 4 * 1024 * 1024

# 只有这些状态允许执行非发送动作；Online 本身不再作为动作通道的充分条件。
_ACTION_READY_STATUSES = {"connected_unverified", "online"}


def _parse_endpoint(url: str | None, label: str, *, websocket: bool) -> str | None:
    if url is None or not url.strip():
        return None
    value = url.strip()
    parsed = urlparse(value)
    allowed_schemes = {"ws", "wss"} if websocket else {"http", "https"}
    if parsed.scheme not in allowed_schemes:
        # 允许用户把 http(s) 填到 WS 位置，自动转换，减少配置错误。
        # 使用 _replace 而不是按字符串位置切片，避免大写的 HTTPS:// 变成 wsS://。
        if websocket and parsed.scheme in {"http", "https"}:
            target_scheme = "wss" if parsed.scheme == "https" else "ws"
            value = parsed._replace(scheme=target_scheme).geturl()
            parsed = urlparse(value)
        else:
            expected = "ws:// 或 wss://" if websocket else "http:// 或 https://"
            raise AppError(
                ErrorCode.ADAPTER_CONNECT_FAILED,
                f"{label} 必须以 {expected} 开头。",
                status_code=400,
            )
    if not parsed.hostname:
        raise AppError(ErrorCode.ADAPTER_CONNECT_FAILED, f"{label} 地址无效。", status_code=400)
    return value


def _host_allowed(host: str) -> bool:
    if host in {"localhost", "127.0.0.1", "::1"}:
        return True
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return False
    return address.is_loopback or address.is_private


def validate_onebot_endpoints(
    endpoint: str | None,
    api_endpoint: str | None,
    *,
    allow_remote: bool,
) -> tuple[str | None, str | None]:
    """校验并规范化 OneBot 地址；公网地址必须显式确认风险。"""
    ws_url = _parse_endpoint(endpoint, "WebSocket 地址", websocket=True)
    http_url = _parse_endpoint(api_endpoint, "HTTP API 地址", websocket=False)
    _ensure_allowed(ws_url, allow_remote=allow_remote, label="WebSocket 地址")
    _ensure_allowed(http_url, allow_remote=allow_remote, label="HTTP API 地址")
    return ws_url, http_url


def _ensure_allowed(url: str | None, *, allow_remote: bool, label: str) -> None:
    if not url:
        return
    host = urlparse(url).hostname
    if not host:
        raise AppError(ErrorCode.ADAPTER_CONNECT_FAILED, f"{label} 地址无效。", status_code=400)
    if _host_allowed(host):
        return
    if not allow_remote:
        raise AppError(
            ErrorCode.ADAPTER_REMOTE_FORBIDDEN,
            f"{label} 不是本机或私网地址。若确需公网连接，请显式开启「允许远程连接」并自行承担风险。",
            status_code=400,
            details={"label": label},
        )


def _id_value(value: str) -> int | str:
    return int(value) if value.isdigit() else value


def _text_of(value: Any, limit: int = 200) -> str:
    if not isinstance(value, str):
        return ""
    return value.strip()[:limit]


def _media_metadata(segment_type: str, data: dict[str, Any]) -> dict[str, Any]:
    """只保留安全的媒体元数据；不保存可能过期的 URL 或本地路径。"""
    metadata: dict[str, Any] = {"source": "onebot11", "media_type": segment_type}
    summary = _text_of(data.get("summary"))
    if summary:
        metadata["summary"] = summary
    if data.get("url") or data.get("file"):
        metadata["media_available"] = True
    if data.get("sub_type") is not None:
        metadata["sub_type"] = _text_of(str(data.get("sub_type")), limit=32)
    return metadata


def parse_onebot_segments(raw: Any) -> tuple[list[MessageSegment], list[str], str | None]:
    """解析 OneBot 11 消息段；未知类型保留为 unknown，绝不丢失消息结构。"""
    segments: list[MessageSegment] = []
    mentions: list[str] = []
    reply_to: str | None = None
    items = raw if isinstance(raw, list) else [raw]
    for item in items:
        if isinstance(item, str):
            if item:
                segments.append(MessageSegment(type="text", text=item))
            continue
        if not isinstance(item, dict):
            segments.append(MessageSegment(type="unknown", metadata={"reason": "invalid_segment"}))
            continue
        segment_type = str(item.get("type") or "unknown")
        raw_data: Any = item.get("data")
        data: dict[str, Any] = raw_data if isinstance(raw_data, dict) else {}
        if segment_type == "text":
            text = str(data.get("text") or "")
            if text:
                segments.append(MessageSegment(type="text", text=text))
        elif segment_type == "at":
            qq = str(data.get("qq") or "")
            is_all = qq == "all"
            name = _text_of(data.get("name"), limit=64) or ("全体成员" if is_all else qq)
            segments.append(MessageSegment(type="mention", text=name, metadata={"qq": qq, "all": is_all}))
            if qq:
                mentions.append(qq)
        elif segment_type == "reply":
            reply_id = str(data.get("id") or "")
            if reply_id:
                reply_to = reply_id
                segments.append(MessageSegment(type="reply", metadata={"id": reply_id}))
        elif segment_type == "face":
            name = _text_of(data.get("raw"), limit=32) or "表情"
            segments.append(
                MessageSegment(
                    type="sticker",
                    metadata={"face_id": str(data.get("id") or ""), "name": name},
                )
            )
        elif segment_type in {"image", "record", "video", "file"}:
            canonical = {
                "image": "image",
                "record": "audio",
                "video": "video",
                "file": "file",
            }[segment_type]
            segments.append(MessageSegment(type=canonical, metadata=_media_metadata(segment_type, data)))  # type: ignore[arg-type]
        else:
            segments.append(
                MessageSegment(
                    type="unknown",
                    metadata={"onebot_type": _text_of(segment_type, limit=32)},
                )
            )
    if not segments:
        segments.append(MessageSegment(type="unknown", metadata={"reason": "empty_message"}))
    return segments, mentions, reply_to


class OneBot11Adapter(BaseQQAdapter):
    adapter_type = "onebot11"

    def __init__(
        self,
        *,
        instance_id: str,
        account_id: str,
        endpoint: str,
        token: str | None = None,
        allow_remote: bool = False,
        api_endpoint: str | None = None,
    ) -> None:
        ws_url, api_url = validate_onebot_endpoints(
            endpoint,
            api_endpoint,
            allow_remote=allow_remote,
        )
        if ws_url is None:
            raise AppError(ErrorCode.ADAPTER_CONNECT_FAILED, "请填写 OneBot 11 WebSocket 地址。", status_code=400)
        super().__init__(
            instance_id=instance_id,
            account_id=account_id,
            endpoint=ws_url,
            token=token,
            allow_remote=allow_remote,
        )
        self.api_endpoint = api_url
        self._ws: ClientConnection | None = None
        self._http: httpx.AsyncClient | None = None
        self._supervisor: asyncio.Task[None] | None = None
        self._pending: dict[str, asyncio.Future[dict[str, Any]]] = {}
        self._closing = False
        self._reconnect_delay = _RECONNECT_MIN_SECONDS
        self.connected_at: datetime | None = None
        # 只由连接器主动推送的事件帧更新，不包含动作响应 echo。
        self.last_event_at: datetime | None = None
        # 身份验证：WS 握手成功只代表传输可用，必须拿到 get_login_info 的 user_id
        # 才能进入 online。epoch 用来丢弃旧连接上迟到的身份查询结果。
        self._identity_verified = False
        self._identity_verified_at: datetime | None = None
        self._identity_task: asyncio.Task[None] | None = None
        self._identity_last_attempt_at: datetime | None = None
        self._connection_epoch = 0

    def capabilities(self) -> AdapterCapabilities:
        # 只声明协议层面确定的能力；图片/语音回复未实现，因此为 False。
        return AdapterCapabilities(
            receive_group_message=True,
            receive_private_message=True,
            send_text=True,
            send_image=False,
            send_reply=True,
            mention_support=True,
            group_member_info=False,
            group_list=True,
            message_recall_event=False,
            file_upload=False,
            voice_message=False,
            video_message=False,
            typing_indicator=False,
            official_api=False,
        )

    @property
    def online(self) -> bool:
        return self.status == "online" and self._identity_verified and self._ws is not None

    def _headers(self) -> dict[str, str]:
        if self.token:
            return {"Authorization": f"Bearer {self.token}"}
        return {}

    async def _open_ws(self) -> None:
        assert self.endpoint is not None
        ws = await websockets.connect(
            self.endpoint,
            additional_headers=self._headers(),
            open_timeout=10,
            close_timeout=5,
            ping_interval=20,
            ping_timeout=20,
            max_size=_MAX_PAYLOAD_BYTES,
        )
        self._ws = ws
        self.connected_at = utcnow()
        # 心跳时间只由真实收到的帧更新；握手成功不等于收到心跳。
        self.last_heartbeat_at = None
        self._connection_epoch += 1
        self._identity_verified = False
        self._identity_verified_at = None
        self._identity_last_attempt_at = None

    async def connect(self) -> None:
        if self._supervisor is not None and not self._supervisor.done():
            return
        self._closing = False
        try:
            await self._open_ws()
        except InvalidStatus as exc:
            await self._set_status(
                "error",
                ErrorCode.ADAPTER_AUTH_FAILED,
                f"连接器拒绝了 WebSocket 握手（HTTP {exc.response.status_code}），请检查 Token。",
            )
            raise AppError(
                ErrorCode.ADAPTER_AUTH_FAILED,
                "连接器拒绝连接：Token 可能错误或未配置。",
                status_code=401,
            ) from exc
        except (InvalidURI, ValueError) as exc:
            await self._set_status("error", ErrorCode.ADAPTER_CONNECT_FAILED, "WebSocket 地址格式无效。")
            raise AppError(ErrorCode.ADAPTER_CONNECT_FAILED, "WebSocket 地址格式无效。", status_code=400) from exc
        except (OSError, WebSocketException, TimeoutError) as exc:
            await self._set_status(
                "error",
                ErrorCode.ADAPTER_CONNECT_FAILED,
                "无法连接连接器，请确认 NapCat 已启动并开启正向 WebSocket。",
            )
            raise AppError(
                ErrorCode.ADAPTER_CONNECT_FAILED,
                "无法连接到 OneBot WebSocket，请检查地址、端口与连接器状态。",
                status_code=502,
                details={"reason": type(exc).__name__},
            ) from exc
        self._reconnect_delay = _RECONNECT_MIN_SECONDS
        await self._set_status("connected_unverified")
        self._supervisor = asyncio.create_task(self._receive_loop(), name=f"onebot11-recv-{self.instance_id}")
        # 初始连接等待一次身份探测，保持 connect() 返回时状态已确定的语义。
        task = self._schedule_identity_check(force=True)
        if task is not None:
            try:
                await task
            except asyncio.CancelledError:
                if self._closing:
                    return
                raise
        logger.info("OneBot11 WebSocket 已连接", extra={"adapter_instance_id": self.instance_id})

    def _invalidate_identity(self) -> asyncio.Task[None] | None:
        """连接失效时递增 epoch，确保旧连接上迟到的身份结果被丢弃。"""
        self._identity_verified = False
        self._identity_verified_at = None
        self._connection_epoch += 1
        task = self._identity_task
        self._identity_task = None
        if task is not None and not task.done() and task is not asyncio.current_task():
            task.cancel()
        return task

    def _schedule_identity_check(self, *, force: bool = False) -> asyncio.Task[None] | None:
        if self._closing or self._ws is None:
            return None
        if self._identity_task is not None and not self._identity_task.done():
            return self._identity_task
        now = utcnow()
        if not force and self._identity_last_attempt_at is not None:
            elapsed = (now - self._identity_last_attempt_at).total_seconds()
            if elapsed < _IDENTITY_RETRY_SECONDS:
                return None
        self._identity_last_attempt_at = now
        task = asyncio.create_task(
            self._verify_identity(self._connection_epoch),
            name=f"onebot11-identity-{self.instance_id}",
        )
        self._identity_task = task
        return task

    async def _verify_identity(self, epoch: int) -> None:
        try:
            info = await asyncio.wait_for(self.get_login_info(), timeout=_IDENTITY_TIMEOUT_SECONDS)
        except asyncio.CancelledError:
            raise
        except TimeoutError:
            await self._identity_failed(epoch, "连接器未在 8 秒内返回登录账号。")
            return
        except AppError as exc:
            if exc.code == ErrorCode.ADAPTER_AUTH_FAILED:
                await self._identity_auth_failed(epoch, exc.message)
            else:
                await self._identity_failed(epoch, exc.message)
            return
        except Exception as exc:  # 不让身份查询异常打断接收循环
            logger.exception("OneBot11 身份查询异常", extra={"adapter_instance_id": self.instance_id})
            await self._identity_failed(epoch, f"身份查询异常（{type(exc).__name__}）。")
            return
        if epoch != self._connection_epoch or self._closing or self._ws is None:
            return
        user_id = info.get("user_id") if isinstance(info, dict) else None
        if user_id is None:
            await self._identity_failed(epoch, "连接器已连接，但 get_login_info 未返回 QQ 账号，无法确认机器人身份。")
            return
        self.self_platform_user_id = str(user_id)
        self._identity_verified = True
        self._identity_verified_at = utcnow()
        await self._set_status("online")
        logger.info(
            "OneBot11 身份已验证",
            extra={"adapter_instance_id": self.instance_id, "self_platform_user_id": self.self_platform_user_id},
        )

    async def _identity_failed(self, epoch: int, message: str) -> None:
        if epoch != self._connection_epoch or self._closing:
            return
        self._identity_verified = False
        await self._set_status("connected_unverified", ErrorCode.ADAPTER_IDENTITY_UNVERIFIED, message)

    async def _identity_auth_failed(self, epoch: int, message: str) -> None:
        if epoch != self._connection_epoch or self._closing:
            return
        self._identity_verified = False
        await self._set_status("error", ErrorCode.ADAPTER_AUTH_FAILED, message)

    async def disconnect(self) -> None:
        self._closing = True
        identity_task = self._invalidate_identity()
        supervisor = self._supervisor
        self._supervisor = None
        for task in (identity_task, supervisor):
            if task is None:
                continue
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass
        self._fail_pending("连接已断开。")
        await self._close_ws()
        if self._http is not None:
            await self._http.aclose()
            self._http = None
        await self._set_status("disconnected")

    async def _close_ws(self) -> None:
        ws = self._ws
        self._ws = None
        if ws is None:
            return
        try:
            await ws.close()
        except Exception:
            pass

    def _fail_pending(self, message: str) -> None:
        pending = list(self._pending.values())
        self._pending.clear()
        for future in pending:
            if not future.done():
                future.set_exception(AppError(ErrorCode.ADAPTER_UNAVAILABLE, message, status_code=503, retryable=True))

    async def _receive_loop(self) -> None:
        while not self._closing:
            ws = self._ws
            if ws is None:
                await self._set_status(
                    "reconnecting",
                    self.last_error_code or ErrorCode.ADAPTER_CONNECT_FAILED,
                    self.last_error_message or "连接已中断，正在重连。",
                )
                await asyncio.sleep(self._reconnect_delay)
                self._reconnect_delay = min(self._reconnect_delay * 2, _RECONNECT_MAX_SECONDS)
                try:
                    await self._open_ws()
                except InvalidStatus as exc:
                    await self._set_status(
                        "reconnecting",
                        ErrorCode.ADAPTER_AUTH_FAILED,
                        f"重连握手被拒绝（HTTP {exc.response.status_code}），请检查 Token。",
                    )
                    continue
                except (OSError, WebSocketException, TimeoutError) as exc:
                    await self._set_status(
                        "reconnecting",
                        ErrorCode.ADAPTER_CONNECT_FAILED,
                        f"重连失败（{type(exc).__name__}），将继续尝试。",
                    )
                    continue
                self._reconnect_delay = _RECONNECT_MIN_SECONDS
                await self._set_status("connected_unverified")
                # 不能在接收循环内 await 动作，否则身份查询与响应读取会互相等待。
                self._schedule_identity_check(force=True)
                logger.info("OneBot11 重连成功，等待身份验证", extra={"adapter_instance_id": self.instance_id})
                continue
            try:
                raw = await ws.recv()
            except asyncio.CancelledError:
                raise
            except ConnectionClosed as exc:
                if self._closing:
                    return
                self._ws = None
                self._invalidate_identity()
                self._fail_pending("WebSocket 连接已关闭。")
                await self._set_status(
                    "reconnecting",
                    ErrorCode.ADAPTER_CONNECT_FAILED,
                    f"WebSocket 连接中断（{exc.code or 'closed'}），正在重连。",
                )
                continue
            except Exception as exc:
                if self._closing:
                    return
                self._ws = None
                self._invalidate_identity()
                self._fail_pending("WebSocket 连接异常。")
                await self._set_status(
                    "reconnecting",
                    ErrorCode.ADAPTER_CONNECT_FAILED,
                    f"WebSocket 读取异常（{type(exc).__name__}），正在重连。",
                )
                continue
            try:
                await self._handle_raw(raw)
            except Exception:
                logger.exception("处理 OneBot11 事件失败", extra={"adapter_instance_id": self.instance_id})
        self._fail_pending("连接器已停止。")
        await self._close_ws()

    async def _handle_raw(self, raw: str | bytes) -> None:
        if isinstance(raw, bytes):
            try:
                raw = raw.decode("utf-8")
            except UnicodeDecodeError:
                logger.warning("收到无法解码的 OneBot 事件", extra={"adapter_instance_id": self.instance_id})
                return
        try:
            payload = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            logger.warning("收到无效 JSON 事件", extra={"adapter_instance_id": self.instance_id})
            return
        if not isinstance(payload, dict):
            return
        self.last_heartbeat_at = utcnow()

        echo = payload.get("echo")
        if echo is not None and ("retcode" in payload or "status" in payload):
            future = self._pending.pop(str(echo), None)
            if future is not None and not future.done():
                future.set_result(payload)
            return

        self.last_event_at = utcnow()
        post_type = payload.get("post_type")
        if post_type == "meta_event":
            await self._handle_meta(payload)
            return
        if post_type != "message":
            # message_sent 是自身消息回显，业务已单独记录出站消息，忽略以免自激。
            return
        message = self._parse_message(payload)
        if message is None:
            return
        self.touch_received()
        self.queue_event(message)

    async def _handle_meta(self, payload: dict[str, Any]) -> None:
        meta_type = payload.get("meta_event_type")
        if meta_type == "heartbeat":
            self.last_heartbeat_at = utcnow()
            # 心跳只证明传输存活，不能证明 QQ 身份；未验证时最多触发节流重试。
            if self.status == "connected_unverified":
                self._schedule_identity_check()
            else:
                await self._notify_status()
        elif meta_type == "lifecycle":
            sub_type = payload.get("sub_type")
            if sub_type in {"enable", "connect"} and not self._closing:
                if self.status != "online":
                    await self._set_status("connected_unverified")
                    self._schedule_identity_check()
            elif sub_type == "disable" and not self._closing:
                self._invalidate_identity()
                await self._set_status("disconnected", error_message="连接器已断开。")

    def _parse_message(self, payload: dict[str, Any]) -> CanonicalMessage | None:
        message_type = payload.get("message_type")
        if message_type not in {"group", "private"}:
            return None
        message_id = str(payload.get("message_id") or "")
        if not message_id:
            return None
        raw_sender: Any = payload.get("sender")
        sender: dict[str, Any] = raw_sender if isinstance(raw_sender, dict) else {}
        user_id = str(payload.get("user_id") or sender.get("user_id") or "")
        if not user_id:
            return None
        conversation_type = "group" if message_type == "group" else "private"
        group_id = str(payload.get("group_id") or "")
        if conversation_type == "group" and not group_id:
            return None
        segments, mentions, reply_to = parse_onebot_segments(payload.get("message"))
        sender_name = _text_of(sender.get("card"), 64) or _text_of(sender.get("nickname"), 64) or None
        timestamp = payload.get("time")
        if isinstance(timestamp, (int, float)) and timestamp > 0:
            event_time = datetime.fromtimestamp(float(timestamp), tz=UTC)
        else:
            event_time = utcnow()
        self_id = self.self_platform_user_id or (
            str(payload.get("self_id")) if payload.get("self_id") is not None else None
        )
        return CanonicalMessage(
            platform="qq",
            account_id=self.account_id,
            message_id=message_id,
            conversation_id=group_id if conversation_type == "group" else user_id,
            conversation_type=conversation_type,  # type: ignore[arg-type]
            sender_id=user_id,
            sender_name=sender_name,
            segments=segments,
            reply_to_message_id=reply_to,
            mentions=mentions,
            timestamp=event_time,
            is_self_message=bool(self_id and user_id == self_id),
            source_adapter="onebot11",
            event_id=str(payload.get("event_id") or f"onebot:{self.instance_id}:{message_id}"),
        )

    def _get_http(self) -> httpx.AsyncClient:
        if self._http is None:
            self._http = httpx.AsyncClient(
                timeout=httpx.Timeout(15.0, connect=10.0),
                follow_redirects=False,
            )
        return self._http

    async def _action(self, action: str, params: dict[str, Any], *, send: bool = False) -> Any:
        if self.api_endpoint:
            return await self._http_action(action, params, send=send)
        return await self._ws_action(action, params, send=send)

    async def _http_action(self, action: str, params: dict[str, Any], *, send: bool) -> Any:
        assert self.api_endpoint is not None
        url = f"{self.api_endpoint.rstrip('/')}/{action}"
        try:
            response = await self._get_http().post(url, json=params, headers=self._headers())
        except httpx.ConnectError as exc:
            if send:
                raise AppError(
                    ErrorCode.SEND_FAILED,
                    "无法连接 OneBot HTTP API，消息未发送，可稍后重试。",
                    status_code=503,
                    retryable=True,
                ) from exc
            raise AppError(
                ErrorCode.ADAPTER_CONNECT_FAILED,
                "无法连接 OneBot HTTP API。",
                status_code=502,
                retryable=True,
            ) from exc
        except (httpx.TimeoutException, httpx.HTTPError) as exc:
            raise self._transport_error(send, type(exc).__name__) from exc
        if response.status_code in {401, 403}:
            message = "OneBot HTTP API 鉴权失败，请检查 Token。"
            await self._set_status("error", ErrorCode.ADAPTER_AUTH_FAILED, message)
            if send:
                raise AppError(ErrorCode.SEND_FAILED, message, status_code=401, retryable=False)
            raise AppError(ErrorCode.ADAPTER_AUTH_FAILED, message, status_code=401)
        if response.status_code >= 400:
            message = f"OneBot HTTP API 返回 HTTP {response.status_code}。"
            if send:
                raise AppError(
                    ErrorCode.SEND_FAILED,
                    message,
                    status_code=502,
                    retryable=response.status_code >= 500,
                )
            raise AppError(ErrorCode.ADAPTER_CONNECT_FAILED, message, status_code=502)
        try:
            payload = response.json()
        except ValueError as exc:
            raise self._transport_error(send, "invalid_json") from exc
        return self._unwrap(payload, send=send)

    def _unwrap(self, payload: Any, *, send: bool) -> Any:
        if not isinstance(payload, dict):
            if send:
                raise AppError(
                    ErrorCode.SEND_STATUS_UNKNOWN,
                    "OneBot 返回了无法识别的响应，发送状态未知，已停止重发。",
                    status_code=504,
                )
            raise AppError(ErrorCode.ADAPTER_CONNECT_FAILED, "OneBot 返回了无法识别的响应。", status_code=502)
        retcode = payload.get("retcode")
        failed = payload.get("status") == "failed" or (retcode is not None and retcode not in {0, "0"})
        if not failed:
            return payload.get("data")
        retcode_text = str(retcode)
        message = f"OneBot 操作失败（retcode={retcode_text}）。"
        if send:
            retryable = retcode_text in {"100", "1200", "1"}
            raise AppError(
                ErrorCode.SEND_FAILED,
                message,
                status_code=502,
                retryable=retryable,
                details={"retcode": retcode_text},
            )
        raise AppError(
            ErrorCode.ADAPTER_CONNECT_FAILED,
            message,
            status_code=502,
            retryable=True,
            details={"retcode": retcode_text},
        )

    def _transport_error(self, send: bool, reason: str) -> AppError:
        if send:
            return AppError(
                ErrorCode.SEND_STATUS_UNKNOWN,
                "OneBot 请求超时或连接中断，发送状态未知，已停止自动重发以避免重复。",
                status_code=504,
                details={"reason": reason},
            )
        return AppError(
            ErrorCode.ADAPTER_CONNECT_FAILED,
            "OneBot 请求超时或连接中断。",
            status_code=502,
            retryable=True,
            details={"reason": reason},
        )

    async def _ws_action(self, action: str, params: dict[str, Any], *, send: bool) -> Any:
        ws = self._ws
        if ws is None:
            if send:
                raise AppError(
                    ErrorCode.SEND_FAILED,
                    "OneBot WebSocket 当前未连接，消息未发送，可稍后重试。",
                    status_code=503,
                    retryable=True,
                )
            raise AppError(
                ErrorCode.ADAPTER_UNAVAILABLE,
                "OneBot WebSocket 当前未连接。",
                status_code=503,
                retryable=True,
            )
        if send:
            if not self.online:
                raise AppError(
                    ErrorCode.SEND_FAILED,
                    "OneBot 身份尚未验证，消息未发送，可稍后重试。",
                    status_code=503,
                    retryable=True,
                )
        elif self.status not in _ACTION_READY_STATUSES:
            raise AppError(
                ErrorCode.ADAPTER_UNAVAILABLE,
                "OneBot WebSocket 尚未就绪。",
                status_code=503,
                retryable=True,
            )
        echo = uuid.uuid4().hex
        loop = asyncio.get_running_loop()
        future: asyncio.Future[dict[str, Any]] = loop.create_future()
        self._pending[echo] = future
        try:
            await ws.send(json.dumps({"action": action, "params": params, "echo": echo}))
            payload = await asyncio.wait_for(future, timeout=_ACTION_TIMEOUT_SECONDS)
        except TimeoutError as exc:
            self._pending.pop(echo, None)
            if send:
                raise AppError(
                    ErrorCode.SEND_STATUS_UNKNOWN,
                    "OneBot 动作响应超时，发送状态未知，已停止自动重发以避免重复。",
                    status_code=504,
                ) from exc
            raise AppError(
                ErrorCode.ADAPTER_CONNECT_FAILED,
                "OneBot 动作响应超时。",
                status_code=504,
                retryable=True,
            ) from exc
        except (ConnectionClosed, WebSocketException) as exc:
            self._pending.pop(echo, None)
            if send:
                raise AppError(
                    ErrorCode.SEND_STATUS_UNKNOWN,
                    "发送时 WebSocket 连接中断，发送状态未知，已停止自动重发。",
                    status_code=504,
                ) from exc
            raise AppError(
                ErrorCode.ADAPTER_CONNECT_FAILED,
                "动作发送时 WebSocket 连接中断。",
                status_code=502,
                retryable=True,
            ) from exc
        except AppError:
            self._pending.pop(echo, None)
            raise
        return self._unwrap(payload, send=send)

    async def get_login_info(self) -> dict[str, Any] | None:
        data = await self._action("get_login_info", {})
        if isinstance(data, dict):
            return data
        return None

    async def probe_action(self) -> dict[str, Any]:
        """无害动作探测；只确认动作通道可用，不发送消息、不修改任何状态。"""
        data = await self._action("get_status", {})
        return data if isinstance(data, dict) else {}

    async def get_group_list(self) -> list[dict[str, Any]]:
        data = await self._action("get_group_list", {})
        if not isinstance(data, list):
            return []
        groups: list[dict[str, Any]] = []
        for item in data:
            if not isinstance(item, dict) or item.get("group_id") is None:
                continue
            groups.append(
                {
                    "group_id": str(item.get("group_id")),
                    "group_name": _text_of(item.get("group_name"), 128) or None,
                }
            )
        return groups

    async def send_text(
        self,
        conversation_id: str,
        text: str,
        *,
        conversation_type: str = "group",
        reply_to_message_id: str | None = None,
    ) -> SentMessage:
        if not text.strip():
            raise AppError(ErrorCode.SEND_FAILED, "回复内容为空，已取消发送。", status_code=400)
        # HTTP 动作不需要 WS 对象，但同样要求已完成身份验证。
        if not self._identity_verified or self.status != "online":
            raise AppError(
                ErrorCode.SEND_FAILED,
                "OneBot 身份尚未验证，消息未发送，可稍后重试。",
                status_code=503,
                retryable=True,
            )
        segments: list[dict[str, Any]] = []
        if reply_to_message_id:
            segments.append({"type": "reply", "data": {"id": reply_to_message_id}})
        segments.append({"type": "text", "data": {"text": text}})
        if conversation_type == "group":
            action = "send_group_msg"
            params: dict[str, Any] = {"group_id": _id_value(conversation_id), "message": segments}
        else:
            action = "send_private_msg"
            params = {"user_id": _id_value(conversation_id), "message": segments}
        data = await self._action(action, params, send=True)
        message_id: str | None = None
        if isinstance(data, dict) and data.get("message_id") is not None:
            message_id = str(data["message_id"])
        elif isinstance(data, (int, str)) and str(data):
            message_id = str(data)
        if not message_id:
            logger.warning(
                "OneBot 发送成功但未返回 message_id",
                extra={"adapter_instance_id": self.instance_id},
            )
            message_id = f"onebot-unconfirmed-{uuid.uuid4().hex[:12]}"
        self.touch_sent()
        # 发送成功不改变连接身份状态；online 只能由 get_login_info 成功产生。
        return SentMessage(
            platform_message_id=message_id,
            conversation_id=conversation_id,
            status="sent",
            raw={"adapter": "onebot11", "action": action},
        )

    async def health_check(self) -> dict[str, Any]:
        result = await super().health_check()
        heartbeat_age = (
            (utcnow() - self.last_heartbeat_at).total_seconds() if self.last_heartbeat_at is not None else None
        )
        result.update(
            {
                "mode": "onebot11",
                "api_endpoint_configured": bool(self.api_endpoint),
                "connected_at": self.connected_at.isoformat() if self.connected_at else None,
                "heartbeat_age_seconds": heartbeat_age,
                "identity_verified": self._identity_verified,
                "identity_verified_at": iso_utc(self._identity_verified_at),
                "self_platform_user_id": self.self_platform_user_id,
                "status_source": "adapter_process",
                "observed_at": iso_utc(utcnow()),
            }
        )
        return result

    async def test_round_trip(self) -> dict[str, Any]:
        """主动读一次登录信息，用于「测试连接」按钮，不发送任何消息。"""
        started = time.monotonic()
        info = await self.get_login_info()
        groups = await self.get_group_list()
        return {
            "ok": True,
            "login": info,
            "group_count": len(groups),
            "latency_ms": int((time.monotonic() - started) * 1000),
        }


__all__ = ["OneBot11Adapter", "parse_onebot_segments", "validate_onebot_endpoints"]

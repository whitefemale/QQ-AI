"""OneBot 11 进程内假服务器：仅本机回环，不接触真实 QQ/连接器。"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from websockets.asyncio.server import ServerConnection, serve


class FakeOneBotServer:
    def __init__(
        self,
        *,
        login: dict[str, Any] | None = None,
        groups: list[dict[str, Any]] | None = None,
        initial_events: list[dict[str, Any]] | None = None,
        action_failures: dict[str, int] | None = None,
        close_after_first_login: bool = False,
        delay_login: float = 0.0,
    ) -> None:
        self.login = {"user_id": 10000, "nickname": "Fake Bot"} if login is None else login
        self.groups = [{"group_id": 100001, "group_name": "假服务器群"}] if groups is None else groups
        self.initial_events = list(initial_events or [])
        self.action_failures = dict(action_failures or {})
        self.close_after_first_login = close_after_first_login
        self.delay_login = delay_login
        self.actions: list[dict[str, Any]] = []
        self.authorization: str | None = None
        self.connections = 0
        self.port: int | None = None
        self._closed_once = False

    async def handler(self, connection: ServerConnection) -> None:
        self.connections += 1
        self.authorization = connection.request.headers.get("Authorization")
        for event in self.initial_events:
            await connection.send(json.dumps(event, ensure_ascii=False))
        async for raw in connection:
            payload = json.loads(raw)
            self.actions.append(payload)
            action = payload.get("action")
            echo = payload.get("echo")
            if action in self.action_failures:
                await connection.send(
                    json.dumps(
                        {
                            "status": "failed",
                            "retcode": self.action_failures[action],
                            "data": None,
                            "echo": echo,
                        }
                    )
                )
                continue
            if action == "get_login_info":
                if self.delay_login:
                    await asyncio.sleep(self.delay_login)
                data: Any = self.login
            elif action == "get_group_list":
                data = self.groups
            elif action == "get_status":
                data = {"online": True, "good": True}
            else:
                data = {"message_id": 777}
            await connection.send(
                json.dumps({"status": "ok", "retcode": 0, "data": data, "echo": echo}, ensure_ascii=False)
            )
            if action == "get_login_info" and self.close_after_first_login and not self._closed_once:
                self._closed_once = True
                await connection.close()
                return

    @property
    def ws_url(self) -> str:
        assert self.port is not None
        return f"ws://127.0.0.1:{self.port}"

    def action_names(self) -> list[str]:
        return [str(item.get("action")) for item in self.actions]


@asynccontextmanager
async def fake_onebot(**kwargs: Any) -> AsyncIterator[FakeOneBotServer]:
    fake = FakeOneBotServer(**kwargs)
    async with serve(fake.handler, "127.0.0.1", 0, ping_interval=None) as server:
        sockets = server.sockets
        assert sockets
        fake.port = sockets[0].getsockname()[1]
        yield fake


def heartbeat_event(interval: int = 5000) -> dict[str, Any]:
    return {
        "post_type": "meta_event",
        "meta_event_type": "heartbeat",
        "self_id": 10000,
        "interval": interval,
    }

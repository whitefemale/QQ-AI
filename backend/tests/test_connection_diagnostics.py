"""连接身份门控与分项诊断：全部使用本机假服务器。"""

from __future__ import annotations

import asyncio
import json

import pytest
from app.adapters.qq.mock import MockQQAdapter
from app.adapters.qq.onebot11 import OneBot11Adapter
from app.core.errors import AppError, ErrorCode
from app.core.time import utcnow
from app.db.session import Database
from app.models.account import Account, AdapterInstance
from app.services.adapter_manager import AdapterManager, reset_stale_runtime_statuses
from app.services.connection_diagnostics import (
    failed_report,
    run_connection_diagnostics,
)
from tests.onebot_fakes import fake_onebot, heartbeat_event


def _adapter(fake: object) -> OneBot11Adapter:
    return OneBot11Adapter(
        instance_id="onebot-diagnostics",
        account_id="account-diagnostics",
        endpoint=fake.ws_url,  # type: ignore[attr-defined]
        token="secret-token",
    )


@pytest.mark.asyncio
async def test_identity_failure_keeps_connected_unverified() -> None:
    async with fake_onebot(login={}) as fake:
        adapter = _adapter(fake)
        try:
            await adapter.connect()
            assert adapter.status == "connected_unverified"
            assert adapter.online is False
            assert adapter.last_error_code == ErrorCode.ADAPTER_IDENTITY_UNVERIFIED
            with pytest.raises(AppError) as excinfo:
                await adapter.send_text("100001", "不应发送")
            assert excinfo.value.code == ErrorCode.SEND_FAILED
            assert excinfo.value.retryable is True
            assert "send_group_msg" not in fake.action_names()
            assert AdapterManager._is_online(adapter) is False
        finally:
            await adapter.disconnect()


@pytest.mark.asyncio
async def test_heartbeat_does_not_promote_unverified_identity() -> None:
    async with fake_onebot(login={}, initial_events=[heartbeat_event()]) as fake:
        adapter = _adapter(fake)
        try:
            await adapter.connect()
            await asyncio.sleep(0.2)
            assert adapter.status == "connected_unverified"
            assert adapter.online is False
        finally:
            await adapter.disconnect()


@pytest.mark.asyncio
async def test_reconnect_reverifies_identity_without_deadlock() -> None:
    async with fake_onebot(close_after_first_login=True) as fake:
        adapter = _adapter(fake)
        try:
            await adapter.connect()
            for _ in range(100):
                if fake.connections >= 2 and adapter.status == "online":
                    break
                await asyncio.sleep(0.1)
            assert fake.connections >= 2
            assert adapter.status == "online"
            assert adapter.online is True
            assert fake.action_names().count("get_login_info") >= 2
        finally:
            await adapter.disconnect()


@pytest.mark.asyncio
async def test_successful_diagnostics_are_explicit_about_unverified_scope() -> None:
    async with fake_onebot(initial_events=[heartbeat_event()]) as fake:
        adapter = _adapter(fake)
        started = utcnow()
        try:
            await adapter.connect()
            report = await run_connection_diagnostics(
                adapter,
                connection_mode="onebot11",
                started_at=started,
                token_configured=True,
            )
        finally:
            await adapter.disconnect()

    assert report.state == "identity_verified"
    assert report.ok is True
    assert len(report.checks) == 9
    by_id = {check.id: check for check in report.checks}
    assert by_id["websocket"].state == "ok"
    assert by_id["auth"].state == "ok"
    assert by_id["identity"].state == "ok"
    assert by_id["action"].state == "ok"
    assert by_id["groups"].state == "ok"
    assert by_id["event_stream"].state == "ok"
    assert by_id["real_inbound"].state == "not_verified"
    assert by_id["real_outbound"].state == "not_verified"
    assert report.login is not None and report.login["user_id"] == "10000"
    assert report.group_count == 1
    assert report.identity_verified is True
    assert report.real_inbound_verified is False
    assert report.real_outbound_verified is False
    assert report.message_send_attempted is False
    assert "secret-token" not in json.dumps(report.model_dump(mode="json"))


@pytest.mark.asyncio
async def test_identity_failure_diagnostics_stop_at_identity() -> None:
    async with fake_onebot(login={}) as fake:
        adapter = _adapter(fake)
        started = utcnow()
        try:
            await adapter.connect()
            report = await run_connection_diagnostics(
                adapter,
                connection_mode="onebot11",
                started_at=started,
                token_configured=True,
            )
        finally:
            await adapter.disconnect()

    by_id = {check.id: check for check in report.checks}
    assert report.state == "failed"
    assert report.ok is False
    assert by_id["identity"].state == "failed"
    assert by_id["groups"].state == "skipped"
    assert report.identity_verified is False
    assert report.next_step


@pytest.mark.asyncio
async def test_group_list_failure_is_only_a_warning() -> None:
    async with fake_onebot(action_failures={"get_group_list": 1404}) as fake:
        adapter = _adapter(fake)
        started = utcnow()
        try:
            await adapter.connect()
            report = await run_connection_diagnostics(
                adapter,
                connection_mode="onebot11",
                started_at=started,
                token_configured=True,
            )
        finally:
            await adapter.disconnect()

    by_id = {check.id: check for check in report.checks}
    assert report.state == "identity_verified"
    assert report.ok is True
    assert report.identity_verified is True
    assert by_id["groups"].state == "warning"
    assert by_id["groups"].error_code == ErrorCode.ADAPTER_CONNECT_FAILED


@pytest.mark.asyncio
async def test_missing_token_is_a_warning_not_a_failure() -> None:
    async with fake_onebot() as fake:
        adapter = OneBot11Adapter(
            instance_id="onebot-no-token",
            account_id="account-diagnostics",
            endpoint=fake.ws_url,
        )
        started = utcnow()
        try:
            await adapter.connect()
            report = await run_connection_diagnostics(
                adapter,
                connection_mode="onebot11",
                started_at=started,
                token_configured=False,
            )
        finally:
            await adapter.disconnect()

    by_id = {check.id: check for check in report.checks}
    assert by_id["auth"].state == "warning"
    assert report.state == "identity_verified"
    assert report.ok is True


@pytest.mark.asyncio
async def test_mock_diagnostics_are_mock_only() -> None:
    adapter = MockQQAdapter(instance_id="mock-instance", account_id="mock-account")
    report = await run_connection_diagnostics(
        adapter,
        connection_mode="mock",
        started_at=utcnow(),
        token_configured=False,
    )
    assert report.state == "mock_only"
    assert report.is_mock is True
    assert report.ok is True
    assert report.identity_verified is False
    assert report.action_path_verified is False
    assert report.real_inbound_verified is False
    by_id = {check.id: check for check in report.checks}
    assert by_id["websocket"].state == "skipped"
    assert by_id["real_outbound"].state == "not_verified"
    assert "真实 QQ" in report.note


@pytest.mark.asyncio
async def test_startup_resets_stale_runtime_statuses(database: Database) -> None:
    async with database.session() as session:
        account = Account(display_name="旧进程账号", status="online")
        session.add(account)
        await session.flush()
        instance = AdapterInstance(
            account_id=account.id,
            name="旧连接",
            connection_mode="onebot11",
            status="connected_unverified",
            last_error_code=ErrorCode.ADAPTER_IDENTITY_UNVERIFIED,
            last_error_message="旧进程残留",
        )
        session.add(instance)
        await session.commit()
        account_id = account.id
        instance_id = instance.id

    await reset_stale_runtime_statuses(database)

    async with database.session() as session:
        reset_account = await session.get(Account, account_id)
        reset_instance = await session.get(AdapterInstance, instance_id)
        assert reset_account is not None and reset_account.status == "disconnected"
        assert reset_instance is not None
        assert reset_instance.status == "disconnected"
        assert reset_instance.last_error_code is None
        assert reset_instance.last_error_message is None


def test_config_failure_report_does_not_claim_network_checks() -> None:
    report = failed_report(
        connection_mode="onebot11",
        started_at=utcnow(),
        error_code=ErrorCode.ADAPTER_CONNECT_FAILED,
        error_message="请填写 OneBot 11 WebSocket 地址。",
        config_error=True,
    )
    by_id = {check.id: check for check in report.checks}
    assert report.ok is False
    assert report.state == "failed"
    assert by_id["config"].state == "failed"
    assert by_id["websocket"].state == "skipped"
    assert by_id["identity"].state == "skipped"

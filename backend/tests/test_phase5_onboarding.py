"""阶段 5：只读接入向导的证据与状态。全部使用临时数据库与本机假服务器。"""

from __future__ import annotations

import json
from datetime import timedelta
from typing import Any

import app.models  # noqa: F401
import pytest
import pytest_asyncio
from app.core.config import Settings
from app.core.time import iso_utc, utcnow
from app.db.base import Base
from app.main import create_app
from app.models.account import AdapterInstance
from app.models.connector import ConnectorInstallation
from app.models.governance import AuditLog
from app.models.group import Group
from app.models.message import Message
from app.models.provider import LLMProvider
from app.runtime import AppRuntime
from app.services.audit import write_audit
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from tests.onebot_fakes import fake_onebot


@pytest.fixture
def client(settings: Settings) -> Any:
    app = create_app(settings)
    with TestClient(app) as test_client:
        yield test_client


@pytest_asyncio.fixture
async def runtime(settings: Settings) -> Any:
    instance = AppRuntime(settings)
    async with instance.database.engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    try:
        yield instance
    finally:
        await instance.manager.stop()
        await instance.connectors.stop()
        await instance.database.dispose()


def _data(response: Any) -> Any:
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["error"] is None, body
    return body["data"]


def _steps(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {step["key"]: step for step in payload["steps"]}


async def _audit_count(runtime: AppRuntime, action: str | None = None) -> int:
    async with runtime.database.session() as session:
        query = select(func.count(AuditLog.id))
        if action:
            query = query.where(AuditLog.action == action)
        return int(await session.scalar(query) or 0)


async def _real_account(runtime: AppRuntime, ws_url: str) -> tuple[str, str]:
    account = await runtime.accounts.create_account(
        {
            "display_name": "真实测试账号",
            "enabled": True,
            "instance": {
                "name": "OneBot 测试",
                "connection_mode": "onebot11",
                "endpoint": ws_url,
                "auto_connect": False,
                "enabled": True,
            },
        }
    )
    instance = account["instances"][0]
    return account["id"], instance["id"]


async def _ready_provider(runtime: AppRuntime) -> str:
    provider = await runtime.providers.create_llm_provider(
        {
            "name": "真实测试 Provider",
            "provider_type": "openai_compatible",
            "base_url": "https://example.invalid/v1",
            "model": "test-model",
            "api_key": "sk-test-phase5",
            "enabled": True,
            "is_default": True,
        }
    )
    await _set_provider_test(runtime, provider["id"], outcome="success", age=timedelta(minutes=5))
    return provider["id"]


async def _set_provider_test(
    runtime: AppRuntime,
    provider_id: str,
    *,
    outcome: str,
    age: timedelta,
) -> None:
    async with runtime.database.session() as session:
        record = await session.get(LLMProvider, provider_id)
        assert record is not None
        tested_at = utcnow() - age
        record.last_test_json = {
            "kind": "connectivity",
            "outcome": outcome,
            "ok": outcome == "success",
            "tested_at": iso_utc(tested_at),
            "latency_ms": 12,
            "is_mock": False,
            "model": "敏感模型名-should-not-leak",
            "message": "敏感错误-should-not-leak",
        }
        record.last_tested_at = tested_at
        await session.commit()


async def test_empty_database_is_action_required(runtime: AppRuntime) -> None:
    payload = await runtime.onboarding.build()
    assert payload["schema_version"] == "onboarding.v1"
    assert payload["overall"] == "action_required"
    assert payload["ready_for_replies"] is False
    assert payload["mock_only"] is False
    assert [item["key"] for item in payload["steps"]] == [
        "backend",
        "connector",
        "qq_login",
        "connection_test",
        "model",
        "groups",
        "observe",
        "enable",
    ]
    steps = _steps(payload)
    assert steps["backend"]["state"] == "done"
    assert steps["connector"]["state"] == "action_required"
    assert steps["qq_login"]["state"] == "action_required"
    assert steps["connection_test"]["state"] == "action_required"
    assert steps["model"]["state"] == "action_required"
    assert steps["groups"]["state"] == "action_required"
    assert steps["observe"]["state"] == "optional"
    assert steps["enable"]["state"] == "action_required"
    assert payload["next_action"]["key"] == "connector"


def test_demo_bootstrap_is_mock_only(client: TestClient) -> None:
    _data(client.post("/api/demo/bootstrap", json={}))
    payload = _data(client.get("/api/onboarding"))
    steps = _steps(payload)
    assert payload["overall"] == "ready_mock_only"
    assert payload["ready_for_replies"] is False
    assert payload["mock_only"] is True
    assert steps["qq_login"]["state"] == "mock_only"
    assert steps["connection_test"]["state"] == "mock_only"
    assert steps["model"]["state"] == "mock_only"
    assert steps["groups"]["state"] == "mock_only"
    assert steps["enable"]["state"] == "mock_only"
    assert steps["enable"]["state"] != "done"
    assert all(step["route"].startswith("/") for step in payload["steps"])
    assert any("Mock" in warning for warning in payload["warnings"])


@pytest.mark.asyncio
async def test_live_diagnose_audit_becomes_evidence_and_get_is_read_only(
    runtime: AppRuntime,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async with fake_onebot() as fake:
        account_id, instance_id = await _real_account(runtime, fake.ws_url)
        await runtime.accounts.connect_instance(account_id, instance_id)
        await runtime.connectors.confirm_identity(account_id, user_id="10000", actor="phase5")

        async with runtime.database.session() as session:
            installation = ConnectorInstallation(
                kind="napcat",
                root_path=str(runtime.settings.connectors_path / "fake"),
                managed=True,
                last_state="installed_not_started",
            )
            session.add(installation)
            await session.flush()
            instance = await session.get(AdapterInstance, instance_id)
            assert instance is not None
            instance.connector_installation_id = installation.id
            await session.commit()
            installation_id = installation.id

        before = await _audit_count(runtime)
        report = await runtime.connectors.diagnose_installation(installation_id, actor="phase5")
        assert report["ok"] is True
        assert report["state"] == "identity_verified"
        assert await _audit_count(runtime, "connector.diagnose") == 1

        payload = await runtime.onboarding.build()
        steps = _steps(payload)
        assert steps["backend"]["state"] == "done"
        assert steps["connector"]["state"] == "done"
        assert steps["qq_login"]["state"] == "done"
        assert steps["connection_test"]["state"] == "done"
        assert steps["connection_test"]["freshness"] in {"fresh", "aging"}
        assert steps["connection_test"]["evidence"]["source"] == "live_adapter"
        assert steps["connection_test"]["evidence"]["identity_verified"] is True
        assert steps["connection_test"]["evidence"]["real_outbound_verified"] is False

        after = await _audit_count(runtime)
        second = await runtime.onboarding.build()
        assert second["overall"] == payload["overall"]
        assert await _audit_count(runtime) == after

        dumped = json.dumps(payload, ensure_ascii=False)
        for secret in (account_id, instance_id, installation_id, "10000", fake.ws_url):
            assert secret not in dumped
        assert before + 1 == after

        # 未保存配置测试永远不作为证据。
        await write_audit(
            runtime.database,
            action="account.instance.test_unsaved",
            target_type="adapter_instance",
            target_id=instance_id,
            details={"ok": True, "state": "identity_verified"},
        )
        still_done = await runtime.onboarding.build()
        assert _steps(still_done)["connection_test"]["state"] == "done"

        # 之后修改实例配置使旧测试证据失效。
        await runtime.accounts.update_instance(account_id, instance_id, {"name": "改名后"})
        updated = await runtime.onboarding.build()
        assert _steps(updated)["connection_test"]["state"] == "not_verified"
        assert _steps(updated)["connection_test"]["freshness"] == "missing"


@pytest.mark.asyncio
async def test_stale_evidence_and_latest_failure_override_success(runtime: AppRuntime) -> None:
    async with fake_onebot() as fake:
        account_id, instance_id = await _real_account(runtime, fake.ws_url)
        await runtime.accounts.connect_instance(account_id, instance_id)
        await runtime.connectors.confirm_identity(account_id, user_id="10000", actor="phase5")

        await write_audit(
            runtime.database,
            action="connector.diagnose",
            target_type="adapter_instance",
            target_id=instance_id,
            details={
                "mode": "onebot11",
                "ok": True,
                "state": "identity_verified",
                "source": "live_adapter",
                "identity_verified": True,
                "action_path_verified": True,
                "group_list_verified": True,
                "real_inbound_verified": False,
                "real_outbound_verified": False,
            },
        )
        async with runtime.database.session() as session:
            row = await session.scalar(
                select(AuditLog)
                .where(AuditLog.action == "connector.diagnose")
                .order_by(AuditLog.created_at.desc())
                .limit(1)
            )
            assert row is not None
            row.created_at = utcnow() - timedelta(hours=25)
            await session.commit()

        stale = await runtime.onboarding.build()
        assert _steps(stale)["connection_test"]["state"] == "not_verified"
        assert _steps(stale)["connection_test"]["freshness"] == "stale"

        await write_audit(
            runtime.database,
            action="account.instance.test",
            target_type="adapter_instance",
            target_id=instance_id,
            details={"mode": "onebot11", "ok": False, "state": "failed"},
        )
        failed = await runtime.onboarding.build()
        assert _steps(failed)["connection_test"]["state"] == "action_required"
        assert _steps(failed)["connection_test"]["evidence"]["ok"] is False


@pytest.mark.asyncio
async def test_model_requires_fresh_real_success_without_leaking_names(runtime: AppRuntime) -> None:
    provider_id = await _ready_provider(runtime)
    ready = await runtime.onboarding.build()
    model = _steps(ready)["model"]
    assert model["state"] == "done"
    assert model["evidence"]["real_providers"] == 1
    assert model["evidence"]["tested_real_providers"] == 1
    dumped = json.dumps(ready, ensure_ascii=False)
    assert provider_id not in dumped
    assert "sk-test-phase5" not in dumped
    assert "敏感模型名-should-not-leak" not in dumped
    assert "敏感错误-should-not-leak" not in dumped

    await _set_provider_test(runtime, provider_id, outcome="success", age=timedelta(hours=30))
    stale = await runtime.onboarding.build()
    assert _steps(stale)["model"]["state"] == "not_verified"
    assert _steps(stale)["model"]["freshness"] == "stale"

    await _set_provider_test(runtime, provider_id, outcome="failure", age=timedelta(minutes=1))
    failed = await runtime.onboarding.build()
    assert _steps(failed)["model"]["state"] == "action_required"


@pytest.mark.asyncio
async def test_observe_requires_persisted_real_inbound_message(runtime: AppRuntime) -> None:
    async with fake_onebot() as fake:
        account_id, instance_id = await _real_account(runtime, fake.ws_url)
        await runtime.accounts.connect_instance(account_id, instance_id)
        group = await runtime.groups.create_group(
            {
                "account_id": account_id,
                "platform_group_id": "778899",
                "name": "真实观察群",
                "enabled": True,
                "reply_mode": "observe",
            }
        )
        await _ready_provider(runtime)

        configured = await runtime.onboarding.build()
        assert _steps(configured)["observe"]["state"] == "optional"
        assert _steps(configured)["observe"]["evidence"]["observed_currently"] == 0

        async with runtime.database.session() as session:
            record = await session.get(Group, group["id"])
            assert record is not None
            session.add(
                Message(
                    platform_message_id="observed-1",
                    account_id=account_id,
                    group_id=record.id,
                    conversation_id="group:778899",
                    conversation_type="group",
                    sender_id="20000",
                    direction="inbound",
                    content_text="观察消息正文",
                    event_timestamp=utcnow(),
                    processing_status="observed",
                )
            )
            await session.commit()

        observed = await runtime.onboarding.build()
        assert _steps(observed)["observe"]["state"] == "done"
        assert _steps(observed)["observe"]["evidence"]["observed_currently"] == 1
        assert "观察消息正文" not in json.dumps(observed, ensure_ascii=False)


@pytest.mark.asyncio
async def test_full_real_chain_ready_for_replies(runtime: AppRuntime) -> None:
    async with fake_onebot() as fake:
        account_id, instance_id = await _real_account(runtime, fake.ws_url)
        await runtime.accounts.connect_instance(account_id, instance_id)
        await runtime.connectors.confirm_identity(account_id, user_id="10000", actor="phase5")
        await _ready_provider(runtime)
        await runtime.groups.create_group(
            {
                "account_id": account_id,
                "platform_group_id": "556677",
                "name": "真实回复群",
                "enabled": True,
                "reply_mode": "manual_confirm",
            }
        )

        async with runtime.database.session() as session:
            installation = ConnectorInstallation(
                kind="napcat",
                root_path=str(runtime.settings.connectors_path / "fake"),
                managed=True,
                last_state="installed_not_started",
            )
            session.add(installation)
            await session.flush()
            instance = await session.get(AdapterInstance, instance_id)
            assert instance is not None
            instance.connector_installation_id = installation.id
            await session.commit()
            installation_id = installation.id
        await runtime.connectors.diagnose_installation(installation_id, actor="phase5")

        payload = await runtime.onboarding.build()
        assert payload["overall"] == "ready_real"
        assert payload["ready_for_replies"] is True
        assert payload["mock_only"] is False
        steps = _steps(payload)
        assert steps["enable"]["state"] == "done"
        assert steps["enable"]["evidence"]["ready_manual_groups"] == 1
        assert steps["enable"]["summary"].count("待审") >= 1

        # 全局暂停始终优先。
        from app.services.settings_store import set_global_pause

        await set_global_pause(runtime.database, paused=True, reason="测试暂停", actor="phase5")
        paused = await runtime.onboarding.build()
        assert paused["overall"] == "blocked"
        assert paused["ready_for_replies"] is False
        assert _steps(paused)["enable"]["state"] == "blocked"
        assert paused["blockers"]


def test_onboarding_api_envelope_and_read_only(client: TestClient) -> None:
    before = _data(client.get("/api/audit", params={"page_size": 1}))
    first = _data(client.get("/api/onboarding"))
    second = _data(client.get("/api/onboarding"))
    after = _data(client.get("/api/audit", params={"page_size": 1}))
    assert first["schema_version"] == "onboarding.v1"
    assert first["overall"] == second["overall"]
    assert first["steps"] == second["steps"]
    assert before["total"] == after["total"]

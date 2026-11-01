"""阶段 5：诊断汇总的 allowlist 与只读性。"""

from __future__ import annotations

import json
from typing import Any

import app.models  # noqa: F401
import pytest
import pytest_asyncio
from app.core.config import Settings
from app.core.security import CredentialCipher
from app.core.time import utcnow
from app.db.base import Base
from app.main import create_app
from app.models.account import Account, AdapterInstance
from app.models.governance import AuditLog
from app.models.group import Group
from app.models.message import Message, OutboxMessage
from app.models.provider import LLMProvider
from app.runtime import AppRuntime
from fastapi.testclient import TestClient
from sqlalchemy import func, select


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


SECRETS = [
    "SECRET-ACCOUNT-NAME",
    "SECRET-QQ-123456789",
    "SECRET-INSTANCE-NAME",
    "ws://secret-host.invalid:43999/SECRET-PATH",
    "SECRET-TOKEN-VALUE",
    "SECRET-GROUP-ID-987654",
    "SECRET-GROUP-NAME",
    "SECRET-SENDER-NAME",
    "SECRET-MESSAGE-BODY",
    "SECRET-PROVIDER-NAME",
    "https://secret-provider.invalid/v1",
    "SECRET-MODEL-ID",
    "SECRET-API-KEY",
    "SECRET-ERROR-MESSAGE",
    "SECRET-AUDIT-DETAIL",
    "SECRET-REPLY-PREVIEW",
    "secret-user",
    "C:/secret/path",
]


async def _seed(runtime: AppRuntime) -> None:
    cipher: CredentialCipher = runtime.cipher
    async with runtime.database.session() as session:
        account = Account(
            display_name="SECRET-ACCOUNT-NAME",
            self_platform_user_id="SECRET-QQ-123456789",
            enabled=True,
            status="online",
            notes="SECRET-AUDIT-DETAIL",
        )
        session.add(account)
        await session.flush()
        instance = AdapterInstance(
            account_id=account.id,
            name="SECRET-INSTANCE-NAME",
            endpoint="ws://secret-host.invalid:43999/SECRET-PATH",
            api_endpoint="https://secret-provider.invalid/v1",
            connection_mode="onebot11",
            token_encrypted=cipher.encrypt("SECRET-TOKEN-VALUE"),
            enabled=True,
            status="online",
            last_error_message="SECRET-ERROR-MESSAGE",
            identity_confirmed_at=utcnow(),
        )
        session.add(instance)
        group = Group(
            account_id=account.id,
            platform_group_id="SECRET-GROUP-ID-987654",
            name="SECRET-GROUP-NAME",
            enabled=True,
            reply_mode="mention_only",
        )
        session.add(group)
        provider = LLMProvider(
            name="SECRET-PROVIDER-NAME",
            provider_type="openai_compatible",
            base_url="https://secret-provider.invalid/v1",
            model="SECRET-MODEL-ID",
            api_key_encrypted=cipher.encrypt("SECRET-API-KEY"),
            enabled=True,
            is_default=True,
            last_test_json={
                "kind": "connectivity",
                "outcome": "failure",
                "ok": False,
                "tested_at": utcnow().isoformat(),
                "is_mock": False,
                "message": "SECRET-ERROR-MESSAGE",
                "reply_preview": "SECRET-REPLY-PREVIEW",
                "model": "SECRET-MODEL-ID",
            },
            last_error="SECRET-ERROR-MESSAGE",
        )
        session.add(provider)
        await session.flush()
        session.add(
            Message(
                platform_message_id="SECRET-GROUP-ID-987654",
                account_id=account.id,
                group_id=group.id,
                conversation_id="group:987654",
                conversation_type="group",
                sender_id="SECRET-QQ-123456789",
                sender_name="SECRET-SENDER-NAME",
                direction="inbound",
                content_text="SECRET-MESSAGE-BODY",
                event_timestamp=utcnow(),
                processing_status="observed",
            )
        )
        session.add(
            OutboxMessage(
                account_id=account.id,
                group_id=group.id,
                conversation_id="group:987654",
                content="SECRET-MESSAGE-BODY",
                idempotency_key="secret-outbox-key",
                status="failed",
                last_error_message="SECRET-ERROR-MESSAGE",
            )
        )
        session.add(
            AuditLog(
                actor="secret-user",
                action="account.instance.test",
                target_type="adapter_instance",
                target_id=instance.id,
                details_json={
                    "ok": True,
                    "state": "identity_verified",
                    "source": "saved_instance_test",
                    "secret": "SECRET-AUDIT-DETAIL",
                },
                request_id="SECRET-REPLY-PREVIEW",
                ip_address="203.0.113.9",
            )
        )
        await session.commit()


async def _audit_total(runtime: AppRuntime) -> int:
    async with runtime.database.session() as session:
        return int(await session.scalar(select(func.count(AuditLog.id))) or 0)


TOP_LEVEL_KEYS = {
    "schema_version",
    "generated_at",
    "excluded",
    "app",
    "readiness",
    "counts",
    "accounts",
    "connectors",
    "providers",
    "groups",
    "messages",
    "connection_test",
    "recent_audit_actions",
    "text",
}

SECTION_KEYS = {
    "app": {"version", "env"},
    "readiness": {
        "database",
        "credential_key_configured",
        "global_paused",
        "global_pause_updated_at",
        "event_stream_subscribers",
    },
    "accounts": {
        "modes",
        "live_online_instances",
        "identity_confirmed_instances",
        "connected_unverified_instances",
    },
    "connectors": {
        "installation_count",
        "states",
        "identity_confirmed",
        "real_traffic_verified",
        "real_qq_verified",
    },
    "providers": {
        "total",
        "mock",
        "real",
        "real_config_complete",
        "real_test_passed",
        "real_test_failed",
        "real_never_tested",
    },
    "groups": {
        "total",
        "enabled",
        "observe_only",
        "auto_reply_modes",
        "paused",
        "provider_resolved",
        "provider_unresolved",
    },
    "messages": {
        "received",
        "observed",
        "replied",
        "sent",
        "outbox_pending",
        "outbox_failed",
    },
    "connection_test": {
        "last_outcome",
        "last_state",
        "last_source",
        "tested_at",
        "age_seconds",
        "freshness",
        "identity_verified",
        "action_path_verified",
        "group_list_verified",
        "real_inbound_verified",
        "real_outbound_verified",
        "message_send_attempted",
    },
}


@pytest.mark.asyncio
async def test_diagnostics_allowlist_excludes_sensitive_values(runtime: AppRuntime) -> None:
    await _seed(runtime)
    before = await _audit_total(runtime)
    data = await runtime.diagnostics.build()
    after = await _audit_total(runtime)
    second = await runtime.diagnostics.build()

    assert before == after
    assert data["schema_version"] == "diagnostics.v1"
    assert set(data) == TOP_LEVEL_KEYS
    for section, keys in SECTION_KEYS.items():
        assert set(data[section]) == keys, section
    assert set(data["counts"]) == {
        "accounts",
        "adapter_instances",
        "groups",
        "personas",
        "providers",
        "messages",
        "memories",
        "memory_candidates",
        "media_assets",
        "outbox_messages",
    }
    assert data["counts"]["accounts"] == 1
    assert data["counts"]["adapter_instances"] == 1
    assert data["counts"]["groups"] == 1
    assert data["counts"]["providers"] == 1
    assert data["counts"]["messages"] == 1
    assert data["counts"]["outbox_messages"] == 1
    assert data["accounts"]["modes"]["onebot11"] == 1
    assert data["providers"]["real"] == 1
    assert data["providers"]["real_test_failed"] == 1
    assert data["groups"]["enabled"] == 1
    assert data["groups"]["provider_resolved"] == 1
    assert data["messages"]["received"] == 1
    assert data["messages"]["observed"] == 1
    assert data["messages"]["outbox_failed"] == 1
    assert data["connectors"]["real_qq_verified"] is False
    assert data["connection_test"]["message_send_attempted"] is False
    assert data["connection_test"]["last_outcome"] == "success"
    assert data["connection_test"]["last_source"] == "saved_instance_test"
    assert data["connection_test"]["identity_verified"] is False

    assert data["excluded"]
    assert all(set(item) == {"action", "count"} for item in data["recent_audit_actions"])
    assert any(item["action"] == "account.instance.test" for item in data["recent_audit_actions"])

    dumped = json.dumps(data, ensure_ascii=False)
    for secret in SECRETS:
        assert secret not in dumped, secret
    for secret in SECRETS:
        assert secret not in data["text"], secret
    assert "已脱敏" in data["text"]
    assert "日志" in data["text"]
    assert "mock" in data["text"].lower()
    assert data["text"].endswith("分享前请自行检查。")
    assert second["text"].count("诊断摘要") == 1


def test_diagnostics_api_envelope_and_read_only(client: TestClient) -> None:
    before = _data(client.get("/api/audit", params={"page_size": 1}))
    first = _data(client.get("/api/diagnostics"))
    second = _data(client.get("/api/diagnostics"))
    after = _data(client.get("/api/audit", params={"page_size": 1}))
    assert first["schema_version"] == "diagnostics.v1"
    assert set(first) == TOP_LEVEL_KEYS
    stable_first = {key: value for key, value in first.items() if key not in {"generated_at", "text"}}
    stable_second = {key: value for key, value in second.items() if key not in {"generated_at", "text"}}
    assert stable_first == stable_second
    assert before["total"] == after["total"]
    assert first["connection_test"]["message_send_attempted"] is False
    assert first["connectors"]["real_qq_verified"] is False

"""阶段 6：账号/群/人格删除完整性、媒体保护、Outbox 取消与确认词。"""

from __future__ import annotations

from typing import Any

import app.models  # noqa: F401
import pytest
import pytest_asyncio
from app.core.config import Settings
from app.core.time import utcnow
from app.db.base import Base
from app.main import create_app
from app.models.account import Account
from app.models.governance import AuditLog
from app.models.group import Group, Member
from app.models.media import MediaAsset
from app.models.memory import Memory, MemoryCandidate
from app.models.message import Message, OutboxMessage
from app.models.persona import Persona, PersonaEvolutionEvent, PersonaTrait, PersonaVersion
from app.runtime import AppRuntime
from fastapi.testclient import TestClient
from sqlalchemy import func, select


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


def _message(session_account_id: str, group_id: str | None, name: str, **extra: Any) -> Message:
    return Message(
        platform_message_id=f"phase6-{name}",
        account_id=session_account_id,
        group_id=group_id,
        conversation_id="group:phase6",
        conversation_type="group" if group_id else "private",
        sender_id="90001",
        sender_name="测试成员",
        direction="inbound",
        content_text=f"阶段六测试消息 {name}",
        segments_json=extra.pop("segments_json", []),
        event_timestamp=utcnow(),
        processing_status="received",
        **extra,
    )


async def _audit_detail(runtime: AppRuntime, action: str) -> dict[str, Any]:
    async with runtime.database.session() as session:
        record = await session.scalar(
            select(AuditLog).where(AuditLog.action == action).order_by(AuditLog.created_at.desc()).limit(1)
        )
    assert record is not None, action
    return {"actor": record.actor, "details": dict(record.details_json or {})}


async def _seed_account_deletion(runtime: AppRuntime) -> dict[str, Any]:
    async with runtime.database.session() as session:
        account = Account(display_name="待删除账号", self_platform_user_id="90000", enabled=True)
        other = Account(display_name="保留账号", self_platform_user_id="90001", enabled=True)
        persona = Persona(name="待删除账号人格")
        session.add_all([account, other, persona])
        await session.flush()
        group = Group(
            account_id=account.id,
            platform_group_id="phase6-group",
            name="阶段六群",
            enabled=True,
            reply_mode="mention_only",
            persona_id=persona.id,
        )
        session.add(group)
        await session.commit()
        await session.refresh(account)
        await session.refresh(other)
        await session.refresh(group)

    unshared = await runtime.media_service.ingest(
        b"phase6-unshared-media",
        mime="image/png",
        media_type="image",
        account_id=account.id,
    )
    shared = await runtime.media_service.ingest(
        b"phase6-shared-media",
        mime="image/png",
        media_type="image",
        account_id=account.id,
    )
    assert await runtime.media_service.store.exists(unshared.id)
    assert await runtime.media_service.store.exists(shared.id)

    async with runtime.database.session() as session:
        message = _message(account.id, group.id, "owned", segments_json=[{"type": "image", "media_ref": unshared.id}])
        shared_message = _message(
            account.id, group.id, "shared-owner", segments_json=[{"type": "image", "media_ref": shared.id}]
        )
        other_message = _message(
            other.id, None, "shared-user", segments_json=[{"type": "image", "media_ref": shared.id}]
        )
        session.add_all([message, shared_message, other_message])
        await session.flush()
        session.add_all(
            [
                Member(account_id=account.id, platform_user_id="90001", display_name="测试成员"),
                OutboxMessage(
                    account_id=account.id,
                    group_id=group.id,
                    conversation_id="group:phase6",
                    content="待发送回复",
                    idempotency_key="phase6-account-outbox",
                    status="pending",
                ),
                Memory(account_id=account.id, group_id=group.id, content="账号删除时应被清理的记忆"),
                MemoryCandidate(
                    account_id=account.id,
                    group_id=group.id,
                    content="账号删除时应被清理的候选记忆",
                    source_message_ids_json=[],
                ),
                PersonaVersion(
                    persona_id=persona.id,
                    version_no=1,
                    change_summary="初始版本",
                    snapshot_json={"name": persona.name},
                ),
                PersonaTrait(
                    persona_id=persona.id,
                    trait_key="tone",
                    trait_value="友善",
                    evidence_message_ids_json=[message.id],
                ),
                PersonaEvolutionEvent(
                    persona_id=persona.id,
                    batch_id="phase6-batch",
                    trigger_type="manual",
                    summary="证据事件",
                    proposal_json={},
                    result="ignored",
                ),
            ]
        )
        await session.commit()
        await session.refresh(message)
        return {
            "account_id": account.id,
            "other_id": other.id,
            "group_id": group.id,
            "persona_id": persona.id,
            "message_id": message.id,
            "unshared_id": unshared.id,
            "shared_id": shared.id,
        }


@pytest.mark.asyncio
async def test_account_deletion_cleans_relations_and_unshared_media(runtime: AppRuntime) -> None:
    seeded = await _seed_account_deletion(runtime)

    await runtime.accounts.delete_account(seeded["account_id"], actor="phase6-tester")

    async with runtime.database.session() as session:
        assert await session.get(Account, seeded["account_id"]) is None
        assert await session.get(Group, seeded["group_id"]) is None
        assert await session.get(Persona, seeded["persona_id"]) is not None
        for model in (Member, Memory, MemoryCandidate, OutboxMessage):
            count = int(
                await session.scalar(
                    select(func.count()).select_from(model).where(model.account_id == seeded["account_id"])
                )
                or 0
            )
            assert count == 0, model.__tablename__
        message_count = int(
            await session.scalar(select(func.count(Message.id)).where(Message.account_id == seeded["account_id"])) or 0
        )
        assert message_count == 0

        unshared = await session.get(MediaAsset, seeded["unshared_id"])
        shared = await session.get(MediaAsset, seeded["shared_id"])
        assert unshared is not None and unshared.status == "deleted"
        assert unshared.deleted_at is not None and unshared.storage_path is None
        assert shared is not None and shared.deleted_at is None
        assert shared.storage_path is not None

        trait = await session.scalar(select(PersonaTrait).where(PersonaTrait.persona_id == seeded["persona_id"]))
        assert trait is not None
        assert seeded["message_id"] not in list(trait.evidence_message_ids_json or [])

    assert not await runtime.media_service.store.exists(seeded["unshared_id"])
    assert await runtime.media_service.store.exists(seeded["shared_id"])

    audit = await _audit_detail(runtime, "account.delete")
    assert audit["actor"] == "phase6-tester"
    assert audit["details"]["groups"] == 1
    assert audit["details"]["messages"] == 2
    assert audit["details"]["memories"] == 1
    assert audit["details"]["outbox_messages"] == 1
    assert audit["details"]["media_deleted"] == 1
    assert audit["details"]["media_skipped_shared"] == 1
    assert audit["details"]["media_refs"] == 2
    assert audit["details"]["media_errors"] == 0


@pytest.mark.asyncio
async def test_group_deletion_cancels_outbox_keeps_history_and_memories(runtime: AppRuntime) -> None:
    async with runtime.database.session() as session:
        account = Account(display_name="群删除账号", enabled=True)
        session.add(account)
        await session.flush()
        group = Group(
            account_id=account.id,
            platform_group_id="phase6-delete-group",
            name="待删除群",
            enabled=True,
            reply_mode="always",
        )
        session.add(group)
        await session.commit()
        await session.refresh(group)
        keep = _message(account.id, group.id, "keep-a")
        keep_second = _message(account.id, group.id, "keep-b")
        session.add_all([keep, keep_second])
        session.add_all(
            [
                Memory(account_id=account.id, group_id=group.id, content="群删除时清理的记忆"),
                MemoryCandidate(
                    account_id=account.id,
                    group_id=group.id,
                    content="群删除时清理的候选",
                    source_message_ids_json=[],
                ),
            ]
        )
        pending = OutboxMessage(
            account_id=account.id,
            group_id=group.id,
            conversation_id="group:phase6-delete-group",
            content="待发送",
            idempotency_key="phase6-group-pending",
            status="pending",
        )
        approval = OutboxMessage(
            account_id=account.id,
            group_id=group.id,
            conversation_id="group:phase6-delete-group",
            content="待确认",
            idempotency_key="phase6-group-approval",
            status="pending_approval",
        )
        sending = OutboxMessage(
            account_id=account.id,
            group_id=group.id,
            conversation_id="group:phase6-delete-group",
            content="发送中",
            idempotency_key="phase6-group-sending",
            status="sending",
        )
        session.add_all([pending, approval, sending])
        await session.commit()
        ids = {
            "account_id": account.id,
            "group_id": group.id,
            "message_ids": [keep.id, keep_second.id],
            "pending": pending.id,
            "approval": approval.id,
            "sending": sending.id,
        }

    await runtime.groups.delete_group(ids["group_id"], actor="phase6-tester")

    async with runtime.database.session() as session:
        assert await session.get(Group, ids["group_id"]) is None
        messages = list(
            (
                await session.execute(select(Message).where(Message.id.in_(ids["message_ids"])).order_by(Message.id))
            ).scalars()
        )
        assert len(messages) == 2
        assert all(message.group_id is None for message in messages)
        assert all(message.content_text.startswith("阶段六测试消息") for message in messages)
        assert await session.get(OutboxMessage, ids["pending"]) is not None
        assert await session.get(OutboxMessage, ids["approval"]) is not None
        pending = await session.get(OutboxMessage, ids["pending"])
        approval = await session.get(OutboxMessage, ids["approval"])
        sending = await session.get(OutboxMessage, ids["sending"])
        assert pending is not None and pending.status == "cancelled"
        assert pending.next_attempt_at is None
        assert pending.last_error_code == "POLICY_BLOCKED"
        assert pending.last_error_message == "群已删除，待发送消息已取消。"
        assert approval is not None and approval.status == "cancelled"
        assert approval.next_attempt_at is None
        assert sending is not None and sending.status == "sending"
        assert (
            int(await session.scalar(select(func.count(Memory.id)).where(Memory.group_id == ids["group_id"])) or 0) == 0
        )
        assert (
            int(
                await session.scalar(
                    select(func.count(MemoryCandidate.id)).where(MemoryCandidate.group_id == ids["group_id"])
                )
                or 0
            )
            == 0
        )

    # 已取消的待发消息不会进入发送循环：解析器绝不应被调用。
    def _must_not_resolve(*_args: Any) -> Any:
        raise AssertionError("删除群后不应再发送任何待发消息")

    assert await runtime.outbox.send_due(_must_not_resolve) == 0

    audit = await _audit_detail(runtime, "group.delete")
    assert audit["actor"] == "phase6-tester"
    assert audit["details"] == {
        "messages_retained": 2,
        "memories_deleted": 1,
        "memory_candidates_deleted": 1,
        "outbox_cancelled": 2,
        "name": "待删除群",
    }


@pytest.mark.asyncio
async def test_persona_deletion_removes_versions_events_and_unbinds_groups(runtime: AppRuntime) -> None:
    async with runtime.database.session() as session:
        account = Account(display_name="人格删除账号", enabled=True)
        persona = Persona(name="待删除人格")
        session.add_all([account, persona])
        await session.flush()
        group = Group(
            account_id=account.id,
            platform_group_id="phase6-persona-group",
            name="人格绑定群",
            enabled=True,
            persona_id=persona.id,
        )
        version = PersonaVersion(
            persona_id=persona.id,
            version_no=1,
            change_summary="初始版本",
            snapshot_json={"name": persona.name},
        )
        trait = PersonaTrait(persona_id=persona.id, trait_key="tone", trait_value="克制")
        event = PersonaEvolutionEvent(
            persona_id=persona.id,
            batch_id="phase6-persona-batch",
            trigger_type="manual",
            summary="待删除事件",
        )
        session.add_all([group, version, trait, event])
        await session.commit()
        ids = {
            "persona_id": persona.id,
            "group_id": group.id,
            "version_id": version.id,
            "trait_id": trait.id,
            "event_id": event.id,
        }

    await runtime.personas.delete_persona(ids["persona_id"], actor="phase6-tester")

    async with runtime.database.session() as session:
        assert await session.get(Persona, ids["persona_id"]) is None
        assert await session.get(PersonaVersion, ids["version_id"]) is None
        assert await session.get(PersonaTrait, ids["trait_id"]) is None
        assert await session.get(PersonaEvolutionEvent, ids["event_id"]) is None
        group = await session.get(Group, ids["group_id"])
        assert group is not None and group.persona_id is None

    audit = await _audit_detail(runtime, "persona.delete")
    assert audit["actor"] == "phase6-tester"
    assert audit["details"]["name"] == "待删除人格"


def test_delete_routes_require_server_side_confirmation(settings: Settings) -> None:
    app = create_app(settings)
    with TestClient(app) as client:
        demo = _data(client.post("/api/demo/bootstrap", json={}))
        account_id = demo["account"]["id"]
        group_id = demo["group"]["id"]

        missing = client.delete(f"/api/accounts/{account_id}")
        assert missing.status_code == 400
        assert missing.json()["error"]["code"] == "CONFIRMATION_REQUIRED"
        _data(client.get(f"/api/accounts/{account_id}"))

        wrong = client.delete(f"/api/accounts/{account_id}", params={"confirm": "delete"})
        assert wrong.status_code == 400
        assert wrong.json()["error"]["code"] == "CONFIRMATION_REQUIRED"
        _data(client.get(f"/api/accounts/{account_id}"))

        assert client.delete(f"/api/groups/{group_id}").status_code == 400
        _data(client.get(f"/api/groups/{group_id}"))

        _data(client.delete(f"/api/groups/{group_id}", params={"confirm": "DELETE"}))
        assert client.get(f"/api/groups/{group_id}").status_code == 404

        _data(client.delete(f"/api/accounts/{account_id}", params={"confirm": "DELETE"}))
        assert client.get(f"/api/accounts/{account_id}").status_code == 404

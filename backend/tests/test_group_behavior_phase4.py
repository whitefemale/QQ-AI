"""阶段 4 群聊行为：四档模式、人工确认、限频、群级长度与输出审查。"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest
from app.core.config import Settings
from app.core.errors import AppError, ErrorCode
from app.core.time import utcnow
from app.db.session import Database
from app.main import create_app
from app.models.account import Account
from app.models.governance import AuditLog
from app.models.group import Group, Member
from app.models.message import OutboxMessage
from app.pipeline.policy import (
    DEFAULT_RATE_LIMITS,
    PolicyEngine,
    PolicyInput,
    RateLimitSnapshot,
    check_rate_limits,
    effective_max_reply_chars,
)
from app.schemas.message import CanonicalMessage
from app.services.settings_store import set_global_pause
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from tests.test_pipeline import MEMBER_ID, build_env, count_rows, mention

SENSITIVE_REPLY = "我的登录密码是 abc12345"


def _data(response: Any, expected_status: int = 200) -> Any:
    assert response.status_code == expected_status, response.text
    body = response.json()
    assert body["error"] is None, body
    return body["data"]


def _error(response: Any, expected_status: int) -> dict[str, Any]:
    assert response.status_code == expected_status, response.text
    body = response.json()
    assert body["error"] is not None
    return body["error"]


def test_new_group_defaults_to_observe_and_modes_are_honest(settings: Settings) -> None:
    app = create_app(settings)
    with TestClient(app) as client:
        demo = _data(client.post("/api/demo/bootstrap", json={}))
        account_id = demo["account"]["id"]
        listing = _data(client.get("/api/groups"))
        modes = {item["value"]: item for item in listing["reply_modes"]}
        assert modes["observe"]["label"].startswith("观察")
        assert modes["manual_confirm"]["label"] == "手动确认"
        assert modes["keyword"]["label"].startswith("关键词")
        assert modes["context"]["state"] == "planned"
        assert modes["scheduled"]["state"] == "planned"

        created = _data(
            client.post(
                "/api/groups",
                json={
                    "account_id": account_id,
                    "platform_group_id": "phase4-default-group",
                    "name": "新群默认观察",
                },
            )
        )
        assert created["reply_mode"] == "observe"
        assert created["enabled"] is False
        assert created["max_reply_chars"] is None
        assert created["max_reply_chars_effective"] == settings.max_reply_chars
        assert created["context_message_limit_effective"] == settings.context_message_limit

        limited = _data(
            client.patch(
                f"/api/groups/{created['id']}",
                json={"max_reply_chars": 120, "context_message_limit": 12},
            )
        )
        assert limited["max_reply_chars"] == 120
        assert limited["context_message_limit"] == 12
        assert limited["max_reply_chars_effective"] == 120

        _error(
            client.patch(f"/api/groups/{created['id']}", json={"max_reply_chars": 10}),
            400,
        )
        _error(
            client.patch(f"/api/groups/{created['id']}", json={"context_message_limit": 101}),
            400,
        )

        # 导入已存在的群只更新名称，不静默改写 reply_mode；演示群仍是显式 mention_only。
        imported = _data(
            client.post(
                "/api/groups/import",
                json={
                    "account_id": account_id,
                    "groups": [
                        {"platform_group_id": "phase4-default-group", "name": "导入后的名称"},
                        {"platform_group_id": "phase4-imported-new", "name": "导入的新群"},
                    ],
                },
            )
        )
        assert imported == {"created": 1, "updated": 1}
        groups = {item["platform_group_id"]: item for item in _data(client.get("/api/groups"))["items"]}
        assert groups["phase4-default-group"]["reply_mode"] == "observe"
        assert groups["phase4-default-group"]["name"] == "导入后的名称"
        assert groups["phase4-imported-new"]["reply_mode"] == "observe"
        assert groups[demo["group"]["platform_group_id"]]["reply_mode"] == "mention_only"


async def test_manual_confirm_queues_then_approve_sends_and_reject_stops(
    database: Database,
    settings: Settings,
) -> None:
    env = await build_env(database, settings, group_attrs={"reply_mode": "manual_confirm"})

    result = await env.pipeline.handle(
        mention(env.adapter, "手动确认测试"),
        account=env.account,
        group=env.group,
        adapter=env.adapter,
    )

    assert result.accepted is True
    assert result.action == "awaiting_approval"
    assert result.outbox_id
    assert env.adapter.sent_messages == []
    outbox = env.pipeline.outbox
    record = await outbox.get(result.outbox_id)
    assert record is not None
    assert record.status == "pending_approval"
    assert record.origin_member_platform_user_id == MEMBER_ID
    assert record.reply_kind == "reply"

    stored = await env.message_service.get(result.message_id or "")
    assert stored is not None
    assert stored.processing_status == "awaiting_approval"

    # 到期派发绝不能发送待审核草稿。
    processed = await outbox.send_due(lambda *_args: env.adapter)
    assert processed == 0
    pending = await outbox.get(result.outbox_id)
    assert pending is not None and pending.status == "pending_approval"

    approved = await outbox.approve(result.outbox_id, adapter=env.adapter, actor="tester")
    assert approved.status == "sent"
    assert len(env.adapter.sent_messages) == 1
    sent = await outbox.get(result.outbox_id)
    assert sent is not None and sent.content == result.reply

    audits = []
    async with database.session() as session:
        audits = list((await session.execute(select(AuditLog).where(AuditLog.action == "outbox.approve"))).scalars())
    assert len(audits) == 1
    assert audits[0].details_json["result"] == "approved"
    assert "password" not in str(audits[0].details_json).lower()

    # 重复批准/拒绝非待审记录都返回冲突，而不是再次发送。
    with pytest.raises(AppError) as excinfo:
        await outbox.approve(result.outbox_id, adapter=env.adapter, actor="tester")
    assert excinfo.value.code == ErrorCode.CONFLICT

    second = await env.pipeline.handle(
        mention(env.adapter, "拒绝测试"),
        account=env.account,
        group=env.group,
        adapter=env.adapter,
    )
    assert second.outbox_id
    rejected = await outbox.reject(second.outbox_id, reason="内容不合适", actor="tester")
    assert rejected.status == "rejected"
    with pytest.raises(AppError) as reject_conflict:
        await outbox.approve(second.outbox_id, adapter=env.adapter, actor="tester")
    assert reject_conflict.value.code == ErrorCode.CONFLICT
    assert len(env.adapter.sent_messages) == 1


async def test_approval_rechecks_rules_and_keeps_pending_on_failure(
    database: Database,
    settings: Settings,
) -> None:
    env = await build_env(database, settings, group_attrs={"reply_mode": "manual_confirm"})
    result = await env.pipeline.handle(
        mention(env.adapter, "批准前检查"),
        account=env.account,
        group=env.group,
        adapter=env.adapter,
    )
    assert result.outbox_id

    # 全局暂停优先阻断，记录必须留在待审状态。
    await set_global_pause(database, paused=True, reason="测试")
    with pytest.raises(AppError) as paused:
        await env.pipeline.outbox.approve(result.outbox_id, adapter=env.adapter, actor="tester")
    assert paused.value.code == ErrorCode.CONFLICT
    assert paused.value.details and paused.value.details.get("reason") == "global_paused"
    record = await env.pipeline.outbox.get(result.outbox_id)
    assert record is not None
    assert record.status == "pending_approval"
    assert record.last_error_code == ErrorCode.POLICY_BLOCKED
    await set_global_pause(database, paused=False)

    # 敏感编辑内容被拦截，也不会发送。
    with pytest.raises(AppError) as sensitive:
        await env.pipeline.outbox.approve(
            result.outbox_id,
            content=SENSITIVE_REPLY,
            adapter=env.adapter,
            actor="tester",
        )
    assert sensitive.value.details and sensitive.value.details.get("reason") == "sensitive_output"
    assert env.adapter.sent_messages == []

    # 群暂停同样阻止批准。
    async with database.session() as session:
        group = await session.get(Group, env.group.id)
        assert group is not None
        group.paused = True
        await session.commit()
    with pytest.raises(AppError) as group_paused:
        await env.pipeline.outbox.approve(result.outbox_id, adapter=env.adapter, actor="tester")
    assert group_paused.value.details and group_paused.value.details.get("reason") == "group_paused"
    async with database.session() as session:
        group = await session.get(Group, env.group.id)
        assert group is not None
        group.paused = False
        await session.commit()

    # 恢复后可以正常批准；编辑后的文本经过清洗并发送。
    approved = await env.pipeline.outbox.approve(
        result.outbox_id,
        content="人工编辑后的回复",
        adapter=env.adapter,
        actor="tester",
    )
    assert approved.status == "sent"
    assert approved.content == "人工编辑后的回复"
    assert len(env.adapter.sent_messages) == 1


async def test_approval_respects_quiet_hours_and_member_mute(
    database: Database,
    settings: Settings,
) -> None:
    env = await build_env(database, settings, group_attrs={"reply_mode": "manual_confirm"})
    async with database.session() as session:
        group = await session.get(Group, env.group.id)
        assert group is not None
        group.quiet_hours_json = {"enabled": True, "start": "00:00", "end": "23:59", "timezone": "Asia/Shanghai"}
        session.add(
            Member(
                account_id=env.account.id,
                platform_user_id=MEMBER_ID,
                display_name="被静默成员",
                muted_until=utcnow() + timedelta(hours=1),
            )
        )
        await session.commit()

    record = await env.pipeline.outbox.enqueue(
        account_id=env.account.id,
        group_id=env.group.id,
        conversation_id=env.group.platform_group_id,
        conversation_type="group",
        content="待审核内容",
        idempotency_key="phase4-quiet-approval",
        origin_member_platform_user_id=MEMBER_ID,
        status="pending_approval",
    )
    with pytest.raises(AppError) as quiet:
        await env.pipeline.outbox.approve(record.id, adapter=env.adapter, actor="tester")
    assert quiet.value.details and quiet.value.details.get("reason") == "quiet_hours"

    async with database.session() as session:
        group = await session.get(Group, env.group.id)
        assert group is not None
        group.quiet_hours_json = {}
        await session.commit()
    with pytest.raises(AppError) as muted:
        await env.pipeline.outbox.approve(record.id, adapter=env.adapter, actor="tester")
    assert muted.value.details and muted.value.details.get("reason") == "member_muted"
    stored = await env.pipeline.outbox.get(record.id)
    assert stored is not None and stored.status == "pending_approval"


async def test_send_preflight_blocks_sensitive_and_overlong_output(database: Database, settings: Settings) -> None:
    env = await build_env(database, settings)
    record = await env.pipeline.outbox.enqueue(
        account_id=env.account.id,
        group_id=env.group.id,
        conversation_id=env.group.platform_group_id,
        conversation_type="group",
        content="初始正常内容",
        idempotency_key="phase4-preflight-sensitive",
    )
    async with database.session() as session:
        row = await session.get(OutboxMessage, record.id)
        assert row is not None
        row.content = SENSITIVE_REPLY
        await session.commit()

    sent = await env.pipeline.outbox.send(record.id, env.adapter)
    assert sent.status == "failed"
    assert sent.last_error_code == ErrorCode.SENSITIVE_OUTPUT
    assert env.adapter.sent_messages == []

    async with database.session() as session:
        group = await session.get(Group, env.group.id)
        assert group is not None
        group.max_reply_chars = 50
        await session.commit()
    overlong = await env.pipeline.outbox.enqueue(
        account_id=env.account.id,
        group_id=env.group.id,
        conversation_id=env.group.platform_group_id,
        conversation_type="group",
        content="很" * 60,
        idempotency_key="phase4-preflight-long",
    )
    sent = await env.pipeline.outbox.send(overlong.id, env.adapter)
    assert sent.status == "failed"
    assert sent.last_error_code == ErrorCode.OUTPUT_TOO_LONG
    assert env.adapter.sent_messages == []


async def test_member_rate_limit_counts_only_sent_ai_replies(database: Database, settings: Settings) -> None:
    env = await build_env(database, settings)
    outbox = env.pipeline.outbox
    for index in range(3):
        record = await outbox.enqueue(
            account_id=env.account.id,
            group_id=env.group.id,
            conversation_id=env.group.platform_group_id,
            conversation_type="group",
            content=f"已发送回复 {index}",
            idempotency_key=f"phase4-member-sent-{index}",
            origin_member_platform_user_id=MEMBER_ID,
            reply_kind="reply",
        )
        async with database.session() as session:
            row = await session.get(OutboxMessage, record.id)
            assert row is not None
            row.status = "sent"
            row.sent_at = utcnow()
            await session.commit()

    # 命令回复、待审核草稿和其他成员的回复都不占用该成员的额度。
    command = await outbox.enqueue(
        account_id=env.account.id,
        group_id=env.group.id,
        conversation_id=env.group.platform_group_id,
        conversation_type="group",
        content="命令回复",
        idempotency_key="phase4-member-command",
        origin_member_platform_user_id=MEMBER_ID,
        reply_kind="command",
    )
    pending = await outbox.enqueue(
        account_id=env.account.id,
        group_id=env.group.id,
        conversation_id=env.group.platform_group_id,
        conversation_type="group",
        content="待审核",
        idempotency_key="phase4-member-pending",
        origin_member_platform_user_id=MEMBER_ID,
        status="pending_approval",
    )
    other = await outbox.enqueue(
        account_id=env.account.id,
        group_id=env.group.id,
        conversation_id=env.group.platform_group_id,
        conversation_type="group",
        content="其他成员",
        idempotency_key="phase4-member-other",
        origin_member_platform_user_id="29999",
    )
    async with database.session() as session:
        for outbox_id in (command.id, other.id):
            row = await session.get(OutboxMessage, outbox_id)
            assert row is not None
            row.status = "sent"
            row.sent_at = utcnow()
        await session.commit()

    stats = await env.message_service.outbox_stats_by_origin(
        env.account.id,
        env.group.id,
        MEMBER_ID,
        utcnow() - timedelta(hours=1),
    )
    assert stats["count"] == 3
    snapshot = RateLimitSnapshot(member_replies_last_hour=3, member_replies_today=3)
    limits = {**DEFAULT_RATE_LIMITS, "cooldown_seconds": 0, "max_replies_per_member_per_hour": 3}
    blocked = check_rate_limits(snapshot, limits, utcnow())
    assert blocked is not None
    assert blocked.reason == "member_hourly_limit"
    stored_pending = await outbox.get(pending.id)
    assert stored_pending is not None and stored_pending.status == "pending_approval"
    pending_stats = await env.message_service.outbox_stats_by_origin(
        env.account.id,
        env.group.id,
        MEMBER_ID,
        utcnow() - timedelta(hours=1),
    )
    assert pending_stats["count"] == 3  # 待审核草稿始终不计入


def test_group_effective_limits_and_repeat_loop_guard() -> None:
    group = Group(account_id="acc", platform_group_id="g", max_reply_chars=120, context_message_limit=5)
    assert effective_max_reply_chars(group, 500) == 120
    assert effective_max_reply_chars(None, 500) == 500

    policy = PolicyEngine()
    account = Account(id="acc", enabled=True)
    group.enabled = True
    group.paused = False
    group.reply_mode = "always"
    now = utcnow()

    def message(index: int) -> CanonicalMessage:
        return CanonicalMessage(
            account_id="acc",
            message_id=f"loop-{index}",
            conversation_id="g",
            conversation_type="group",
            sender_id=MEMBER_ID,
            segments=[{"type": "text", "text": "重复刷屏内容"}],
            source_adapter="test",
        )

    def decide(index: int) -> Any:
        current = message(index)
        return policy.hard_block(
            PolicyInput(
                message=current,
                account=account,
                group=group,
                member=None,
                global_paused=False,
                self_platform_user_id="10000",
                reply_to_self=False,
                rate=RateLimitSnapshot(),
                now=now,
            )
        )

    # 同一条消息重复经过 hard_block（命令判断 + 主判断）不得重复计数。
    assert decide(1) is None
    assert decide(1) is None
    assert decide(2) is None
    assert decide(2) is None
    assert decide(3) is None
    assert decide(4) is not None
    assert decide(4).reason == "repeat_loop"

    empty = CanonicalMessage(
        account_id="acc",
        message_id="empty-1",
        conversation_id="g",
        conversation_type="group",
        sender_id=MEMBER_ID,
        segments=[],
        source_adapter="test",
    )
    blocked = policy.hard_block(
        PolicyInput(
            message=empty,
            account=account,
            group=group,
            member=None,
            global_paused=False,
            self_platform_user_id="10000",
            reply_to_self=False,
            rate=RateLimitSnapshot(),
            now=now,
        )
    )
    assert blocked is not None and blocked.reason == "invalid_message"


async def test_manual_confirm_outbox_fields_are_public(database: Database, settings: Settings) -> None:
    env = await build_env(database, settings, group_attrs={"reply_mode": "manual_confirm"})
    result = await env.pipeline.handle(
        mention(env.adapter, "队列字段"),
        account=env.account,
        group=env.group,
        adapter=env.adapter,
    )
    assert result.outbox_id
    async with database.session() as session:
        count = await session.scalar(select(func.count()).select_from(OutboxMessage))
    assert count == 1
    assert await count_rows(database, OutboxMessage) == 1

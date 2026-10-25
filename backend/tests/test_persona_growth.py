"""人格子系统测试：三模式、证据门槛、治理、锁定、跨群隔离、版本与回滚。"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import pytest
import pytest_asyncio
from app.adapters.llm.mock import MockLLMProvider
from app.adapters.qq.mock import MockQQAdapter
from app.budgets.service import BudgetService
from app.core.config import Settings
from app.core.errors import AppError, ErrorCode
from app.core.security import CredentialCipher
from app.db.session import Database
from app.models.account import Account
from app.models.group import Group
from app.models.message import Message
from app.models.persona import PersonaEvolutionEvent, PersonaTrait
from app.models.provider import LLMProvider, LLMUsage
from app.pipeline.events import EventBus
from app.pipeline.llm_gateway import LLMGateway
from app.pipeline.persona_growth import PersonaGrowthService, _parse_proposal
from app.schemas.message import CanonicalMessage
from app.services.message_service import MessageService
from app.services.persona_store import PersonaStore
from sqlalchemy import func, select

SELF_ID = "10000"
MEMBER_ID = "20001"


@dataclass
class GrowthEnv:
    database: Database
    settings: Settings
    store: PersonaStore
    growth: PersonaGrowthService
    gateway: LLMGateway
    adapter: MockQQAdapter
    messages: MessageService
    events: EventBus
    account: Account
    provider: LLMProvider
    group1: Group
    group2: Group
    persona_id: str


async def build_env(
    database: Database,
    settings: Settings,
    *,
    persona_overrides: dict[str, Any] | None = None,
    provider_config: dict[str, Any] | None = None,
    bind_second: bool = False,
) -> GrowthEnv:
    async with database.session() as session:
        account = Account(
            display_name="人格测试账号",
            platform="qq",
            adapter_type="mock",
            self_platform_user_id=SELF_ID,
            enabled=True,
        )
        session.add(account)
        await session.flush()
        provider = LLMProvider(
            name="Mock 成长模型",
            provider_type="mock",
            model="mock-model",
            enabled=True,
            is_default=True,
            config_json=provider_config or {},
        )
        session.add(provider)
        await session.commit()
        await session.refresh(account)
        await session.refresh(provider)

    store = PersonaStore(database)
    payload: dict[str, Any] = {
        "name": "空白小友",
        "mode": "emergent",
        "growth_policy": "auto",
        "growth_enabled": True,
        "learning_scope": "group",
        "thresholds": {"min_conversations": 1},
    }
    payload.update(persona_overrides or {})
    created = await store.create_persona(payload, actor="test")
    persona_id = created["id"]

    async with database.session() as session:
        group1 = Group(
            account_id=account.id,
            platform_group_id="100001",
            name="成长测试群一",
            enabled=True,
            reply_mode="mention_only",
            persona_id=persona_id,
        )
        group2 = Group(
            account_id=account.id,
            platform_group_id="100002",
            name="成长测试群二",
            enabled=True,
            reply_mode="mention_only",
            persona_id=persona_id if bind_second else None,
        )
        session.add_all([group1, group2])
        await session.commit()
        await session.refresh(group1)
        await session.refresh(group2)

    events = EventBus()
    messages = MessageService(database)
    budget = BudgetService(database, settings)
    gateway = LLMGateway(
        database,
        settings,
        CredentialCipher(settings.credential_encryption_key or ""),
        budget,
    )
    growth = PersonaGrowthService(
        database,
        settings,
        gateway,
        store=store,
        events=events,
    )
    adapter = MockQQAdapter(instance_id="growth-adapter", account_id=account.id, self_id=SELF_ID)
    return GrowthEnv(
        database=database,
        settings=settings,
        store=store,
        growth=growth,
        gateway=gateway,
        adapter=adapter,
        messages=messages,
        events=events,
        account=account,
        provider=provider,
        group1=group1,
        group2=group2,
        persona_id=persona_id,
    )


async def add_messages(
    env: GrowthEnv,
    group: Group,
    texts: list[str],
    *,
    prefix: str,
) -> list[Message]:
    records: list[Message] = []
    for index, text in enumerate(texts):
        message: CanonicalMessage = env.adapter.inject_message(
            conversation_id=group.platform_group_id,
            text=text,
            message_id=f"{prefix}-{index}",
            sender_id=f"2000{index + 1}",
        )
        record = await env.messages.persist_incoming(message, group_id=group.id)
        assert record is not None
        records.append(record)
    return records


async def count_rows(database: Database, model: type) -> int:
    async with database.session() as session:
        return int(await session.scalar(select(func.count()).select_from(model)) or 0)


@pytest_asyncio.fixture
async def env(database: Database, settings: Settings) -> GrowthEnv:
    return await build_env(database, settings)


async def test_emergent_persona_starts_blank_and_rejects_presets(database: Database, settings: Settings) -> None:
    store = PersonaStore(database)
    created = await store.create_persona(
        {"name": "空白人格", "mode": "emergent"},
        actor="test",
    )
    detail = await store.detail(created["id"])
    assert detail["mode"] == "emergent"
    assert detail["self_description"] == ""
    assert detail["stable_trait_count"] == 0
    assert detail["latest_version"] == 1
    assert detail["traits"] == []

    with pytest.raises(AppError) as excinfo:
        await store.create_persona(
            {
                "name": "伪造空白",
                "mode": "emergent",
                "self_description": "我本来就有性格",
            },
            actor="test",
        )
    assert excinfo.value.code == ErrorCode.PERSONA_MODE_INVALID

    template = await store.create_persona(
        {"name": "模板人格", "mode": "template", "template_key": "quiet_observer"},
        actor="test",
    )
    assert template["self_description"]


async def test_single_message_does_not_change_persona(env: GrowthEnv) -> None:
    records = await add_messages(env, env.group1, ["只有一句话"], prefix="solo")
    assert len(records) == 1

    outcome = await env.growth.analyze(env.persona_id, group_id=env.group1.id, trigger="manual")

    assert outcome.result == "insufficient_evidence"
    assert outcome.applied is False
    assert outcome.evidence_count == 1
    assert await count_rows(env.database, PersonaTrait) == 0
    assert await count_rows(env.database, LLMUsage) == 0
    detail = await env.store.detail(env.persona_id)
    assert detail["self_description"] == ""
    assert detail["latest_version"] == 1
    events = await env.store.list_events(env.persona_id)
    assert events[0]["result"] == "insufficient_evidence"


async def test_auto_growth_applies_version_and_skips_reasoning(
    env: GrowthEnv,
) -> None:
    await add_messages(env, env.group1, ["今天聊得很开心", "有什么推荐吗", "谢谢你的建议"], prefix="auto")

    outcome = await env.growth.analyze(env.persona_id, group_id=env.group1.id, trigger="manual")

    assert outcome.applied is True
    assert outcome.result == "applied"
    assert outcome.version_no == 2
    assert outcome.trait_count >= 2
    detail = await env.store.detail(env.persona_id)
    assert detail["self_description"]
    assert detail["stable_trait_count"] == 1
    traits = await env.store.list_traits(env.persona_id, status="stable")
    assert traits[0]["source_scope"] == env.group1.id
    assert traits[0]["evidence_count"] >= 3
    events = await env.store.list_events(env.persona_id)
    applied = events[0]
    assert applied["result"] == "applied"
    payload = json.dumps(applied["proposal"], ensure_ascii=False)
    assert "reason_summary" not in payload
    assert "diff" not in payload
    assert "assistant_analysis" not in payload


async def test_default_threshold_requires_two_conversations(database: Database, settings: Settings) -> None:
    env = await build_env(
        database,
        settings,
        persona_overrides={"thresholds": {}},
    )
    await add_messages(env, env.group1, ["一", "二", "三"], prefix="th-group1")
    await add_messages(env, env.group2, ["四", "五", "六"], prefix="th-group2")

    outcome = await env.growth.analyze(env.persona_id, group_id=env.group1.id)

    assert outcome.result == "insufficient_evidence"
    assert outcome.conversation_count == 1
    detail = await env.store.detail(env.persona_id)
    assert detail["latest_version"] == 1


async def test_cross_group_learning_is_explicit_and_scoped(database: Database, settings: Settings) -> None:
    env = await build_env(
        database,
        settings,
        persona_overrides={"learning_scope": "cross_group", "thresholds": {}},
        bind_second=True,
    )
    await add_messages(env, env.group1, ["群一的消息甲", "群一的消息乙", "群一的消息丙"], prefix="cg1")
    await add_messages(env, env.group2, ["群二的消息甲", "群二的消息乙", "群二的消息丙"], prefix="cg2")

    outcome = await env.growth.analyze(env.persona_id, trigger="manual")

    assert outcome.applied is True
    assert outcome.conversation_count == 2
    traits = await env.store.list_traits(env.persona_id, status="stable")
    assert traits[0]["source_scope"] == "global"


async def test_group_scope_cannot_read_unbound_group(env: GrowthEnv) -> None:
    await add_messages(env, env.group2, ["别人的群", "别人的聊天", "别人的内容"], prefix="iso")

    with pytest.raises(AppError) as excinfo:
        await env.growth.analyze(env.persona_id, group_id=env.group2.id)

    assert excinfo.value.code == ErrorCode.PERSONA_SCOPE_REQUIRED
    assert await count_rows(env.database, PersonaTrait) == 0


async def test_review_policy_creates_candidate_then_approval_applies(
    env: GrowthEnv,
) -> None:
    await env.store.update_persona(
        env.persona_id,
        {"growth_policy": "review"},
        actor="test",
    )
    await add_messages(env, env.group1, ["早呀", "今天聊什么", "我来听听"], prefix="review")

    outcome = await env.growth.analyze(env.persona_id, group_id=env.group1.id)

    assert outcome.result == "pending_review"
    assert outcome.applied is False
    detail = await env.store.detail(env.persona_id)
    assert detail["self_description"] == ""
    assert detail["candidate_trait_count"] == 1
    assert detail["stable_trait_count"] == 0
    assert detail["latest_version"] == 2  # 创建 + 更新成长策略

    approved = await env.growth.review(outcome.event_id or "", approve=True)

    assert approved.applied is True
    assert approved.version_no == 3
    detail = await env.store.detail(env.persona_id)
    assert detail["self_description"]
    assert detail["stable_trait_count"] == 1
    event = await env.store.list_events(env.persona_id)
    assert event[0]["result"] == "applied"


async def test_review_rejection_keeps_persona_unchanged(env: GrowthEnv) -> None:
    await env.store.update_persona(env.persona_id, {"growth_policy": "review"}, actor="test")
    await add_messages(env, env.group1, ["甲", "乙", "丙"], prefix="reject")

    outcome = await env.growth.analyze(env.persona_id, group_id=env.group1.id)
    rejected = await env.growth.review(outcome.event_id or "", approve=False)

    assert rejected.result == "rejected"
    detail = await env.store.detail(env.persona_id)
    assert detail["self_description"] == ""
    assert detail["stable_trait_count"] == 0
    assert detail["latest_version"] == 2


async def test_paused_and_authored_are_not_grown(database: Database, settings: Settings) -> None:
    paused = await build_env(
        database,
        settings,
        persona_overrides={"growth_policy": "paused"},
    )
    await add_messages(paused, paused.group1, ["甲", "乙", "丙"], prefix="paused")
    with pytest.raises(AppError) as excinfo:
        await paused.growth.analyze(paused.persona_id, group_id=paused.group1.id)
    assert excinfo.value.code == ErrorCode.PERSONA_GROWTH_PAUSED


async def test_authored_persona_is_unsupported(database: Database, settings: Settings) -> None:
    env = await build_env(
        database,
        settings,
        persona_overrides={
            "mode": "authored",
            "self_description": "我是用户写好的角色。",
            "growth_policy": "auto",
        },
    )
    await add_messages(env, env.group1, ["甲", "乙", "丙"], prefix="authored")
    with pytest.raises(AppError) as excinfo:
        await env.growth.analyze(env.persona_id, group_id=env.group1.id)
    assert excinfo.value.code == ErrorCode.PERSONA_GROWTH_UNSUPPORTED


async def test_locked_description_is_skipped_but_trait_applies(env: GrowthEnv) -> None:
    await env.store.update_persona(
        env.persona_id,
        {"locked_fields": ["self_description"]},
        actor="test",
    )
    await add_messages(env, env.group1, ["甲", "乙", "丙"], prefix="lockdesc")

    outcome = await env.growth.analyze(env.persona_id, group_id=env.group1.id)

    assert outcome.applied is True
    assert "跳过" in outcome.message
    detail = await env.store.detail(env.persona_id)
    assert detail["self_description"] == ""
    assert detail["stable_trait_count"] == 1


async def test_locked_trait_blocks_all_changes(database: Database, settings: Settings) -> None:
    proposal = {
        "self_description": None,
        "proposed_traits": [
            {
                "trait_key": "reply_style",
                "trait_value": "偏好简短回应",
                "category": "style",
                "confidence": 0.9,
            }
        ],
        "summary": "提案一条特征",
        "scope": "global",
    }
    env = await build_env(
        database,
        settings,
        provider_config={"mock_growth_proposal": proposal},
        bind_second=False,
    )
    await env.store.update_persona(
        env.persona_id,
        {"locked_fields": ["trait:reply_style"]},
        actor="test",
    )
    await add_messages(env, env.group1, ["甲", "乙", "丙"], prefix="locktrait")

    outcome = await env.growth.analyze(env.persona_id, group_id=env.group1.id)

    assert outcome.result == "skipped"
    assert outcome.applied is False
    detail = await env.store.detail(env.persona_id)
    assert detail["stable_trait_count"] == 0
    assert detail["latest_version"] == 2  # 创建 + 锁定设置
    assert outcome.event_id


async def test_fabricated_evidence_is_rejected(database: Database, settings: Settings) -> None:
    proposal = {
        "self_description": None,
        "proposed_traits": [
            {
                "trait_key": "chat_habit",
                "trait_value": "喜欢主动打招呼",
                "category": "habit",
                "confidence": 0.9,
                "evidence_message_ids": ["fake-1", "fake-2", "fake-3"],
            }
        ],
        "summary": "伪造证据的提案",
    }
    env = await build_env(database, settings, provider_config={"mock_growth_proposal": proposal})
    await add_messages(env, env.group1, ["甲", "乙", "丙"], prefix="fake")

    outcome = await env.growth.analyze(env.persona_id, group_id=env.group1.id)

    assert outcome.result == "rejected"
    assert "不存在或无权限" in outcome.message
    assert await count_rows(env.database, PersonaTrait) == 0
    detail = await env.store.detail(env.persona_id)
    assert detail["latest_version"] == 1


async def test_sensitive_inference_is_rejected(database: Database, settings: Settings) -> None:
    proposal = {
        "self_description": None,
        "proposed_traits": [
            {
                "trait_key": "member_profile",
                "trait_value": "知道某位成员的性取向和疾病情况",
                "category": "other",
                "confidence": 0.9,
            }
        ],
        "summary": "敏感推断",
    }
    env = await build_env(database, settings, provider_config={"mock_growth_proposal": proposal})
    await add_messages(env, env.group1, ["甲", "乙", "丙"], prefix="sensitive")

    outcome = await env.growth.analyze(env.persona_id, group_id=env.group1.id)

    assert outcome.result == "rejected"
    assert "敏感" in outcome.message
    assert await count_rows(env.database, PersonaTrait) == 0


async def test_invalid_scope_is_rejected(database: Database, settings: Settings) -> None:
    proposal = {
        "self_description": None,
        "proposed_traits": [
            {
                "trait_key": "tone",
                "trait_value": "语气克制",
                "category": "style",
                "confidence": 0.8,
            }
        ],
        "summary": "作用域错误",
        "scope": "another-group-id",
    }
    env = await build_env(database, settings, provider_config={"mock_growth_proposal": proposal})
    await add_messages(env, env.group1, ["甲", "乙", "丙"], prefix="scope")

    outcome = await env.growth.analyze(env.persona_id, group_id=env.group1.id)

    assert outcome.result == "rejected"
    assert "作用域" in outcome.message


async def test_rollback_reset_and_evidence_deletion(env: GrowthEnv) -> None:
    records = await add_messages(env, env.group1, ["甲", "乙", "丙"], prefix="history")
    outcome = await env.growth.analyze(env.persona_id, group_id=env.group1.id)
    assert outcome.applied is True
    detail = await env.store.detail(env.persona_id)
    assert detail["self_description"]

    versions = await env.store.list_versions(env.persona_id)
    version_one = next(item for item in versions if item["version_no"] == 1)
    restored = await env.store.rollback(env.persona_id, version_one["id"], actor="test")
    assert restored["self_description"] == ""
    assert restored["stable_trait_count"] == 0
    assert restored["latest_version"] == 3

    await env.growth.analyze(env.persona_id, group_id=env.group1.id)
    traits = await env.store.list_traits(env.persona_id, status="stable")
    assert traits and traits[0]["evidence_count"] == 3
    result = await env.store.delete_evidence(records[0].id, actor="test")
    assert result["affected_traits"] == 1
    assert result["demoted_traits"] == 1
    traits = await env.store.list_traits(env.persona_id)
    assert traits[0]["status"] == "candidate"
    assert records[0].id not in traits[0]["evidence_message_ids"]

    reset = await env.store.reset(env.persona_id, actor="test")
    assert reset["self_description"] == ""
    assert reset["stable_trait_count"] == 0
    assert reset["candidate_trait_count"] == 0


async def test_events_are_recorded_without_chain_of_thought(env: GrowthEnv) -> None:
    await add_messages(env, env.group1, ["甲", "乙", "丙"], prefix="events")
    await env.growth.analyze(env.persona_id, group_id=env.group1.id)
    async with env.database.session() as session:
        events = list((await session.execute(select(PersonaEvolutionEvent))).scalars())
    assert events
    stored = json.dumps(events[0].proposal_json, ensure_ascii=False)
    assert "reason_summary" not in stored
    assert "chain_of_thought" not in stored
    assert "diff" not in stored


def test_parse_proposal_rejects_invalid_json_and_keeps_only_allowed_fields() -> None:
    document, error = _parse_proposal("这不是 JSON")
    assert document is None
    assert error

    document, error = _parse_proposal(
        '```json\n{"self_description": "温和", "proposed_traits": [], '
        '"summary": "摘要", "reason_summary": "不要保存", "diff": "不要保存"}\n```'
    )
    assert error is None
    assert document is not None
    sanitized = document.sanitized(5)
    assert "reason_summary" not in sanitized
    assert "diff" not in sanitized
    assert sanitized["self_description"] == "温和"


def test_mock_growth_provider_is_honest() -> None:
    provider = MockLLMProvider(
        provider_id="mock",
        name="Mock",
        model="mock-model",
    )
    assert provider.is_mock is True
    assert provider.provider_type == "mock"

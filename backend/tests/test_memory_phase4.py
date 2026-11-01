"""阶段 4 记忆：短期上下文隔离、导出、来源、清理与候选敏感度。"""

from __future__ import annotations

import csv
import io
from datetime import timedelta
from typing import Any

import pytest
from app.api.messages import MEMORY_CSV_COLUMNS
from app.core.config import Settings
from app.core.time import utcnow
from app.db.session import Database
from app.main import create_app
from app.models.account import Account
from app.models.group import Group
from app.models.memory import Memory, MemoryCandidate
from app.models.message import Message
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, text
from tests.test_pipeline import MEMBER_ID, build_env


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


def _csv_rows(content: bytes) -> list[list[str]]:
    assert content.startswith(b"\xef\xbb\xbf")
    return list(csv.reader(io.StringIO(content.decode("utf-8-sig"))))


def test_memory_export_excludes_sensitive_by_default_and_audits(settings: Settings) -> None:
    app = create_app(settings)
    with TestClient(app) as client:
        demo = _data(client.post("/api/demo/bootstrap", json={}))
        account_id = demo["account"]["id"]
        group_id = demo["group"]["id"]

        normal = _data(
            client.post(
                "/api/memories",
                json={"account_id": account_id, "group_id": group_id, "content": "每周五同步项目计划"},
            )
        )
        sensitive = _data(
            client.post(
                "/api/memories",
                json={
                    "account_id": account_id,
                    "group_id": group_id,
                    "content": "成员不愿公开的个人安排",
                    "sensitivity": "sensitive",
                },
            )
        )
        formula = _data(
            client.post(
                "/api/memories",
                json={"account_id": account_id, "group_id": group_id, "content": "=SUM(A1:A2)"},
            )
        )

        exported = client.get("/api/memories/export.csv", params={"group_id": group_id})
        assert exported.status_code == 200, exported.text
        assert exported.headers["content-type"].startswith("text/csv")
        assert "attachment" in exported.headers["content-disposition"]
        assert exported.headers["cache-control"] == "no-store"
        assert exported.headers["x-content-type-options"] == "nosniff"
        assert exported.headers["x-memory-export-includes-sensitive"] == "false"
        rows = _csv_rows(exported.content)
        assert rows[0] == MEMORY_CSV_COLUMNS
        body = rows[1:]
        assert {row[0] for row in body} == {normal["id"], formula["id"]}
        assert all(row[6] == "normal" for row in body)
        assert sensitive["content"] not in exported.content.decode("utf-8-sig")
        formula_row = next(row for row in body if row[0] == formula["id"])
        assert formula_row[5] == "'=SUM(A1:A2)"

        with_sensitive = client.get(
            "/api/memories/export.csv",
            params={"group_id": group_id, "include_sensitive": "true"},
        )
        assert with_sensitive.status_code == 200
        assert with_sensitive.headers["x-memory-export-includes-sensitive"] == "true"
        included = _csv_rows(with_sensitive.content)[1:]
        assert {row[0] for row in included} == {normal["id"], sensitive["id"], formula["id"]}

        audit = _data(client.get("/api/audit", params={"action": "memory.export"}))
        assert audit["total"] == 2
        details = [item["details"] for item in audit["items"]]
        assert {item["include_sensitive"] for item in details} == {False, True}
        assert all("content" not in str(item).lower() for item in details)
        assert all(item["rows"] == 2 for item in details) or {item["rows"] for item in details} == {2, 3}


def test_memory_sources_are_scoped_and_redacted(settings: Settings) -> None:
    app = create_app(settings)
    with TestClient(app) as client:
        demo = _data(client.post("/api/demo/bootstrap", json={}))
        account_id = demo["account"]["id"]
        group_id = demo["group"]["id"]

        _data(
            client.post(
                f"/api/accounts/{account_id}/mock/events",
                json={
                    "group_internal_id": group_id,
                    "text": "来源消息一：周五同步进度",
                    "sender_id": "20001",
                    "sender_name": "来源群友",
                },
            )
        )
        messages = _data(client.get("/api/messages", params={"group_id": group_id, "direction": "inbound"}))["items"]
        source_id = messages[0]["id"]

        memory = _data(
            client.post(
                "/api/memories",
                json={
                    "account_id": account_id,
                    "group_id": group_id,
                    "content": "来源测试记忆",
                    "source_message_ids": [source_id, "deleted-message"],
                },
            )
        )
        sources = _data(client.get(f"/api/memories/{memory['id']}/sources"))
        assert sources["items"][0]["id"] == source_id
        assert sources["items"][0]["missing"] is False
        assert sources["items"][0]["group_id"] == group_id
        assert "周五同步进度" in sources["items"][0]["preview"]
        deleted = next(item for item in sources["items"] if item["id"] == "deleted-message")
        assert deleted["missing"] is True
        assert deleted["preview"] == ""
        assert sources["missing_count"] == 1


def test_cleanup_handles_expired_pinned_and_older_than(settings: Settings) -> None:
    app = create_app(settings)
    with TestClient(app) as client:
        demo = _data(client.post("/api/demo/bootstrap", json={}))
        account_id = demo["account"]["id"]
        group_id = demo["group"]["id"]
        past = (utcnow() - timedelta(days=1)).isoformat()
        old = (utcnow() - timedelta(days=60)).isoformat()

        expired = _data(
            client.post(
                "/api/memories",
                json={
                    "account_id": account_id,
                    "group_id": group_id,
                    "content": "已过期记忆",
                    "expires_at": past,
                },
            )
        )
        pinned = _data(
            client.post(
                "/api/memories",
                json={
                    "account_id": account_id,
                    "group_id": group_id,
                    "content": "固定过期记忆",
                    "expires_at": past,
                    "is_pinned": True,
                },
            )
        )
        old_memory = _data(
            client.post(
                "/api/memories",
                json={"account_id": account_id, "group_id": group_id, "content": "很久以前的记忆"},
            )
        )

        dry = _data(client.post("/api/memories/cleanup", json={"mode": "expired", "dry_run": True}))
        assert dry["matched"] == 1
        assert dry["deleted"] == 0
        assert "仅统计" in dry["note"]
        _data(client.get(f"/api/memories/{expired['id']}"))

        missing_confirm = _error(client.post("/api/memories/cleanup", json={"mode": "expired"}), 400)
        assert missing_confirm["code"] == "CONFIRMATION_REQUIRED"
        _data(client.get(f"/api/memories/{expired['id']}"))

        real = _data(client.post("/api/memories/cleanup", json={"mode": "expired", "confirm": "CLEANUP"}))
        assert real["matched"] == 1
        assert real["deleted"] == 1
        _error(client.get(f"/api/memories/{expired['id']}"), 404)
        _data(client.get(f"/api/memories/{pinned['id']}"))

        # 通过同步引擎回填创建时间，验证 older_than；固定记忆仍不会被清理。
        engine = create_engine(settings.database_sync_url)
        try:
            with engine.begin() as connection:
                connection.execute(
                    text("UPDATE memories SET created_at = :created WHERE id = :id"),
                    {"created": old, "id": old_memory["id"]},
                )
        finally:
            engine.dispose()

        older_dry = _data(
            client.post(
                "/api/memories/cleanup",
                json={"mode": "older_than", "days": 30, "dry_run": True},
            )
        )
        assert older_dry["matched"] == 1
        assert older_dry["deleted"] == 0
        older = _data(
            client.post(
                "/api/memories/cleanup",
                json={"mode": "older_than", "days": 30, "confirm": "CLEANUP"},
            )
        )
        assert older["deleted"] == 1
        _error(client.get(f"/api/memories/{old_memory['id']}"), 404)
        _data(client.get(f"/api/memories/{pinned['id']}"))

        _error(client.post("/api/memories/cleanup", json={"mode": "older_than", "days": 0}), 400)
        _error(client.post("/api/memories/cleanup", json={"mode": "everything"}), 400)

        audit = _data(client.get("/api/audit", params={"action": "memory.cleanup"}))
        assert audit["total"] == 4
        dry_flags = [item["details"]["dry_run"] for item in audit["items"]]
        assert dry_flags.count(True) == 2
        assert dry_flags.count(False) == 2


async def test_deleted_memory_is_not_retrieved_and_context_is_isolated(database: Database, settings: Settings) -> None:
    env = await build_env(database, settings, group_attrs={"allow_memory": True})
    memory = await env.memory_service.create_memory(
        {
            "account_id": env.account.id,
            "group_id": env.group.id,
            "content": "小绿习惯在每周五同步项目进度。",
            "memory_type": "preference",
            "confidence": 0.9,
        }
    )
    selection = await env.memory_service.retrieve_for_prompt(
        account_id=env.account.id,
        group=env.group,
        sender_id=MEMBER_ID,
        query_text="项目进度怎么样？",
    )
    assert memory["id"] in selection.ids
    assert any("小绿习惯在每周五同步项目进度" in note for note in selection.notes)

    assert await env.memory_service.delete_memory(memory["id"]) is True
    selection = await env.memory_service.retrieve_for_prompt(
        account_id=env.account.id,
        group=env.group,
        sender_id=MEMBER_ID,
        query_text="项目进度怎么样？",
    )
    assert memory["id"] not in selection.ids
    assert all("小绿习惯在每周五同步项目进度" not in note for note in selection.notes)

    # 相同 conversation_id 但不同账号/群的短期上下文互不可见。
    async with database.session() as session:
        other_account = Account(display_name="另一个账号", enabled=True)
        session.add(other_account)
        await session.flush()
        other_group = Group(
            account_id=other_account.id,
            platform_group_id=env.group.platform_group_id,
            name="另一个群",
            enabled=True,
        )
        session.add(other_group)
        await session.commit()
        await session.refresh(other_account)
        await session.refresh(other_group)
        for index, (account_id, group_id, label) in enumerate(
            [
                (env.account.id, env.group.id, "本群旧消息"),
                (other_account.id, other_group.id, "别的群消息"),
                (env.account.id, None, "私聊旧消息"),
            ]
        ):
            session.add(
                Message(
                    platform_message_id=f"ctx-{index}",
                    account_id=account_id,
                    group_id=group_id,
                    conversation_id=env.group.platform_group_id,
                    conversation_type="group" if group_id else "private",
                    sender_id="20001",
                    direction="inbound",
                    content_text=label,
                    segments_json=[{"type": "text", "text": label}],
                    event_timestamp=utcnow() - timedelta(minutes=10 - index),
                    processing_status="received",
                )
            )
        await session.commit()

    group_records = await env.message_service.recent_for_conversation(
        env.group.platform_group_id,
        account_id=env.account.id,
        group_id=env.group.id,
    )
    assert [record.content_text for record in group_records] == ["本群旧消息"]
    private_records = await env.message_service.recent_for_conversation(
        env.group.platform_group_id,
        account_id=env.account.id,
        group_id=None,
    )
    assert [record.content_text for record in private_records] == ["私聊旧消息"]


async def test_candidate_approval_can_mark_sensitive(database: Database, settings: Settings) -> None:
    env = await build_env(database, settings, group_attrs={"allow_memory": True})
    async with database.session() as session:
        candidate = MemoryCandidate(
            account_id=env.account.id,
            group_id=env.group.id,
            memory_type="fact",
            content="成员的家庭住址细节不应自动注入。",
            source_message_ids_json=[],
            confidence=0.8,
            status="pending",
            is_mock=False,
        )
        session.add(candidate)
        await session.commit()
        await session.refresh(candidate)
        candidate_id = candidate.id

    approved = await env.extraction_service.approve_candidate(
        candidate_id,
        actor="tester",
        payload={"sensitivity": "sensitive"},
    )
    assert approved["memory"]["sensitivity"] == "sensitive"
    assert approved["memory"]["auto_injectable"] is False
    selection = await env.memory_service.retrieve_for_prompt(
        account_id=env.account.id,
        group=env.group,
        sender_id=MEMBER_ID,
        query_text="家庭住址",
    )
    assert approved["memory"]["id"] not in selection.ids

    async with database.session() as session:
        second = MemoryCandidate(
            account_id=env.account.id,
            group_id=env.group.id,
            memory_type="fact",
            content="另一条待审核记忆。",
            source_message_ids_json=[],
            confidence=0.7,
            status="pending",
            is_mock=False,
        )
        session.add(second)
        await session.commit()
        await session.refresh(second)
        second_id = second.id

    with pytest.raises(Exception) as excinfo:
        await env.extraction_service.approve_candidate(second_id, actor="tester", payload={"sensitivity": "secret"})
    assert getattr(excinfo.value, "code", "") == "VALIDATION_ERROR"

    async with database.session() as session:
        rows = list((await session.execute(select(Memory))).scalars())
    assert len(rows) == 1

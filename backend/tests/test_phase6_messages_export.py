"""阶段 6：消息 CSV 导出范围、公式防注入、审计脱敏与行数上限。"""

from __future__ import annotations

import csv
import io
from typing import Any

from app.api.messages import MESSAGE_CSV_COLUMNS
from app.core.config import Settings
from app.main import create_app
from app.services.query_service import MessageQueryService
from fastapi.testclient import TestClient


def _data(response: Any) -> Any:
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["error"] is None, body
    return body["data"]


def _csv_rows(content: bytes) -> list[list[str]]:
    assert content.startswith(b"\xef\xbb\xbf")
    return list(csv.reader(io.StringIO(content.decode("utf-8-sig"))))


def test_message_export_has_bom_filters_formula_escaping_and_safe_audit(settings: Settings) -> None:
    app = create_app(settings)
    with TestClient(app) as client:
        demo = _data(client.post("/api/demo/bootstrap", json={}))
        account_id = demo["account"]["id"]
        group_id = demo["group"]["id"]
        for text, sender in (
            ("唯一导出关键词：周五同步", "发送者甲"),
            ("另一条普通消息", "发送者乙"),
            ("=SUM(A1:A2)", "发送者丙"),
        ):
            _data(
                client.post(
                    f"/api/accounts/{account_id}/mock/events",
                    json={
                        "group_internal_id": group_id,
                        "text": text,
                        "sender_id": f"3000{len(text)}",
                        "sender_name": sender,
                    },
                )
            )

        exported = client.get("/api/messages/export.csv", params={"group_id": group_id, "direction": "inbound"})
        assert exported.status_code == 200, exported.text
        assert exported.headers["content-type"].startswith("text/csv")
        assert "attachment" in exported.headers["content-disposition"]
        assert exported.headers["cache-control"] == "no-store"
        assert exported.headers["x-content-type-options"] == "nosniff"
        rows = _csv_rows(exported.content)
        assert rows[0] == MESSAGE_CSV_COLUMNS
        content_index = MESSAGE_CSV_COLUMNS.index("content_text")
        direction_index = MESSAGE_CSV_COLUMNS.index("direction")
        body = rows[1:]
        assert len(body) == 3
        assert {row[direction_index] for row in body} == {"inbound"}
        assert "'=SUM(A1:A2)" in {row[content_index] for row in body}
        rendered = exported.content.decode("utf-8-sig")
        for forbidden in ("segments", "api_key", "secret", "password", "authorization", "prompt"):
            assert forbidden not in rendered.lower()

        filtered = client.get(
            "/api/messages/export.csv",
            params={"group_id": group_id, "search": "唯一导出关键词"},
        )
        assert filtered.status_code == 200
        filtered_body = _csv_rows(filtered.content)[1:]
        assert len(filtered_body) == 1
        assert "唯一导出关键词" in filtered_body[0][content_index]

        audit = _data(client.get("/api/audit", params={"action": "message.export"}))
        assert audit["total"] == 2
        details = [item["details"] for item in audit["items"]]
        assert all(item["format"] == "csv" for item in details)
        assert sorted(item["rows"] for item in details) == [1, 3]
        assert {item["has_search"] for item in details} == {False, True}
        for item in details:
            assert "search" not in item
            assert "唯一导出关键词" not in str(item)
            assert "周五同步" not in str(item)


def test_message_export_rejects_invalid_range_and_row_limit(
    settings: Settings,
    monkeypatch: Any,
) -> None:
    app = create_app(settings)
    with TestClient(app) as client:
        demo = _data(client.post("/api/demo/bootstrap", json={}))
        group_id = demo["group"]["id"]

        invalid = client.get(
            "/api/messages/export.csv",
            params={"since": "2026-02-01T00:00:00Z", "until": "2026-01-01T00:00:00Z"},
        )
        assert invalid.status_code == 400
        assert invalid.json()["error"]["code"] == "VALIDATION_ERROR"

        async def _too_many(_self: Any, **_: Any) -> list[dict[str, str]]:
            return [{"id": str(index)} for index in range(50_001)]

        monkeypatch.setattr(MessageQueryService, "export_messages", _too_many)
        oversized = client.get("/api/messages/export.csv", params={"group_id": group_id})
        assert oversized.status_code == 413
        assert oversized.json()["error"]["code"] == "VALIDATION_ERROR"

        audit = _data(client.get("/api/audit", params={"action": "message.export"}))
        assert audit["total"] == 0

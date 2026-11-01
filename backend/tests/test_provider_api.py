"""Provider 测试 API：Mock 诚实性、费用、证据持久化、取消与脱敏（不访问真实网络）。"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

import pytest
from app.adapters.llm.base import BaseLLMProvider
from app.core.config import Settings
from app.main import create_app
from app.schemas.llm import LLMRequest, LLMResponse
from fastapi.testclient import TestClient


class SuccessAdapter(BaseLLMProvider):
    provider_type = "openai_compatible"

    def __init__(self, provider_id: str) -> None:
        super().__init__(provider_id=provider_id, name="测试真实类型", model="demo-model")
        self.calls = 0

    async def generate(self, request: LLMRequest) -> LLMResponse:
        self.calls += 1
        return LLMResponse(
            text="这是一次真实类型适配器的测试回复。",
            input_tokens=11,
            output_tokens=7,
            request_id="upstream-request-1",
        )


class PendingTask:
    def done(self) -> bool:
        return False


def _data(response: Any, expected_status: int = 200) -> Any:
    assert response.status_code == expected_status, response.text
    body = response.json()
    assert body["error"] is None, body
    assert body["request_id"]
    return body["data"]


def _error(response: Any, expected_status: int) -> dict[str, Any]:
    assert response.status_code == expected_status, response.text
    body = response.json()
    assert body["error"] is not None
    assert body["error"]["code"]
    assert body["error"]["message"]
    return body["error"]


def _sqlite_path(settings: Settings) -> Path:
    raw = settings.database_url.split("///", 1)[1]
    return Path(raw)


@pytest.fixture
def client(settings: Settings) -> Any:
    app = create_app(settings)
    with TestClient(app) as test_client:
        yield test_client


def _mock_provider(client: TestClient, name: str = "Mock 测试模型") -> dict[str, Any]:
    return _data(
        client.post(
            "/api/providers",
            json={"name": name, "provider_type": "mock"},
        )
    )


def _remote_provider(
    client: TestClient,
    *,
    secret: str = "sk-test-plain-secret",
    name: str = "远端测试模型",
) -> dict[str, Any]:
    return _data(
        client.post(
            "/api/providers",
            json={
                "name": name,
                "provider_type": "openai_compatible",
                "base_url": "https://llm.example.invalid/v1",
                "model": "demo-model",
                "api_key": secret,
            },
        )
    )


def test_mock_connectivity_and_generation_are_honest(client: TestClient) -> None:
    created = _mock_provider(client)
    provider_id = created["id"]
    assert created["is_mock"] is True
    assert created["config_complete"] is True
    assert created["last_test"] is None

    connectivity = _data(client.post(f"/api/providers/{provider_id}/test", json={}))
    assert connectivity["ok"] is True
    assert connectivity["kind"] == "connectivity"
    assert connectivity["outcome"] == "success"
    assert connectivity["is_mock"] is True
    assert connectivity["billable"] is False
    assert connectivity["usage"]["cost_status"] == "mock_zero"
    assert connectivity["usage"]["estimated_cost"] is None
    assert "Mock" in connectivity["message"]

    generation = _data(
        client.post(
            f"/api/providers/{provider_id}/test-generation",
            json={"prompt": "请写一句问候", "max_output_tokens": 16},
        )
    )
    assert generation["ok"] is True
    assert generation["kind"] == "generation"
    assert generation["text"]
    assert generation["is_mock"] is True

    detail = _data(client.get(f"/api/providers/{provider_id}"))
    assert detail["last_test"]["kind"] == "connectivity"
    assert detail["last_test"]["outcome"] == "success"
    assert detail["last_generation"]["kind"] == "generation"
    assert detail["last_tested_at"]
    assert detail["status"] == "available"

    usage = _data(client.get("/api/usage", params={"provider_id": provider_id}))
    assert usage["total"] == 2
    assert {item["purpose"] for item in usage["items"]} == {"test"}
    assert all(item["status"] == "success" for item in usage["items"])
    assert all(item["estimated_cost"] is None for item in usage["items"])

    models = _data(client.get(f"/api/providers/{provider_id}/models"))
    assert models["state"] == "mock"
    assert models["supported"] is False


def test_remote_test_records_usage_and_clear_key_invalidates_evidence(
    client: TestClient,
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret = "sk-test-plain-secret"
    created = _remote_provider(client, secret=secret)
    provider_id = created["id"]
    assert created["config_complete"] is True
    assert created["api_key_masked"] not in {"", secret}
    assert secret not in json.dumps(created)

    runtime = client.app.state.runtime
    adapter = SuccessAdapter(provider_id)
    monkeypatch.setattr(runtime.llm_gateway, "_adapter_for", lambda record, require_model=True: adapter)

    connectivity = _data(client.post(f"/api/providers/{provider_id}/test", json={}))
    assert connectivity["ok"] is True
    assert connectivity["is_mock"] is False
    assert connectivity["billable"] is True
    assert connectivity["usage"]["input_tokens"] == 11
    assert connectivity["usage"]["output_tokens"] == 7
    assert connectivity["usage"]["estimated_cost"] is None
    assert connectivity["usage"]["cost_status"] == "unavailable"
    assert connectivity["upstream_request_id"] == "upstream-request-1"

    generation = _data(
        client.post(
            f"/api/providers/{provider_id}/test-generation",
            json={"prompt": "自定义提示词", "max_output_tokens": 32, "temperature": 0.2},
        )
    )
    assert generation["text"] == "这是一次真实类型适配器的测试回复。"
    assert generation["billable"] is True
    assert generation["usage"]["cost_status"] == "unavailable"

    usage = _data(client.get("/api/usage", params={"provider_id": provider_id}))
    assert usage["total"] == 2
    assert all(item["request_id"] == "upstream-request-1" for item in usage["items"])

    detail = _data(client.get(f"/api/providers/{provider_id}"))
    assert detail["last_test"]["ok"] is True
    assert detail["last_generation"]["ok"] is True

    cleared = _data(client.patch(f"/api/providers/{provider_id}", json={"api_key": ""}))
    assert cleared["api_key_configured"] is False
    assert cleared["api_key_masked"] == ""
    assert cleared["config_complete"] is False
    assert cleared["status"] == "unconfigured"
    assert cleared["last_test"] is None
    assert cleared["last_generation"] is None
    assert cleared["last_tested_at"] is None
    assert cleared["last_error"] is None

    # 无 Key 时测试应返回 200 + ok=false，而不是抛出 500，也不访问网络。
    monkeypatch.undo()
    failed = _data(client.post(f"/api/providers/{provider_id}/test", json={}))
    assert failed["ok"] is False
    assert failed["error_code"] == "LLM_NOT_CONFIGURED"
    assert failed["is_mock"] is False

    models = _data(client.get(f"/api/providers/{provider_id}/models"))
    assert models["state"] == "not_configured"

    assert secret not in json.dumps(cleared)
    with sqlite3.connect(_sqlite_path(settings)) as connection:
        encrypted = connection.execute(
            "SELECT api_key_encrypted FROM llm_providers WHERE id = ?", (provider_id,)
        ).fetchone()[0]
        audit_rows = connection.execute("SELECT details_json FROM audit_logs").fetchall()
    # 清除后密文应为空；即使保留密文也不能是明文。
    assert encrypted is None or secret not in str(encrypted)
    assert all(secret not in str(row[0]) for row in audit_rows)


def test_priced_provider_test_reports_local_estimate_not_zero(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created = _data(
        client.post(
            "/api/providers",
            json={
                "name": "已定价远端模型",
                "provider_type": "openai_compatible",
                "base_url": "https://llm.example.invalid/v1",
                "model": "demo-model",
                "api_key": "sk-test-priced-secret",
                "config": {"input_price_per_1k": 0.01, "output_price_per_1k": 0.02},
            },
        )
    )
    provider_id = created["id"]
    runtime = client.app.state.runtime
    monkeypatch.setattr(
        runtime.llm_gateway,
        "_adapter_for",
        lambda record, require_model=True: SuccessAdapter(provider_id),
    )

    result = _data(client.post(f"/api/providers/{provider_id}/test", json={}))
    usage = result["usage"]
    assert usage["cost_status"] == "estimated"
    assert usage["estimated_cost"] == pytest.approx(11 * 0.01 / 1000 + 7 * 0.02 / 1000)
    assert usage["estimated_cost"] > 0
    assert "不是服务商账单" in usage["note"]

    records = _data(client.get("/api/usage", params={"provider_id": provider_id}))["items"]
    assert records[0]["estimated_cost"] == pytest.approx(usage["estimated_cost"])


def test_unpriced_provider_is_blocked_by_cost_budget_but_mock_is_not(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    remote = _remote_provider(client, name="未定价模型")
    mock = _mock_provider(client)
    runtime = client.app.state.runtime
    adapter = SuccessAdapter(remote["id"])
    monkeypatch.setattr(runtime.llm_gateway, "_adapter_for", lambda record, require_model=True: adapter)

    _data(
        client.post(
            "/api/budgets",
            json={
                "scope_type": "global",
                "scope_id": "",
                "window": "day",
                "metric": "cost",
                "limit_value": 1.0,
                "enabled": True,
            },
        )
    )

    error = _error(client.post(f"/api/providers/{remote['id']}/test", json={}), 429)
    assert error["code"] == "BUDGET_EXCEEDED"
    assert error["details"]["reason"] == "cost_unavailable"

    mock_result = _data(client.post(f"/api/providers/{mock['id']}/test", json={}))
    assert mock_result["ok"] is True
    assert mock_result["usage"]["cost_status"] == "mock_zero"


def test_operation_conflict_cancel_and_request_validation(client: TestClient) -> None:
    provider = _mock_provider(client)
    provider_id = provider["id"]

    _error(client.post(f"/api/providers/{provider_id}/test", json={"operation_id": "short"}), 400)
    _error(
        client.post(
            f"/api/providers/{provider_id}/test-generation",
            json={"prompt": "", "max_output_tokens": 8},
        ),
        400,
    )
    _error(
        client.post(
            f"/api/providers/{provider_id}/test-generation",
            json={"prompt": "测试", "max_output_tokens": 129},
        ),
        400,
    )

    cancelled = _data(client.post(f"/api/providers/{provider_id}/operations/cancel-operation-1/cancel"))
    assert cancelled["found"] is False
    assert cancelled["operation_id"] == "cancel-operation-1"

    runtime = client.app.state.runtime
    operation_id = "conflict-operation-1"
    runtime.llm_gateway.operations._tasks[(provider_id, operation_id)] = PendingTask()  # noqa: SLF001
    try:
        error = _error(
            client.post(f"/api/providers/{provider_id}/test", json={"operation_id": operation_id}),
            409,
        )
        assert error["code"] == "PROVIDER_OPERATION_CONFLICT"
    finally:
        runtime.llm_gateway.operations._tasks.pop((provider_id, operation_id), None)  # noqa: SLF001


def test_evidence_no_plaintext_and_audit_redacted(client: TestClient, settings: Settings) -> None:
    secret = "sk-audit-secret-value"
    created = _remote_provider(client, secret=secret)
    provider_id = created["id"]

    listed = client.get("/api/providers")
    assert listed.status_code == 200
    assert secret not in listed.text

    with sqlite3.connect(_sqlite_path(settings)) as connection:
        encrypted = connection.execute(
            "SELECT api_key_encrypted FROM llm_providers WHERE id = ?", (provider_id,)
        ).fetchone()[0]
        audit_rows = connection.execute("SELECT details_json FROM audit_logs").fetchall()
    assert encrypted and secret not in encrypted
    assert encrypted.startswith("enc:v1:")
    assert all(secret not in str(row[0]) for row in audit_rows)


def test_invalid_api_key_type_is_rejected(client: TestClient) -> None:
    provider = _remote_provider(client)
    response = client.patch(f"/api/providers/{provider['id']}", json={"api_key": None})
    error = _error(response, 400)
    assert error["code"] == "VALIDATION_ERROR"

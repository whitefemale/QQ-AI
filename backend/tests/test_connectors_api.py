"""连接器 API：本机守卫、确认词与诚实状态。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
from app.connectors.napcat import MANIFEST_MARKER
from app.core.config import Settings
from app.main import create_app
from fastapi.testclient import TestClient


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


def _build_managed(root: Path) -> None:
    package = root / "v4.18.42"
    package.mkdir(parents=True)
    installer = package / "NapCatInstaller.exe"
    installer.write_bytes(b"fake-installer")
    manifest = {
        "installer": MANIFEST_MARKER,
        "version": "v4.18.42",
        "installer_relative_path": "NapCatInstaller.exe",
        "installer_sha256": hashlib.sha256(installer.read_bytes()).hexdigest(),
    }
    (package / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    shell = package / "NapCat.Shell"
    (shell / "config").mkdir(parents=True)
    (shell / "napcat.bat").write_text("@echo off\n", encoding="utf-8")
    (shell / "config" / "onebot11.json").write_text(
        json.dumps({"network": {"httpServers": [], "websocketServers": []}}),
        encoding="utf-8",
    )


@pytest.fixture
def client(settings: Settings) -> Any:
    _build_managed(settings.connectors_path)
    app = create_app(settings)
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def remote_client(settings: Settings) -> Any:
    app = create_app(settings)
    with TestClient(app, client=("203.0.113.9", 50000)) as test_client:
        yield test_client


def test_summary_and_capabilities_are_honest(client: TestClient) -> None:
    summary = _data(client.get("/api/connectors"))
    assert summary["installations"]
    item = summary["installations"][0]
    assert item["managed"] is True
    assert item["state"]["state"] == "installed_not_started"
    assert item["real_traffic_verified"] is False
    assert summary["global_pause"]["paused"] is False

    capabilities = _data(client.get("/api/connectors/capabilities"))
    assert capabilities["local_only"] is True
    assert capabilities["real_qq_verified"] is False
    assert capabilities["supports"]["auto_update"] is False
    assert capabilities["supports"]["uninstall_or_delete"] is False
    assert capabilities["supports"]["remote_management"] is False


def test_connector_routes_reject_remote_client_even_when_local_host(remote_client: TestClient) -> None:
    for path in ("/api/connectors", "/api/connectors/capabilities", "/api/connectors/installations"):
        error = _error(remote_client.get(path), 403)
        assert error["code"] == "CONNECTOR_LOCAL_ONLY"


def test_connector_routes_reject_bad_host_or_origin(client: TestClient) -> None:
    # 未知 Host 由 TrustedHost 提前拒绝（纯文本 400）；允许来源仍可访问。
    bad_host = client.get("/api/connectors", headers={"Host": "evil.example"})
    assert bad_host.status_code == 400, bad_host.text
    assert bad_host.text == "Invalid host header"
    error = _error(client.get("/api/connectors", headers={"Origin": "https://evil.example"}), 403)
    assert error["code"] == "CONNECTOR_LOCAL_ONLY"
    assert client.get("/api/connectors", headers={"Origin": "http://127.0.0.1:5173"}).status_code == 200


def test_install_requires_exact_confirmation(client: TestClient) -> None:
    error = _error(client.post("/api/connectors/install", json={"version": "v4.18.42"}), 400)
    assert error["code"] == "CONNECTOR_CONFIRMATION_REQUIRED"
    error = _error(
        client.post("/api/connectors/install", json={"version": "v4.18.42", "confirm_text": "install"}),
        400,
    )
    assert error["code"] == "CONNECTOR_CONFIRMATION_REQUIRED"


def test_start_and_config_apply_require_confirmation(client: TestClient) -> None:
    item = _data(client.get("/api/connectors/installations"))["items"][0]
    assert (
        _error(client.post(f"/api/connectors/installations/{item['id']}/start", json={}), 400)["code"]
        == "CONNECTOR_CONFIRMATION_REQUIRED"
    )
    assert (
        _error(
            client.post(
                f"/api/connectors/installations/{item['id']}/config/apply",
                json={"confirm_text": "write config"},
            ),
            400,
        )["code"]
        == "CONNECTOR_CONFIRMATION_REQUIRED"
    )

    shell = Path(item["shell_path"])
    before = (shell / "config" / "onebot11.json").read_text(encoding="utf-8")
    applied = _data(
        client.post(
            f"/api/connectors/installations/{item['id']}/config/apply",
            json={"confirm_text": "WRITE CONFIG"},
        )
    )
    assert applied["applied"] is True
    assert applied["auto_connect"] is False
    assert applied["token_masked"]
    assert applied["token_masked"] != ""
    snapshot = _data(client.get(f"/api/connectors/installations/{item['id']}/snapshots"))
    assert snapshot["items"]
    assert "encrypted_content" not in json.dumps(snapshot)
    assert before != (shell / "config" / "onebot11.json").read_text(encoding="utf-8")


def test_global_pause_blocks_start_and_config_write(client: TestClient) -> None:
    item = _data(client.get("/api/connectors/installations"))["items"][0]
    _data(client.post("/api/system/pause-all", json={"reason": "连接器 API 测试"}))

    start = _error(
        client.post(
            f"/api/connectors/installations/{item['id']}/start",
            json={"confirm_text": "START NAPCAT"},
        ),
        409,
    )
    assert start["code"] == "CONNECTOR_GLOBAL_PAUSE"
    apply = _error(
        client.post(
            f"/api/connectors/installations/{item['id']}/config/apply",
            json={"confirm_text": "WRITE CONFIG"},
        ),
        409,
    )
    assert apply["code"] == "CONNECTOR_GLOBAL_PAUSE"


def test_unknown_installation_and_job_return_stable_codes(client: TestClient) -> None:
    assert _error(client.get("/api/connectors/installations/missing"), 404)["code"] == "CONNECTOR_NOT_FOUND"
    assert _error(client.get("/api/connectors/jobs/missing"), 404)["code"] == "CONNECTOR_JOB_NOT_FOUND"


def test_import_config_requires_confirmation_and_returns_masked_token(client: TestClient) -> None:
    payload = {
        "network": {
            "websocketServers": [
                {
                    "name": "ws",
                    "enable": True,
                    "host": "127.0.0.1",
                    "port": 3201,
                    "token": "secret-import-token-value",
                }
            ]
        }
    }
    assert (
        _error(
            client.post("/api/connectors/import-config", json={"text": json.dumps(payload)}),
            400,
        )["code"]
        == "CONNECTOR_CONFIRMATION_REQUIRED"
    )
    imported = _data(
        client.post(
            "/api/connectors/import-config",
            json={"text": json.dumps(payload), "confirm_text": "IMPORT CONFIG"},
        )
    )
    assert imported["verified"] is False
    assert "secret-import-token-value" not in json.dumps(imported)


def test_import_connector_groups_requires_matching_identity(client: TestClient) -> None:
    account = _data(
        client.post(
            "/api/accounts",
            json={
                "display_name": "Mock 导入身份测试",
                "instance": {"connection_mode": "mock", "name": "mock", "auto_connect": False},
            },
        )
    )
    instance = account["instances"][0]
    _data(client.post(f"/api/accounts/{account['id']}/instances/{instance['id']}/connect"))

    missing = _error(
        client.post(
            "/api/groups/import-connector",
            json={"account_id": account["id"], "instance_id": instance["id"]},
        ),
        400,
    )
    assert missing["code"] == "CONNECTOR_IDENTITY_MISMATCH"

    mock = _error(
        client.post(
            "/api/groups/import-connector",
            json={
                "account_id": account["id"],
                "instance_id": instance["id"],
                "confirm_self_user_id": "10000",
            },
        ),
        400,
    )
    assert mock["code"] == "ADAPTER_UNSUPPORTED_OPERATION"

"""ConnectorManager：配置快照/回滚、实例创建、导入与身份确认。"""

from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
from app.adapters.qq.mock import MockQQAdapter
from app.connectors.manager import ConnectorManager
from app.connectors.napcat import MANIFEST_MARKER
from app.core.config import Settings
from app.core.errors import AppError
from app.core.security import CredentialCipher
from app.db.session import Database
from app.models.account import Account, AdapterInstance
from app.models.connector import ConnectorConfigSnapshot
from sqlalchemy import select


class FakeAdapterManager:
    def __init__(self) -> None:
        self.adapters: dict[str, Any] = {}
        self.online: Any = None
        self.forgotten: list[str] = []

    def get_adapter(self, instance_id: str) -> Any:
        return self.adapters.get(instance_id)

    def online_adapter(self, account_id: str, instance_id: str | None = None) -> Any:
        if self.online is None:
            return None
        if instance_id and getattr(self.online, "instance_id", None) != instance_id:
            return None
        if getattr(self.online, "account_id", None) != account_id:
            return None
        return self.online

    async def forget_instance(self, instance_id: str) -> None:
        self.forgotten.append(instance_id)
        self.adapters.pop(instance_id, None)

    async def disconnect_instance(self, instance_id: str) -> None:
        adapter = self.adapters.pop(instance_id, None)
        if adapter is not None:
            adapter.status = "disconnected"


class FakeAccountService:
    async def test_saved_instance(self, account_id: str, instance_id: str, overrides: Any = None) -> dict[str, Any]:
        return {"ok": False, "state": "diagnostic_failed", "checks": [], "account_id": account_id}


def _write(path: Path, payload: dict[str, Any] | str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False, indent=2)
    path.write_text(text + "\n", encoding="utf-8")


def build_managed(root: Path, version: str = "v4.18.42") -> Path:
    package = root / version
    package.mkdir(parents=True)
    installer = package / "NapCatInstaller.exe"
    installer.write_bytes(b"fake-installer")
    manifest = {
        "installer": MANIFEST_MARKER,
        "version": version,
        "installer_relative_path": "NapCatInstaller.exe",
        "installer_sha256": hashlib.sha256(installer.read_bytes()).hexdigest(),
        "license": {"status": "not_fetched"},
    }
    _write(package / "manifest.json", manifest)
    shell = package / "NapCat.Shell"
    (shell / "config").mkdir(parents=True)
    (shell / "napcat.bat").write_text("@echo off\n", encoding="utf-8")
    _write(shell / "package.json", {"version": version})
    _write(
        shell / "config" / "onebot11.json",
        {
            "musicSignUrl": "keep-me",
            "network": {
                "httpServers": [{"name": "user-http", "enable": True, "port": 3999}],
                "websocketServers": [],
            },
        },
    )
    return shell


@pytest.fixture
async def manager(
    settings: Settings,
    database: Database,
) -> ConnectorManager:
    build_managed(settings.connectors_path)
    return ConnectorManager(
        database=database,
        settings=settings,
        cipher=CredentialCipher(settings.credential_encryption_key),
        adapter_manager=FakeAdapterManager(),  # type: ignore[arg-type]
        account_service=FakeAccountService(),  # type: ignore[arg-type]
    )


async def _only_installation(manager: ConnectorManager) -> dict[str, Any]:
    items = await manager.scan()
    assert len(items) == 1
    return items[0]


async def test_scan_reports_installed_not_started(manager: ConnectorManager) -> None:
    item = await _only_installation(manager)
    assert item["managed"] is True
    assert item["shell_installed"] is True
    assert item["state"]["state"] == "installed_not_started"
    assert item["version_compatibility"] == "documented"
    assert item["real_traffic_verified"] is False
    assert item["can_configure"] is True


async def test_apply_creates_encrypted_instance_and_snapshot(manager: ConnectorManager, database: Database) -> None:
    item = await _only_installation(manager)
    preview = await manager.preview_config(item["id"])
    assert preview["can_apply"] is True, preview
    assert preview["planned_ports"]["http"] and preview["planned_ports"]["websocket"]
    assert "token" not in json.dumps(preview).lower() or "token_masked" in preview

    applied = await manager.apply_config(item["id"], actor="test")
    assert applied["applied"] is True
    assert applied["auto_connect"] is False
    assert applied["token_masked"]

    shell = Path(item["shell_path"])
    written = json.loads((shell / "config" / "onebot11.json").read_text(encoding="utf-8"))
    assert written["musicSignUrl"] == "keep-me"
    managed_http = next(entry for entry in written["network"]["httpServers"] if entry["name"] == "ai-group-friend-http")
    assert managed_http["host"] == "127.0.0.1"
    assert managed_http["port"] == applied["ports"]["http"]
    assert len(managed_http["token"]) >= 32

    async with database.session() as session:
        instance = await session.scalar(
            select(AdapterInstance).where(AdapterInstance.connector_installation_id == item["id"])
        )
        assert instance is not None
        assert instance.auto_connect is False
        assert instance.connection_mode == "onebot11"
        assert instance.token_encrypted
        assert instance.token_encrypted != managed_http["token"]
        snapshot = await session.scalar(
            select(ConnectorConfigSnapshot).where(
                ConnectorConfigSnapshot.installation_id == item["id"],
                ConnectorConfigSnapshot.snapshot_group == applied["snapshot_group"],
            )
        )
        assert snapshot is not None
        assert managed_http["token"] not in snapshot.encrypted_content
        assert snapshot.sha256


async def test_second_apply_and_rollback_restore_config_and_token(
    manager: ConnectorManager,
    database: Database,
    settings: Settings,
) -> None:
    item = await _only_installation(manager)
    first = await manager.apply_config(item["id"], actor="test")
    first_token = await _instance_token(database, first["instance_id"], settings.credential_encryption_key)
    second = await manager.apply_config(item["id"], actor="test")
    second_token = await _instance_token(database, second["instance_id"], settings.credential_encryption_key)
    assert first_token != second_token

    rolled = await manager.rollback_config(item["id"], snapshot_group=second["snapshot_group"], actor="test")
    assert rolled["restored"] is True
    shell = Path(item["shell_path"])
    restored = json.loads((shell / "config" / "onebot11.json").read_text(encoding="utf-8"))
    http_entry = next(entry for entry in restored["network"]["httpServers"] if entry["name"] == "ai-group-friend-http")
    assert http_entry["token"] == first_token
    assert await _instance_token(database, second["instance_id"], settings.credential_encryption_key) == first_token


async def _instance_token(
    database: Database,
    instance_id: str,
    key: str,
) -> str | None:
    async with database.session() as session:
        instance = await session.get(AdapterInstance, instance_id)
        assert instance is not None
        cipher = CredentialCipher(key)
        return cipher.decrypt(instance.token_encrypted) if instance.token_encrypted else None


async def test_failed_verification_restores_config_and_instance(
    manager: ConnectorManager,
    database: Database,
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    item = await _only_installation(manager)
    first = await manager.apply_config(item["id"], actor="test")
    first_token = await _instance_token(database, first["instance_id"], settings.credential_encryption_key)
    shell = Path(item["shell_path"])
    before = (shell / "config" / "onebot11.json").read_text(encoding="utf-8")

    def _fail(target: Path, **_: Any) -> None:
        raise RuntimeError("simulated verification failure")

    monkeypatch.setattr(manager, "_verify_applied", _fail)
    with pytest.raises(AppError) as exc:
        await manager.apply_config(item["id"], actor="test")
    assert exc.value.code == "CONNECTOR_CONFIG_WRITE_FAILED"
    assert (shell / "config" / "onebot11.json").read_text(encoding="utf-8") == before
    assert await _instance_token(database, first["instance_id"], settings.credential_encryption_key) == first_token
    assert exc.value.details.get("restored") is True


async def test_import_config_encrypts_token_and_never_returns_plaintext(
    manager: ConnectorManager,
    database: Database,
) -> None:
    raw_token = "import-token-" + "x" * 24
    payload = {
        "network": {
            "httpServers": [
                {"name": "imported-http", "enable": True, "host": "127.0.0.1", "port": 3100, "token": raw_token}
            ],
            "websocketServers": [
                {"name": "imported-ws", "enable": True, "host": "127.0.0.1", "port": 3101, "token": raw_token}
            ],
        }
    }
    result = await manager.import_config(text=json.dumps(payload), display_name="导入测试", actor="test")
    assert result["verified"] is False
    assert result["endpoint"] == "ws://127.0.0.1:3101"
    assert result["api_endpoint"] == "http://127.0.0.1:3100"
    assert raw_token not in json.dumps(result)
    async with database.session() as session:
        instance = await session.get(AdapterInstance, result["instance_id"])
        assert instance is not None
        assert instance.token_encrypted
        assert raw_token not in instance.token_encrypted


async def test_import_rejects_invalid_or_remote_config(manager: ConnectorManager) -> None:
    with pytest.raises(AppError) as exc:
        await manager.import_config(text="{not json", display_name=None, actor="test")
    assert exc.value.code == "CONNECTOR_IMPORT_INVALID"

    remote = {
        "network": {"websocketServers": [{"name": "ws", "enable": True, "host": "8.8.8.8", "port": 3001, "token": "t"}]}
    }
    with pytest.raises(AppError) as exc:
        await manager.import_config(text=json.dumps(remote), display_name=None, actor="test")
    assert exc.value.code == "CONNECTOR_IMPORT_INVALID"


async def test_identity_confirmation_requires_matching_online_non_mock(
    manager: ConnectorManager,
    database: Database,
) -> None:
    async with database.session() as session:
        account = Account(display_name="身份测试", platform="qq", adapter_type="onebot11", enabled=True)
        session.add(account)
        await session.flush()
        instance = AdapterInstance(
            account_id=account.id,
            name="conn",
            endpoint="ws://127.0.0.1:3001",
            connection_mode="onebot11",
            status="online",
            token_encrypted=None,
        )
        session.add(instance)
        await session.commit()
        account_id = account.id
        instance_id = instance.id

    fake = type(
        "OnlineAdapter",
        (),
        {
            "instance_id": instance_id,
            "account_id": account_id,
            "status": "online",
            "self_platform_user_id": "10001",
        },
    )()
    assert isinstance(manager.adapter_manager, FakeAdapterManager)
    manager.adapter_manager.online = fake

    with pytest.raises(AppError) as exc:
        await manager.confirm_identity(account_id, user_id="20002", actor="test")
    assert exc.value.code == "CONNECTOR_IDENTITY_MISMATCH"

    confirmed = await manager.confirm_identity(account_id, user_id="10001", actor="test")
    assert confirmed["user_id"] == "10001"
    async with database.session() as session:
        stored = await session.get(AdapterInstance, instance_id)
        assert stored is not None
        assert stored.identity_confirmed_user_id == "10001"
        assert stored.identity_confirmed_at is not None

    manager.adapter_manager.online = MockQQAdapter(instance_id=instance_id, account_id=account_id)
    manager.adapter_manager.online.status = "online"
    with pytest.raises(AppError) as exc:
        await manager.confirm_identity(account_id, user_id="10001", actor="test")
    assert exc.value.code == "ADAPTER_UNSUPPORTED_OPERATION"


async def test_paused_global_blocks_config_and_start(manager: ConnectorManager, database: Database) -> None:
    item = await _only_installation(manager)
    from app.services.settings_store import set_global_pause

    await set_global_pause(database, paused=True, reason="test", actor="test")
    with pytest.raises(AppError) as exc:
        await manager.apply_config(item["id"], actor="test")
    assert exc.value.code == "CONNECTOR_GLOBAL_PAUSE"
    with pytest.raises(AppError) as exc:
        await manager.start_connector(item["id"], actor="test")
    assert exc.value.code == "CONNECTOR_GLOBAL_PAUSE"


async def test_diagnose_reuses_online_adapter_without_second_connection(
    manager: ConnectorManager,
    database: Database,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    item = await _only_installation(manager)
    applied = await manager.apply_config(item["id"], actor="test")
    assert isinstance(manager.adapter_manager, FakeAdapterManager)
    assert isinstance(manager.account_service, FakeAccountService)

    calls: list[tuple[Any, str]] = []

    class _Report:
        def model_dump(self, *, mode: str) -> dict[str, Any]:
            return {"checks": [{"name": "websocket", "status": "ok", "detail": "ok", "source": "x"}]}

    async def fake_diagnostics(adapter: Any, *, connection_mode: str, **_: Any) -> Any:
        calls.append((adapter, connection_mode))
        return _Report()

    monkeypatch.setattr("app.connectors.manager.run_connection_diagnostics", fake_diagnostics)
    live = type(
        "LiveAdapter",
        (),
        {
            "instance_id": applied["instance_id"],
            "account_id": applied["account_id"],
            "status": "online",
        },
    )()
    manager.adapter_manager.online = live
    manager.account_service.calls = 0  # type: ignore[attr-defined]

    result = await manager.diagnose_installation(item["id"])

    assert result["reused_live_adapter"] is True
    assert result["diagnostic_source"] == "live_adapter"
    assert result["message_send_attempted"] is False
    assert calls == [(live, "onebot11")]
    assert manager.account_service.calls == 0  # type: ignore[attr-defined]
    assert result["checks"][0]["source"] == "live_adapter"


async def test_start_refuses_listening_port_without_touching_external_process(
    manager: ConnectorManager,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    item = await _only_installation(manager)
    started: list[str] = []
    monkeypatch.setattr("app.connectors.manager.is_port_listening", lambda port: port == 3999)
    monkeypatch.setattr(
        manager.process,
        "start_connector",
        lambda *args, **kwargs: started.append("start"),
    )

    with pytest.raises(AppError) as exc:
        await manager.start_connector(item["id"], actor="test")
    assert exc.value.code == "CONNECTOR_PORT_CONFLICT"
    assert exc.value.details.get("ports") == [3999]
    assert started == []


async def test_config_apply_refuses_while_owned_process_running(
    manager: ConnectorManager,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    item = await _only_installation(manager)
    monkeypatch.setattr(manager.process, "connector_record", lambda _id: object())
    with pytest.raises(AppError) as exc:
        await manager.apply_config(item["id"], actor="test")
    assert exc.value.code == "CONNECTOR_CONFIG_BUSY"


async def test_activate_switches_managed_versions_without_deleting_old(
    manager: ConnectorManager,
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    item = await _only_installation(manager)
    old_shell = build_managed(settings.connectors_path, "v4.18.41")
    monkeypatch.setattr("app.connectors.manager.is_port_listening", lambda _port: False)
    items = await manager.scan()
    assert len(items) == 2, [(e["id"], e["version"], e["active"]) for e in items]
    active = next(entry for entry in items if entry["active"])
    target = next(entry for entry in items if not entry["active"])
    assert active["id"] == item["id"]

    result = await manager.activate_installation(target["id"], actor="test")
    assert result["activated"] is True
    after = await manager.list_installations(rescan=False)
    assert next(entry for entry in after if entry["id"] == target["id"])["active"] is True
    assert next(entry for entry in after if entry["id"] == item["id"])["active"] is False
    assert await asyncio.to_thread(old_shell.is_dir)
    assert await asyncio.to_thread(Path(item["shell_path"]).is_dir)

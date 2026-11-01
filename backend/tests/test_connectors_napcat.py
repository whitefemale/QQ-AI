"""NapCat profile：受管探测、版本门槛、配置合并与路径安全。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from app.connectors.base import ConnectorConfigFile, ConnectorInstallationInfo
from app.connectors.napcat import (
    MANIFEST_MARKER,
    NapCatError,
    NapCatProfile,
)


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def managed_package(root: Path, *, version: str = "v4.18.42", with_shell: bool = True) -> Path:
    package = root / version
    package.mkdir(parents=True)
    installer = package / "NapCatInstaller.exe"
    installer.write_bytes(b"fake-installer")
    manifest = {
        "installer": MANIFEST_MARKER,
        "managed_by": "ai-group-friend",
        "version": version,
        "installer_relative_path": "NapCatInstaller.exe",
        "installer_sha256": hashlib.sha256(installer.read_bytes()).hexdigest(),
        "license": {"status": "not_fetched", "review_required": True},
    }
    _write(package / "manifest.json", json.dumps(manifest))
    if with_shell:
        shell = package / "NapCat.Shell"
        (shell / "config").mkdir(parents=True)
        (shell / "napcat.bat").write_text("@echo off\n", encoding="utf-8")
        _write(shell / "package.json", json.dumps({"version": version}))
    return package


def test_detect_managed_installer_ready_is_not_installed(tmp_path: Path) -> None:
    root = tmp_path / "connectors"
    package = managed_package(root, with_shell=False)
    profile = NapCatProfile()

    items = profile.detect_installations(root)

    assert len(items) == 1
    item = items[0]
    assert item.package_root == package
    assert item.shell_path is None
    assert item.managed is True
    assert item.layout_confidence == "manifest_only"
    assert item.installer_ready is True
    assert item.version == "v4.18.42"
    assert "package:installer-not-run" in item.evidence


def test_missing_installer_cannot_claim_installer_ready(tmp_path: Path) -> None:
    root = tmp_path / "connectors"
    managed_package(root, with_shell=False)
    (root / "v4.18.42" / "NapCatInstaller.exe").unlink()

    items = NapCatProfile().detect_installations(root)

    assert len(items) == 1
    assert items[0].installer_ready is False
    assert items[0].installer_path is None


def test_detect_shell_and_external_shell(tmp_path: Path) -> None:
    root = tmp_path / "connectors"
    managed_package(root)
    external = root / "other" / "napcat.bat"
    external.parent.mkdir(parents=True)
    external.write_text("@echo off\n", encoding="utf-8")
    (external.parent / "config").mkdir()
    _write(external.parent / "package.json", json.dumps({"version": "v4.18.42"}))

    items = NapCatProfile().detect_installations(root)

    managed = [item for item in items if item.managed]
    readonly = [item for item in items if not item.managed]
    assert len(managed) == 1
    assert managed[0].shell_path is not None
    assert managed[0].layout_confidence == "detected_shell"
    assert len(readonly) == 1
    assert readonly[0].source == "detected_external"
    assert readonly[0].version == "v4.18.42"


def test_version_gate_only_documented_version_can_auto_configure() -> None:
    profile = NapCatProfile()
    assert profile.version_compatibility("v4.18.42") == "documented"
    assert profile.can_auto_configure("4.18.42") is True
    assert profile.version_compatibility("v4.19.0") == "not_verified"
    assert profile.can_auto_configure("v4.19.0") is False
    assert profile.version_compatibility("unknown") == "incompatible"


def test_build_config_preserves_unknown_fields_and_replaces_managed_entries() -> None:
    existing = {
        "musicSignUrl": "keep",
        "network": {
            "httpServers": [
                {"name": "user-http", "enable": True, "port": 4000},
                {"name": "ai-group-friend-http", "enable": False, "port": 3000},
            ],
            "websocketServers": [
                {"name": "ai-group-friend-ws", "port": 3001, "token": "old"},
            ],
            "unknownNetworkKey": {"x": 1},
        },
    }
    merged = NapCatProfile().build_config(existing, http_port=3100, ws_port=3101, token="n" * 32)

    assert merged["musicSignUrl"] == "keep"
    assert merged["network"]["unknownNetworkKey"] == {"x": 1}
    http_entries = merged["network"]["httpServers"]
    assert [item["name"] for item in http_entries].count("ai-group-friend-http") == 1
    assert http_entries[0]["name"] == "user-http"
    managed_http = next(item for item in http_entries if item["name"] == "ai-group-friend-http")
    assert managed_http["port"] == 3100
    assert managed_http["host"] == "127.0.0.1"
    assert managed_http["token"] == "n" * 32
    managed_ws = next(item for item in merged["network"]["websocketServers"] if item["name"] == "ai-group-friend-ws")
    assert managed_ws["port"] == 3101
    assert managed_ws["heartInterval"] == 30000


def test_build_config_rejects_unknown_network_shape() -> None:
    with pytest.raises(NapCatError):
        NapCatProfile().build_config({"network": []}, http_port=3000, ws_port=3001, token="n" * 32)
    with pytest.raises(NapCatError):
        NapCatProfile().build_config({"network": {"httpServers": {}}}, http_port=3000, ws_port=3001, token="n" * 32)


def _installation_with_files(files: list[ConnectorConfigFile]) -> ConnectorInstallationInfo:
    return ConnectorInstallationInfo(
        kind="napcat",
        package_root=Path("C:/managed"),
        shell_path=Path("C:/managed/NapCat.Shell"),
        version="v4.18.42",
        source="managed_release",
        managed=True,
        layout_confidence="detected_shell",
        config_files=tuple(files),
    )


def test_select_config_prefers_default_then_ambiguous_account_files() -> None:
    profile = NapCatProfile()
    default = ConnectorConfigFile("config/onebot11.json", "onebot11.json", True, 2, None, True)
    account = ConnectorConfigFile("config/onebot11_10001.json", "onebot11_10001.json", True, 2, "10001", True)
    other = ConnectorConfigFile("config/onebot11_10002.json", "onebot11_10002.json", True, 2, "10002", True)

    selected = profile.select_config_file(_installation_with_files([default, account, other]))
    assert selected.relative_path == "config/onebot11.json"
    selected = profile.select_config_file(_installation_with_files([account, other]), identity_user_id="10002")
    assert selected.relative_path == "config/onebot11_10002.json"
    with pytest.raises(NapCatError) as exc:
        profile.select_config_file(_installation_with_files([account, other]))
    assert exc.value.code == "CONNECTOR_CONFIG_AMBIGUOUS"
    with pytest.raises(NapCatError) as exc:
        profile.select_config_file(
            _installation_with_files([default]),
            requested_relative="../outside.json",
        )
    assert exc.value.code == "CONNECTOR_PATH_UNSAFE"


def test_unparseable_config_is_rejected(tmp_path: Path) -> None:
    installation = _installation_with_files(
        [
            ConnectorConfigFile(
                "config/onebot11.json",
                "onebot11.json",
                True,
                10,
                None,
                False,
                error="bad json",
            )
        ]
    )
    with pytest.raises(NapCatError) as exc:
        NapCatProfile().select_config_file(installation)
    assert exc.value.code == "CONNECTOR_CONFIG_INVALID"

"""受管进程：固定参数、哈希校验、仅本会话所有权与安全环境。"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path
from typing import Any

import pytest
from app.connectors.napcat import MANIFEST_MARKER, NapCatProfile
from app.connectors.process import ManagedProcessRunner, ProcessError, sanitized_environment


class FakeProcess:
    def __init__(self, *, exit_on_wait: bool = False) -> None:
        self.pid = 4242
        self.killed = False
        self.exit_on_wait = exit_on_wait
        self.returncode: int | None = None

    def poll(self) -> int | None:
        return 0 if self.killed else self.returncode

    def wait(self, timeout: float | None = None) -> int:
        if self.killed or self.exit_on_wait:
            self.returncode = 0
            return 0
        raise subprocess.TimeoutExpired(cmd="fake", timeout=timeout or 0)


def _build_managed(root: Path) -> tuple[Path, Path]:
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
    return package, shell


def _info(root: Path) -> Any:
    items = NapCatProfile().detect_installations(root)
    assert len(items) == 1
    return items[0]


def test_start_connector_uses_fixed_command_and_visible_flags(tmp_path: Path) -> None:
    package, shell = _build_managed(tmp_path / "connectors")
    info = _info(tmp_path / "connectors")
    calls: list[dict[str, Any]] = []

    def fake_popen(command: list[str], **kwargs: Any) -> FakeProcess:
        calls.append({"command": command, **kwargs})
        return FakeProcess()

    runner = ManagedProcessRunner(popen_factory=fake_popen, platform_supported=True, taskkill_path=tmp_path / "tk.exe")
    spec = NapCatProfile().launcher_spec(info)
    assert spec is not None

    result = runner.start_connector("inst-1", info, spec)

    assert result["kind"] == "connector"
    assert len(calls) == 1
    command = calls[0]["command"]
    assert command[1:] == ["/d", "/s", "/c", "napcat.bat"]
    assert command[0].lower().endswith("cmd.exe")
    assert calls[0]["shell"] is False
    assert calls[0]["cwd"] == str(shell)
    assert calls[0]["env"].get("CREDENTIAL_ENCRYPTION_KEY") is None
    assert runner.connector_alive("inst-1") is True


def test_stop_only_owned_process_and_refuses_untracked(tmp_path: Path) -> None:
    _build_managed(tmp_path / "connectors")
    info = _info(tmp_path / "connectors")
    process = FakeProcess()
    ran: list[list[str]] = []

    def fake_run(command: list[str], **_: Any) -> Any:
        ran.append(command)
        process.killed = True
        return type("Result", (), {"returncode": 0})()

    runner = ManagedProcessRunner(
        popen_factory=lambda *a, **k: process,
        run_factory=fake_run,
        platform_supported=True,
        taskkill_path=tmp_path / "taskkill.exe",
    )
    with pytest.raises(ProcessError) as exc:
        runner.stop_connector("missing")
    assert exc.value.code == "CONNECTOR_PROCESS_NOT_TRACKED"
    assert ran == []

    spec = NapCatProfile().launcher_spec(info)
    assert spec is not None
    runner.start_connector("inst-1", info, spec)
    result = runner.stop_connector("inst-1")
    assert result["stopped"] is True
    assert ran and ran[0][-4:] == ["/PID", "4242", "/T", "/F"]
    assert runner.connector_alive("inst-1") is False


def test_stop_failure_keeps_ownership(tmp_path: Path) -> None:
    _build_managed(tmp_path / "connectors")
    info = _info(tmp_path / "connectors")
    process = FakeProcess()

    runner = ManagedProcessRunner(
        popen_factory=lambda *a, **k: process,
        run_factory=lambda *a, **k: type("Result", (), {"returncode": 1})(),
        platform_supported=True,
        taskkill_path=tmp_path / "taskkill.exe",
    )
    spec = NapCatProfile().launcher_spec(info)
    assert spec is not None
    runner.start_connector("inst-1", info, spec)

    with pytest.raises(ProcessError) as exc:
        runner.stop_connector("inst-1")
    assert exc.value.code == "CONNECTOR_PROCESS_STOP_FAILED"
    assert runner.connector_alive("inst-1") is True


def test_installer_hash_mismatch_is_rejected(tmp_path: Path) -> None:
    package, _ = _build_managed(tmp_path / "connectors")
    manifest = json.loads((package / "manifest.json").read_text(encoding="utf-8"))
    manifest["installer_sha256"] = "0" * 64
    (package / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    info = _info(tmp_path / "connectors")
    spec = NapCatProfile().installer_spec(info)
    assert spec is not None
    calls: list[Any] = []

    runner = ManagedProcessRunner(
        popen_factory=lambda *a, **k: calls.append(a) or FakeProcess(),
        platform_supported=True,
        taskkill_path=tmp_path / "taskkill.exe",
    )
    with pytest.raises(ProcessError) as exc:
        runner.start_installer("inst-1", info, spec)
    assert exc.value.code == "CONNECTOR_INSTALLER_HASH_MISMATCH"
    assert calls == []


def test_unsupported_platform_refuses_process_control(tmp_path: Path) -> None:
    _build_managed(tmp_path / "connectors")
    info = _info(tmp_path / "connectors")
    runner = ManagedProcessRunner(platform_supported=False)
    spec = NapCatProfile().launcher_spec(info)
    # NapCatProfile.supported is platform-bound; construct a fixed spec if needed.
    if spec is None:
        from app.connectors.base import LaunchSpec

        spec = LaunchSpec(executable=Path("cmd.exe"), args=("/d", "/s", "/c", "napcat.bat"), cwd=Path("cwd"), label="x")
    with pytest.raises(ProcessError) as exc:
        runner.start_connector("inst-1", info, spec)
    assert exc.value.code == "CONNECTOR_PROCESS_UNSUPPORTED"


def test_sanitized_environment_drops_application_secrets(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CREDENTIAL_ENCRYPTION_KEY", "super-secret")
    monkeypatch.setenv("ADMIN_API_TOKEN", "admin-secret")
    monkeypatch.setenv("DATABASE_URL", "sqlite:///secret.db")
    monkeypatch.setenv("PATH", "/usr/bin")
    env = sanitized_environment()
    assert "CREDENTIAL_ENCRYPTION_KEY" not in env
    assert "ADMIN_API_TOKEN" not in env
    assert "DATABASE_URL" not in env
    assert env.get("PATH") == "/usr/bin"


def test_taskkill_uses_absolute_system_path() -> None:
    runner = ManagedProcessRunner(platform_supported=True)
    assert os.path.isabs(str(runner._taskkill))
    assert runner._taskkill.name.lower() == "taskkill.exe"

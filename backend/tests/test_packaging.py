"""安装包运行时路径、密钥文件与冻结安装器入口的测试（不执行真实安装或网络）。"""

from __future__ import annotations

from pathlib import Path

import pytest
from app import __version__
from app.connectors.installer import InstallerProcess
from app.core import config
from app.core.config import Settings, _env_file, resolve_backend_root
from cryptography.fernet import Fernet


def _minimal_settings(tmp_path: Path, **overrides: object) -> Settings:
    data_dir = tmp_path / "data"
    values: dict[str, object] = {
        "data_dir": str(data_dir),
        "database_url": f"sqlite+aiosqlite:///{(data_dir / 'test.db').as_posix()}",
        "frontend_dist": str(tmp_path / "frontend-dist"),
        "connectors_dir": str(tmp_path / "connectors"),
        "credential_encryption_key": Fernet.generate_key().decode("utf-8"),
        "app_secret_key": "test-secret",
    }
    values.update(overrides)
    return Settings(**values)


def test_env_file_can_be_overridden_for_installed_app(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    env_file = tmp_path / "userdata" / ".env"
    monkeypatch.setenv("AI_GROUP_FRIEND_ENV_FILE", str(env_file))
    assert _env_file(tmp_path) == env_file.resolve()


def test_settings_read_keys_from_explicit_env_file(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    credential_key = Fernet.generate_key().decode("utf-8")
    env_file.write_text(
        f"APP_SECRET_KEY=installed-secret\nCREDENTIAL_ENCRYPTION_KEY={credential_key}\n",
        encoding="utf-8",
    )
    data_dir = tmp_path / "data"
    settings = Settings(
        _env_file=str(env_file),
        data_dir=str(data_dir),
        database_url=f"sqlite+aiosqlite:///{(data_dir / 'test.db').as_posix()}",
        frontend_dist=str(tmp_path / "frontend-dist"),
        connectors_dir=str(tmp_path / "connectors"),
    )
    assert settings.app_secret_key == "installed-secret"
    assert settings.credential_encryption_key == credential_key
    assert settings.has_credential_key is True


def test_backend_root_supports_source_and_bundle_layouts(tmp_path: Path) -> None:
    source = tmp_path / "repo"
    (source / "backend" / "alembic").mkdir(parents=True)
    (source / "backend" / "alembic.ini").write_text("", encoding="utf-8")
    assert resolve_backend_root(source) == source / "backend"

    bundle = tmp_path / "bundle"
    (bundle / "alembic").mkdir(parents=True)
    (bundle / "alembic.ini").write_text("", encoding="utf-8")
    assert resolve_backend_root(bundle) == bundle


def test_frozen_defaults_use_user_writable_directories(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config, "is_frozen", lambda: True)
    monkeypatch.setattr(config, "PROJECT_ROOT", tmp_path)
    settings = Settings(
        _env_file=str(tmp_path / "missing.env"),
        data_dir="",
        database_url="",
        frontend_dist="",
        connectors_dir="",
        credential_encryption_key="",
        app_secret_key="",
    )
    assert Path(settings.data_dir) == Path.home() / ".ai-group-friend" / "data"
    assert Path(settings.connectors_dir) == Path(settings.data_dir) / "connectors" / "napcat"
    assert settings.masked_runtime_info()["runtime_mode"] == "packaged"


def test_source_runtime_info_is_honest(tmp_path: Path) -> None:
    settings = _minimal_settings(tmp_path)
    assert settings.masked_runtime_info()["runtime_mode"] == "source"


def test_app_version_has_single_source(tmp_path: Path) -> None:
    """Settings 默认版本必须直接来自 app.__version__，不能再维护第二份常量。"""
    assert Settings.model_fields["app_version"].default == __version__
    assert _minimal_settings(tmp_path).app_version == __version__


def test_frozen_installer_executable_is_used_without_python(tmp_path: Path) -> None:
    executable = tmp_path / "aiqf-napcat-installer.exe"
    executable.write_bytes(b"")
    process = InstallerProcess(installer_executable=executable, project_root=tmp_path)
    assert process.available is True
    command = process._install_command(dest=tmp_path / "dest", version="v4.18.42")
    assert command[0] == str(executable.resolve())
    assert command[1:] == ["--json-events", "--dest", str(tmp_path / "dest"), "--version", "v4.18.42"]
    assert "python" not in command[0].lower()


def test_installer_executable_can_come_from_fixed_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    executable = tmp_path / "installer.exe"
    executable.write_bytes(b"")
    monkeypatch.setenv("AI_GROUP_FRIEND_INSTALLER_EXE", str(executable))
    process = InstallerProcess(project_root=tmp_path)
    assert process.available is True
    assert process.installer_executable == executable.resolve()


def test_packaged_entry_rejects_unsafe_port_and_log_level(monkeypatch: pytest.MonkeyPatch) -> None:
    from app import desktop_entry

    monkeypatch.setenv("APP_PORT", "70000")
    assert desktop_entry._port() == 8000
    monkeypatch.setenv("APP_PORT", "not-a-port")
    assert desktop_entry._port() == 8000
    monkeypatch.setenv("APP_PORT", "8123")
    assert desktop_entry._port() == 8123
    monkeypatch.setenv("LOG_LEVEL", "verbose")
    assert desktop_entry._log_level() == "info"
    assert desktop_entry._loopback_host() == "127.0.0.1"

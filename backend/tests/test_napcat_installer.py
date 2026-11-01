"""NapCat 安装脚本的安全校验测试：全部注入假 I/O，不发网络请求、不启动进程。"""

from __future__ import annotations

import base64
import hashlib
import importlib.util
import io
import json
import os
import stat
import sys
import urllib.request
import zipfile
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "install_napcat.py"


def _load_installer() -> ModuleType:
    spec = importlib.util.spec_from_file_location("install_napcat_test", _SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


installer = _load_installer()
InstallerError = installer.InstallerError


class FakeResponse:
    def __init__(self, body: bytes, *, headers: dict[str, str] | None = None) -> None:
        self._buffer = io.BytesIO(body)
        self.headers = headers or {}

    def read(self, size: int = -1) -> bytes:
        return self._buffer.read(size)

    def __enter__(self) -> FakeResponse:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def close(self) -> None:
        self._buffer.close()


class FakeOpener:
    def __init__(self, responses: dict[str, bytes]) -> None:
        self.responses = responses
        self.requests: list[str] = []

    def open(self, request: urllib.request.Request, timeout: float = 30.0) -> FakeResponse:
        del timeout
        url = request.full_url
        self.requests.append(url)
        if url not in self.responses:
            raise installer.urllib.error.HTTPError(url, 404, "not found", {}, None)  # type: ignore[arg-type]
        body = self.responses[url]
        return FakeResponse(body, headers={"Content-Length": str(len(body))})


def _zip_bytes(entries: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in entries.items():
            archive.writestr(name, content)
    return buffer.getvalue()


def _release(asset_bytes: bytes, *, digest: str | None = None) -> dict[str, Any]:
    return {
        "tag_name": "v4.18.42",
        "html_url": "https://github.com/NapNeko/NapCatQQ/releases/tag/v4.18.42",
        "assets": [
            {
                "name": installer.ASSET_NAME,
                "size": len(asset_bytes),
                "digest": digest or f"sha256:{hashlib.sha256(asset_bytes).hexdigest()}",
                "browser_download_url": (
                    "https://github.com/NapNeko/NapCatQQ/releases/download/v4.18.42/NapCat.Shell.Windows.OneKey.zip"
                ),
            }
        ],
    }


def _full_responses(asset_bytes: bytes, release: dict[str, Any]) -> dict[str, bytes]:
    license_text = "NapCat Limited Redistribution License\n"
    return {
        installer.LATEST_RELEASE_URL: json.dumps(release).encode(),
        release["assets"][0]["browser_download_url"]: asset_bytes,
        f"{installer.API_ROOT}/contents?ref=v4.18.42": json.dumps(
            [
                {
                    "name": "LICENSE",
                    "type": "file",
                    "url": f"{installer.API_ROOT}/contents/LICENSE?ref=v4.18.42",
                }
            ]
        ).encode(),
        f"{installer.API_ROOT}/contents/LICENSE?ref=v4.18.42": json.dumps(
            {
                "content": base64.b64encode(license_text.encode()).decode(),
                "sha": "abc123",
                "html_url": "https://github.com/NapNeko/NapCatQQ/blob/v4.18.42/LICENSE",
            }
        ).encode(),
    }


# ---------------------------------------------------------------- 资产与地址


def test_selects_only_the_onekey_windows_asset() -> None:
    payload = b"zip"
    release = _release(payload)
    release["assets"].append(
        {"name": "Other.zip", "size": 1, "digest": f"sha256:{'0' * 64}", "browser_download_url": ""}
    )
    asset = installer.select_windows_asset(release)
    assert asset.name == installer.ASSET_NAME
    assert asset.size == len(payload)
    assert asset.digest == hashlib.sha256(payload).hexdigest()
    assert asset.tag == "v4.18.42"


def test_rejects_asset_without_digest() -> None:
    release = _release(b"zip")
    del release["assets"][0]["digest"]
    with pytest.raises(InstallerError, match="digest"):
        installer.select_windows_asset(release)


def test_rejects_non_allowlisted_or_unsafe_download_hosts() -> None:
    for url in (
        "http://github.com/x",
        "https://evil.example/x",
        "https://user:pass@github.com/x",
        "https://127.0.0.1/x",
        "https://github.com:8443/x",
        "https://[::1]/x",
    ):
        with pytest.raises(InstallerError):
            installer.validate_download_url(url)
    assert installer.validate_download_url("https://github.com/x") == "https://github.com/x"


def test_redirect_handler_rejects_non_allowlisted_target() -> None:
    handler = installer.SafeRedirectHandler()
    request = urllib.request.Request("https://github.com/start")
    with pytest.raises(InstallerError):
        handler.redirect_request(request, None, 302, "Found", {}, "https://evil.example/next")
    allowed = handler.redirect_request(
        request,
        None,
        302,
        "Found",
        {},
        "https://release-assets.githubusercontent.com/next",
    )
    assert allowed is not None


def test_invalid_version_tag_is_rejected_before_network() -> None:
    with pytest.raises(InstallerError, match="版本标签"):
        installer.fetch_release("../../evil", opener=FakeOpener({}))


# ---------------------------------------------------------------- 下载校验


def test_download_checks_hash_and_removes_bad_file(tmp_path: Path) -> None:
    payload = b"payload"
    asset = installer.ReleaseAsset(
        tag="v4.18.42",
        name=installer.ASSET_NAME,
        size=len(payload),
        digest="0" * 64,
        download_url="https://github.com/download.zip",
    )
    target = tmp_path / "download.zip"
    with pytest.raises(InstallerError, match="SHA-256"):
        installer.download_asset(asset, target, opener=FakeOpener({asset.download_url: payload}))
    assert not target.exists()


def test_download_checks_declared_size(tmp_path: Path) -> None:
    payload = b"payload"
    asset = installer.ReleaseAsset(
        tag="v4.18.42",
        name=installer.ASSET_NAME,
        size=len(payload) + 1,
        digest=hashlib.sha256(payload).hexdigest(),
        download_url="https://github.com/download.zip",
    )
    with pytest.raises(InstallerError, match="大小"):
        installer.download_asset(asset, tmp_path / "download.zip", opener=FakeOpener({asset.download_url: payload}))


def test_download_retry_recovers_from_bad_payload(tmp_path: Path) -> None:
    payload = b"good-payload"
    bad = b"bad!-payload"
    assert len(bad) == len(payload)

    class FlakyOpener(FakeOpener):
        def __init__(self) -> None:
            super().__init__({})
            self.calls = 0

        def open(self, request: urllib.request.Request, timeout: float = 30.0) -> FakeResponse:
            del timeout
            self.calls += 1
            body = bad if self.calls < 3 else payload
            return FakeResponse(body, headers={"Content-Length": str(len(body))})

    asset = installer.ReleaseAsset(
        tag="v4.18.42",
        name=installer.ASSET_NAME,
        size=len(payload),
        digest=hashlib.sha256(payload).hexdigest(),
        download_url="https://github.com/download.zip",
    )
    opener = FlakyOpener()
    events: list[dict[str, Any]] = []
    sleeps: list[float] = []
    digest, size = installer.download_asset_with_retry(
        asset,
        tmp_path / "download.zip",
        opener=opener,
        retries=2,
        retry_delay=0,
        sleep_func=sleeps.append,
        event_sink=events.append,
    )
    assert digest == hashlib.sha256(payload).hexdigest()
    assert size == len(payload)
    assert opener.calls == 3
    assert [event["event"] for event in events] == ["retry", "retry"]
    assert not sleeps
    assert (tmp_path / "download.zip").read_bytes() == payload


def test_download_retry_exhaustion_removes_target(tmp_path: Path) -> None:
    payload = b"expected"
    asset = installer.ReleaseAsset(
        tag="v4.18.42",
        name=installer.ASSET_NAME,
        size=len(payload),
        digest=hashlib.sha256(payload).hexdigest(),
        download_url="https://github.com/download.zip",
    )
    target = tmp_path / "download.zip"
    target.write_bytes(b"stale")
    with pytest.raises(InstallerError, match="重试"):
        installer.download_asset_with_retry(
            asset,
            target,
            opener=FakeOpener({asset.download_url: b"wrong!!!"}),
            retries=1,
            retry_delay=0,
            sleep_func=lambda _: None,
        )
    assert not target.exists()


# ---------------------------------------------------------------- 解压安全


def _write_zip(path: Path, entries: dict[str, bytes]) -> Path:
    path.write_bytes(_zip_bytes(entries))
    return path


def test_rejects_path_traversal(tmp_path: Path) -> None:
    archive = _write_zip(tmp_path / "bad.zip", {"../evil.txt": b"x"})
    with pytest.raises(InstallerError, match="绝对路径|空组件"):
        installer.safe_extract_zip(archive, tmp_path / "out")


@pytest.mark.parametrize(
    "name",
    [
        "/absolute.txt",
        "C:/drive.txt",
        "CON.txt",
        "dir/file.txt:ads",
        "a/./b.txt",
        "bad\\path.txt",
        "trailing.",
    ],
)
def test_rejects_unsafe_zip_names(tmp_path: Path, name: str) -> None:
    archive = _write_zip(tmp_path / "bad.zip", {name: b"x"})
    with pytest.raises(InstallerError):
        installer.safe_extract_zip(archive, tmp_path / "out")


def test_rejects_case_insensitive_duplicate_entries(tmp_path: Path) -> None:
    archive = _write_zip(tmp_path / "bad.zip", {"A.txt": b"1", "a.txt": b"2"})
    with pytest.raises(InstallerError, match="重复"):
        installer.safe_extract_zip(archive, tmp_path / "out")


def test_rejects_symlink_entries(tmp_path: Path) -> None:
    archive_path = tmp_path / "symlink.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        info = zipfile.ZipInfo("link")
        info.external_attr = (stat.S_IFLNK | 0o777) << 16
        archive.writestr(info, "target")
    with pytest.raises(InstallerError, match="符号链接"):
        installer.safe_extract_zip(archive_path, tmp_path / "out")


def test_rejects_too_many_entries(tmp_path: Path) -> None:
    entries = {f"file-{index}.txt": b"" for index in range(installer.MAX_ZIP_ENTRIES + 1)}
    archive = _write_zip(tmp_path / "many.zip", entries)
    with pytest.raises(InstallerError, match="条目过多"):
        installer.safe_extract_zip(archive, tmp_path / "out")


def test_requires_installer_executable(tmp_path: Path) -> None:
    archive = _write_zip(tmp_path / "no-installer.zip", {"README.txt": b"x"})
    with pytest.raises(InstallerError, match="NapCatInstaller.exe"):
        installer.safe_extract_zip(archive, tmp_path / "out")


def test_truncated_zip_reports_integrity_error(tmp_path: Path) -> None:
    full = _zip_bytes({"NapCatInstaller.exe": b"installer" * 200})
    archive = tmp_path / "truncated.zip"
    archive.write_bytes(full[: len(full) // 2])
    with pytest.raises(InstallerError, match="ZIP|压缩包|有效"):
        installer.safe_extract_zip(archive, tmp_path / "out")


def test_rejects_suspicious_compression_ratio(tmp_path: Path) -> None:
    archive = tmp_path / "bomb.zip"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as handle:
        handle.writestr("NapCatInstaller.exe", b"installer")
        handle.writestr("bomb.bin", b"\0" * (2 * 1024 * 1024))
    with pytest.raises(InstallerError, match="压缩比"):
        installer.safe_extract_zip(archive, tmp_path / "out")
    assert not (tmp_path / "out" / "NapCatInstaller.exe").exists()


def test_extracts_installer_safely(tmp_path: Path) -> None:
    archive = _write_zip(
        tmp_path / "good.zip",
        {"NapCatInstaller.exe": b"installer", "sub/README.txt": b"readme"},
    )
    extracted = tmp_path / "out"
    result = installer.safe_extract_zip(archive, extracted)
    assert result.is_file()
    assert (extracted / "sub" / "README.txt").read_bytes() == b"readme"


# ---------------------------------------------------------------- 完整流程


def test_install_writes_manifest_license_and_reuses_existing(tmp_path: Path) -> None:
    asset_bytes = _zip_bytes(
        {
            "NapCatInstaller.exe": b"fake-installer",
            "README.txt": b"official package",
        }
    )
    release = _release(asset_bytes)
    opener = FakeOpener(_full_responses(asset_bytes, release))
    dest = tmp_path / "connectors" / "napcat"

    assert installer.install(version=None, dest=dest, dry_run=False, launch=False, opener=opener) == 0

    target = dest / "v4.18.42"
    manifest = json.loads((target / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["version"] == "v4.18.42"
    assert manifest["asset"]["computed_digest"] == f"sha256:{hashlib.sha256(asset_bytes).hexdigest()}"
    assert manifest["license"]["status"] == "fetched"
    assert (target / "LICENSE-NapCat.txt").read_text(encoding="utf-8").startswith("NapCat")
    assert manifest["real_qq_verified"] is False
    assert manifest["installer_sha256"] == hashlib.sha256(b"fake-installer").hexdigest()
    assert not list(dest.glob(".staging-*"))

    download_url = release["assets"][0]["browser_download_url"]
    downloaded_before = opener.requests.count(download_url)
    events: list[dict[str, Any]] = []
    assert (
        installer.install(
            version=None,
            dest=dest,
            dry_run=False,
            launch=False,
            opener=opener,
            event_sink=events.append,
        )
        == 0
    )
    assert opener.requests.count(download_url) == downloaded_before
    assert events[-1]["event"] == "installed"
    assert events[-1]["action"] == "reused"
    assert (target / "README.txt").read_bytes() == b"official package"
    assert not list(dest.glob(".staging-*"))


def _build_managed_target(dest: Path, *, corrupt_installer: bool = False) -> Path:
    target = dest / "v4.18.42"
    target.mkdir(parents=True)
    installer_file = target / "NapCatInstaller.exe"
    installer_file.write_bytes(b"damaged" if corrupt_installer else b"fake-installer")
    manifest = {
        "installer": "ai-group-friend-napcat-installer",
        "version": "v4.18.42",
        "installer_relative_path": "NapCatInstaller.exe",
        "installer_sha256": hashlib.sha256(b"fake-installer").hexdigest(),
    }
    (target / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (target / "user-config.json").write_text('{"keep": true}', encoding="utf-8")
    return target


def test_repairs_managed_damaged_target_by_quarantine(tmp_path: Path) -> None:
    asset_bytes = _zip_bytes({"NapCatInstaller.exe": b"fake-installer", "README.txt": b"new"})
    release = _release(asset_bytes)
    opener = FakeOpener(_full_responses(asset_bytes, release))
    dest = tmp_path / "connectors" / "napcat"
    target = _build_managed_target(dest, corrupt_installer=True)
    events: list[dict[str, Any]] = []

    assert (
        installer.install(
            version=None,
            dest=dest,
            dry_run=False,
            launch=False,
            opener=opener,
            event_sink=events.append,
        )
        == 0
    )

    assert (target / "README.txt").read_bytes() == b"new"
    manifest = json.loads((target / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["replaced_install"]["quarantined_as"].startswith(".quarantine-v4.18.42-")
    quarantines = list(dest.glob(".quarantine-v4.18.42-*"))
    assert len(quarantines) == 1
    # 旧目录只被隔离，用户数据仍保留在隔离区，不直接删除。
    assert (quarantines[0] / "user-config.json").read_text(encoding="utf-8") == '{"keep": true}'
    assert [event["event"] for event in events][-1] == "installed"
    assert events[-1]["action"] == "repaired"
    assert not list(dest.glob(".staging-*"))


def test_refuses_unknown_existing_directory_without_touching_it(tmp_path: Path) -> None:
    asset_bytes = _zip_bytes({"NapCatInstaller.exe": b"fake-installer"})
    release = _release(asset_bytes)
    opener = FakeOpener(_full_responses(asset_bytes, release))
    dest = tmp_path / "connectors" / "napcat"
    target = dest / "v4.18.42"
    target.mkdir(parents=True)
    (target / "user-file.txt").write_text("do not delete", encoding="utf-8")

    with pytest.raises(InstallerError, match="无法安全复用"):
        installer.install(version=None, dest=dest, dry_run=False, launch=False, opener=opener)

    assert (target / "user-file.txt").read_text(encoding="utf-8") == "do not delete"
    assert not list(dest.glob(".quarantine-*"))
    assert not list(dest.glob(".staging-*"))


def test_cleanup_stale_staging_only_removes_old_directories(tmp_path: Path) -> None:
    dest = tmp_path / "napcat"
    dest.mkdir()
    old = dest / ".staging-old"
    old.mkdir()
    (old / "partial.bin").write_bytes(b"x")
    fresh = dest / ".staging-fresh"
    fresh.mkdir()
    unrelated = dest / "keep"
    unrelated.mkdir()
    now = 10_000.0
    stale_time = now - installer.STALE_STAGING_SECONDS - 1
    fresh_time = now - 10
    os.utime(old, (stale_time, stale_time))
    os.utime(fresh, (fresh_time, fresh_time))
    os.utime(unrelated, (stale_time, stale_time))

    removed = installer.cleanup_stale_staging(dest, now=now)

    assert removed == [".staging-old"]
    assert not old.exists()
    assert fresh.exists()
    assert unrelated.exists()


def test_launch_without_tty_does_not_execute_installer(tmp_path: Path) -> None:
    asset_bytes = _zip_bytes({"NapCatInstaller.exe": b"fake-installer"})
    release = _release(asset_bytes)
    opener = FakeOpener(_full_responses(asset_bytes, release))
    launched: list[Any] = []

    code = installer.install(
        version=None,
        dest=tmp_path / "napcat-launch",
        dry_run=False,
        launch=True,
        opener=opener,
        stdin_is_tty=False,
        runner=lambda *args, **kwargs: launched.append((args, kwargs)),
    )

    assert code == 2
    assert launched == []


def test_dry_run_does_not_create_destination(tmp_path: Path) -> None:
    asset_bytes = _zip_bytes({"NapCatInstaller.exe": b"fake-installer"})
    release = _release(asset_bytes)
    dest = tmp_path / "dry-run"
    opener = FakeOpener({installer.LATEST_RELEASE_URL: json.dumps(release).encode()})

    assert installer.install(version=None, dest=dest, dry_run=True, launch=False, opener=opener) == 0
    assert not dest.exists()


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("磁盘空间不足：无法写入解压目录", "CONNECTOR_INSUFFICIENT_DISK"),
        ("权限不足：无法写入解压目录", "CONNECTOR_PERMISSION_DENIED"),
        ("无法安全复用：目标目录没有受管安装清单", "CONNECTOR_TARGET_EXISTS"),
        ("无法移动目录（文件可能被占用或路径过长）", "CONNECTOR_TARGET_BUSY"),
        ("压缩包包含特殊文件", "CONNECTOR_ZIP_INVALID"),
        ("下载重试 3 次仍失败", "CONNECTOR_DOWNLOAD_FAILED"),
    ],
)
def test_error_code_classifies_windows_failures(message: str, expected: str) -> None:
    assert installer._error_code(InstallerError(message)) == expected


def test_permission_error_while_moving_target_is_not_reported_as_busy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dest = tmp_path / "napcat"
    target = dest / "v4.18.42"
    target.mkdir(parents=True)

    def deny(*_args: object, **_kwargs: object) -> None:
        raise PermissionError(13, "access denied")

    monkeypatch.setattr(installer.os, "replace", deny)
    monkeypatch.setattr(installer.time, "sleep", lambda _seconds: None)

    with pytest.raises(InstallerError) as raised:
        installer.quarantine_existing_target(target, dest, reason="test")

    assert installer._error_code(raised.value) == "CONNECTOR_PERMISSION_DENIED"
    assert target.exists()

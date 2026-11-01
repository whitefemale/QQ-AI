"""从 NapCat 官方 GitHub Release 下载、校验并解压 Windows OneKey 安装包。

安全边界：
- 只接受 HTTPS + 固定主机白名单；拒绝 IP 字面量、userinfo、非 443 端口。
- 只下载 ``NapCat.Shell.Windows.OneKey.zip``，必须提供 ``sha256:`` digest。
- 下载后核对大小与 SHA-256；解压前拒绝路径穿越、符号链接、ADS 与重复路径。
- 默认只安装到 ``connectors/napcat/<tag>/``，不覆盖已有目录。
- 不修改 NapCat 配置、不登录 QQ、不发送消息；``--launch`` 需 TTY 且输入 LAUNCH。

仅使用 Python 标准库。真实网络请求只发生在运行脚本时，测试必须注入假 I/O。
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import ipaddress
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO = "NapNeko/NapCatQQ"
API_ROOT = f"https://api.github.com/repos/{REPO}"
LATEST_RELEASE_URL = f"{API_ROOT}/releases/latest"
RELEASES_URL = f"{API_ROOT}/releases?per_page=20"
ASSET_NAME = "NapCat.Shell.Windows.OneKey.zip"
MANAGED_BY = "ai-group-friend"
MAX_LISTED_RELEASES = 10
MIN_FREE_DISK_MARGIN = 100 * 1024 * 1024
ALLOWED_HOSTS = {
    "api.github.com",
    "github.com",
    "release-assets.githubusercontent.com",
    "objects.githubusercontent.com",
}
MAX_REDIRECTS = 5
MAX_ZIP_ENTRIES = 200
MAX_ZIP_TOTAL_BYTES = 50 * 1024 * 1024
MAX_ZIP_FILE_BYTES = 50 * 1024 * 1024
MAX_DOWNLOAD_BYTES = 200 * 1024 * 1024
TAG_PATTERN = re.compile(r"^v\d+\.\d+\.\d+(?:[-+][A-Za-z0-9._-]+)?$")
DIGEST_PATTERN = re.compile(r"^sha256:([0-9a-fA-F]{64})$")
RESERVED_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{index}" for index in range(1, 10)),
    *(f"LPT{index}" for index in range(1, 10)),
}
ROOT = Path(__file__).resolve().parent.parent


class InstallerError(RuntimeError):
    """安装器可预期的安全或校验失败。"""


@dataclass(frozen=True)
class ReleaseAsset:
    tag: str
    name: str
    size: int
    digest: str
    download_url: str


_LOG_STREAM: Any = None


def set_log_stream(stream: Any) -> None:
    """JSON 事件模式把人类可读日志转到 stderr，stdout 只保留 NDJSON。"""
    global _LOG_STREAM
    _LOG_STREAM = stream


def log(message: str) -> None:
    print(message, file=_LOG_STREAM or sys.stdout, flush=True)


def emit_event(sink: Callable[[dict[str, Any]], None] | None, event: str, **payload: Any) -> None:
    if sink is None:
        return
    sink({"event": event, **payload})


def release_metadata(asset: ReleaseAsset, *, target: Path | None = None) -> dict[str, Any]:
    return {
        "version": asset.tag,
        "asset_name": asset.name,
        "size": asset.size,
        "digest": f"sha256:{asset.digest}",
        "download_url": asset.download_url,
        "license": {"status": "not_fetched"},
        "target": str(target) if target is not None else None,
    }


# ---------------------------------------------------------------- 网络与地址校验


def validate_download_url(url: str) -> str:
    """只允许白名单内的 HTTPS 主机；拒绝容易被滥用的 URL 形态。"""
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != "https":
        raise InstallerError(f"下载地址必须使用 HTTPS：{url}")
    if parsed.username or parsed.password:
        raise InstallerError("下载地址不得包含用户名或密码。")
    host = (parsed.hostname or "").lower()
    if not host or host not in ALLOWED_HOSTS:
        raise InstallerError(f"下载主机不在白名单内：{host or '(空)'}")
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        raise InstallerError("下载地址不得使用 IP 字面量。")
    try:
        port = parsed.port
    except ValueError as exc:
        raise InstallerError("下载地址端口无效。") from exc
    if port not in (None, 443):
        raise InstallerError(f"下载地址只允许默认 HTTPS 端口，实际为 {port}。")
    return url


class SafeRedirectHandler(urllib.request.HTTPRedirectHandler):
    max_redirections = MAX_REDIRECTS

    def redirect_request(  # type: ignore[override]
        self,
        req: urllib.request.Request,
        fp: Any,
        code: int,
        msg: str,
        headers: Mapping[str, str],
        newurl: str,
    ) -> urllib.request.Request | None:
        validate_download_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def build_opener() -> urllib.request.OpenerDirector:
    return urllib.request.build_opener(SafeRedirectHandler())


def _open(opener: Any, request: urllib.request.Request, timeout: float) -> Any:
    if hasattr(opener, "open"):
        return opener.open(request, timeout=timeout)
    raise InstallerError("内部错误：下载器缺少 open 方法。")


def fetch_json(url: str, *, opener: Any, timeout: float = 30.0) -> Any:
    validate_download_url(url)
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "ai-group-friend-napcat-installer",
        },
    )
    try:
        with _open(opener, request, timeout) as response:
            raw = response.read()
    except (urllib.error.URLError, OSError, TimeoutError) as exc:
        raise InstallerError(f"请求 GitHub API 失败：{exc}") from exc
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise InstallerError("GitHub API 返回了无法解析的 JSON。") from exc


def fetch_release(version: str | None, *, opener: Any, timeout: float = 30.0) -> dict[str, Any]:
    if version is not None and not TAG_PATTERN.match(version):
        raise InstallerError("版本标签格式无效，应形如 v4.18.42。")
    url = f"{API_ROOT}/releases/tags/{version}" if version else LATEST_RELEASE_URL
    release = fetch_json(url, opener=opener, timeout=timeout)
    if not isinstance(release, dict):
        raise InstallerError("GitHub Release 响应格式异常。")
    tag = release.get("tag_name")
    if not isinstance(tag, str) or not TAG_PATTERN.match(tag):
        raise InstallerError(f"Release 标签格式无效：{tag!r}")
    return release


def fetch_releases(*, opener: Any, timeout: float = 30.0) -> list[dict[str, Any]]:
    """列出最多 10 个包含合法 OneKey 资产与 digest 的稳定版本。

    只读取固定 GitHub API 主机；单个 release 资产不合规时跳过，不猜版本。
    """
    payload = fetch_json(RELEASES_URL, opener=opener, timeout=timeout)
    if not isinstance(payload, list):
        raise InstallerError("GitHub Release 列表格式异常。")
    result: list[dict[str, Any]] = []
    for release in payload:
        if not isinstance(release, dict):
            continue
        if release.get("draft") or release.get("prerelease"):
            continue
        tag = release.get("tag_name")
        if not isinstance(tag, str) or not TAG_PATTERN.match(tag):
            continue
        try:
            asset = select_windows_asset(release)
        except InstallerError:
            continue
        result.append(
            {
                "version": asset.tag,
                "asset_name": asset.name,
                "size": asset.size,
                "digest": f"sha256:{asset.digest}",
                "download_url": asset.download_url,
                "published_at": release.get("published_at"),
                "license": {"status": "not_fetched"},
            }
        )
        if len(result) >= MAX_LISTED_RELEASES:
            break
    return result


def check_disk_space(
    destination: Path,
    required_bytes: int,
    *,
    disk_usage: Callable[[Path], Any] = shutil.disk_usage,
) -> int:
    """下载 + 解压 + 余量检查；返回可用字节数。"""
    probe = destination
    while not probe.exists() and probe.parent != probe:
        probe = probe.parent
    try:
        usage = disk_usage(probe)
        free = int(usage.free)
    except OSError as exc:
        raise InstallerError(f"无法检查磁盘空间：{exc}") from exc
    if free < required_bytes:
        raise InstallerError(f"磁盘空间不足（INSUFFICIENT_DISK）：需要约 {required_bytes} 字节，当前可用 {free} 字节。")
    return free


def select_windows_asset(release: Mapping[str, Any]) -> ReleaseAsset:
    tag = release.get("tag_name")
    if not isinstance(tag, str) or not TAG_PATTERN.match(tag):
        raise InstallerError(f"Release 标签格式无效：{tag!r}")
    assets = release.get("assets")
    if not isinstance(assets, list):
        raise InstallerError("Release 没有资产列表。")
    matches = [item for item in assets if isinstance(item, dict) and item.get("name") == ASSET_NAME]
    if len(matches) != 1:
        raise InstallerError(f"Release 中应恰好有一个 {ASSET_NAME} 资产。")
    asset = matches[0]
    size = asset.get("size")
    if not isinstance(size, int) or isinstance(size, bool) or size <= 0 or size > MAX_DOWNLOAD_BYTES:
        raise InstallerError(f"资产大小无效：{size!r}")
    digest = asset.get("digest")
    if not isinstance(digest, str) or not DIGEST_PATTERN.match(digest):
        raise InstallerError("资产缺少合法的 sha256 digest，拒绝下载。")
    download_url = asset.get("browser_download_url")
    if not isinstance(download_url, str):
        raise InstallerError("资产缺少下载地址。")
    validate_download_url(download_url)
    return ReleaseAsset(
        tag=tag,
        name=ASSET_NAME,
        size=size,
        digest=digest.split(":", 1)[1].lower(),
        download_url=download_url,
    )


def download_asset(
    asset: ReleaseAsset,
    target: Path,
    *,
    opener: Any,
    timeout: float = 60.0,
    chunk_size: int = 1024 * 1024,
    on_progress: Callable[[int, int], None] | None = None,
) -> tuple[str, int]:
    """流式下载并同步校验大小与 SHA-256；任何不符都会删除临时文件。"""
    validate_download_url(asset.download_url)
    request = urllib.request.Request(
        asset.download_url,
        headers={"User-Agent": "ai-group-friend-napcat-installer"},
    )
    digest = hashlib.sha256()
    written = 0
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        with _open(opener, request, timeout) as response:
            headers = getattr(response, "headers", None)
            content_length = headers.get("Content-Length") if headers is not None else None
            if content_length is not None:
                try:
                    declared = int(content_length)
                except (TypeError, ValueError) as exc:
                    raise InstallerError("响应的 Content-Length 无效。") from exc
                if declared != asset.size:
                    raise InstallerError(f"响应大小与 Release 资产不一致：{declared} != {asset.size}。")
            with target.open("wb") as handle:
                while True:
                    chunk = response.read(chunk_size)
                    if not chunk:
                        break
                    written += len(chunk)
                    if written > asset.size:
                        raise InstallerError("下载内容超过 Release 声明的资产大小。")
                    digest.update(chunk)
                    handle.write(chunk)
                    if on_progress is not None:
                        on_progress(written, asset.size)
    except (urllib.error.URLError, OSError, TimeoutError) as exc:
        target.unlink(missing_ok=True)
        raise InstallerError(f"下载资产失败：{exc}") from exc
    except InstallerError:
        target.unlink(missing_ok=True)
        raise

    actual = digest.hexdigest()
    if written != asset.size:
        target.unlink(missing_ok=True)
        raise InstallerError(f"下载字节数不符：{written} != {asset.size}。")
    if not hmac.compare_digest(actual, asset.digest):
        target.unlink(missing_ok=True)
        raise InstallerError("SHA-256 校验失败，已删除下载文件。")
    return actual, written


# ---------------------------------------------------------------- 安全解压


def _validate_zip_name(name: str) -> tuple[str, ...]:
    if not name or "\x00" in name:
        raise InstallerError("压缩包包含空路径或 NUL 字符。")
    if any(ord(char) < 32 for char in name):
        raise InstallerError(f"压缩包路径包含控制字符：{name!r}")
    if "\\" in name:
        raise InstallerError(f"压缩包路径不得包含反斜杠：{name!r}")
    if name.startswith("/") or re.match(r"^[A-Za-z]:", name):
        raise InstallerError(f"压缩包包含绝对路径：{name!r}")
    if ":" in name:
        raise InstallerError(f"压缩包路径不得包含冒号或 ADS：{name!r}")
    parts = tuple(part for part in name.rstrip("/").split("/"))
    if not parts or any(part in ("", ".", "..") for part in parts):
        raise InstallerError(f"压缩包路径包含空组件或 ..：{name!r}")
    for part in parts:
        if part.endswith((" ", ".")):
            raise InstallerError(f"压缩包路径以空格或点结尾：{name!r}")
        base = part.split(".", 1)[0].upper()
        if base in RESERVED_NAMES:
            raise InstallerError(f"压缩包包含 Windows 保留名：{name!r}")
    return parts


def safe_extract_zip(zip_path: Path, destination: Path) -> Path:
    """校验并解压；返回解压出的 NapCatInstaller.exe 路径。"""
    destination.mkdir(parents=True, exist_ok=True)
    seen: set[str] = set()
    entries = 0
    declared_total = 0
    installer: Path | None = None
    try:
        with zipfile.ZipFile(zip_path) as archive:
            infos = archive.infolist()
            if len(infos) > MAX_ZIP_ENTRIES:
                raise InstallerError(f"压缩包条目过多：{len(infos)} > {MAX_ZIP_ENTRIES}。")
            for info in infos:
                entries += 1
                parts = _validate_zip_name(info.filename)
                key = "/".join(parts).casefold()
                if key in seen:
                    raise InstallerError(f"压缩包包含大小写不敏感的重复路径：{info.filename!r}")
                seen.add(key)
                if info.flag_bits & 0x1:
                    raise InstallerError("不允许加密的压缩包条目。")
                mode = info.external_attr >> 16
                if mode:
                    if stat.S_ISLNK(mode):
                        raise InstallerError(f"压缩包包含符号链接：{info.filename!r}")
                    # Windows 工具常只写入权限位，文件类型为 0；只拒绝明确的特殊类型。
                    file_type = stat.S_IFMT(mode)
                    if file_type not in (0, stat.S_IFREG, stat.S_IFDIR):
                        raise InstallerError(f"压缩包包含特殊文件：{info.filename!r}")
                if info.file_size < 0 or info.file_size > MAX_ZIP_FILE_BYTES:
                    raise InstallerError(f"压缩包单文件过大：{info.filename!r}")
                declared_total += info.file_size
                if declared_total > MAX_ZIP_TOTAL_BYTES:
                    raise InstallerError("压缩包解压后总大小超过限制。")
                relative = Path(*parts)
                target = (destination / relative).resolve()
                try:
                    target.relative_to(destination.resolve())
                except ValueError as exc:
                    raise InstallerError(f"压缩包路径逃逸目标目录：{info.filename!r}") from exc
                if info.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                written = 0
                with archive.open(info) as source, target.open("wb") as sink:
                    while True:
                        chunk = source.read(1024 * 1024)
                        if not chunk:
                            break
                        written += len(chunk)
                        if written > info.file_size:
                            raise InstallerError(f"压缩包条目实际大小异常：{info.filename!r}")
                        sink.write(chunk)
                if written != info.file_size:
                    raise InstallerError(f"压缩包条目大小不符：{info.filename!r}")
                if target.name.casefold() == "napcatinstaller.exe":
                    installer = target
    except zipfile.BadZipFile as exc:
        raise InstallerError("下载的资产不是有效 ZIP 文件。") from exc
    if entries == 0:
        raise InstallerError("压缩包为空。")
    if installer is None:
        raise InstallerError("压缩包内没有 NapCatInstaller.exe。")
    return installer


# ---------------------------------------------------------------- 许可证与 manifest


def fetch_license(tag: str, *, opener: Any, timeout: float = 30.0) -> dict[str, Any]:
    """通过 GitHub contents API 获取该 tag 的 LICENSE 文件；失败只记录不可用。"""
    if not TAG_PATTERN.match(tag):
        raise InstallerError("版本标签格式无效。")
    quoted = urllib.parse.quote(tag, safe="")
    listing_url = f"{API_ROOT}/contents?ref={quoted}"
    try:
        listing = fetch_json(listing_url, opener=opener, timeout=timeout)
        if not isinstance(listing, list):
            raise InstallerError("许可证目录响应格式异常。")
        candidate = next(
            (
                item
                for item in listing
                if isinstance(item, dict)
                and isinstance(item.get("name"), str)
                and item["name"].upper().startswith("LICENSE")
                and item.get("type") == "file"
            ),
            None,
        )
        if candidate is None:
            return {"status": "unavailable", "reason": "该 tag 未找到 LICENSE 文件。"}
        content_url = candidate.get("url")
        if not isinstance(content_url, str):
            raise InstallerError("许可证文件缺少 API 地址。")
        payload = fetch_json(content_url, opener=opener, timeout=timeout)
        if not isinstance(payload, dict) or not isinstance(payload.get("content"), str):
            raise InstallerError("许可证响应缺少内容。")
        encoded = "".join(payload["content"].split())
        text = base64.b64decode(encoded, validate=True).decode("utf-8", errors="replace")
        return {
            "status": "fetched",
            "name": candidate.get("name"),
            "blob_sha": payload.get("sha"),
            "url": payload.get("html_url") or candidate.get("html_url"),
            "text": text,
        }
    except (InstallerError, ValueError, OSError) as exc:
        return {"status": "unavailable", "reason": str(exc)}


def sanitize_tag(tag: str) -> str:
    if not TAG_PATTERN.match(tag):
        raise InstallerError("版本标签格式无效。")
    cleaned = re.sub(r"[^A-Za-z0-9._-]", "_", tag).strip(".")
    if not cleaned or cleaned in (".", ".."):
        raise InstallerError("版本标签无法安全用作目录名。")
    return cleaned


def default_destination() -> Path:
    return ROOT / "connectors" / "napcat"


# ---------------------------------------------------------------- 安装流程


def install(
    *,
    version: str | None,
    dest: Path,
    dry_run: bool,
    launch: bool,
    opener: Any | None = None,
    timeout: float = 60.0,
    input_func: Callable[[str], str] = input,
    stdin_is_tty: bool | None = None,
    runner: Callable[..., Any] = subprocess.run,
    event_sink: Callable[[dict[str, Any]], None] | None = None,
    disk_usage: Callable[[Path], Any] = shutil.disk_usage,
) -> int:
    emit_event(event_sink, "resolving", message="正在解析版本与资产", progress=5)
    opener = opener or build_opener()
    release = fetch_release(version, opener=opener)
    asset = select_windows_asset(release)
    tag = sanitize_tag(asset.tag)
    target = (dest / tag).resolve()
    emit_event(event_sink, "release", **release_metadata(asset, target=target))

    if dry_run:
        log("NapCat 安装器 dry-run（不会下载、解压或启动任何程序）")
        log(f"版本：{asset.tag}")
        log(f"资产：{asset.name}（{asset.size} 字节）")
        log(f"下载：{asset.download_url}")
        log(f"GitHub digest：sha256:{asset.digest}")
        log(f"目标目录：{target}")
        return 0

    if target.exists():
        raise InstallerError(f"目标目录已存在，拒绝覆盖：{target}")

    required = asset.size * 3 + MIN_FREE_DISK_MARGIN
    free = check_disk_space(dest, required, disk_usage=disk_usage)
    emit_event(
        event_sink,
        "preflight",
        message="磁盘空间检查通过",
        required_bytes=required,
        free_bytes=free,
        progress=8,
    )

    dest.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".staging-", dir=dest))
    emit_event(event_sink, "progress", stage="staging", staging_path=str(staging), progress=9)
    succeeded = False
    try:
        archive_path = staging / ASSET_NAME
        log(f"下载 {asset.name} ...")
        emit_event(event_sink, "progress", stage="download", message="开始下载", progress=10)

        def _progress(written: int, total: int) -> None:
            percent = 10 + int(45 * written / total) if total else 10
            emit_event(
                event_sink,
                "progress",
                stage="download",
                message=f"已下载 {written}/{total} 字节",
                downloaded_bytes=written,
                total_bytes=total,
                progress=min(percent, 55),
            )

        actual_digest, actual_size = download_asset(
            asset,
            archive_path,
            opener=opener,
            timeout=timeout,
            on_progress=_progress,
        )
        log(f"校验通过：{actual_size} 字节，sha256:{actual_digest}")
        emit_event(
            event_sink,
            "verified",
            message="SHA-256 校验通过",
            size=actual_size,
            digest=f"sha256:{actual_digest}",
            progress=60,
        )

        emit_event(event_sink, "extracting", message="正在安全解压", progress=65)
        extracted = staging / "extracted"
        installer = safe_extract_zip(archive_path, extracted)
        log(f"解压完成：{installer}")
        emit_event(event_sink, "extracting", message="解压完成", progress=90)

        license_info = fetch_license(asset.tag, opener=opener)
        license_text = license_info.pop("text", None)
        if license_text:
            (extracted / "LICENSE-NapCat.txt").write_text(str(license_text), encoding="utf-8")
            license_info["saved_as"] = "LICENSE-NapCat.txt"
            log("许可证文件已保存，请在使用或再分发前自行阅读并确认条款。")
        else:
            log("警告：未能获取许可证文件；这不代表许可证已审阅或允许再分发。")

        installer_relative = installer.relative_to(extracted).as_posix()
        installer_hash = hashlib.sha256(installer.read_bytes()).hexdigest()
        emit_event(event_sink, "progress", stage="manifest", message="正在写入清单", progress=95)
        manifest = {
            "installer": "ai-group-friend-napcat-installer",
            "managed_by": MANAGED_BY,
            "installed_at": datetime.now(UTC).isoformat(),
            "version": asset.tag,
            "release_url": release.get("html_url") if isinstance(release, dict) else None,
            "asset": {
                "name": asset.name,
                "url": asset.download_url,
                "size": asset.size,
                "github_digest": f"sha256:{asset.digest}",
                "computed_digest": f"sha256:{actual_digest}",
            },
            "license": license_info,
            "install_dir": str(target),
            "installer_relative_path": installer_relative,
            "installer_sha256": installer_hash,
            "next_steps": [
                "运行 NapCatInstaller.exe（本脚本不会自动登录 QQ）。",
                "在 NapCat 中登录你本人授权的专用 QQ 账号。",
                "启用正向 WebSocket 与 HTTP API，并设置独立 Token。",
                "回到控制台填写地址与 Token，先执行「测试并诊断」。",
            ],
            "real_qq_verified": False,
        }
        (extracted / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

        if target.exists():
            raise InstallerError(f"目标目录在安装期间被创建，拒绝覆盖：{target}")
        os.replace(extracted, target)
        succeeded = True
        log(f"安装完成：{target}")
        log(f"安装器：{target / installer_relative}")
        log("下一步：人工运行安装器并登录 QQ；本项目不接触密码或验证码。")
        emit_event(
            event_sink,
            "installed",
            message="下载、校验与解压完成；安装器尚未运行",
            version=asset.tag,
            target=str(target),
            installer_relative_path=installer_relative,
            installer_sha256=installer_hash,
            progress=100,
        )
    finally:
        if not succeeded or staging.exists():
            shutil.rmtree(staging, ignore_errors=True)

    final_installer = target / installer_relative
    if launch:
        tty = stdin_is_tty if stdin_is_tty is not None else sys.stdin.isatty()
        if not tty:
            log("拒绝启动：--launch 需要交互式终端，以避免无人值守执行第三方程序。")
            return 2
        log("即将运行 NapCat 官方安装器（无参数、无提权、shell=False）。")
        answer = input_func("确认运行请输入 LAUNCH：")
        if answer.strip() != "LAUNCH":
            log("未确认，取消启动。")
            return 2
        current_hash = hashlib.sha256(final_installer.read_bytes()).hexdigest()
        if not hmac.compare_digest(current_hash, installer_hash):
            log("安装器哈希在安装后发生变化，拒绝启动。")
            return 3
        log(f"启动：{final_installer}")
        runner([str(final_installer)], shell=False, check=False)
    return 0


def describe_release(
    *,
    version: str | None,
    dest: Path,
    opener: Any | None = None,
    timeout: float = 30.0,
) -> dict[str, Any]:
    opener = opener or build_opener()
    release = fetch_release(version, opener=opener, timeout=timeout)
    asset = select_windows_asset(release)
    target = (dest / sanitize_tag(asset.tag)).resolve()
    return release_metadata(asset, target=target)


# ---------------------------------------------------------------- CLI


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="从 NapCat 官方 GitHub Release 下载、校验并解压 Windows OneKey 包。",
    )
    parser.add_argument("--version", help="指定 Release 标签，例如 v4.18.42；默认最新版。")
    parser.add_argument(
        "--dest",
        type=Path,
        default=default_destination(),
        help="安装根目录，默认 connectors/napcat。",
    )
    parser.add_argument("--dry-run", action="store_true", help="只显示将下载的版本/资产/哈希，不下载。")
    parser.add_argument(
        "--launch",
        action="store_true",
        help="安装完成后，在交互式终端输入 LAUNCH 才运行官方安装器；不自动登录 QQ。",
    )
    parser.add_argument("--list-releases", action="store_true", help="列出可选稳定版本，不下载。")
    parser.add_argument(
        "--json",
        action="store_true",
        help="与 --dry-run 或 --list-releases 搭配，stdout 只输出结构化 JSON。",
    )
    parser.add_argument(
        "--json-events",
        action="store_true",
        help="安装过程 stdout 只输出 NDJSON 事件，人类可读日志转到 stderr。",
    )
    parser.add_argument("--timeout", type=float, default=60.0, help="网络超时秒数，默认 60。")
    return parser.parse_args(argv)


def _error_code(exc: InstallerError) -> str:
    message = str(exc)
    if "INSUFFICIENT_DISK" in message:
        return "CONNECTOR_INSUFFICIENT_DISK"
    if "目标目录已存在" in message:
        return "CONNECTOR_TARGET_EXISTS"
    if "SHA-256" in message:
        return "CONNECTOR_DIGEST_MISMATCH"
    if "磁盘" in message:
        return "CONNECTOR_INSUFFICIENT_DISK"
    if "下载" in message or "GitHub" in message:
        return "CONNECTOR_DOWNLOAD_FAILED"
    return "CONNECTOR_INSTALL_FAILED"


def main(argv: list[str] | None = None) -> int:
    # 与仓库其他 Windows 脚本一致，固定 UTF-8 输出，避免中文在控制台乱码。
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except (ValueError, OSError):
                pass
    args = parse_args(argv)
    structured = bool(args.json or args.json_events)
    if structured:
        set_log_stream(sys.stderr)
    sink: Callable[[dict[str, Any]], None] | None = None
    if args.json_events:
        sink = lambda event: print(json.dumps(event, ensure_ascii=False), flush=True)  # noqa: E731
    try:
        if args.list_releases:
            releases = fetch_releases(opener=build_opener(), timeout=args.timeout)
            if args.json:
                print(json.dumps({"releases": releases}, ensure_ascii=False), flush=True)
            else:
                for item in releases:
                    log(f"{item['version']}（{item['asset_name']}，{item['size']} 字节）")
            return 0
        if args.json and not args.dry_run:
            raise InstallerError("--json 只能与 --dry-run 或 --list-releases 一起使用。")
        if args.json:
            metadata = describe_release(
                version=args.version,
                dest=args.dest.expanduser().resolve(),
                timeout=min(args.timeout, 30.0),
            )
            print(json.dumps(metadata, ensure_ascii=False), flush=True)
            return 0
        return install(
            version=args.version,
            dest=args.dest.expanduser().resolve(),
            dry_run=args.dry_run,
            launch=args.launch,
            timeout=args.timeout,
            event_sink=sink,
        )
    except InstallerError as exc:
        if args.json_events:
            emit_event(sink, "error", code=_error_code(exc), message=str(exc))
        elif args.json:
            print(
                json.dumps({"error": {"code": _error_code(exc), "message": str(exc)}}, ensure_ascii=False),
                flush=True,
            )
        else:
            log(f"错误：{exc}")
        return 1
    except KeyboardInterrupt:
        if args.json_events:
            emit_event(sink, "error", code="CONNECTOR_JOB_CANCELLED", message="已取消。")
        log("已取消。")
        return 130


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""发行包干净环境冒烟：冻结后端 + 安装版 Electron 桌面壳。

只使用仓库内固定路径与临时目录，不读取用户真实 ``.env``、数据库、桌面设置或
连接器目录，不接触真实 QQ / 真实模型。运行前需先执行 ``scripts/build_release.py``。

检查项：
1. ``release/win-unpacked`` 布局与 BUILD_INFO 哈希一致；
2. 冻结后端可在无源码依赖的临时数据目录中启动、迁移并响应健康检查；
3. 安装版 Electron ``--smoke`` 通过，截图存在且版本一致。

结果写入 ``release/RELEASE_SMOKE.json``；不需要 Python/Node 的目标机器可直接运行
``release/win-unpacked/AI 群友.exe``，本脚本只是构建机上的验证工具。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RELEASE = ROOT / "release"
UNPACKED = RELEASE / "win-unpacked"
BACKEND_DIR = UNPACKED / "resources" / "backend"
FRONTEND_DIST = UNPACKED / "resources" / "frontend" / "dist"
DESKTOP_EXE = UNPACKED / "AI 群友.exe"
INSTALLER_GLOB = "AI-Group-Friend-Setup-*.exe"


class SmokeFailure(RuntimeError):
    pass


def log(message: str) -> None:
    print(f"[release-smoke] {message}", flush=True)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_build_info() -> dict:
    path = RELEASE / "BUILD_INFO.json"
    if not path.is_file():
        raise SmokeFailure("缺少 release/BUILD_INFO.json，请先运行 scripts/build_release.py。")
    return json.loads(path.read_text(encoding="utf-8"))


def check_layout(info: dict) -> dict:
    required = [
        DESKTOP_EXE,
        BACKEND_DIR / "aiqf-backend.exe",
        BACKEND_DIR / "_internal",
        BACKEND_DIR / "_internal" / "alembic.ini",
        BACKEND_DIR / "_internal" / "alembic",
        BACKEND_DIR / "tools" / "aiqf-napcat-installer.exe",
        FRONTEND_DIST / "index.html",
        UNPACKED / "resources" / "app" / "main.js",
    ]
    missing = [str(path.relative_to(ROOT)) for path in required if not path.exists()]
    if missing:
        raise SmokeFailure(f"安装版布局缺少：{', '.join(missing)}")

    artifacts = info.get("artifacts") or {}
    for relative, expected in artifacts.items():
        path = RELEASE / relative
        if not path.is_file():
            raise SmokeFailure(f"BUILD_INFO 记录的产物不存在：{relative}")
        actual = sha256(path)
        if actual != expected.get("sha256"):
            raise SmokeFailure(f"哈希不一致：{relative}")
        if path.stat().st_size != expected.get("bytes"):
            raise SmokeFailure(f"大小不一致：{relative}")

    version = str(info.get("version") or "")
    if not version:
        raise SmokeFailure("BUILD_INFO.json 缺少版本号。")
    expected_installer = RELEASE / f"AI-Group-Friend-Setup-{version}-x64.exe"
    if not expected_installer.is_file():
        raise SmokeFailure(f"未找到当前版本 NSIS 安装包：{expected_installer.name}")
    installers = sorted(RELEASE.glob(INSTALLER_GLOB))
    unexpected = [path.name for path in installers if path.name != expected_installer.name]
    if unexpected:
        raise SmokeFailure(f"release/ 含其他版本安装包，请先清理再构建：{', '.join(unexpected)}")
    return {
        "unpacked": str(UNPACKED),
        "installer": str(expected_installer),
        "frontend_index": str(FRONTEND_DIST / "index.html"),
        "backend": str(BACKEND_DIR / "aiqf-backend.exe"),
        "artifacts_verified": sorted(artifacts),
    }


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def http_json(url: str, timeout: float = 3.0) -> dict:
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        if response.status != 200:
            raise SmokeFailure(f"{url} 返回 HTTP {response.status}")
        return json.loads(response.read().decode("utf-8"))


def http_text(url: str, timeout: float = 3.0) -> tuple[str, str]:
    request = urllib.request.Request(url)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.headers.get("Content-Type", ""), response.read().decode("utf-8", errors="replace")


def generate_keys() -> tuple[str, str]:
    try:
        from cryptography.fernet import Fernet
    except ImportError as exc:  # pragma: no cover - 构建机依赖缺失
        raise SmokeFailure("release_smoke 需要后端虚拟环境中的 cryptography。") from exc
    fernet_key = Fernet.generate_key().decode("ascii")
    app_secret = os.urandom(48).hex()
    return fernet_key, app_secret


def write_env_file(path: Path, data_dir: Path, connectors_dir: Path, port: int) -> tuple[str, str]:
    fernet_key, app_secret = generate_keys()
    values = [
        "APP_ENV=smoke",
        f"APP_SECRET_KEY={app_secret}",
        f"CREDENTIAL_ENCRYPTION_KEY={fernet_key}",
        f"DATA_DIR={data_dir.as_posix()}",
        f"CONNECTORS_DIR={connectors_dir.as_posix()}",
        "AUTO_MIGRATE=true",
        "ALLOW_REMOTE_ADMIN=false",
        "LOG_LEVEL=warning",
        "APP_PORT=" + str(port),
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(values) + "\n", encoding="utf-8")
    return fernet_key, app_secret


def backend_env(base: dict[str, str], env_file: Path, data_dir: Path, port: int) -> dict[str, str]:
    env = dict(base)
    for key in (
        "CONNECTORS_DIR",
        "DATABASE_URL",
        "DATA_DIR",
        "FRONTEND_DIST",
        "AI_GROUP_FRIEND_RESOURCE_ROOT",
        "ADMIN_API_TOKEN",
        "ALLOW_REMOTE_ADMIN",
        "CREDENTIAL_ENCRYPTION_KEY",
        "APP_SECRET_KEY",
        "APP_ENV",
        "APP_PORT",
    ):
        env.pop(key, None)
    env.update(
        {
            "AI_GROUP_FRIEND_ENV_FILE": str(env_file),
            "APP_ENV": "smoke",
            "APP_PORT": str(port),
            "LOG_LEVEL": "warning",
            "PYTHONUNBUFFERED": "1",
        }
    )
    return env


def wait_for_backend(port: int, process: subprocess.Popen, log_path: Path, expected_version: str) -> dict:
    deadline = time.monotonic() + 90
    last_error = ""
    while time.monotonic() < deadline:
        if process.poll() is not None:
            tail = log_path.read_text(encoding="utf-8", errors="replace")[-4000:] if log_path.is_file() else ""
            raise SmokeFailure(f"冻结后端提前退出（code={process.returncode}）：\n{tail}")
        try:
            payload = http_json(f"http://127.0.0.1:{port}/api/health", timeout=1.5)
            data = payload.get("data", {})
            if data.get("status") == "ok":
                if data.get("version") != expected_version:
                    raise SmokeFailure(f"健康检查版本 {data.get('version')} != {expected_version}")
                return payload
        except (OSError, urllib.error.URLError, TimeoutError, ValueError) as exc:
            last_error = str(exc)
        time.sleep(0.5)
    tail = log_path.read_text(encoding="utf-8", errors="replace")[-4000:] if log_path.is_file() else ""
    raise SmokeFailure(f"等待冻结后端健康检查超时：{last_error}\n{tail}")


def check_backend(info: dict, workdir: Path, base_env: dict[str, str]) -> dict:
    exe = BACKEND_DIR / "aiqf-backend.exe"
    data_dir = workdir / "data"
    connectors_dir = workdir / "connectors" / "napcat"
    env_file = workdir / "runtime.env"
    log_path = workdir / "backend.log"
    data_dir.mkdir(parents=True, exist_ok=True)
    connectors_dir.mkdir(parents=True, exist_ok=True)
    port = free_port()
    write_env_file(env_file, data_dir, connectors_dir, port)
    env = backend_env(base_env, env_file, data_dir, port)

    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    log("启动冻结后端（隔离 data/connectors/env）")
    with log_path.open("w", encoding="utf-8", errors="replace") as log_file:
        process = subprocess.Popen(
            [str(exe)],
            cwd=str(workdir),
            env=env,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            creationflags=creationflags,
        )
        try:
            health = wait_for_backend(port, process, log_path, str(info["version"]))
            settings = http_json(f"http://127.0.0.1:{port}/api/settings")
            runtime = settings.get("data", {}).get("runtime", {})
            if runtime.get("runtime_mode") != "packaged":
                raise SmokeFailure(f"运行模式不是 packaged：{runtime.get('runtime_mode')}")
            reported_data = Path(str(runtime.get("data_dir", ""))).resolve()
            if reported_data != data_dir.resolve():
                raise SmokeFailure(f"数据目录未使用隔离路径：{reported_data}")
            if not runtime.get("credential_key_configured"):
                raise SmokeFailure("凭证加密密钥未生效。")
            content_type, html = http_text(f"http://127.0.0.1:{port}/")
            if "text/html" not in content_type or '<div id="app">' not in html:
                raise SmokeFailure("后端未托管内置前端。")
            database = data_dir / "ai_group_friend.db"
            if not database.is_file():
                raise SmokeFailure("数据库文件未创建。")
            with sqlite3.connect(database) as connection:
                row = connection.execute("SELECT version_num FROM alembic_version").fetchone()
            if not row or not row[0]:
                raise SmokeFailure("Alembic 版本表为空，迁移未执行。")
            return {
                "status": health.get("data", {}).get("status"),
                "version": health.get("data", {}).get("version"),
                "runtime_mode": runtime.get("runtime_mode"),
                "data_dir": str(reported_data),
                "credential_key_configured": runtime.get("credential_key_configured"),
                "allowed_hosts": settings.get("data", {}).get("security", {}).get("allowed_hosts"),
                "frontend_served": True,
                "alembic_revision": row[0],
                "database_bytes": database.stat().st_size,
            }
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=10)


def electron_env(base: dict[str, str], workdir: Path) -> dict[str, str]:
    env = dict(base)
    for key in (
        "AI_GROUP_FRIEND_ENV_FILE",
        "AI_GROUP_FRIEND_INSTALLER_EXE",
        "AI_GROUP_FRIEND_RESOURCE_ROOT",
        "CONNECTORS_DIR",
        "DATABASE_URL",
        "DATA_DIR",
        "FRONTEND_DIST",
        "ADMIN_API_TOKEN",
        "ALLOW_REMOTE_ADMIN",
        "CREDENTIAL_ENCRYPTION_KEY",
        "APP_SECRET_KEY",
    ):
        env.pop(key, None)
    # 只保留系统目录，证明安装版不依赖本机 Python/Node 或仓库内工具链。
    env["PATH"] = os.pathsep.join(
        value for value in [os.environ.get("SystemRoot", r"C:\Windows"), r"C:\Windows\System32"] if value
    )
    env["AI_GROUP_FRIEND_ENV_FILE"] = str(workdir / "should-not-be-used.env")
    env.pop("PYTHONHOME", None)
    env.pop("PYTHONPATH", None)
    env.pop("NODE_OPTIONS", None)
    env.pop("NODE_PATH", None)
    return env


def check_desktop(info: dict, workdir: Path, base_env: dict[str, str]) -> dict:
    if not DESKTOP_EXE.is_file():
        raise SmokeFailure("缺少安装版桌面可执行文件。")
    log("启动安装版 Electron --smoke（隔离 userData 与临时数据目录）")
    started = time.monotonic()
    result = subprocess.run(
        [str(DESKTOP_EXE), "--smoke"],
        cwd=str(workdir),
        env=electron_env(base_env, workdir),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=300,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    output = (result.stdout or "") + (result.stderr or "")
    (workdir / "desktop-smoke.log").write_text(output, encoding="utf-8")
    if result.returncode != 0:
        raise SmokeFailure(f"安装版冒烟退出码 {result.returncode}：\n{output[-6000:]}")
    if "DESKTOP_SMOKE_OK" not in output:
        raise SmokeFailure(f"安装版冒烟未输出 DESKTOP_SMOKE_OK：\n{output[-6000:]}")
    marker = output.split("DESKTOP_SMOKE_OK", 1)[1].splitlines()[0].strip()
    try:
        payload = json.loads(marker)
    except ValueError as exc:
        raise SmokeFailure(f"DESKTOP_SMOKE_OK 负载无法解析：{marker[:500]}") from exc
    if payload.get("version") != str(info["version"]):
        raise SmokeFailure(f"安装版版本 {payload.get('version')} != {info['version']}")
    screenshots = payload.get("screenshots") or []
    if len(screenshots) < 6:
        raise SmokeFailure(f"截图数量不足：{len(screenshots)}")
    missing = [path for path in screenshots if not Path(path).is_file() or Path(path).stat().st_size == 0]
    if missing:
        raise SmokeFailure(f"截图缺失或为空：{missing}")
    # 桌面冒烟把截图写入其临时 userData；复制到 release/ 作为可复查证据。
    evidence_dir = RELEASE / "smoke-screenshots"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    evidence: list[str] = []
    for path in screenshots:
        target = evidence_dir / Path(path).name
        shutil.copy2(path, target)
        evidence.append(str(target))
    return {
        "version": payload.get("version"),
        "port": payload.get("port"),
        "startup_port": payload.get("startupPort"),
        "screenshots": evidence,
        "duration_seconds": round(time.monotonic() - started, 1),
    }


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="发行包干净环境冒烟")
    parser.add_argument("--keep", action="store_true", help="保留临时目录以便排查")
    parser.add_argument("--skip-desktop", action="store_true", help="只验证冻结后端与布局")
    args = parser.parse_args()

    if os.name != "nt":
        raise SystemExit("当前发行包仅支持 Windows x64。")
    if not DESKTOP_EXE.is_file():
        raise SystemExit("缺少 release/win-unpacked，请先运行 scripts/build_release.py。")

    info = load_build_info()
    workdir = Path(tempfile.mkdtemp(prefix="aiqf-release-smoke-"))
    base_env = dict(os.environ)
    report: dict[str, object] = {
        "product": info.get("product"),
        "version": info.get("version"),
        "platform": info.get("platform"),
        "git_commit": info.get("git_commit"),
        "git_branch": info.get("git_branch"),
        "git_dirty": info.get("git_dirty"),
        "git_status_sha256": info.get("git_status_sha256"),
        "git_diff_sha256": info.get("git_diff_sha256"),
        "version_sources": info.get("version_sources"),
        "checked_at": datetime.now(UTC).astimezone().isoformat(timespec="seconds"),
        "clean_env": {
            "workdir": str(workdir),
            "data_dir": str(workdir / "data"),
            "desktop_user_data": "临时目录（由 --smoke 自行创建）",
            "path": "仅系统目录",
            "real_env_file_used": False,
            "real_connectors_dir_used": False,
        },
        "real_qq_verified": False,
        "real_model_verified": False,
    }
    try:
        log("校验安装版布局与 BUILD_INFO 哈希")
        report["layout"] = check_layout(info)
        report["backend"] = check_backend(info, workdir, base_env)
        if args.skip_desktop:
            report["desktop"] = {"skipped": True}
        else:
            report["desktop"] = check_desktop(info, workdir, base_env)
        report["status"] = "ok"
        (RELEASE / "RELEASE_SMOKE.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        log(f"通过：后端 {report['backend']} / 桌面 {report.get('desktop')}")
        log("未接触真实 QQ 或真实模型；安装包内不含用户凭证。")
        return 0
    except (SmokeFailure, subprocess.TimeoutExpired, OSError) as exc:
        report["status"] = "failed"
        report["error"] = str(exc)
        (RELEASE / "RELEASE_SMOKE.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        log(f"失败：{exc}")
        return 1
    finally:
        if args.keep:
            log(f"临时目录保留在 {workdir}")
        else:
            shutil.rmtree(workdir, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())

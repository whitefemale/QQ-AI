#!/usr/bin/env python3
"""构建 Windows 发行包：前端 → 冻结后端/安装器 → Electron NSIS 安装包。

只做项目内固定命令，不接受外部命令参数。产物写入仓库根 ``release/``，
并生成 ``release/BUILD_INFO.json`` 与哈希清单。真实 QQ/模型不会被调用。
默认拒绝在未提交的工作树上构建；确需测试打包流程时显式使用 ``--allow-dirty``，
此时 ``BUILD_INFO.json`` 会记录 dirty 状态与工作树指纹。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
FRONTEND = ROOT / "frontend"
DESKTOP = ROOT / "desktop"
RELEASE = ROOT / "release"
VENV_PYTHON = BACKEND / (".venv/Scripts/python.exe" if os.name == "nt" else ".venv/bin/python")


def log(message: str) -> None:
    print(f"[build] {message}", flush=True)


def run(command: list[str], cwd: Path) -> None:
    log(f"$ {' '.join(command)}  (cwd={cwd})")
    subprocess.run(command, cwd=cwd, check=True)


def npm_command(*args: str) -> list[str]:
    """直接调用 npm-cli.js，避免 Windows 上 .cmd 无法直接 CreateProcess。"""
    node = shutil.which("node")
    if not node:
        raise SystemExit("未找到 Node.js。")
    npm_cli = Path(node).resolve().parent / "node_modules" / "npm" / "bin" / "npm-cli.js"
    if not npm_cli.is_file():
        raise SystemExit("未找到 npm-cli.js，请安装完整 Node.js。")
    return [node, str(npm_cli), *args]


def read_python_version() -> str:
    """从 app/__init__.py 读取版本，避免导入 app 触发配置与依赖。"""
    match = re.search(r'__version__\s*=\s*"([^"]+)"', (BACKEND / "app" / "__init__.py").read_text(encoding="utf-8"))
    return match.group(1) if match else ""


def read_version_sources() -> dict[str, str]:
    """校验桌面、前端、后端包与 pyproject 的版本一致。

    ``Settings.app_version`` 直接导入 ``app.__version__``，不再维护第二份版本常量。
    """
    data = json.loads((DESKTOP / "package.json").read_text(encoding="utf-8"))
    version = str(data.get("version", ""))
    if not version:
        raise SystemExit("desktop/package.json 缺少版本号。")
    frontend_version = str(json.loads((FRONTEND / "package.json").read_text(encoding="utf-8"))["version"])
    backend_version = read_python_version()
    pyproject_version = re.search(
        r'^version\s*=\s*"([^"]+)"', (BACKEND / "pyproject.toml").read_text(encoding="utf-8"), re.MULTILINE
    )
    versions = {
        "desktop/package.json": version,
        "frontend/package.json": frontend_version,
        "backend/app/__init__.py": backend_version,
        "backend/pyproject.toml": pyproject_version.group(1) if pyproject_version else "",
    }
    if len(set(versions.values())) != 1:
        raise SystemExit(f"版本号不一致，请先统一：{versions}")
    return versions


def read_electron_version() -> str:
    """从 desktop/package.json 读取 Electron 版本，并与已安装版本交叉校验。"""
    package = json.loads((DESKTOP / "package.json").read_text(encoding="utf-8"))
    declared = str((package.get("devDependencies") or {}).get("electron", "")).strip()
    if not declared:
        raise SystemExit("desktop/package.json 未声明 Electron 版本。")
    installed_path = DESKTOP / "node_modules" / "electron" / "package.json"
    if not installed_path.is_file():
        raise SystemExit("缺少 desktop/node_modules/electron，请先运行 npm install。")
    installed = str(json.loads(installed_path.read_text(encoding="utf-8")).get("version", "")).strip()
    if installed != declared:
        raise SystemExit(f"已安装 Electron {installed} 与 package.json 声明 {declared} 不一致，请重新 npm install。")
    return installed


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _git(*args: str) -> str | None:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=ROOT,
            capture_output=True,
            check=True,
        )
        return result.stdout.decode("utf-8", errors="replace")
    except (OSError, subprocess.CalledProcessError):
        return None


def git_commit() -> str:
    return (_git("rev-parse", "HEAD") or "").strip() or "unknown"


def git_branch() -> str:
    return (_git("rev-parse", "--abbrev-ref", "HEAD") or "").strip() or "unknown"


def git_worktree_state() -> tuple[bool | None, str | None, str | None]:
    """返回 (是否 dirty, status 指纹, diff 指纹)。

    Git 不可用或命令失败时返回 ``(None, None, None)``，构建脚本会拒绝继续，
    避免把无法确认的工作树伪装成可复现构建。
    """
    status = _git("status", "--porcelain=v1", "--untracked-files=normal")
    if status is None:
        return None, None, None
    dirty = bool(status.strip())
    status_sha = hashlib.sha256(status.encode("utf-8")).hexdigest() if dirty else None
    diff_sha: str | None = None
    if dirty:
        diff = _git("diff", "--binary", "HEAD")
        if diff is None:
            return None, None, None
        diff_sha = hashlib.sha256(diff.encode("utf-8")).hexdigest()
    return dirty, status_sha, diff_sha


def clean_release_dir() -> None:
    """只清理仓库根 ``release/``；拒绝符号链接或路径逃逸。"""
    expected = (ROOT / "release").resolve()
    if RELEASE.is_symlink() or RELEASE.resolve() != expected:
        raise SystemExit("release 路径异常，拒绝清理。")
    if RELEASE.exists() and not RELEASE.is_dir():
        raise SystemExit("release 不是目录，拒绝清理。")
    if RELEASE.exists():
        try:
            shutil.rmtree(RELEASE)
        except OSError as exc:
            raise SystemExit(f"无法清理 release/（可能有程序占用）：{exc}") from exc
    RELEASE.mkdir(parents=True, exist_ok=True)


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="构建 AI 群友 Windows 发行包")
    parser.add_argument("--dir-only", action="store_true", help="只生成 unpacked 目录，不生成 NSIS 安装包")
    parser.add_argument("--skip-frontend", action="store_true", help="复用已有 frontend/dist")
    parser.add_argument(
        "--allow-dirty",
        action="store_true",
        help="允许在未提交的工作树上构建；BUILD_INFO 会记录 dirty 状态与指纹",
    )
    args = parser.parse_args()

    if not VENV_PYTHON.is_file():
        raise SystemExit("缺少 backend/.venv，请先安装后端依赖。")
    pyinstaller_check = subprocess.run(
        [str(VENV_PYTHON), "-m", "PyInstaller", "--version"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if pyinstaller_check.returncode != 0:
        raise SystemExit('缺少 PyInstaller，请先安装打包依赖：pip install -e ".[dev,packaging]"')
    version_sources = read_version_sources()
    version = version_sources["desktop/package.json"]
    electron_version = read_electron_version()
    dirty, status_sha, diff_sha = git_worktree_state()
    if dirty is None:
        raise SystemExit("无法确认 Git 工作树状态；拒绝构建不可复现的发行包。")
    if dirty and not args.allow_dirty:
        raise SystemExit("工作树存在未提交改动。请先提交，或显式使用 --allow-dirty 并接受 dirty 标记。")
    log(f"版本 {version}，Electron {electron_version}，目标 Windows x64，工作树 dirty={dirty}")

    clean_release_dir()
    try:
        if not args.skip_frontend:
            run(npm_command("run", "build"), FRONTEND)
        if not (FRONTEND / "dist" / "index.html").is_file():
            raise SystemExit("frontend/dist 缺失，请先构建前端。")

        run([str(VENV_PYTHON), "scripts/make_icon.py"], ROOT)

        log("冻结后端（PyInstaller onedir）")
        shutil.rmtree(BACKEND / "build", ignore_errors=True)
        shutil.rmtree(BACKEND / "dist", ignore_errors=True)
        run(
            [
                str(VENV_PYTHON),
                "-m",
                "PyInstaller",
                "--noconfirm",
                "--clean",
                "--distpath",
                str(BACKEND / "dist"),
                "--workpath",
                str(BACKEND / "build"),
                str(BACKEND / "packaging" / "aiqf-backend.spec"),
            ],
            ROOT,
        )
        backend_exe = BACKEND / "dist" / "aiqf-backend" / "aiqf-backend.exe"
        if not backend_exe.is_file():
            raise SystemExit("后端冻结产物缺失。")

        log("冻结受管 NapCat 安装器")
        run(
            [
                str(VENV_PYTHON),
                "-m",
                "PyInstaller",
                "--noconfirm",
                "--clean",
                "--distpath",
                str(BACKEND / "dist"),
                "--workpath",
                str(BACKEND / "build" / "installer"),
                str(BACKEND / "packaging" / "aiqf-napcat-installer.spec"),
            ],
            ROOT,
        )
        installer_exe = BACKEND / "dist" / "aiqf-napcat-installer.exe"
        if not installer_exe.is_file():
            raise SystemExit("安装器冻结产物缺失。")
        tools_dir = BACKEND / "dist" / "aiqf-backend" / "tools"
        tools_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(installer_exe, tools_dir / installer_exe.name)

        log("构建 Electron 安装包" if not args.dir_only else "构建 Electron unpacked 目录")
        # Windows 上 Node 自带的 CA 可能与系统代理/根证书不一致；使用系统证书完成 NSIS 工具下载。
        node_options = os.environ.get("NODE_OPTIONS", "").strip()
        if "--use-system-ca" not in node_options.split():
            os.environ["NODE_OPTIONS"] = f"{node_options} --use-system-ca".strip()
        builder = DESKTOP / "node_modules" / "electron-builder" / "cli.js"
        if not builder.is_file():
            raise SystemExit("缺少 electron-builder，请在 desktop/ 下运行 npm install。")
        electron_dist = DESKTOP / "node_modules" / "electron" / "dist"
        if not (electron_dist / "electron.exe").is_file():
            raise SystemExit("缺少本机 Electron 发行目录，请先在 desktop/ 下运行 npm install。")
        command = [
            "node",
            str(builder),
            "--win",
            "--x64",
            # 使用已安装的 Electron，避免构建时需要联网下载（离线/证书环境会失败）。
            f"--config.electronDist={electron_dist}",
            "--publish",
            "never",
        ]
        # 默认目标来自 desktop/package.json 的 build.win.target（nsis），无需再传位置参数。
        if args.dir_only:
            command.append("--dir")
        run(command, DESKTOP)

        artifacts: dict[str, dict[str, object]] = {}
        if not args.dir_only:
            installer = RELEASE / f"AI-Group-Friend-Setup-{version}-x64.exe"
            if not installer.is_file():
                raise SystemExit(f"未找到当前版本安装包：{installer.name}")
            artifacts[installer.name] = {"bytes": installer.stat().st_size, "sha256": sha256(installer)}
        unpacked_exe = RELEASE / "win-unpacked" / "AI 群友.exe"
        if not unpacked_exe.is_file():
            raise SystemExit("未找到 win-unpacked/AI 群友.exe。")
        artifacts[unpacked_exe.relative_to(RELEASE).as_posix()] = {
            "bytes": unpacked_exe.stat().st_size,
            "sha256": sha256(unpacked_exe),
        }
    except BaseException:
        log("构建失败，清理 release/ 半成品")
        shutil.rmtree(RELEASE, ignore_errors=True)
        raise

    info = {
        "product": "AI 群友",
        "version": version,
        "built_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "platform": "win32-x64",
        "git_commit": git_commit(),
        "git_branch": git_branch(),
        "git_dirty": bool(dirty),
        "git_status_sha256": status_sha,
        "git_diff_sha256": diff_sha,
        "version_sources": version_sources,
        "python": sys.version.split()[0],
        "node": subprocess.run(["node", "--version"], capture_output=True, text=True, check=False).stdout.strip(),
        "installer": not args.dir_only,
        "signed": False,
        "auto_update": False,
        "bundled_runtime": {
            "backend": "PyInstaller onedir（Python 已内置）",
            "connector_installer": "PyInstaller onefile",
            "frontend": "Vite production build",
            "electron": electron_version,
        },
        "artifacts": artifacts,
        "real_qq_verified": False,
        "real_model_verified": False,
        "installer_executed_on_clean_machine": False,
        "notes": (
            "构建与打包冒烟只验证本机隔离环境；真实 QQ 端到端、真实模型 Key、"
            "在独立干净机器上运行 NSIS 安装器/卸载器均未验证。安装包未签名。"
        ),
    }
    (RELEASE / "BUILD_INFO.json").write_text(json.dumps(info, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    log(f"完成：{RELEASE / 'BUILD_INFO.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

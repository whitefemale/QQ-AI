#!/usr/bin/env python3
"""生成本地安全密钥，并可安全写入项目根目录的 .env。

用法（项目根目录）：
    python scripts/gen_keys.py             # 只打印新密钥
    python scripts/gen_keys.py --write     # 写入 .env（保留已有非占位值）
    python scripts/gen_keys.py --write --force  # 强制轮换密钥（旧凭证将无法解密）

只使用 Python 标准库，不依赖后端虚拟环境。
"""

from __future__ import annotations

import argparse
import base64
import os
import re
import secrets
import stat
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ENV = ROOT / ".env"
EXAMPLE_ENV = ROOT / ".env.example"

KEYS = ("APP_SECRET_KEY", "CREDENTIAL_ENCRYPTION_KEY")


def new_app_secret() -> str:
    return secrets.token_urlsafe(48)


def new_fernet_key() -> str:
    """Fernet 密钥格式：32 字节随机数据的 URL-safe Base64。"""
    return base64.urlsafe_b64encode(os.urandom(32)).decode("ascii")


def _upsert(text: str, key: str, value: str, *, force: bool) -> tuple[str, str]:
    """返回 (新文本, 动作)。动作：created / replaced / kept。"""
    pattern = re.compile(rf"(?m)^{re.escape(key)}=(.*)$")
    match = pattern.search(text)
    if match is None:
        if text and not text.endswith("\n"):
            text += "\n"
        return f"{text}{key}={value}\n", "created"
    current = match.group(1).strip()
    is_placeholder = not current or current.startswith("replace-with") or current.startswith("<")
    if force or is_placeholder:
        return pattern.sub(lambda _m: f"{key}={value}", text, count=1), "replaced"
    return text, "kept"


def _read_base(env_path: Path) -> str:
    if env_path.is_file():
        return env_path.read_text(encoding="utf-8")
    if EXAMPLE_ENV.is_file():
        return EXAMPLE_ENV.read_text(encoding="utf-8")
    return ""


def _write_private(env_path: Path, text: str) -> None:
    env_path.parent.mkdir(parents=True, exist_ok=True)
    with env_path.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)
    try:
        env_path.chmod(stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        pass


def _utf8_console() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
        except (AttributeError, ValueError):
            pass


def main() -> int:
    _utf8_console()
    parser = argparse.ArgumentParser(description="生成 AI 群友本地密钥")
    parser.add_argument("--write", action="store_true", help="写入 .env（默认只打印）")
    parser.add_argument("--force", action="store_true", help="覆盖 .env 中已有密钥，请谨慎使用")
    parser.add_argument("--env", default=str(DEFAULT_ENV), help="目标 .env 路径")
    args = parser.parse_args()

    env_path = Path(args.env).expanduser().resolve()
    generated = {
        "APP_SECRET_KEY": new_app_secret(),
        "CREDENTIAL_ENCRYPTION_KEY": new_fernet_key(),
    }

    if not args.write:
        print("已生成新的本地密钥（仅显示本次，请勿提交到 Git）：\n")
        for key in KEYS:
            print(f"{key}={generated[key]}")
        print("\n写入 .env：python scripts/gen_keys.py --write")
        print("注意：轮换 CREDENTIAL_ENCRYPTION_KEY 后，已保存的 Token / API Key 将无法解密。")
        return 0

    if args.force and env_path.is_file():
        print("警告：--force 将覆盖已有密钥。已保存的 Token / API Key 可能永久无法解密。")

    text = _read_base(env_path)
    actions: dict[str, str] = {}
    for key in KEYS:
        text, action = _upsert(text, key, generated[key], force=args.force)
        actions[key] = action
    _write_private(env_path, text)

    print(f"已写入 {env_path}")
    for key in KEYS:
        action = actions[key]
        label = {
            "created": "已新增",
            "replaced": "已生成",
            "kept": "已存在，保持不变",
        }[action]
        # 不回显密钥本身，避免终端/日志泄漏。
        print(f"  {key}: {label}")
    print("\n请确认 .env 已被 .gitignore 忽略；不要提交或分享该文件。")
    print("首次使用请在控制台「模型 API」中重新填写 API Key（如需要）。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

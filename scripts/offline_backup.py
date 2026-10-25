"""离线 SQLite 备份：供 scripts/backup.ps1 在后端未运行时使用。

只读取数据库并生成一致性副本，不做迁移、恢复或任何网络操作。
"""

from __future__ import annotations

import hashlib
import pathlib
import sqlite3
import sys


def _utf8_console() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(encoding="utf-8")
            except Exception:  # pragma: no cover - 控制台不支持时忽略
                pass


def main(argv: list[str]) -> int:
    _utf8_console()
    if len(argv) != 3:
        print("用法：offline_backup.py <源数据库> <目标文件>", file=sys.stderr)
        return 2
    source = pathlib.Path(argv[1]).resolve()
    target = pathlib.Path(argv[2]).resolve()
    if not source.is_file():
        print(f"数据库不存在：{source}", file=sys.stderr)
        return 2
    if target.exists():
        print(f"目标文件已存在，拒绝覆盖：{target}", file=sys.stderr)
        return 2
    if source == target:
        print("源数据库与目标文件不能相同。", file=sys.stderr)
        return 2
    target.parent.mkdir(parents=True, exist_ok=True)

    with sqlite3.connect(str(source), timeout=30) as src, sqlite3.connect(str(target), timeout=30) as dst:
        src.backup(dst)
    with sqlite3.connect(str(target)) as check:
        result = check.execute("PRAGMA integrity_check").fetchone()
        if not result or str(result[0]).lower() != "ok":
            target.unlink(missing_ok=True)
            print(f"integrity_check 失败：{result}", file=sys.stderr)
            return 1
    digest = hashlib.sha256(target.read_bytes()).hexdigest()
    print(f"OFFLINE_BACKUP={target}")
    print(f"SHA256={digest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))

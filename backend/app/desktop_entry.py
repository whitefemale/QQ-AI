"""打包版后端入口：由桌面壳以固定环境变量启动，不接受命令行参数。

不提供 reload、workers、reload-dir 等能力；主机固定为回环地址，端口由桌面壳分配。
"""

from __future__ import annotations

import os

import uvicorn

from app.main import app

_ALLOWED_LOG_LEVELS = {"critical", "error", "warning", "info", "debug", "trace"}


def _loopback_host() -> str:
    # 打包版绝不监听非回环地址，远程管理仍由 ALLOW_REMOTE_ADMIN 决定。
    return "127.0.0.1"


def _port() -> int:
    try:
        value = int(os.environ.get("APP_PORT", "8000"))
    except ValueError:
        return 8000
    return value if 1 <= value <= 65535 else 8000


def _log_level() -> str:
    value = os.environ.get("LOG_LEVEL", "info").strip().lower()
    return value if value in _ALLOWED_LOG_LEVELS else "info"


def main() -> None:
    uvicorn.run(
        app,
        host=_loopback_host(),
        port=_port(),
        log_level=_log_level(),
        reload=False,
        workers=1,
        access_log=False,
    )


if __name__ == "__main__":
    main()

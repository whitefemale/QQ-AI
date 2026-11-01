# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 规格：打包后端为 onedir 发行物（不含测试与开发依赖）。"""

from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files

backend_root = Path(SPECPATH).resolve().parent
repo_root = backend_root.parent

datas = [
    (str(backend_root / "alembic.ini"), "."),
    (str(backend_root / "alembic"), "alembic"),
    # 时区数据库随包分发，避免依赖目标机器安装 tzdata。
    *collect_data_files("tzdata"),
]

hiddenimports = [
    "aiosqlite",
    "greenlet",
    "sqlalchemy.dialects.sqlite.aiosqlite",
    "uvicorn.logging",
    "uvicorn.loops.auto",
    "uvicorn.loops.asyncio",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.http.h11_impl",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.protocols.websockets.websockets_impl",
    "uvicorn.lifespan.on",
]

a = Analysis(
    [str(backend_root / "app" / "desktop_entry.py")],
    pathex=[str(backend_root)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["pytest", "mypy", "ruff", "tests"],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="aiqf-backend",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="aiqf-backend",
)

# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 规格：把受管 NapCat 安装脚本冻结为独立可执行文件。

仅使用标准库；参数仍由后端固定生成，不接受用户传入命令。
"""

from pathlib import Path

repo_root = Path(SPECPATH).resolve().parent.parent

a = Analysis(
    [str(repo_root / "scripts" / "install_napcat.py")],
    pathex=[str(repo_root)],
    binaries=[],
    datas=[],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["pytest", "app", "tests"],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="aiqf-napcat-installer",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
)

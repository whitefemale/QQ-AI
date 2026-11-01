#!/usr/bin/env python3
"""把 256x256 PNG 转换为 Windows ICO（PNG 压缩条目，Vista+）。

仅使用标准库，供发布构建与测试使用；不联网、不修改其他文件。
"""

from __future__ import annotations

import argparse
import struct
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PNG = ROOT / "desktop" / "assets" / "icon.png"
DEFAULT_ICO = ROOT / "desktop" / "assets" / "icon.ico"


def png_ico_bytes(png: bytes) -> bytes:
    if not png.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ValueError("输入不是 PNG 文件。")
    width, height = struct.unpack(">II", png[16:24])
    if (width, height) not in {(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)}:
        raise ValueError(f"PNG 尺寸 {width}x{height} 不是 Windows 图标支持的尺寸。")
    # ICONDIR + 单个 ICONDIRENTRY（宽高为 0 表示 256）。
    header = struct.pack("<HHH", 0, 1, 1)
    entry = struct.pack(
        "<BBBBHHII",
        0 if width == 256 else width,
        0 if height == 256 else height,
        0,
        0,
        1,
        32,
        len(png),
        6 + 16,
    )
    return header + entry + png


def main() -> int:
    parser = argparse.ArgumentParser(description="生成桌面包 ICO 图标")
    parser.add_argument("--png", default=str(DEFAULT_PNG))
    parser.add_argument("--out", default=str(DEFAULT_ICO))
    args = parser.parse_args()

    png_path = Path(args.png)
    out_path = Path(args.out)
    data = png_ico_bytes(png_path.read_bytes())
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(data)
    print(f"已生成 {out_path}（{len(data)} 字节，来源 {png_path.name}）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

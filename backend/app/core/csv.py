"""CSV 导出公共处理：UTF-8 BOM、公式注入防护与行数上限。"""

from __future__ import annotations

import csv
import hashlib
import io
from collections.abc import Iterable, Sequence
from typing import Any

from app.core.errors import AppError, ErrorCode

CSV_ROW_LIMIT = 50_000
_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def csv_safe(value: Any) -> str:
    """防止 Excel/表格软件把单元格当成公式执行。"""
    if value is None:
        return ""
    text = str(value)
    if text.startswith(_FORMULA_PREFIXES):
        return "'" + text
    return text


def build_csv_bytes(columns: Sequence[str], rows: Iterable[Sequence[Any]]) -> bytes:
    rows = list(rows)
    if len(rows) > CSV_ROW_LIMIT:
        raise AppError(
            ErrorCode.VALIDATION_ERROR,
            f"导出数据超过 {CSV_ROW_LIMIT} 行，请缩小筛选范围后重试。",
            status_code=413,
        )
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\r\n")
    writer.writerow([csv_safe(item) for item in columns])
    for row in rows:
        writer.writerow([csv_safe(item) for item in row])
    # BOM 让 Excel 以 UTF-8 打开，避免中文乱码。
    return b"\xef\xbb\xbf" + buffer.getvalue().encode("utf-8")


def content_digest(text: str) -> str:
    """审计用摘要：只证明内容身份，不保存正文。"""
    return hashlib.sha256(str(text or "").encode("utf-8")).hexdigest()

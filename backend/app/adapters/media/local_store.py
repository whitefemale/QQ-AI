"""本地文件系统媒体存储。消息只保存内部 media_ref，不保存临时 URL 或二进制。"""

from __future__ import annotations

import asyncio
import hashlib
import re
from pathlib import Path

from app.adapters.media.base import MediaStore
from app.core.errors import AppError, ErrorCode
from app.schemas.media import BinarySource, MediaMetadata, StoredMediaRef

_REF_PATTERN = re.compile(r"^[a-f0-9]{64}$")

_MAGIC_SIGNATURES: list[tuple[bytes, str]] = [
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"GIF87a", "image/gif"),
    (b"GIF89a", "image/gif"),
    (b"RIFF", "audio/wav"),
    (b"ID3", "audio/mpeg"),
    (b"%PDF-", "application/pdf"),
    (b"PK\x03\x04", "application/zip"),
    (b"\x1aE\xdf\xa3", "video/webm"),
]


def sniff_mime(data: bytes, provided: str | None) -> str | None:
    for signature, mime in _MAGIC_SIGNATURES:
        if data.startswith(signature):
            if signature == b"RIFF" and len(data) > 12 and data[8:12] == b"WEBP":
                return "image/webp"
            return mime
    if len(data) > 12 and data[4:8] == b"ftyp":
        return "video/mp4"
    return provided


class LocalMediaStore(MediaStore):
    def __init__(self, root: Path, *, max_bytes: int = 10 * 1024 * 1024) -> None:
        self.root = root
        self.max_bytes = max_bytes

    def _path_for(self, media_ref: str) -> Path:
        if not _REF_PATTERN.match(media_ref):
            raise AppError(ErrorCode.MEDIA_NOT_FOUND, "媒体引用无效。", status_code=404)
        return self.root / media_ref[:2] / media_ref

    async def put(self, source: BinarySource, metadata: MediaMetadata) -> StoredMediaRef:
        data = source.data
        if not data:
            raise AppError(ErrorCode.MEDIA_TYPE_UNSUPPORTED, "媒体内容为空。", status_code=400)
        if len(data) > self.max_bytes:
            raise AppError(ErrorCode.MEDIA_TOO_LARGE, "媒体文件超过大小限制。", status_code=413)

        def _write() -> StoredMediaRef:
            digest = hashlib.sha256(data).hexdigest()
            path = self._path_for(digest)
            path.parent.mkdir(parents=True, exist_ok=True)
            if not path.exists():
                path.write_bytes(data)
            return StoredMediaRef(
                media_ref=digest,
                mime=sniff_mime(data, metadata.mime or source.mime),
                size_bytes=len(data),
                sha256=digest,
            )

        return await asyncio.to_thread(_write)

    async def get(self, media_ref: str) -> BinarySource:
        path = self._path_for(media_ref)
        if not path.exists():
            raise AppError(ErrorCode.MEDIA_NOT_FOUND, "媒体文件不存在或已过期。", status_code=404)
        data = await asyncio.to_thread(path.read_bytes)
        return BinarySource(data=data, filename=media_ref)

    async def delete(self, media_ref: str) -> None:
        path = self._path_for(media_ref)

        def _delete() -> None:
            try:
                path.unlink()
            except FileNotFoundError:
                return

        await asyncio.to_thread(_delete)

    async def exists(self, media_ref: str) -> bool:
        return await asyncio.to_thread(self._path_for(media_ref).exists)

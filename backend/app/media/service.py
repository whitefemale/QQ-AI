"""媒体资产服务：保存、查询、清理及派生数据删除。"""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import String, cast, delete, select

from app.adapters.media.local_store import LocalMediaStore
from app.core.config import Settings
from app.core.errors import AppError, ErrorCode
from app.core.time import utcnow
from app.db.session import Database
from app.models.media import MediaAsset, MediaJob, MediaTranscript
from app.models.message import Message
from app.schemas.media import BinarySource, MediaMetadata


class MediaService:
    def __init__(self, database: Database, store: LocalMediaStore, settings: Settings) -> None:
        self.database = database
        self.store = store
        self.settings = settings

    async def ingest(
        self,
        data: bytes,
        *,
        mime: str | None,
        media_type: str,
        account_id: str | None = None,
        group_id: str | None = None,
        source_message_id: str | None = None,
    ) -> MediaAsset:
        metadata = MediaMetadata(
            account_id=account_id,
            group_id=group_id,
            media_type=media_type,
            mime=mime,
            source_message_id=source_message_id,
        )
        stored = await self.store.put(BinarySource(data=data, mime=mime), metadata)
        async with self.database.session() as session:
            existing = await session.get(MediaAsset, stored.media_ref)
            if existing is not None and existing.deleted_at is None:
                return existing
            asset = existing or MediaAsset(id=stored.media_ref)
            asset.account_id = account_id
            asset.group_id = group_id
            asset.media_type = media_type
            asset.mime = stored.mime
            asset.size_bytes = stored.size_bytes
            asset.sha256 = stored.sha256
            asset.storage_path = str(self.store.root / stored.sha256[:2] / stored.sha256)
            asset.source_message_id = source_message_id
            asset.status = "stored"
            asset.expires_at = utcnow() + timedelta(days=self.settings.media_retention_days)
            asset.deleted_at = None
            if existing is None:
                session.add(asset)
            await session.commit()
            await session.refresh(asset)
            return asset

    async def get_asset(self, media_ref: str) -> MediaAsset:
        async with self.database.session() as session:
            asset = await session.get(MediaAsset, media_ref)
        if asset is None or asset.deleted_at is not None:
            raise AppError(ErrorCode.MEDIA_NOT_FOUND, "媒体资产不存在或已删除。", status_code=404)
        return asset

    async def get_bytes(self, media_ref: str) -> bytes:
        await self.get_asset(media_ref)
        source = await self.store.get(media_ref)
        return source.data

    async def find_transcript(self, media_ref: str, kinds: set[str]) -> MediaTranscript | None:
        async with self.database.session() as session:
            result = await session.execute(
                select(MediaTranscript)
                .where(MediaTranscript.media_ref == media_ref, MediaTranscript.kind.in_(kinds))
                .order_by(MediaTranscript.created_at.desc())
                .limit(1)
            )
            return result.scalar_one_or_none()

    async def is_referenced(self, media_ref: str) -> bool:
        """是否仍有消息 segment 引用该媒体。

        本地存储按 SHA 去重，同一 media_ref 可能被多条消息共享；删除前必须检查，
        否则会误删其他仍保留消息的图片/语音。
        """
        async with self.database.session() as session:
            found = await session.scalar(
                select(Message.id).where(cast(Message.segments_json, String).like(f"%{media_ref}%")).limit(1)
            )
        return found is not None

    async def delete(self, media_ref: str, *, protect_referenced: bool = False) -> bool:
        """删除媒体文件及其转写、任务等派生数据。

        protect_referenced=True 时，若仍有消息引用该媒体则跳过并返回 False。
        """
        if protect_referenced and await self.is_referenced(media_ref):
            return False
        await self.store.delete(media_ref)
        async with self.database.session() as session:
            asset = await session.get(MediaAsset, media_ref)
            if asset is None:
                return True
            await session.execute(delete(MediaTranscript).where(MediaTranscript.media_ref == media_ref))
            await session.execute(delete(MediaJob).where(MediaJob.media_ref == media_ref))
            asset.status = "deleted"
            asset.deleted_at = utcnow()
            asset.storage_path = None
            asset.source_message_id = None
            asset.metadata_json = {}
            await session.commit()
        return True

    async def cleanup_expired(self, *, protect_referenced: bool = False) -> int:
        async with self.database.session() as session:
            result = await session.execute(
                select(MediaAsset).where(
                    MediaAsset.deleted_at.is_(None),
                    MediaAsset.expires_at.is_not(None),
                    MediaAsset.expires_at < utcnow(),
                )
            )
            assets = list(result.scalars())
        deleted = 0
        for asset in assets:
            if await self.delete(asset.id, protect_referenced=protect_referenced):
                deleted += 1
        return deleted

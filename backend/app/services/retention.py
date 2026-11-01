"""保留策略与本地清理。

安全边界：
- 自动清理默认关闭，只有管理员在设置页显式开启后调度器才执行。
- 清理只删除超过保留期限的本地数据，不发送消息、不调用模型、不运行媒体任务。
- 全局暂停不影响本地删除；摘要如实记录运行时的暂停状态。
- 先擦除人格证据与记忆来源，再删除消息；派生数据擦除失败时不删除该批消息。
- 日志只删除 logs 目录下的 app.log.* 轮转文件，绝不触碰当前 app.log。
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import suppress
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import String, cast, delete, func, select

from app.core.config import Settings
from app.core.errors import AppError, ErrorCode
from app.core.security import redact_text
from app.core.time import iso_utc, utcnow
from app.db.session import Database
from app.media.service import MediaService
from app.models.media import MediaAsset
from app.models.message import Message
from app.services.audit import write_audit
from app.services.memory_service import MemoryService
from app.services.persona_store import PersonaStore
from app.services.settings_store import get_global_pause, get_setting, set_setting

logger = logging.getLogger(__name__)

RETENTION_SETTING_KEY = "retention"
RETENTION_AUTO_KEY = "retention_auto"
RETENTION_LAST_RUN_KEY = "retention.last_run"

RETENTION_DEFAULTS = {
    "log_retention_days": 30,
    "message_retention_days": 90,
    "media_retention_days": 30,
    # 0 表示不自动清理记忆；不能沿用 1~3650 的归一化，否则 0 会被改写。
    "memory_retention_days": 0,
}


def normalize_memory_retention_days(raw: Any) -> int:
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return 0
    return value if value == 0 or 1 <= value <= 3650 else 0


def normalize_retention_days(raw: Any) -> dict[str, int]:
    """把数据库/接口中的保留天数规范化；记忆保留允许 0（关闭自动清理）。"""
    result = dict(RETENTION_DEFAULTS)
    if not isinstance(raw, dict):
        return result
    for key in ("log_retention_days", "message_retention_days", "media_retention_days"):
        candidate = raw.get(key)
        if candidate is None:
            continue
        try:
            value = int(candidate)
        except (TypeError, ValueError):
            continue
        if 1 <= value <= 3650:
            result[key] = value
    if "memory_retention_days" in raw:
        result["memory_retention_days"] = normalize_memory_retention_days(raw.get("memory_retention_days"))
    return result


def _empty_counts() -> dict[str, int]:
    return {
        "messages": 0,
        "batches": 0,
        "media_from_messages": 0,
        "media_expired": 0,
        "logs": 0,
        "persona_traits_updated": 0,
        "persona_traits_demoted": 0,
        "persona_events_updated": 0,
        "persona_proposals_rejected": 0,
        "persona_versions_updated": 0,
        "memories_scrubbed": 0,
        "memory_candidates_updated": 0,
        "memory_candidates_deleted": 0,
        "memories_deleted": 0,
    }


class RetentionService:
    def __init__(
        self,
        database: Database,
        settings: Settings,
        media: MediaService,
        personas: PersonaStore,
        memories: MemoryService,
    ) -> None:
        self.database = database
        self.settings = settings
        self.media = media
        self.personas = personas
        self.memories = memories
        self._lock = asyncio.Lock()
        self.scheduler: RetentionScheduler | None = None

    # ------------------------------------------------------------------ 设置
    async def retention_days(self) -> dict[str, int]:
        value = await get_setting(self.database, RETENTION_SETTING_KEY)
        return normalize_retention_days(value)

    async def _auto_flag(self) -> tuple[bool, str]:
        raw = await get_setting(self.database, RETENTION_AUTO_KEY)
        if isinstance(raw, dict) and isinstance(raw.get("enabled"), bool):
            return bool(raw["enabled"]), "setting"
        return bool(self.settings.retention_enabled), "config"

    async def is_enabled(self) -> bool:
        enabled, _source = await self._auto_flag()
        return enabled

    async def set_enabled(self, enabled: bool, *, actor: str = "local-admin") -> dict[str, Any]:
        if not isinstance(enabled, bool):
            raise AppError(ErrorCode.VALIDATION_ERROR, "自动清理开关必须是布尔值。", status_code=400)
        value = {"enabled": enabled, "updated_at": iso_utc(utcnow()), "actor": actor}
        await set_setting(self.database, RETENTION_AUTO_KEY, value)
        await write_audit(
            self.database,
            action="retention.auto.toggle",
            target_type="system_settings",
            details={"enabled": enabled},
            actor=actor,
        )
        return value

    async def status(self) -> dict[str, Any]:
        enabled, source = await self._auto_flag()
        last_run = await get_setting(self.database, RETENTION_LAST_RUN_KEY)
        if not isinstance(last_run, dict):
            last_run = None
        return {
            "auto": {
                "enabled": enabled,
                "source": source,
                "config_enabled": bool(self.settings.retention_enabled),
            },
            "running": self._lock.locked(),
            "interval_seconds": self.settings.retention_interval_seconds,
            "batch_size": self.settings.retention_batch_size,
            "max_batches_per_run": self.settings.retention_max_batches_per_run,
            "retention_days": await self.retention_days(),
            "last_run": last_run,
            "scheduler": self.scheduler.snapshot() if self.scheduler is not None else None,
            "notes": [
                "自动清理默认关闭；开启后仅按保留天数删除本地旧数据。",
                "清理不会发送消息、调用模型或处理媒体任务，全局暂停也不会阻止本地删除。",
                "日志只删除 logs 目录下 app.log.* 轮转文件，当前 app.log 始终保留。",
                "人格证据与记忆来源先擦除再删除消息；记忆正文本身不会被改写。",
                "记忆保留天数为 0 表示不自动删除记忆；固定记忆永远不参与自动清理。",
            ],
        }

    # ------------------------------------------------------------------ 预览
    async def preview(self) -> dict[str, Any]:
        """只读统计将被清理的数据；不取运行锁、不写审计、不更新 last_run。"""
        now = utcnow()
        days = await self.retention_days()
        batch_size = max(1, int(self.settings.retention_batch_size))
        max_batches = max(1, int(self.settings.retention_max_batches_per_run))
        will_delete_limit = batch_size * max_batches
        message_cutoff = now - timedelta(days=days["message_retention_days"])
        async with self.database.session() as session:
            messages_expired = int(
                await session.scalar(select(func.count(Message.id)).where(Message.event_timestamp < message_cutoff))
                or 0
            )
            messages_with_media = int(
                await session.scalar(
                    select(func.count(Message.id)).where(
                        Message.event_timestamp < message_cutoff,
                        cast(Message.segments_json, String).like("%media_ref%"),
                    )
                )
                or 0
            )
            media_expired = int(
                await session.scalar(
                    select(func.count(MediaAsset.id)).where(
                        MediaAsset.deleted_at.is_(None),
                        MediaAsset.expires_at.is_not(None),
                        MediaAsset.expires_at < now,
                    )
                )
                or 0
            )
        log_candidates = await asyncio.to_thread(self._log_candidates, days["log_retention_days"])
        memories = 0
        if days["memory_retention_days"] > 0:
            try:
                result = await self.memories.cleanup(
                    mode="older_than",
                    days=days["memory_retention_days"],
                    dry_run=True,
                )
                memories = int(result["matched"])
            except Exception as exc:  # noqa: BLE001 - 预览失败只降级计数，不阻断页面
                logger.warning("统计可清理记忆失败", extra={"reason": type(exc).__name__})
        will_delete = min(messages_expired, will_delete_limit)
        return {
            "generated_at": iso_utc(now),
            "running": self._lock.locked(),
            "retention_days": days,
            "counts": {
                "messages_expired": messages_expired,
                "messages_will_delete": will_delete,
                "messages_remaining_after": max(0, messages_expired - will_delete),
                "messages_with_media": messages_with_media,
                "media_expired": media_expired,
                "logs": len(log_candidates),
                "memories": memories,
            },
            "memory_retention_enabled": days["memory_retention_days"] > 0,
            "limits": {
                "batch_size": batch_size,
                "max_batches": max_batches,
                "max_messages_per_run": will_delete_limit,
            },
            "truncated": messages_expired > will_delete,
            "notes": [
                "预览只统计，不删除任何数据，也不写审计或上次运行记录。",
                "实际运行时先擦除人格证据与记忆来源，再删除消息；派生数据数量以实际运行摘要为准。",
                "日志只统计 logs 目录下早于保留期的 app.log.* 轮转文件，当前 app.log 永不删除。",
                "记忆保留天数为 0 表示不自动清理记忆；固定记忆永远不参与清理。",
            ],
        }

    # ------------------------------------------------------------------ 执行
    async def run(
        self,
        *,
        trigger: str = "manual",
        actor: str = "local-admin",
        confirm: str | None = None,
    ) -> dict[str, Any]:
        if trigger == "manual" and confirm != "CLEANUP":
            raise AppError(
                ErrorCode.CONFIRMATION_REQUIRED,
                "清理不可恢复，请输入 CLEANUP 以确认。",
                status_code=400,
            )
        if self._lock.locked():
            raise AppError(ErrorCode.CONFLICT, "已有清理任务正在运行，请稍后再试。", status_code=409)
        async with self._lock:
            return await self._run_locked(trigger=trigger, actor=actor)

    async def _run_locked(self, *, trigger: str, actor: str) -> dict[str, Any]:
        started_at = utcnow()
        pause = await get_global_pause(self.database)
        days = await self.retention_days()
        summary: dict[str, Any] = {
            "status": "completed",
            "trigger": trigger,
            "actor": actor,
            "started_at": iso_utc(started_at),
            "finished_at": None,
            "global_pause": bool(pause.get("paused")),
            "truncated": False,
            "error": None,
            "retention_days": days,
            "counts": _empty_counts(),
        }
        try:
            await self._cleanup_messages(days["message_retention_days"], summary, actor=actor)
            await self._cleanup_memories(days["memory_retention_days"], summary)
            summary["counts"]["media_expired"] = await self.media.cleanup_expired(protect_referenced=True)
            summary["counts"]["logs"] = await asyncio.to_thread(self._cleanup_logs, days["log_retention_days"])
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            summary["status"] = "failed"
            summary["error"] = redact_text(f"{type(exc).__name__}: {exc}")[:500]
            logger.exception("保留策略清理失败", extra={"trigger": trigger})
        finally:
            summary["finished_at"] = iso_utc(utcnow())
            await self._record(summary)
        return summary

    async def _cleanup_messages(self, retention_days: int, summary: dict[str, Any], *, actor: str) -> None:
        cutoff = utcnow() - timedelta(days=retention_days)
        batch_size = max(1, int(self.settings.retention_batch_size))
        max_batches = max(1, int(self.settings.retention_max_batches_per_run))
        counts = summary["counts"]
        hit_cap = False
        for _batch in range(max_batches):
            async with self.database.session() as session:
                rows = list(
                    (
                        await session.execute(
                            select(Message.id, Message.segments_json)
                            .where(Message.event_timestamp < cutoff)
                            .order_by(Message.event_timestamp)
                            .limit(batch_size)
                        )
                    ).all()
                )
            if not rows:
                break
            hit_cap = len(rows) == batch_size and _batch == max_batches - 1
            message_ids = {str(row.id) for row in rows}
            media_refs: set[str] = set()
            for row in rows:
                for segment in row.segments_json or []:
                    if not isinstance(segment, dict):
                        continue
                    ref = segment.get("media_ref")
                    if isinstance(ref, str) and ref.strip():
                        media_refs.add(ref.strip())

            try:
                persona_result = await self.personas.prune_evidence(message_ids, actor=actor)
                memory_result = await self.memories.scrub_source_message_ids(message_ids, actor=actor)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                # 派生数据未擦干净时绝不删除消息，避免留下指向已删消息的引用。
                summary["status"] = "partial"
                summary["error"] = redact_text(f"{type(exc).__name__}: {exc}")[:500]
                logger.exception("擦除派生数据失败，已停止删除该批消息")
                break

            counts["persona_traits_updated"] += persona_result["affected_traits"]
            counts["persona_traits_demoted"] += persona_result["demoted_traits"]
            counts["persona_events_updated"] += persona_result["events_updated"]
            counts["persona_proposals_rejected"] += persona_result["proposals_rejected"]
            counts["persona_versions_updated"] += persona_result["versions_updated"]
            counts["memories_scrubbed"] += memory_result["memories_updated"]
            counts["memory_candidates_updated"] += memory_result["candidates_updated"]
            counts["memory_candidates_deleted"] += memory_result["candidates_deleted"]

            async with self.database.session() as session:
                await session.execute(delete(Message).where(Message.id.in_(message_ids)))
                await session.commit()
            counts["messages"] += len(message_ids)
            counts["batches"] += 1

            for media_ref in sorted(media_refs):
                try:
                    if await self.media.delete(media_ref, protect_referenced=True):
                        counts["media_from_messages"] += 1
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    summary["status"] = "partial"
                    summary["error"] = redact_text(f"媒体清理失败：{type(exc).__name__}: {exc}")[:500]
                    logger.warning("清理媒体资产失败", extra={"media_ref": media_ref})

        if hit_cap:
            summary["truncated"] = await self._has_expired_messages(cutoff)

    async def _has_expired_messages(self, cutoff: datetime) -> bool:
        async with self.database.session() as session:
            found = await session.scalar(select(Message.id).where(Message.event_timestamp < cutoff).limit(1))
        return found is not None

    async def _cleanup_memories(self, retention_days: int, summary: dict[str, Any]) -> None:
        """0 表示关闭；只删除未固定且创建时间超过保留期的记忆。"""
        if retention_days <= 0:
            return
        try:
            result = await self.memories.cleanup(mode="older_than", days=retention_days, dry_run=False)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            summary["status"] = "partial"
            summary["error"] = redact_text(f"记忆保留清理失败：{type(exc).__name__}: {exc}")[:500]
            logger.exception("清理过期记忆失败")
            return
        summary["counts"]["memories_deleted"] += int(result["deleted"])

    def _log_candidates(self, retention_days: int) -> list[Path]:
        """只返回 logs 目录下早于保留期的 app.log.* 轮转文件；当前 app.log 永不删除。"""
        root = self.settings.logs_path
        if not root.is_dir():
            return []
        cutoff = utcnow() - timedelta(days=retention_days)
        candidates: list[Path] = []
        for path in root.iterdir():
            try:
                if path.is_symlink() or not path.is_file() or not path.name.startswith("app.log."):
                    continue
                mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=UTC)
                if mtime < cutoff:
                    candidates.append(path)
            except OSError:
                logger.warning("跳过无法读取的日志文件", extra={"name": path.name})
        return candidates

    def _cleanup_logs(self, retention_days: int) -> int:
        deleted = 0
        for path in self._log_candidates(retention_days):
            try:
                path.unlink()
                deleted += 1
            except OSError:
                logger.warning("跳过无法清理的日志文件", extra={"name": path.name})
        return deleted

    async def _record(self, summary: dict[str, Any]) -> None:
        try:
            await set_setting(self.database, RETENTION_LAST_RUN_KEY, summary)
        except Exception:
            logger.exception("保存清理运行摘要失败")
        try:
            await write_audit(
                self.database,
                action="retention.run",
                target_type="system_settings",
                details={
                    "status": summary["status"],
                    "trigger": summary["trigger"],
                    "global_pause": summary["global_pause"],
                    "truncated": summary["truncated"],
                    "error": summary["error"],
                    "counts": summary["counts"],
                },
                actor=str(summary["actor"]),
            )
        except Exception:
            logger.exception("写入清理审计失败")


class RetentionScheduler:
    """按固定间隔执行自动清理；并发运行由 RetentionService 的锁拒绝。"""

    def __init__(self, service: RetentionService, *, interval_seconds: float | None = None) -> None:
        self.service = service
        self.interval_seconds = max(
            60.0,
            float(interval_seconds if interval_seconds is not None else service.settings.retention_interval_seconds),
        )
        self._stop_event = asyncio.Event()
        self._task: asyncio.Task[None] | None = None
        self._next_run_at: datetime | None = None
        service.scheduler = self

    def snapshot(self) -> dict[str, Any]:
        return {
            "running": self._task is not None,
            "interval_seconds": self.interval_seconds,
            "next_run_at": iso_utc(self._next_run_at),
        }

    async def start(self) -> None:
        if self._task is not None:
            return
        self._stop_event.clear()
        self._next_run_at = utcnow() + timedelta(seconds=self.interval_seconds)
        self._task = asyncio.create_task(self._loop(), name="retention-scheduler")

    async def stop(self) -> None:
        task = self._task
        self._task = None
        self._next_run_at = None
        if task is None:
            return
        self._stop_event.set()
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task

    async def _loop(self) -> None:
        if self.service.settings.retention_run_on_start and await self.service.is_enabled():
            await self._tick()
        while not self._stop_event.is_set():
            self._next_run_at = utcnow() + timedelta(seconds=self.interval_seconds)
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=self.interval_seconds)
            except TimeoutError:
                pass
            else:
                break
            await self._tick()
        self._next_run_at = None

    async def _tick(self) -> None:
        if not await self.service.is_enabled():
            return
        try:
            await self.service.run(trigger="scheduled", actor="scheduler")
        except asyncio.CancelledError:
            raise
        except AppError as exc:
            if exc.code == ErrorCode.CONFLICT:
                logger.info("上一轮清理仍在运行，跳过本次调度")
            else:
                logger.warning("自动清理失败", extra={"code": exc.code})
        except Exception:
            logger.exception("自动清理发生未预期错误")


__all__ = [
    "RETENTION_AUTO_KEY",
    "RETENTION_DEFAULTS",
    "RETENTION_LAST_RUN_KEY",
    "RETENTION_SETTING_KEY",
    "RetentionScheduler",
    "RetentionService",
    "normalize_retention_days",
]

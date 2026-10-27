"""媒体 Provider 调用审计与聚合。

只记录计数、时延、费用状态与错误码；绝不保存媒体内容、转写文本或提示词。
"""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from sqlalchemy import select

from app.core.time import iso_utc, utcnow
from app.db.session import Database
from app.models.media import MediaProviderUsage

logger = logging.getLogger(__name__)

USAGE_NOTE = (
    "媒体用量只统计 Provider 调用次数、时延、成功/失败与费用状态，不含媒体内容或转写文本。"
    "Mock 调用记录为零外部费用；真实 Provider 未提供费用时保持未知，不伪造 0 成本。"
)


class MediaUsageService:
    def __init__(self, database: Database) -> None:
        self.database = database

    async def record(
        self,
        *,
        provider_id: str | None,
        capability: str,
        job_type: str,
        source: str = "job",
        account_id: str | None = None,
        group_id: str | None = None,
        requests: float = 1.0,
        latency_ms: float = 0.0,
        external_cost: float | None = None,
        is_mock: bool = False,
        succeeded: bool = True,
        error_code: str | None = None,
    ) -> None:
        """best-effort：用量写入失败只记日志，不能把已完成的媒体任务改成失败。"""
        try:
            async with self.database.session() as session:
                session.add(
                    MediaProviderUsage(
                        provider_id=provider_id,
                        capability=capability,
                        job_type=job_type,
                        source=source,
                        account_id=account_id,
                        group_id=group_id,
                        requests=requests,
                        latency_ms=latency_ms,
                        # Mock 明确为零外部费用；真实/未知 Provider 保持 null。
                        external_cost=0.0 if is_mock else external_cost,
                        is_mock=is_mock,
                        succeeded=succeeded,
                        error_code=error_code,
                    )
                )
                await session.commit()
        except Exception:
            logger.exception("媒体用量记录失败", extra={"event": "media.usage.failed"})

    async def aggregate(
        self,
        *,
        hours: int = 24,
        provider_id: str | None = None,
        capability: str | None = None,
        account_id: str | None = None,
        group_id: str | None = None,
    ) -> dict[str, Any]:
        safe_hours = max(1, min(hours, 24 * 31))
        until = utcnow()
        since = until - timedelta(hours=safe_hours)
        conditions = [MediaProviderUsage.created_at >= since, MediaProviderUsage.created_at <= until]
        if provider_id:
            conditions.append(MediaProviderUsage.provider_id == provider_id)
        if capability:
            conditions.append(MediaProviderUsage.capability == capability)
        if account_id:
            conditions.append(MediaProviderUsage.account_id == account_id)
        if group_id:
            conditions.append(MediaProviderUsage.group_id == group_id)
        async with self.database.session() as session:
            rows = list(
                (
                    await session.execute(
                        select(MediaProviderUsage).where(*conditions).order_by(MediaProviderUsage.created_at)
                    )
                ).scalars()
            )
        # 两个桶的键都允许 None：Provider 可能未记录，能力理论上不会为空。
        by_provider: dict[str | None, dict[str, Any]] = {}
        by_capability: dict[str | None, dict[str, Any]] = {}
        for row in rows:
            for bucket, key, extra in (
                (
                    by_provider,
                    row.provider_id,
                    {"provider_id": row.provider_id, "provider_name": row.provider_id or "未记录 Provider"},
                ),
                (by_capability, row.capability, {"capability": row.capability}),
            ):
                entry = bucket.get(key)
                if entry is None:
                    entry = {"_calls": 0, "_requests": 0.0, "_latency": 0.0, **extra}
                    bucket[key] = entry
                entry["_calls"] += 1
                entry["_requests"] += float(row.requests or 0)
                entry["_latency"] += float(row.latency_ms or 0)
                for field in ("succeeded", "is_mock"):
                    name = f"_{field}"
                    entry[name] = int(entry.get(name, 0)) + (1 if getattr(row, field) else 0)
                entry.setdefault("_cost_known", 0)
                entry.setdefault("_cost_total", 0.0)
                if row.external_cost is not None:
                    entry["_cost_known"] += 1
                    entry["_cost_total"] += float(row.external_cost)
        cost_known = sum(1 for row in rows if row.external_cost is not None)
        cost_total = sum(float(row.external_cost or 0.0) for row in rows if row.external_cost is not None)
        return {
            "hours": safe_hours,
            "window_start": iso_utc(since),
            "window_end": iso_utc(until),
            "calls": len(rows),
            "requests": round(sum(float(row.requests or 0) for row in rows), 6),
            "successful_calls": sum(1 for row in rows if row.succeeded),
            "failed_calls": sum(1 for row in rows if not row.succeeded),
            "mock_calls": sum(1 for row in rows if row.is_mock),
            "latency_ms_avg": round(sum(float(row.latency_ms or 0) for row in rows) / len(rows), 3) if rows else 0.0,
            "external_cost": self._cost_value(cost_total, cost_known, len(rows)),
            "cost_status": self._cost_status(cost_known, len(rows)),
            "by_provider": [self._finalize(item) for item in by_provider.values()],
            "by_capability": [self._finalize(item) for item in by_capability.values()],
            "note": USAGE_NOTE,
        }

    @staticmethod
    def _cost_value(total: float, known: int, calls: int) -> float | None:
        if calls <= 0 or known <= 0 or known < calls:
            # 只要有一条真实调用费用未知，就不把部分金额冒充总费用。
            return None
        return round(total, 8)

    @staticmethod
    def _cost_status(known: int, calls: int) -> str:
        if calls <= 0:
            return "no_calls"
        if known >= calls:
            return "complete"
        return "partial" if known > 0 else "unknown"

    @staticmethod
    def _finalize(entry: dict[str, Any]) -> dict[str, Any]:
        calls = int(entry.pop("_calls", 0))
        requests = float(entry.pop("_requests", 0.0))
        latency = float(entry.pop("_latency", 0.0))
        succeeded = int(entry.pop("_succeeded", 0))
        mock_calls = int(entry.pop("_is_mock", 0))
        known = int(entry.pop("_cost_known", 0))
        total = float(entry.pop("_cost_total", 0.0))
        entry.update(
            {
                "calls": calls,
                "requests": round(requests, 6),
                "successful_calls": succeeded,
                "failed_calls": calls - succeeded,
                "mock_calls": mock_calls,
                "latency_ms_avg": round(latency / calls, 3) if calls else 0.0,
                "external_cost": MediaUsageService._cost_value(total, known, calls),
                "cost_status": MediaUsageService._cost_status(known, calls),
            }
        )
        return entry

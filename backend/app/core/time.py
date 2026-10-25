"""UTC 时间与群时区工具。"""

from __future__ import annotations

from datetime import UTC, datetime, time, timedelta
from typing import overload
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.core.errors import AppError


def utcnow() -> datetime:
    """返回带 UTC 时区的当前时间。数据库统一存储 UTC。"""
    return datetime.now(UTC)


def utcnow_naive() -> datetime:
    return utcnow().replace(tzinfo=None)


@overload
def ensure_utc(value: datetime) -> datetime: ...


@overload
def ensure_utc(value: None) -> None: ...


def ensure_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def iso_utc(value: datetime | None) -> str | None:
    value = ensure_utc(value)
    if value is None:
        return None
    return value.isoformat().replace("+00:00", "Z")


def get_zone(name: str | None, fallback: str = "Asia/Shanghai") -> ZoneInfo:
    for candidate in (name, fallback, "UTC"):
        if not candidate:
            continue
        try:
            return ZoneInfo(candidate)
        except (ZoneInfoNotFoundError, ValueError):
            continue
    raise AppError("TIMEZONE_INVALID", "时区配置无效，请检查时区名称。", status_code=400)


def parse_hhmm(value: str) -> time:
    try:
        hour, minute = value.strip().split(":", 1)
        parsed = time(hour=int(hour), minute=int(minute))
    except (ValueError, TypeError) as exc:
        raise AppError("QUIET_HOURS_INVALID", "安静时段格式必须为 HH:MM。", status_code=400) from exc
    return parsed


def local_clock(value: datetime, timezone_name: str | None) -> tuple[time, str]:
    zone = get_zone(timezone_name)
    localized = ensure_utc(value).astimezone(zone) if value else utcnow().astimezone(zone)
    return localized.time().replace(tzinfo=None), localized.strftime("%Y-%m-%d %H:%M")


def in_quiet_hours(now: datetime, quiet: dict | None) -> bool:
    """判断当前是否处于安静时段；支持跨零点的区间。"""
    if not quiet or not quiet.get("enabled"):
        return False
    start_raw = quiet.get("start")
    end_raw = quiet.get("end")
    if not start_raw or not end_raw:
        return False
    zone = get_zone(quiet.get("timezone"))
    current = ensure_utc(now).astimezone(zone).time().replace(tzinfo=None)
    start = parse_hhmm(str(start_raw))
    end = parse_hhmm(str(end_raw))
    if start == end:
        return True
    if start < end:
        return start <= current < end
    return current >= start or current < end


def start_of_day_utc(now: datetime, timezone_name: str | None = None) -> datetime:
    zone = get_zone(timezone_name)
    local = ensure_utc(now).astimezone(zone)
    local_start = local.replace(hour=0, minute=0, second=0, microsecond=0)
    return local_start.astimezone(UTC)


def start_of_week_utc(now: datetime, timezone_name: str | None = None) -> datetime:
    zone = get_zone(timezone_name)
    local = ensure_utc(now).astimezone(zone)
    local_start = (local - timedelta(days=local.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
    return local_start.astimezone(UTC)


def start_of_month_utc(now: datetime, timezone_name: str | None = None) -> datetime:
    zone = get_zone(timezone_name)
    local = ensure_utc(now).astimezone(zone)
    local_start = local.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    return local_start.astimezone(UTC)

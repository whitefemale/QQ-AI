"""长期记忆管理：写入校验、范围隔离与受控检索。

当前版本只做显式记忆的本地检索：
- 群聊只读取当前群、当前发送者的记忆，绝不跨群混用。
- 敏感度不为 normal 或已过期的记忆不会自动注入提示词。
- 被标记为“排除记忆”的成员，其成员级记忆不会被自动注入。
- 不包含密码、验证码、证件号、银行卡号或 API Key 的疑似内容会被拒绝写入。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy import func, or_, select

from app.core.config import Settings
from app.core.errors import AppError, ErrorCode
from app.core.time import ensure_utc, iso_utc, utcnow
from app.db.session import Database
from app.models.account import Account
from app.models.group import Group, Member
from app.models.memory import Memory

MEMORY_TYPES = {
    "fact": "事实",
    "preference": "偏好",
    "relationship": "关系",
    "event": "经历",
    "project": "长期事项",
    "boundary": "边界",
}
SENSITIVITIES = {"normal", "sensitive"}
AUTO_INJECT_SENSITIVITIES = {"normal"}
MAX_CONTENT_CHARS = 2000

_SECRET_PATTERNS = (
    re.compile(r"(?i)(密码|口令|验证码|支付密码|银行卡|身份证号|信用卡|cvv|password|passcode)\s*[:：=是为]\s*\S+"),
    re.compile(r"(?<!\d)(?:\d[ -]?){16,19}(?!\d)"),
    re.compile(r"(?<!\d)\d{17}[\dXx](?!\d)"),
    re.compile(r"(?i)\b(?:sk|pk|rk)-[A-Za-z0-9_-]{16,}\b"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
)
_CJK_RUN = re.compile(r"[㐀-鿿]+")
_ASCII_WORD = re.compile(r"[a-z0-9_]{2,}")
_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


@dataclass(frozen=True)
class MemoryItem:
    id: str
    content: str
    memory_type: str
    confidence: float
    is_pinned: bool
    created_at: datetime


@dataclass
class MemorySelection:
    enabled: bool = False
    items: list[MemoryItem] = field(default_factory=list)
    omitted: int = 0

    @property
    def ids(self) -> list[str]:
        return [item.id for item in self.items]

    @property
    def notes(self) -> list[str]:
        rendered: list[str] = []
        for item in self.items:
            label = MEMORY_TYPES.get(item.memory_type, item.memory_type)
            flags = "；已固定" if item.is_pinned else ""
            created = item.created_at.strftime("%Y-%m-%d")
            rendered.append(
                f"[{label}｜置信度 {item.confidence:.2f}｜记录于 {created}{flags}] {_single_line(item.content)}"
            )
        return rendered


def _single_line(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def validate_memory_content(content: str) -> str:
    cleaned = _CONTROL_CHARS.sub("", str(content or "")).strip()
    if not cleaned:
        raise AppError(ErrorCode.VALIDATION_ERROR, "记忆内容不能为空。", status_code=400)
    if len(cleaned) > MAX_CONTENT_CHARS:
        raise AppError(
            ErrorCode.VALIDATION_ERROR,
            f"记忆内容最多 {MAX_CONTENT_CHARS} 个字符。",
            status_code=400,
        )
    for pattern in _SECRET_PATTERNS:
        if pattern.search(cleaned):
            raise AppError(
                ErrorCode.MEMORY_SENSITIVE_CONTENT,
                "记忆内容疑似包含密码、验证码、证件号、银行卡号或密钥，已拒绝保存。请改为描述性内容。",
                status_code=400,
            )
    return cleaned


def validate_memory_type(value: Any) -> str:
    memory_type = str(value or "fact").strip()
    if memory_type not in MEMORY_TYPES:
        raise AppError(
            ErrorCode.VALIDATION_ERROR,
            f"记忆类型无效，可选：{'、'.join(MEMORY_TYPES)}。",
            status_code=400,
        )
    return memory_type


def validate_sensitivity(value: Any) -> str:
    sensitivity = str(value or "normal").strip()
    if sensitivity not in SENSITIVITIES:
        raise AppError(
            ErrorCode.VALIDATION_ERROR,
            "敏感度必须为 normal 或 sensitive；sensitive 记忆不会自动注入提示词。",
            status_code=400,
        )
    return sensitivity


def validate_confidence(value: Any, default: float = 0.5) -> float:
    try:
        confidence = float(value if value is not None else default)
    except (TypeError, ValueError) as exc:
        raise AppError(ErrorCode.VALIDATION_ERROR, "置信度必须是 0 到 1 之间的数字。", status_code=400) from exc
    if not 0.0 <= confidence <= 1.0:
        raise AppError(ErrorCode.VALIDATION_ERROR, "置信度必须在 0 到 1 之间。", status_code=400)
    return confidence


def _parse_expiry(value: Any) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return ensure_utc(value)
    try:
        parsed = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
    except ValueError as exc:
        raise AppError(ErrorCode.VALIDATION_ERROR, "过期时间格式无效，请使用 ISO 8601 时间。", status_code=400) from exc
    return ensure_utc(parsed)


def _source_ids(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip()[:128] for item in value[:20] if str(item).strip()]


def _tokens(text: str) -> set[str]:
    lowered = str(text or "").casefold()
    tokens: set[str] = set(_ASCII_WORD.findall(lowered))
    for run in _CJK_RUN.findall(lowered):
        if len(run) == 1:
            tokens.add(run)
        else:
            tokens.update(run[index : index + 2] for index in range(len(run) - 1))
    return tokens


def _relevance(query_tokens: set[str], content: str) -> int:
    if not query_tokens:
        return 0
    return len(query_tokens & _tokens(content))


class MemoryService:
    def __init__(self, database: Database, settings: Settings) -> None:
        self.database = database
        self.settings = settings

    # ------------------------------------------------------------------ 管理
    async def create_memory(self, payload: dict[str, Any]) -> dict[str, Any]:
        account_id = str(payload.get("account_id") or "").strip()
        if not account_id:
            raise AppError(ErrorCode.VALIDATION_ERROR, "请选择账号。", status_code=400)
        content = validate_memory_content(str(payload.get("content") or ""))
        memory_type = validate_memory_type(payload.get("memory_type"))
        sensitivity = validate_sensitivity(payload.get("sensitivity"))
        confidence = validate_confidence(payload.get("confidence"))
        expires_at = _parse_expiry(payload.get("expires_at"))
        group_id = str(payload.get("group_id") or "").strip() or None
        member_id = str(payload.get("member_id") or "").strip() or None

        async with self.database.session() as session:
            if await session.get(Account, account_id) is None:
                raise AppError(ErrorCode.NOT_FOUND, "账号不存在。", status_code=404)
            if group_id is not None:
                group = await session.get(Group, group_id)
                if group is None or group.account_id != account_id:
                    raise AppError(ErrorCode.NOT_FOUND, "群不存在或不属于该账号。", status_code=404)
            if member_id is not None:
                member = await session.scalar(
                    select(Member).where(
                        Member.account_id == account_id,
                        Member.platform_user_id == member_id,
                    )
                )
                if member is None:
                    raise AppError(
                        ErrorCode.VALIDATION_ERROR,
                        "成员不存在或不属于该账号；请先让该成员产生消息记录。",
                        status_code=400,
                    )
            record = Memory(
                account_id=account_id,
                group_id=group_id,
                member_id=member_id,
                memory_type=memory_type,
                content=content,
                source_message_ids_json=_source_ids(payload.get("source_message_ids")),
                confidence=confidence,
                sensitivity=sensitivity,
                expires_at=expires_at,
                is_pinned=bool(payload.get("is_pinned", False)),
            )
            session.add(record)
            await session.commit()
            await session.refresh(record)
            return self.public(record)

    async def get_memory(self, memory_id: str) -> dict[str, Any]:
        async with self.database.session() as session:
            record = await session.get(Memory, memory_id)
            if record is None:
                raise AppError(ErrorCode.NOT_FOUND, "记忆不存在或已被删除。", status_code=404)
            return self.public(record)

    async def update_memory(self, memory_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        editable = {
            "content",
            "memory_type",
            "sensitivity",
            "confidence",
            "is_pinned",
            "expires_at",
            "source_message_ids",
        }
        if not editable.intersection(payload):
            raise AppError(ErrorCode.VALIDATION_ERROR, "没有可更新的记忆字段。", status_code=400)
        async with self.database.session() as session:
            record = await session.get(Memory, memory_id)
            if record is None:
                raise AppError(ErrorCode.NOT_FOUND, "记忆不存在或已被删除。", status_code=404)
            if "content" in payload:
                record.content = validate_memory_content(str(payload.get("content") or ""))
            if "memory_type" in payload:
                record.memory_type = validate_memory_type(payload.get("memory_type"))
            if "sensitivity" in payload:
                record.sensitivity = validate_sensitivity(payload.get("sensitivity"))
            if "confidence" in payload:
                record.confidence = validate_confidence(payload.get("confidence"), record.confidence)
            if "is_pinned" in payload:
                record.is_pinned = bool(payload.get("is_pinned"))
            if "expires_at" in payload:
                record.expires_at = _parse_expiry(payload.get("expires_at"))
            if "source_message_ids" in payload:
                record.source_message_ids_json = _source_ids(payload.get("source_message_ids"))
            await session.commit()
            await session.refresh(record)
            return self.public(record)

    async def delete_memory(self, memory_id: str) -> bool:
        async with self.database.session() as session:
            record = await session.get(Memory, memory_id)
            if record is None:
                raise AppError(ErrorCode.NOT_FOUND, "记忆不存在或已被删除。", status_code=404)
            await session.delete(record)
            await session.commit()
        return True

    async def list_memories(
        self,
        *,
        account_id: str | None = None,
        group_id: str | None = None,
        member_id: str | None = None,
        memory_type: str | None = None,
        search: str | None = None,
        include_expired: bool = True,
        page: int = 1,
        page_size: int = 50,
    ) -> dict[str, Any]:
        conditions: list[Any] = []
        if account_id:
            conditions.append(Memory.account_id == account_id)
        if group_id:
            conditions.append(Memory.group_id == group_id)
        if member_id:
            conditions.append(Memory.member_id == member_id)
        if memory_type:
            if memory_type not in MEMORY_TYPES:
                raise AppError(ErrorCode.VALIDATION_ERROR, "记忆类型筛选值无效。", status_code=400)
            conditions.append(Memory.memory_type == memory_type)
        if search and search.strip():
            conditions.append(Memory.content.contains(search.strip()[:200]))
        if not include_expired:
            conditions.append(or_(Memory.expires_at.is_(None), Memory.expires_at > utcnow()))
        size = min(max(1, page_size), 200)
        async with self.database.session() as session:
            total = await session.scalar(select(func.count(Memory.id)).where(*conditions))
            records = list(
                (
                    await session.execute(
                        select(Memory)
                        .where(*conditions)
                        .order_by(Memory.is_pinned.desc(), Memory.created_at.desc())
                        .offset((page - 1) * size)
                        .limit(size)
                    )
                ).scalars()
            )
            items = [self.public(record) for record in records]
        return {
            "items": items,
            "total": int(total or 0),
            "page": page,
            "page_size": size,
        }

    @staticmethod
    def public(record: Memory) -> dict[str, Any]:
        expired = record.expires_at is not None and ensure_utc(record.expires_at) <= utcnow()
        return {
            "id": record.id,
            "account_id": record.account_id,
            "group_id": record.group_id,
            "member_id": record.member_id,
            "memory_type": record.memory_type,
            "content": record.content,
            "source_message_ids": list(record.source_message_ids_json or []),
            "confidence": record.confidence,
            "sensitivity": record.sensitivity,
            "is_pinned": record.is_pinned,
            "expires_at": iso_utc(record.expires_at),
            "expired": expired,
            "auto_injectable": record.sensitivity in AUTO_INJECT_SENSITIVITIES and not expired,
            "created_at": iso_utc(record.created_at),
            "updated_at": iso_utc(record.updated_at),
        }

    # ------------------------------------------------------------------ 检索
    async def retrieve_for_prompt(
        self,
        *,
        account_id: str,
        group: Group | None,
        sender_id: str,
        query_text: str,
    ) -> MemorySelection:
        """只返回当前群、当前发送者可见且适合自动注入的记忆。"""
        if group is None or not group.allow_memory:
            return MemorySelection(enabled=False)
        limit = max(1, min(int(self.settings.memory_max_items), 20))
        max_chars = max(200, min(int(self.settings.memory_max_chars), 8000))
        now = utcnow()
        async with self.database.session() as session:
            excluded = set(
                (
                    await session.execute(
                        select(Member.platform_user_id).where(
                            Member.account_id == account_id,
                            Member.excluded_from_memory.is_(True),
                        )
                    )
                ).scalars()
            )
            candidates = list(
                (
                    await session.execute(
                        select(Memory)
                        .where(
                            Memory.account_id == account_id,
                            Memory.group_id == group.id,
                            Memory.sensitivity.in_(AUTO_INJECT_SENSITIVITIES),
                            or_(Memory.expires_at.is_(None), Memory.expires_at > now),
                            or_(Memory.member_id.is_(None), Memory.member_id == sender_id),
                        )
                        .order_by(Memory.is_pinned.desc(), Memory.confidence.desc(), Memory.created_at.desc())
                        .limit(500)
                    )
                ).scalars()
            )

        query_tokens = _tokens(query_text)
        scored: list[tuple[int, float, datetime, Memory]] = []
        for record in candidates:
            if record.member_id is not None and record.member_id in excluded:
                continue
            relevance = _relevance(query_tokens, record.content)
            if not record.is_pinned and relevance <= 0:
                continue
            scored.append((relevance, float(record.confidence), ensure_utc(record.created_at), record))
        scored.sort(
            key=lambda item: (
                0 if item[3].is_pinned else 1,
                -item[0],
                -item[1],
                -item[2].timestamp(),
            )
        )

        selected: list[MemoryItem] = []
        used_chars = 0
        omitted = 0
        for _relevance_score, _confidence, created_at, record in scored:
            content = _single_line(record.content)
            cost = len(content) + 80
            if len(selected) >= limit or used_chars + cost > max_chars:
                omitted += 1
                continue
            selected.append(
                MemoryItem(
                    id=record.id,
                    content=content,
                    memory_type=record.memory_type,
                    confidence=float(record.confidence),
                    is_pinned=bool(record.is_pinned),
                    created_at=created_at,
                )
            )
            used_chars += cost
        return MemorySelection(enabled=True, items=selected, omitted=omitted)

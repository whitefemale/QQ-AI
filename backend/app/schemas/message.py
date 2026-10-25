"""统一消息模型：平台专有事件只存在于适配器内部。"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

SegmentType = Literal["text", "mention", "reply", "image", "audio", "video", "file", "sticker", "unknown"]
ConversationType = Literal["group", "private"]


class MessageSegment(BaseModel):
    type: SegmentType
    text: str | None = None
    media_ref: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _validate_payload(self) -> MessageSegment:
        if self.metadata and len(str(self.metadata)) > 4096:
            raise ValueError("消息段 metadata 超出大小限制")
        return self


class CanonicalMessage(BaseModel):
    platform: str = "qq"
    account_id: str
    message_id: str
    conversation_id: str
    conversation_type: ConversationType = "group"
    sender_id: str
    sender_name: str | None = None
    segments: list[MessageSegment] = Field(default_factory=list)
    reply_to_message_id: str | None = None
    mentions: list[str] = Field(default_factory=list)
    timestamp: datetime = Field(default_factory=datetime.now)
    is_self_message: bool = False
    source_adapter: str
    raw_event_ref: str | None = None
    event_id: str | None = None

    @field_validator("timestamp")
    @classmethod
    def _ensure_tz(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)

    @property
    def text(self) -> str:
        parts: list[str] = []
        for segment in self.segments:
            if segment.type == "text" and segment.text:
                parts.append(segment.text)
            elif segment.type == "mention":
                parts.append(f"@{segment.text or segment.metadata.get('qq', '')}")
        return "".join(parts).strip()

    @property
    def media_segments(self) -> list[MessageSegment]:
        return [s for s in self.segments if s.type in {"image", "audio", "video", "file", "sticker"}]

    @property
    def mention_all(self) -> bool:
        return any(s.type == "mention" and s.metadata.get("all") for s in self.segments)

    def mentions_user(self, user_id: str | None) -> bool:
        if not user_id:
            return False
        if user_id in self.mentions:
            return True
        return any(
            s.type == "mention" and (s.metadata.get("qq") == user_id or s.text == user_id) for s in self.segments
        )


class SegmentsPayload(BaseModel):
    segments: list[MessageSegment] = Field(default_factory=list)


class SentMessage(BaseModel):
    platform_message_id: str
    conversation_id: str
    status: str = "sent"
    raw: dict[str, Any] = Field(default_factory=dict)

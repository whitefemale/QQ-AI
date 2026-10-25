"""会话上下文构建：严格按会话隔离，群消息属于不可信数据。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from app.core.config import Settings
from app.models.message import Message
from app.schemas.message import CanonicalMessage
from app.services.message_service import MessageService

_SEGMENT_LABELS = {
    "image": "[图片]",
    "audio": "[语音]",
    "video": "[视频]",
    "file": "[文件]",
    "sticker": "[表情]",
    "unknown": "[未知消息]",
}


@dataclass
class ContextBundle:
    messages: list[dict[str, str]] = field(default_factory=list)
    reply_target: str | None = None
    used_messages: int = 0
    truncated: bool = False


def _describe_segments(record: Message) -> str:
    parts: list[str] = []
    for segment in record.segments_json or []:
        if not isinstance(segment, dict):
            continue
        segment_type = segment.get("type")
        if segment_type == "text":
            text = segment.get("text")
            if text:
                parts.append(str(text))
        elif segment_type == "mention":
            parts.append(f"@{segment.get('text') or ''}")
        elif segment_type in _SEGMENT_LABELS:
            parts.append(_SEGMENT_LABELS[segment_type])
    return "".join(parts).strip()


def _speaker_label(record: Message) -> str:
    name = record.sender_name or record.sender_id
    return f"成员 {name}"


class ContextBuilder:
    def __init__(self, message_service: MessageService, settings: Settings) -> None:
        self.message_service = message_service
        self.settings = settings

    async def build(
        self,
        message: CanonicalMessage,
        *,
        conversation_type: str,
        media_notes: list[str] | None = None,
    ) -> ContextBundle:
        limit = max(1, min(self.settings.context_message_limit, 100))
        records = await self.message_service.recent_for_conversation(
            message.conversation_id,
            limit=limit,
            before=message.timestamp,
        )
        bundle = ContextBundle()
        messages: list[dict[str, str]] = []
        total_chars = 0
        max_chars = 8000
        for record in records:
            if record.platform_message_id == message.message_id and record.direction == "inbound":
                continue
            content = _describe_segments(record) or record.content_text
            if not content:
                continue
            if record.direction == "outbound":
                role = "assistant"
                payload = content
            else:
                role = "user"
                prefix = _speaker_label(record) if conversation_type == "group" else "用户"
                payload = f"[不可信消息] {prefix}：{content}"
            if total_chars + len(payload) > max_chars:
                bundle.truncated = True
                continue
            messages.append({"role": role, "content": payload})
            total_chars += len(payload)

        current_parts = [message.text] if message.text else []
        for note in media_notes or []:
            current_parts.append(f"[媒体信息] {note}")
        current_text = "\n".join(part for part in current_parts if part).strip()
        if not current_text:
            current_text = "（对方发送了暂不支持解读的消息）"
        speaker = f"成员 {message.sender_name or message.sender_id}" if conversation_type == "group" else "用户"
        current_payload = f"[不可信消息] {speaker}：{current_text}"
        messages.append({"role": "user", "content": current_payload})
        bundle.messages = messages[-limit:]
        bundle.used_messages = len(bundle.messages)
        bundle.reply_target = await self.message_service.reply_target_text(
            message.account_id, message.reply_to_message_id
        )
        return bundle


def iso_now_label(moment: datetime, timezone_label: str) -> str:
    return f"{moment.isoformat()}（时区：{timezone_label}）"

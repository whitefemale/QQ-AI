"""把媒体段转换为诚实的上下文说明：没有真实 Provider 时绝不宣称识别。"""

from __future__ import annotations

import logging

from app.core.errors import AppError
from app.media.jobs import MediaJobService
from app.schemas.message import CanonicalMessage, MessageSegment

logger = logging.getLogger(__name__)

_TYPE_LABELS = {
    "image": "图片",
    "audio": "语音",
    "video": "视频",
    "file": "文件",
    "sticker": "表情",
}


def _unconfigured_note(media_type: str) -> str:
    label = _TYPE_LABELS.get(media_type, "媒体")
    if media_type in {"video", "file"}:
        return f"用户发送了{label}；当前版本不支持解析该类媒体。"
    return f"用户发送了{label}；当前未配置可用的识别能力，无法查看或转写其内容。"


async def build_media_notes(
    message: CanonicalMessage,
    *,
    media_jobs: MediaJobService | None,
    account_id: str,
    group_id: str | None,
) -> list[str]:
    notes: list[str] = []
    for segment in message.media_segments:
        notes.append(await _note_for_segment(segment, message, media_jobs, account_id, group_id))
    return notes


async def _note_for_segment(
    segment: MessageSegment,
    message: CanonicalMessage,
    media_jobs: MediaJobService | None,
    account_id: str,
    group_id: str | None,
) -> str:
    media_type = segment.type
    if not segment.media_ref:
        return _unconfigured_note(media_type)
    if media_jobs is None or media_type in {"video", "file"}:
        return _unconfigured_note(media_type)
    try:
        transcript = await media_jobs.process_segment(
            media_ref=segment.media_ref,
            media_type=media_type,
            account_id=account_id,
            group_id=group_id,
            source_message_id=message.message_id,
        )
    except AppError as exc:
        return f"用户发送了{_TYPE_LABELS.get(media_type, '媒体')}；处理失败：{exc.message}"
    except Exception as exc:  # 媒体处理失败不能阻断聊天
        logger.warning("媒体上下文处理失败", extra={"error": type(exc).__name__})
        return f"用户发送了{_TYPE_LABELS.get(media_type, '媒体')}；处理时发生异常，未能解读。"
    if transcript is None:
        return _unconfigured_note(media_type)
    kind_label = {"description": "图片描述", "ocr": "OCR 文本", "transcript": "语音转写"}.get(
        transcript.kind, "识别结果"
    )
    if transcript.is_mock:
        return (
            f"用户发送了{_TYPE_LABELS.get(media_type, '媒体')}。以下是 Mock 模拟的{kind_label}，"
            f"不是真实识别结果，绝不能当作实际媒体内容：{transcript.text}"
        )
    return f"用户发送了{_TYPE_LABELS.get(media_type, '媒体')}；{kind_label}：{transcript.text}"

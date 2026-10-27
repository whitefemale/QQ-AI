"""把媒体段转换为诚实的上下文说明：没有真实 Provider 时绝不宣称识别。

流水线只入队、不等待 Provider：媒体识别在后台 worker 中完成，避免拖住 QQ 事件消费。
"""

from __future__ import annotations

import logging

from app.core.errors import AppError
from app.media.jobs import MediaJobService
from app.models.media import MediaTranscript
from app.schemas.message import CanonicalMessage, MessageSegment

logger = logging.getLogger(__name__)

_TYPE_LABELS = {
    "image": "图片",
    "audio": "语音",
    "video": "视频",
    "file": "文件",
    "sticker": "表情",
}

_CAPABILITIES = {
    "image": "image.describe",
    "sticker": "image.describe",
    "audio": "audio.transcribe",
}


def _unconfigured_note(media_type: str) -> str:
    label = _TYPE_LABELS.get(media_type, "媒体")
    if media_type in {"video", "file"}:
        return f"用户发送了{label}；当前版本不支持解析该类媒体。"
    return f"用户发送了{label}；当前未配置可用的识别能力，无法查看或转写其内容。"


def _kind_label(kind: str) -> str:
    return {"description": "图片描述", "ocr": "OCR 文本", "transcript": "语音转写"}.get(kind, "识别结果")


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


def _transcript_note(media_type: str, transcript: MediaTranscript) -> str:
    label = _TYPE_LABELS.get(media_type, "媒体")
    kind = _kind_label(transcript.kind)
    if transcript.is_mock:
        return (
            f"用户发送了{label}。以下是 Mock 模拟的{kind}，不是真实识别结果，绝不能当作实际媒体内容：{transcript.text}"
        )
    return f"用户发送了{label}；{kind}：{transcript.text}"


async def _note_for_segment(
    segment: MessageSegment,
    message: CanonicalMessage,
    media_jobs: MediaJobService | None,
    account_id: str,
    group_id: str | None,
) -> str:
    media_type = segment.type
    capability = _CAPABILITIES.get(media_type)
    if not segment.media_ref or capability is None:
        return _unconfigured_note(media_type)
    if media_jobs is None:
        return _unconfigured_note(media_type)
    label = _TYPE_LABELS.get(media_type, "媒体")
    try:
        transcript = await media_jobs.find_transcript(segment.media_ref, capability)
        if transcript is not None:
            return _transcript_note(media_type, transcript)
        job = await media_jobs.enqueue_segment(
            media_ref=segment.media_ref,
            media_type=media_type,
            account_id=account_id,
            group_id=group_id,
            source_message_id=message.message_id,
            mime=str(segment.metadata.get("mime")) if segment.metadata.get("mime") else None,
        )
    except AppError as exc:
        return f"用户发送了{label}；无法创建后台识别任务：{exc.message}"
    except Exception as exc:  # 媒体任务创建失败不能阻断聊天
        logger.warning("媒体上下文入队失败", extra={"error": type(exc).__name__})
        return f"用户发送了{label}；创建后台识别任务时发生异常，当前无法解读其内容。"
    if job is None:
        return _unconfigured_note(media_type)
    if job.status == "failed":
        return f"用户发送了{label}；后台识别任务失败，当前无法解读其内容。"
    return f"用户发送了{label}；识别任务正在后台处理，本次回复暂时无法使用其内容。"

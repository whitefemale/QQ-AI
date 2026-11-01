"""设置页与诊断页共用的本地数据计数，不包含任何内容字段。"""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select

from app.db.session import Database
from app.models.account import Account
from app.models.group import Group
from app.models.media import MediaAsset
from app.models.memory import Memory, MemoryCandidate
from app.models.message import Message
from app.models.persona import Persona
from app.models.provider import LLMProvider

PRIVACY_NOTES = [
    "消息仅来自用户自行接入的 QQ 账号与白名单群。",
    "Token 与 API Key 使用本地密钥加密存储，接口只返回掩码。",
    "备份只包含数据库，不包含媒体文件与加密密钥。",
    "长期记忆仅在显式开启的群内检索；只使用本群与当前发送者的普通敏感度记忆，不跨群。",
    "敏感记忆、已过期记忆、被排除成员的成员级记忆不会自动注入提示词。",
    "AI 记忆候选只用于人工审核，批准前不是正式记忆、不会注入提示词；已审核候选记录保留在本地供追溯。",
    "自动清理默认关闭；手动或开启后的清理只删除超过保留期限的本地数据，日志仅处理 app.log.* 轮转文件。",
]


async def privacy_counts(database: Database) -> dict[str, int]:
    async with database.session() as session:
        return {
            "accounts": int(await session.scalar(select(func.count(Account.id))) or 0),
            "groups": int(await session.scalar(select(func.count(Group.id))) or 0),
            "personas": int(await session.scalar(select(func.count(Persona.id))) or 0),
            "providers": int(await session.scalar(select(func.count(LLMProvider.id))) or 0),
            "messages": int(await session.scalar(select(func.count(Message.id))) or 0),
            "media_assets": int(await session.scalar(select(func.count(MediaAsset.id))) or 0),
            "memories": int(await session.scalar(select(func.count(Memory.id))) or 0),
            "memory_candidates": int(await session.scalar(select(func.count(MemoryCandidate.id))) or 0),
        }


async def privacy_overview(database: Database) -> dict[str, Any]:
    return {"counts": await privacy_counts(database), "notes": list(PRIVACY_NOTES)}


__all__ = ["PRIVACY_NOTES", "privacy_counts", "privacy_overview"]

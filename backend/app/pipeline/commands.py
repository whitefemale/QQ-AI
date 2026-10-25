"""群内安全命令。管理命令只接受群管理员 ID；高风险操作只能通过控制台完成。"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.core.config import Settings
from app.db.session import Database
from app.models.account import Account
from app.models.group import Group
from app.models.persona import Persona
from app.schemas.message import CanonicalMessage
from app.services.audit import write_audit

_COMMAND_PATTERN = re.compile(r"^/([a-zA-Z_]{1,32})(?:\s+(.*))?$", re.DOTALL)

KNOWN_COMMANDS = frozenset({"help", "status", "persona", "pause", "resume"})

HELP_TEXT = (
    "可用命令：/help 查看帮助；/status 查看本群运行状态；/persona 查看人格模式；/pause、/resume 由群管理员暂停或恢复。"
)


@dataclass
class ParsedCommand:
    name: str
    argument: str = ""


@dataclass
class CommandResult:
    handled: bool
    reply: str | None = None
    reason: str | None = None


def parse_command(text: str) -> ParsedCommand | None:
    stripped = text.strip()
    match = _COMMAND_PATTERN.match(stripped)
    if not match:
        return None
    return ParsedCommand(name=match.group(1).lower(), argument=(match.group(2) or "").strip())


def is_admin(group: Group, sender_id: str) -> bool:
    return sender_id in {str(item) for item in (group.admin_user_ids_json or [])}


async def execute_command(
    command: ParsedCommand,
    *,
    database: Database,
    settings: Settings,
    account: Account,
    group: Group,
    message: CanonicalMessage,
) -> CommandResult:
    name = command.name
    if name == "help":
        return CommandResult(True, HELP_TEXT, "command_help")
    if name == "status":
        async with database.session() as session:
            current_group = await session.get(Group, group.id)
            persona: Persona | None = None
            if current_group is not None and current_group.persona_id:
                persona = await session.get(Persona, current_group.persona_id)
        state = "已暂停" if current_group is not None and current_group.paused else "运行中"
        reply_mode = current_group.reply_mode if current_group is not None else group.reply_mode
        persona_label = persona.name if persona is not None else "未绑定人格"
        return CommandResult(
            True,
            f"状态：{state}；回复模式：{reply_mode}；人格：{persona_label}；仅在本群白名单内工作。",
            "command_status",
        )
    if name == "persona":
        async with database.session() as session:
            persona = await session.get(Persona, group.persona_id) if group.persona_id else None
        if persona is None:
            return CommandResult(True, "本群尚未绑定人格。请在控制台「群聊管理」中配置。", "command_persona")
        growth = "开启" if persona.growth_enabled else "关闭"
        return CommandResult(
            True,
            f"人格：{persona.name}；模式：{persona.mode}；自我成长：{growth}。详细特征请在控制台查看。",
            "command_persona",
        )
    if name in {"pause", "resume"}:
        if not is_admin(group, message.sender_id):
            return CommandResult(True, "只有本群管理员可以执行该命令。", "command_not_admin")
        paused = name == "pause"
        async with database.session() as session:
            current_group = await session.get(Group, group.id)
            if current_group is None:
                return CommandResult(False, None, "group_not_found")
            current_group.paused = paused
            await session.commit()
        await write_audit(
            database,
            action=f"group.{name}",
            target_type="group",
            target_id=group.id,
            details={"via": "qq_command", "sender_id": message.sender_id},
            actor=f"qq-admin:{message.sender_id}",
        )
        return CommandResult(
            True,
            "已暂停本群 AI 回复。" if paused else "已恢复本群 AI 回复。",
            f"command_{name}",
        )
    return CommandResult(False, None, "unknown_command")

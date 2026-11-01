"""快速硬规则与触发决策：任何硬检查失败都不得调用模型或发送消息。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Literal

from app.core.time import in_quiet_hours, start_of_day_utc, utcnow
from app.models.account import Account
from app.models.group import Group, Member
from app.models.message import Message
from app.schemas.message import CanonicalMessage
from app.services.message_service import MessageService

Action = Literal["reply", "observe", "intercept"]

DEFAULT_RATE_LIMITS = {
    "cooldown_seconds": 3,
    "max_replies_per_hour": 20,
    "max_replies_per_day": 100,
    "max_consecutive_replies": 3,
    "max_replies_per_member_per_hour": 10,
    "max_replies_per_member_per_day": 50,
}

SUPPORTED_REPLY_MODES = {"mention_only", "keyword", "always", "observe", "manual_confirm"}
REPEAT_LOOP_WINDOW_SECONDS = 60
REPEAT_LOOP_THRESHOLD = 4


@dataclass
class RateLimitSnapshot:
    last_reply_at: datetime | None = None
    replies_last_hour: int = 0
    replies_today: int = 0
    consecutive_replies: int = 0
    member_replies_last_hour: int = 0
    member_replies_today: int = 0

    @property
    def cooldown_remaining_seconds(self) -> float:
        return 0.0


@dataclass
class PolicyDecision:
    action: Action
    reason: str
    detail: str | None = None
    trigger_reason: str | None = None
    rate_limits: dict[str, float] = field(default_factory=dict)

    @property
    def should_reply(self) -> bool:
        return self.action == "reply"

    @property
    def intercepted(self) -> bool:
        return self.action in {"observe", "intercept"}


@dataclass
class PolicyInput:
    message: CanonicalMessage
    account: Account
    group: Group | None
    member: Member | None
    global_paused: bool
    self_platform_user_id: str | None
    reply_to_self: bool
    rate: RateLimitSnapshot
    now: datetime


class PolicyEngine:
    """无数据库依赖的策略判断；连续回复计数保存在进程内。"""

    def __init__(self) -> None:
        self._last_sender: dict[str, str] = {}
        self._consecutive: dict[str, int] = {}
        self._recent_texts: dict[tuple[str, str, str], list[tuple[datetime, str, str]]] = {}

    def _sync_sender(self, conversation_id: str, sender_id: str) -> None:
        previous = self._last_sender.get(conversation_id)
        if previous != sender_id:
            self._last_sender[conversation_id] = sender_id
            self._consecutive[conversation_id] = 0

    def record_reply(self, conversation_id: str) -> None:
        self._consecutive[conversation_id] = self._consecutive.get(conversation_id, 0) + 1

    def reset(self, conversation_id: str | None = None) -> None:
        if conversation_id is None:
            self._last_sender.clear()
            self._consecutive.clear()
            self._recent_texts.clear()
            return
        self._last_sender.pop(conversation_id, None)
        self._consecutive.pop(conversation_id, None)
        for key in [key for key in self._recent_texts if key[1] == conversation_id]:
            self._recent_texts.pop(key, None)

    def hard_block(self, data: PolicyInput) -> PolicyDecision | None:
        message = data.message
        account = data.account
        group = data.group
        now = data.now

        if message.is_self_message:
            return PolicyDecision("intercept", "self_message", "忽略自身消息，避免自问自答循环。")
        if not account.enabled:
            return PolicyDecision("intercept", "account_disabled", "账号已停用。")
        if data.global_paused:
            return PolicyDecision("intercept", "global_paused", "全局紧急暂停生效中。")
        if message_is_empty(message):
            return PolicyDecision("intercept", "invalid_message", "消息没有文本或媒体内容，已忽略。")
        repeat = self._check_repeat_loop(data)
        if repeat is not None:
            return repeat

        if message.conversation_type == "group":
            if group is None:
                return PolicyDecision(
                    "intercept",
                    "group_not_whitelisted",
                    "该群不在白名单内，或尚未在控制台登记。",
                )
            if not group.enabled:
                return PolicyDecision("intercept", "group_disabled", "该群的 AI 群友功能已关闭。")
            if group.paused:
                return PolicyDecision("intercept", "group_paused", "该群已暂停回复。")
        elif not account.allow_private:
            return PolicyDecision(
                "intercept",
                "private_disabled",
                "私聊回复未开启。如确需开启，请在账号设置中显式允许。",
            )

        if group is not None and in_quiet_hours(now, _quiet_with_timezone(group)):
            return PolicyDecision("intercept", "quiet_hours", "当前处于群安静时段。")

        if data.member is not None and data.member.muted_until is not None:
            if data.member.muted_until > now:
                return PolicyDecision("intercept", "member_muted", "该成员已被暂时静默。")
        return None

    def evaluate(self, data: PolicyInput) -> PolicyDecision:
        message = data.message
        group = data.group
        blocked = self.hard_block(data)
        if blocked is not None:
            return blocked

        self._sync_sender(message.conversation_id, message.sender_id)
        trigger = self._match_trigger(data)
        if trigger is None:
            reason = "observe_mode" if group is not None and group.reply_mode == "observe" else "no_trigger"
            return PolicyDecision("observe", reason, "消息未直接触发 AI 回复，仅记录观察。")

        decision_reason, trigger_reason = trigger
        limits = rate_limits(group)
        if group is not None:
            blocked = check_rate_limits(data.rate, limits, data.now)
            if blocked is not None:
                return blocked
        return PolicyDecision(
            "reply",
            decision_reason,
            trigger_reason=trigger_reason,
            rate_limits=limits,
        )

    def _match_trigger(self, data: PolicyInput) -> tuple[str, str] | None:
        message = data.message
        group = data.group
        if message.conversation_type == "private":
            if not message.text and not message.media_segments:
                return None
            return "private_message", "private"
        if group is None:
            return None
        mode = group.reply_mode
        if mode not in SUPPORTED_REPLY_MODES:
            return None
        if mode == "observe":
            return None
        # manual_confirm 与 mention_only 使用同一触发条件；差别只在生成后的入队状态。

        mentioned = message.mentions_user(data.self_platform_user_id) and not message.mention_all
        if mentioned:
            return "mentioned", "mention"
        if data.reply_to_self:
            return "reply_to_self", "reply_self"
        if not message.text and not message.media_segments:
            return None
        if mode == "always":
            return "always_mode", "always"
        if mode == "keyword":
            lowered = message.text.casefold()
            for keyword in group.keywords_json or []:
                if keyword and str(keyword).casefold() in lowered:
                    return "keyword_matched", "keyword"
        return None

    def _check_repeat_loop(self, data: PolicyInput) -> PolicyDecision | None:
        """进程内启发式：同一会话同一发送者 60 秒内重复完全相同文本。"""
        message = data.message
        text = str(message.text or "").strip()
        if not text:
            return None
        key = (data.account.id, message.conversation_id, message.sender_id)
        cutoff = data.now - timedelta(seconds=REPEAT_LOOP_WINDOW_SECONDS)
        # hard_block 可能对同一条消息调用多次（命令判断 + 主判断）；按消息 ID 去重，
        # 否则重复登记会把 2 条旧消息误算成 4 条并触发回环拦截。
        unique: dict[str, tuple[datetime, str, str]] = {}
        for item in self._recent_texts.get(key, []):
            if item[0] >= cutoff:
                unique[item[2]] = item
        entries = [item for item in unique.values() if item[2] != message.message_id]
        repeat_count = sum(1 for _ts, item_text, _mid in entries if item_text == text) + 1
        if message.message_id not in unique:
            unique[message.message_id] = (data.now, text, message.message_id)
        self._recent_texts[key] = list(unique.values())[-20:]
        if repeat_count >= REPEAT_LOOP_THRESHOLD:
            return PolicyDecision(
                "intercept",
                "repeat_loop",
                "检测到短时间内完全相同的重复消息，已停止回复以避免刷屏或回环。",
            )
        return None

    def current_consecutive(self, conversation_id: str) -> int:
        return self._consecutive.get(conversation_id, 0)


def check_rate_limits(rate: RateLimitSnapshot, limits: dict[str, float], now: datetime) -> PolicyDecision | None:
    """流水线与人工批准共用的纯限频判定。"""
    cooldown = float(limits["cooldown_seconds"])
    if cooldown > 0 and rate.last_reply_at is not None:
        elapsed = (now - rate.last_reply_at).total_seconds()
        if elapsed < cooldown:
            remaining = round(cooldown - elapsed, 1)
            return PolicyDecision(
                "intercept",
                "cooldown",
                f"冷却中，还需等待约 {remaining} 秒。",
            )
    hourly = int(limits["max_replies_per_hour"])
    if hourly > 0 and rate.replies_last_hour >= hourly:
        return PolicyDecision("intercept", "hourly_limit", f"已达到每小时最多 {hourly} 条回复的限制。")
    daily = int(limits["max_replies_per_day"])
    if daily > 0 and rate.replies_today >= daily:
        return PolicyDecision("intercept", "daily_limit", f"已达到每日最多 {daily} 条回复的限制。")
    consecutive = int(limits["max_consecutive_replies"])
    if consecutive > 0 and rate.consecutive_replies >= consecutive:
        return PolicyDecision(
            "intercept",
            "consecutive_limit",
            f"同一成员连续触发已达 {consecutive} 次，等待其他成员参与后再回复。",
        )
    member_hourly = int(limits["max_replies_per_member_per_hour"])
    if member_hourly > 0 and rate.member_replies_last_hour >= member_hourly:
        return PolicyDecision(
            "intercept",
            "member_hourly_limit",
            f"该成员每小时最多触发 {member_hourly} 条回复，请稍后再试。",
        )
    member_daily = int(limits["max_replies_per_member_per_day"])
    if member_daily > 0 and rate.member_replies_today >= member_daily:
        return PolicyDecision(
            "intercept",
            "member_daily_limit",
            f"该成员今日最多触发 {member_daily} 条回复，请明天再试。",
        )
    return None


def _quiet_with_timezone(group: Group) -> dict:
    quiet = dict(group.quiet_hours_json or {})
    if quiet and not quiet.get("timezone"):
        quiet["timezone"] = group.timezone
    return quiet


def rate_limits(group: Group | None) -> dict[str, float]:
    limits: dict[str, float] = {key: float(value) for key, value in DEFAULT_RATE_LIMITS.items()}
    if group is None:
        return limits
    configured = group.rate_limit_json or {}
    for key, default in DEFAULT_RATE_LIMITS.items():
        value = configured.get(key, default)
        try:
            limits[key] = max(0.0, float(value))
        except (TypeError, ValueError):
            limits[key] = float(default)
    return limits


async def build_rate_snapshot(
    message_service: MessageService,
    message: CanonicalMessage,
    group: Group | None,
    policy: PolicyEngine,
    now: datetime | None = None,
) -> RateLimitSnapshot:
    now = now or utcnow()
    if group is None:
        return RateLimitSnapshot(consecutive_replies=policy.current_consecutive(message.conversation_id))
    last_hour = await message_service.outbound_stats(group.id, now - timedelta(hours=1))
    today = await message_service.outbound_stats(group.id, start_of_day_utc(now, group.timezone))
    member_hour = await message_service.outbox_stats_by_origin(
        group.account_id, group.id, message.sender_id, now - timedelta(hours=1)
    )
    member_today = await message_service.outbox_stats_by_origin(
        group.account_id, group.id, message.sender_id, start_of_day_utc(now, group.timezone)
    )
    last_reply_at: datetime | None = last_hour.get("last_at")
    return RateLimitSnapshot(
        last_reply_at=last_reply_at,
        replies_last_hour=int(last_hour.get("count") or 0),
        replies_today=int(today.get("count") or 0),
        consecutive_replies=policy.current_consecutive(message.conversation_id),
        member_replies_last_hour=int(member_hour.get("count") or 0),
        member_replies_today=int(member_today.get("count") or 0),
    )


def effective_self_id(account: Account, adapter_self_id: str | None) -> str | None:
    return account.self_platform_user_id or adapter_self_id


def message_is_empty(message: CanonicalMessage) -> bool:
    return not str(message.text or "").strip() and not message.media_segments


def quiet_hours_decision(group: Group | None, now: datetime) -> PolicyDecision | None:
    if group is not None and in_quiet_hours(now, _quiet_with_timezone(group)):
        return PolicyDecision("intercept", "quiet_hours", "当前处于群安静时段，已阻止发送。")
    return None


def effective_max_reply_chars(group: Group | None, default: int) -> int:
    return int(group.max_reply_chars) if group is not None and group.max_reply_chars else int(default)


def effective_context_limit(group: Group | None, default: int) -> int:
    return int(group.context_message_limit) if group is not None and group.context_message_limit else int(default)


def get_message_row_status(message: Message | None) -> str | None:
    return message.processing_status if message is not None else None

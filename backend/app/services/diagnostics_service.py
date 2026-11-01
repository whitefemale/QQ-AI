"""只读诊断摘要：显式 allowlist，绝不透传账号、群、消息或路径。

本服务不读取日志正文、不触发网络/模型/连接器进程，也不写审计。
"""

from __future__ import annotations

import asyncio
from collections import Counter
from typing import Any

from sqlalchemy import func, select, text

from app.core.time import iso_utc, utcnow
from app.db.session import Database
from app.models.account import Account, AdapterInstance
from app.models.governance import AuditLog
from app.models.group import Group
from app.models.message import Message, OutboxMessage
from app.models.provider import LLMProvider
from app.services.privacy_service import privacy_counts
from app.services.provider_service import REMOTE_LLM_TYPES
from app.services.settings_store import get_global_pause
from app.services.system_evidence import latest_connection_test, live_instance_facts

EXCLUDED_FIELDS = [
    "Token / API Key / Authorization / Cookie",
    "QQ 号 / 昵称 / 头像 / 登录身份",
    "群号 / 群名 / 群成员",
    "消息正文 / 媒体内容 / 回复预览 / 提示词",
    "连接器或配置路径 / PID / 端口 / WebSocket 与 HTTP 端点",
    "系统用户名 / 用户目录 / 数据目录 / 日志路径 / 备份文件名",
    "模型 Base URL / 模型 ID / Provider 名称 / 密钥掩码",
    "审计 details / 事件 payload / 原始异常 / 日志行 / IP / 上游 request ID",
]

_EXCLUDED_NOTE = (
    "本摘要不包含：Token、API Key、Authorization、Cookie；QQ 号、昵称与登录身份；"
    "群号、群名与群成员；消息正文、媒体内容、回复预览与提示词；连接器/配置路径、"
    "PID、端口与网络端点；系统用户名、目录与日志/备份路径；Base URL、模型 ID、"
    "Provider 名称与密钥掩码；审计 details、事件 payload、原始异常、日志行、IP 与上游 request ID。"
)


def _provider_config_complete(provider: LLMProvider) -> bool:
    if not provider.enabled or provider.provider_type not in REMOTE_LLM_TYPES:
        return False
    if not provider.model or not provider.api_key_encrypted:
        return False
    if provider.provider_type == "openai_compatible" and not provider.base_url:
        return False
    return True


def _provider_test_state(provider: LLMProvider) -> str:
    record = provider.last_test_json if isinstance(provider.last_test_json, dict) else None
    if not record:
        return "never"
    if record.get("outcome") == "success" and record.get("ok") is True:
        return "passed"
    if record.get("outcome") == "failure":
        return "failed"
    return "never"


def _resolve_provider(group: Group, providers: list[LLMProvider], ordered: list[LLMProvider]) -> LLMProvider | None:
    if group.llm_provider_id:
        return next((item for item in providers if item.id == group.llm_provider_id and item.enabled), None)
    return ordered[0] if ordered else None


class DiagnosticsService:
    def __init__(
        self,
        *,
        database: Database,
        adapter_manager: Any,
        connector_manager: Any,
        settings: Any,
        events: Any,
        cipher: Any,
    ) -> None:
        self.database = database
        self.adapter_manager = adapter_manager
        self.connector_manager = connector_manager
        self.settings = settings
        self.events = events
        self.cipher = cipher

    async def build(self) -> dict[str, Any]:
        now = utcnow()
        try:
            async with self.database.session() as session:
                await session.execute(text("SELECT 1"))
            database_ok = True
        except Exception:
            database_ok = False

        try:
            pause = await get_global_pause(self.database)
        except Exception:
            pause = {"paused": False, "updated_at": None}
        try:
            installations = await self.connector_manager.list_installations(rescan=False)
        except Exception:
            installations = []

        counts = {
            "accounts": 0,
            "adapter_instances": 0,
            "groups": 0,
            "personas": 0,
            "providers": 0,
            "messages": 0,
            "memories": 0,
            "memory_candidates": 0,
            "media_assets": 0,
            "outbox_messages": 0,
        }
        accounts: list[Account] = []
        providers: list[LLMProvider] = []
        groups: list[Group] = []
        message_stats = {
            "received": 0,
            "observed": 0,
            "replied": 0,
            "sent": 0,
            "outbox_pending": 0,
            "outbox_failed": 0,
        }
        recent_actions: list[tuple[str, int]] = []
        if database_ok:
            try:
                counts.update(await privacy_counts(self.database))
                async with self.database.session() as session:
                    counts["adapter_instances"] = int(await session.scalar(select(func.count(AdapterInstance.id))) or 0)
                    counts["outbox_messages"] = int(await session.scalar(select(func.count(OutboxMessage.id))) or 0)
                    accounts = list((await session.execute(select(Account).order_by(Account.created_at))).scalars())
                    providers = list((await session.execute(select(LLMProvider))).scalars())
                    groups = list((await session.execute(select(Group))).scalars())
                    message_stats = {
                        "received": int(
                            await session.scalar(select(func.count(Message.id)).where(Message.direction == "inbound"))
                            or 0
                        ),
                        "observed": int(
                            await session.scalar(
                                select(func.count(Message.id)).where(Message.processing_status == "observed")
                            )
                            or 0
                        ),
                        "replied": int(
                            await session.scalar(
                                select(func.count(Message.id)).where(Message.processing_status == "replied")
                            )
                            or 0
                        ),
                        "sent": int(
                            await session.scalar(select(func.count(Message.id)).where(Message.direction == "outbound"))
                            or 0
                        ),
                        "outbox_pending": int(
                            await session.scalar(
                                select(func.count(OutboxMessage.id)).where(
                                    OutboxMessage.status.in_(("pending", "sending", "pending_approval"))
                                )
                            )
                            or 0
                        ),
                        "outbox_failed": int(
                            await session.scalar(
                                select(func.count(OutboxMessage.id)).where(OutboxMessage.status == "failed")
                            )
                            or 0
                        ),
                    }
                    action_rows = list(
                        (
                            await session.execute(
                                select(AuditLog.action)
                                .order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
                                .limit(200)
                            )
                        ).scalars()
                    )
                    recent_actions = [
                        (action, count)
                        for action, count in Counter(str(item)[:128] for item in action_rows).most_common()
                    ]
            except Exception:
                database_ok = False

        instances: list[tuple[Account, AdapterInstance]] = [
            (account, instance) for account in accounts for instance in account.instances
        ]
        live_facts: dict[str, dict[str, Any] | None] = {}
        if instances:
            results = await asyncio.gather(
                *(live_instance_facts(self.adapter_manager, instance.id) for _, instance in instances)
            )
            live_facts = {instance.id: fact for (_, instance), fact in zip(instances, results, strict=True)}

        modes = {"mock": 0, "onebot11": 0, "other": 0}
        live_online_instances = 0
        connected_unverified_instances = 0
        identity_confirmed_instances = 0
        for _, instance in instances:
            if instance.connection_mode in modes:
                modes[instance.connection_mode] += 1
            else:
                modes["other"] += 1
            if instance.connection_mode != "onebot11":
                continue
            fact = live_facts.get(instance.id) or {}
            if fact.get("ok") is True and fact.get("status") == "online":
                live_online_instances += 1
            if fact.get("status") == "connected_unverified":
                connected_unverified_instances += 1
            if instance.identity_confirmed_at is not None:
                identity_confirmed_instances += 1

        connector_states = Counter(str((item.get("state") or {}).get("state") or "unknown") for item in installations)
        connector_identity_confirmed = sum(
            1
            for item in installations
            if isinstance(item.get("instance"), dict) and item["instance"].get("identity_confirmed_at")
        )
        real_traffic_verified = sum(1 for item in installations if item.get("real_traffic_verified") is True)

        real_providers = [provider for provider in providers if provider.provider_type in REMOTE_LLM_TYPES]
        provider_test_states = Counter(_provider_test_state(provider) for provider in real_providers)
        provider_counts = {
            "total": len(providers),
            "mock": sum(1 for provider in providers if provider.provider_type == "mock"),
            "real": len(real_providers),
            "real_config_complete": sum(1 for provider in real_providers if _provider_config_complete(provider)),
            "real_test_passed": provider_test_states["passed"],
            "real_test_failed": provider_test_states["failed"],
            "real_never_tested": provider_test_states["never"],
        }

        enabled_providers_ordered = sorted(
            (provider for provider in providers if provider.enabled),
            key=lambda provider: (not provider.is_default, provider.created_at),
        )
        provider_resolved = sum(
            1 for group in groups if _resolve_provider(group, providers, enabled_providers_ordered) is not None
        )
        group_counts = {
            "total": len(groups),
            "enabled": sum(1 for group in groups if group.enabled),
            "observe_only": sum(1 for group in groups if group.reply_mode == "observe"),
            "auto_reply_modes": sum(
                1 for group in groups if group.enabled and group.reply_mode in {"mention_only", "keyword", "always"}
            ),
            "paused": sum(1 for group in groups if group.paused),
            "provider_resolved": provider_resolved,
            "provider_unresolved": len(groups) - provider_resolved,
        }

        test_evidence: list[dict[str, Any]] = []
        for _, instance in instances:
            if instance.connection_mode != "onebot11":
                continue
            row = await latest_connection_test(self.database, instance, now=now)
            if row["found"]:
                test_evidence.append(row)
        latest_test = max(test_evidence, key=lambda item: item["tested_at"] or "", default=None)
        connection_test = {
            "last_outcome": None,
            "last_state": None,
            "last_source": None,
            "tested_at": None,
            "age_seconds": None,
            "freshness": "missing",
            "identity_verified": False,
            "action_path_verified": False,
            "group_list_verified": False,
            "real_inbound_verified": False,
            "real_outbound_verified": False,
            "message_send_attempted": False,
        }
        if latest_test:
            connection_test.update(
                {
                    "last_outcome": "success" if latest_test["ok"] else "failure",
                    "last_state": latest_test["state"],
                    "last_source": latest_test["source"],
                    "tested_at": latest_test["tested_at"],
                    "age_seconds": latest_test["age_seconds"],
                    "freshness": latest_test["freshness"],
                    "identity_verified": latest_test["identity_verified"],
                    "action_path_verified": latest_test["action_path_verified"],
                    "group_list_verified": latest_test["group_list_verified"],
                    "real_inbound_verified": latest_test["real_inbound_verified"],
                    "real_outbound_verified": latest_test["real_outbound_verified"],
                    "message_send_attempted": False,
                }
            )

        data: dict[str, Any] = {
            "schema_version": "diagnostics.v1",
            "generated_at": iso_utc(now),
            "excluded": list(EXCLUDED_FIELDS),
            "app": {
                "version": str(self.settings.app_version),
                "env": str(self.settings.app_env),
            },
            "readiness": {
                "database": database_ok,
                "credential_key_configured": bool(self.cipher.available),
                "global_paused": bool(pause.get("paused")),
                "global_pause_updated_at": pause.get("updated_at"),
                "event_stream_subscribers": int(self.events.subscriber_count),
            },
            "counts": counts,
            "accounts": {
                "modes": modes,
                "live_online_instances": live_online_instances,
                "identity_confirmed_instances": identity_confirmed_instances,
                "connected_unverified_instances": connected_unverified_instances,
            },
            "connectors": {
                "installation_count": len(installations),
                "states": [{"state": state, "count": count} for state, count in sorted(connector_states.items())],
                "identity_confirmed": connector_identity_confirmed,
                "real_traffic_verified": real_traffic_verified,
                "real_qq_verified": False,
            },
            "providers": provider_counts,
            "groups": group_counts,
            "messages": message_stats,
            "connection_test": connection_test,
            "recent_audit_actions": [{"action": action, "count": count} for action, count in recent_actions],
        }
        data["text"] = self._build_text(data)
        return data

    @staticmethod
    def _build_text(data: dict[str, Any]) -> str:
        counts = data["counts"]
        readiness = data["readiness"]
        accounts = data["accounts"]
        connectors = data["connectors"]
        providers = data["providers"]
        groups = data["groups"]
        messages = data["messages"]
        test = data["connection_test"]
        test_line = (
            f"结果={test['last_outcome'] or '无证据'}，状态={test['last_state'] or '无'}，"
            f"来源={test['last_source'] or '无'}，新鲜度={test['freshness']}，"
            f"身份={test['identity_verified']}，动作={test['action_path_verified']}，"
            f"入站={test['real_inbound_verified']}，出站={test['real_outbound_verified']}，"
            f"测试时间={test['tested_at'] or '无'}"
        )
        audit_line = "；".join(f"{item['action']}×{item['count']}" for item in data["recent_audit_actions"]) or "无"
        lines = [
            "AI 群友诊断摘要（后端生成，已脱敏）",
            f"生成时间：{data['generated_at']}",
            f"应用版本：{data['app']['version']}（{data['app']['env']}）",
            (
                f"运行环境：数据库={'可用' if readiness['database'] else '不可用'}，"
                f"凭证密钥={'已配置' if readiness['credential_key_configured'] else '缺失'}，"
                f"全局暂停={readiness['global_paused']}，"
                f"事件订阅数={readiness['event_stream_subscribers']}"
            ),
            (
                f"数据计数：账号 {counts['accounts']}，实例 {counts['adapter_instances']}，"
                f"群 {counts['groups']}，人格 {counts['personas']}，Provider {counts['providers']}，"
                f"消息 {counts['messages']}，媒体 {counts['media_assets']}，"
                f"记忆 {counts['memories']}，记忆候选 {counts['memory_candidates']}，"
                f"发送队列 {counts['outbox_messages']}"
            ),
            (
                f"账号实例：Mock {accounts['modes']['mock']}，OneBot 11 {accounts['modes']['onebot11']}，"
                f"其他 {accounts['modes']['other']}；真实实例实时在线 {accounts['live_online_instances']}，"
                f"待身份确认 {accounts['connected_unverified_instances']}，"
                f"已确认身份 {accounts['identity_confirmed_instances']}"
            ),
            (
                f"连接器：安装 {connectors['installation_count']}，"
                f"状态 {', '.join(f'{item["state"]}={item["count"]}' for item in connectors['states']) or '无'}；"
                f"已确认身份 {connectors['identity_confirmed']}，"
                f"真实收发证据 {connectors['real_traffic_verified']}；"
                f"真实 QQ 已验证={connectors['real_qq_verified']}"
            ),
            (
                f"模型 Provider：总数 {providers['total']}，Mock {providers['mock']}，真实 {providers['real']}；"
                f"配置完整 {providers['real_config_complete']}，"
                f"测试通过 {providers['real_test_passed']}，失败 {providers['real_test_failed']}，"
                f"从未测试 {providers['real_never_tested']}"
            ),
            (
                f"群聊：总数 {groups['total']}，启用 {groups['enabled']}，观察 {groups['observe_only']}，"
                f"自动回复模式 {groups['auto_reply_modes']}，暂停 {groups['paused']}，"
                f"Provider 可解析 {groups['provider_resolved']}，不可解析 {groups['provider_unresolved']}"
            ),
            (
                f"消息：入站 {messages['received']}，观察 {messages['observed']}，已回复 {messages['replied']}，"
                f"出站 {messages['sent']}；发送队列待处理 {messages['outbox_pending']}，"
                f"失败 {messages['outbox_failed']}"
            ),
            f"最近连接测试：{test_line}（诊断从不发送消息）",
            f"最近 200 条审计动作：{audit_line}",
            _EXCLUDED_NOTE,
            "完整日志只保存在本机；桌面版可在诊断与日志页打开日志目录，分享前请自行检查。",
        ]
        return "\n".join(lines)


__all__ = ["DiagnosticsService", "EXCLUDED_FIELDS"]

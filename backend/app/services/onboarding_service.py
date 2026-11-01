"""只读接入向导：把分散的配置与证据聚合成可执行的八步状态。

这里的所有事实都来自数据库、内存适配器健康状态与既有审计证据；
本服务绝不触发模型调用、QQ 连接、下载、安装器或连接器扫描。
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any

from sqlalchemy import select, text

from app.core.security import CredentialCipher
from app.core.time import ensure_utc, iso_utc, utcnow
from app.db.session import Database
from app.models.account import Account, AdapterInstance
from app.models.group import Group
from app.models.message import Message
from app.models.provider import LLMProvider
from app.services.provider_service import REMOTE_LLM_TYPES
from app.services.settings_store import get_global_pause
from app.services.system_evidence import (
    freshness_for,
    latest_connection_test,
    live_instance_facts,
)

STEP_ORDER: tuple[tuple[str, str], ...] = (
    ("backend", "运行环境"),
    ("connector", "连接器准备"),
    ("qq_login", "QQ 登录"),
    ("connection_test", "连接测试"),
    ("model", "模型配置"),
    ("groups", "选择群聊"),
    ("observe", "观察消息"),
    ("enable", "开启回复"),
)

_STEP_ROUTES = {
    "backend": "/diagnostics",
    "connector": "/connectors",
    "qq_login": "/accounts",
    "connection_test": "/accounts",
    "model": "/providers",
    "groups": "/groups",
    "observe": "/groups",
    "enable": "/groups",
}

_READY_INSTALLATION_STATES = {
    "traffic_verified",
    "connected_traffic_unverified",
    "waiting_login",
    "logged_in_not_connected",
    "installed_not_started",
    "starting",
    "running_unmanaged",
    "external_readonly",
    "installer_ready",
    "installer_running",
}

_REAL_PROVIDER_TYPES = REMOTE_LLM_TYPES


def _step(
    key: str,
    *,
    state: str,
    summary: str,
    next_step: str | None = None,
    freshness: str = "not_applicable",
    evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    title = dict(STEP_ORDER)[key]
    return {
        "key": key,
        "order": [item[0] for item in STEP_ORDER].index(key) + 1,
        "title": title,
        "state": state,
        "summary": summary,
        "next_step": next_step,
        "route": _STEP_ROUTES[key],
        "freshness": freshness,
        "evidence": evidence or {},
    }


def _provider_config_complete(provider: LLMProvider) -> bool:
    if provider.provider_type == "mock":
        return True
    if not provider.enabled or not provider.model or not provider.api_key_encrypted:
        return False
    if provider.provider_type == "openai_compatible" and not provider.base_url:
        return False
    return provider.provider_type in _REAL_PROVIDER_TYPES


def _parse_iso(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return ensure_utc(datetime.fromisoformat(value.strip().replace("Z", "+00:00")))
    except ValueError:
        return None


def _provider_health(provider: LLMProvider, now: datetime) -> dict[str, Any]:
    """只读取测试结果、时间与延迟，不读取消息、预览或模型标识。"""
    record = provider.last_test_json if isinstance(provider.last_test_json, dict) else None
    tested_at = _parse_iso(record.get("tested_at")) if record else None
    fresh = freshness_for(tested_at, now=now)
    outcome = record.get("outcome") if record else None
    ok = record.get("ok") is True if record else False
    is_mock = record.get("is_mock") is True if record else False
    latency = record.get("latency_ms") if record and isinstance(record.get("latency_ms"), int) else None
    success = bool(record and outcome == "success" and ok and not is_mock and fresh["state"] in {"fresh", "aging"})
    return {
        "outcome": outcome if isinstance(outcome, str) else None,
        "ok": ok,
        "is_mock": is_mock,
        "tested_at": iso_utc(tested_at),
        "age_seconds": fresh["age_seconds"],
        "freshness": fresh["state"],
        "latency_ms": latency,
        "success": success,
    }


class OnboardingService:
    def __init__(
        self,
        *,
        database: Database,
        cipher: CredentialCipher,
        adapter_manager: Any,
        connector_manager: Any,
    ) -> None:
        self.database = database
        self.cipher = cipher
        self.adapter_manager = adapter_manager
        self.connector_manager = connector_manager

    async def build(self) -> dict[str, Any]:
        now = utcnow()
        try:
            async with self.database.session() as session:
                await session.execute(text("SELECT 1"))
            database_ok = True
        except Exception:
            database_ok = False
        if not database_ok:
            return self._blocked_environment(now, "无法连接本地数据库。")

        try:
            pause = await get_global_pause(self.database)
        except Exception:
            pause = {"paused": False, "updated_at": None}
        try:
            installations = await self.connector_manager.list_installations(rescan=False)
        except Exception:
            installations = []

        async with self.database.session() as session:
            accounts = list((await session.execute(select(Account).order_by(Account.created_at))).scalars())
            providers = list((await session.execute(select(LLMProvider))).scalars())
            groups = list((await session.execute(select(Group))).scalars())
            observed_group_ids = set(
                (
                    await session.execute(
                        select(Message.group_id)
                        .where(Message.direction == "inbound", Message.group_id.is_not(None))
                        .distinct()
                    )
                ).scalars()
            )

        instances: list[tuple[Account, AdapterInstance]] = [
            (account, instance) for account in accounts for instance in account.instances
        ]
        live_facts: dict[str, dict[str, Any] | None] = {}
        if instances:
            results = await asyncio.gather(
                *(live_instance_facts(self.adapter_manager, instance.id) for _, instance in instances)
            )
            live_facts = {instance.id: fact for (_, instance), fact in zip(instances, results, strict=True)}

        accounts_by_id = {account.id: account for account in accounts}
        real_account_ids = {
            account.id
            for account in accounts
            if any(instance.connection_mode == "onebot11" and instance.enabled for instance in account.instances)
        }
        mock_account_ids = {
            account.id
            for account in accounts
            if any(instance.connection_mode == "mock" and instance.enabled for instance in account.instances)
        } - real_account_ids
        real_instances = [
            (account, instance) for account, instance in instances if instance.connection_mode == "onebot11"
        ]
        enabled_real_instances = [
            (account, instance) for account, instance in real_instances if instance.enabled and account.enabled
        ]
        live_real_instances = [
            (account, instance)
            for account, instance in enabled_real_instances
            if (live_facts.get(instance.id) or {}).get("ok") is True
            and (live_facts.get(instance.id) or {}).get("status") == "online"
        ]
        confirmed_live_instances = [
            (account, instance)
            for account, instance in live_real_instances
            if instance.identity_confirmed_at is not None
        ]
        mock_instances = [(account, instance) for account, instance in instances if instance.connection_mode == "mock"]

        provider_tests = {provider.id: _provider_health(provider, now) for provider in providers}
        ready_real_providers = {
            provider.id
            for provider in providers
            if provider.enabled
            and provider.provider_type in _REAL_PROVIDER_TYPES
            and _provider_config_complete(provider)
            and provider_tests[provider.id]["success"]
        }
        real_providers = [provider for provider in providers if provider.provider_type in _REAL_PROVIDER_TYPES]
        configured_real_providers = [provider for provider in real_providers if _provider_config_complete(provider)]
        mock_providers = [provider for provider in providers if provider.provider_type == "mock"]

        steps: list[dict[str, Any]] = []
        warnings: list[str] = []
        blockers: list[str] = []

        # 1. 运行环境
        if not self.cipher.available:
            backend_state = "blocked"
            backend_summary = "本地凭证密钥不可用，无法安全保存或读取 Token 与 API Key。"
            backend_next = "检查根目录 .env 的 CREDENTIAL_ENCRYPTION_KEY 后重启后端。"
            blockers.append("凭证加密密钥不可用；Token 与 API Key 无法读取。")
        else:
            backend_state = "done"
            backend_summary = "后端进程与本地数据库可用，凭证加密密钥已加载。"
            backend_next = None
        steps.append(
            _step(
                "backend",
                state=backend_state,
                summary=backend_summary,
                next_step=backend_next,
                evidence={
                    "database": True,
                    "credential_key_configured": self.cipher.available,
                    "global_paused": bool(pause.get("paused")),
                },
            )
        )

        # 2. 连接器准备
        real_installation_count = len(installations)
        shell_installed_count = sum(1 for item in installations if item.get("shell_installed") is True)
        ready_installation_count = sum(
            1
            for item in installations
            if item.get("shell_installed") is True
            and str((item.get("state") or {}).get("state") or "") in _READY_INSTALLATION_STATES
        )
        if real_instances or ready_installation_count:
            connector_state = "done"
            connector_summary = (
                f"已配置 {len(real_instances)} 个 OneBot 11 实例，检测到 {real_installation_count} 个连接器安装。"
            )
            connector_next = "安装或进程存在不等于已登录；请继续完成 QQ 登录与连接测试。"
        elif mock_instances or mock_providers:
            connector_state = "mock_only"
            connector_summary = "当前只有 Mock 连接器；不会连接真实 QQ。"
            connector_next = "需要真实 QQ 时，请准备 NapCat 等 OneBot 11 连接器并添加 OneBot 11 实例。"
            warnings.append("连接器步骤仅使用 Mock，不代表真实 QQ 已接入。")
        else:
            connector_state = "action_required"
            connector_summary = "尚未配置连接器，也没有检测到受管连接器安装。"
            connector_next = "在连接器页下载/导入 NapCat，或在 QQ 接入页添加 OneBot 11 实例。"
        steps.append(
            _step(
                "connector",
                state=connector_state,
                summary=connector_summary,
                next_step=connector_next,
                evidence={
                    "onebot_instances": len(real_instances),
                    "mock_instances": len(mock_instances),
                    "installations": real_installation_count,
                    "shell_installed": shell_installed_count,
                    "ready_installations": ready_installation_count,
                },
            )
        )

        # 3. QQ 登录
        if confirmed_live_instances:
            qq_state = "done"
            qq_summary = "已确认登录的真实 OneBot 11 实例当前在线。"
            qq_next = "QQ 登录与身份确认已就绪；真实群消息收发仍需独立验收。"
        elif real_instances:
            qq_state = "action_required"
            if live_real_instances:
                qq_summary = "真实连接器在线，但尚未确认当前登录的 QQ 身份。"
                qq_next = "在连接器完成登录后，于 QQ 接入页确认当前登录身份。"
            else:
                qq_summary = "已配置真实 OneBot 11 实例，但当前没有实时在线连接。"
                qq_next = "启动连接器并完成 QQ 登录，然后在 QQ 接入页连接实例。"
        elif mock_instances:
            qq_state = "mock_only"
            qq_summary = "只有 Mock 连接器在线；Mock 没有真实 QQ 登录身份。"
            qq_next = "真实接入需要 OneBot 11 实例与用户自行完成的 QQ 登录。"
            warnings.append("QQ 登录步骤仅使用 Mock，不代表真实账号已登录。")
        else:
            qq_state = "action_required"
            qq_summary = "没有可用的 QQ 接入实例。"
            qq_next = "先配置 OneBot 11 实例并连接。"
        steps.append(
            _step(
                "qq_login",
                state=qq_state,
                summary=qq_summary,
                next_step=qq_next,
                evidence={
                    "live_online_instances": len(live_real_instances),
                    "identity_confirmed_instances": len(confirmed_live_instances),
                },
            )
        )

        # 4. 连接测试：取最近一条可归属证据，失败覆盖更早成功。
        evidence_rows: list[dict[str, Any]] = []
        for _, instance in real_instances:
            row = await latest_connection_test(self.database, instance, now=now)
            if row["found"]:
                evidence_rows.append(row)
        latest_test = max(
            evidence_rows,
            key=lambda item: item["tested_at"] or "",
            default=None,
        )
        test_evidence: dict[str, Any] = {}
        if latest_test:
            test_evidence = {
                "tested_at": latest_test["tested_at"],
                "source": latest_test["source"],
                "ok": latest_test["ok"],
                "state": latest_test["state"],
                "age_seconds": latest_test["age_seconds"],
                "identity_verified": latest_test["identity_verified"],
                "action_path_verified": latest_test["action_path_verified"],
                "group_list_verified": latest_test["group_list_verified"],
                "real_inbound_verified": latest_test["real_inbound_verified"],
                "real_outbound_verified": latest_test["real_outbound_verified"],
            }
            test_freshness = latest_test["freshness"]
            if test_freshness == "stale":
                test_state = "not_verified"
                test_summary = "最近一次连接测试已超过 24 小时，不能作为当前证据。"
                test_next = "在 QQ 接入页重新运行连接诊断。"
            elif latest_test["ok"] and latest_test["state"] == "identity_verified":
                test_state = "done"
                test_summary = "最近一次连接测试已通过身份与动作通道检查。"
                test_next = "连接测试不等于真实群收发；请在受控群完成独立验收。"
            else:
                test_state = "action_required"
                test_summary = "最近一次连接测试未通过；旧的成功结果已被覆盖。"
                test_next = "查看诊断错误并重新测试。"
        elif real_instances:
            test_state = "not_verified"
            test_freshness = "missing"
            test_summary = "已配置真实实例，但还没有可归属的连接测试证据。"
            test_next = "在 QQ 接入页或连接器页运行一次连接诊断。"
        elif mock_instances:
            test_state = "mock_only"
            test_freshness = "not_applicable"
            test_summary = "Mock 测试只验证本地流程，不会验证真实 QQ 连接。"
            test_next = "真实接入需要一次非 Mock 的连接诊断。"
            warnings.append("连接测试步骤仅使用 Mock，不代表真实连接已通过。")
        else:
            test_state = "action_required"
            test_freshness = "missing"
            test_summary = "没有可测试的连接实例。"
            test_next = "先完成连接器与 QQ 登录步骤。"
        steps.append(
            _step(
                "connection_test",
                state=test_state,
                summary=test_summary,
                next_step=test_next,
                freshness=test_freshness,
                evidence=test_evidence,
            )
        )

        # 5. 模型：真实、配置完整，且 24 小时内有成功测试记录。
        readiness_providers = [provider for provider in real_providers if provider_tests[provider.id]["success"]]
        real_test_records = [
            provider_tests[provider.id] for provider in real_providers if provider_tests[provider.id]["tested_at"]
        ]
        latest_provider_test = max(real_test_records, key=lambda item: item["tested_at"] or "", default=None)
        if readiness_providers:
            model_state = "done"
            model_summary = "至少一个真实模型 Provider 配置完整，且测试成功仍在 24 小时内。"
            model_next = "测试成功不代表所有模型/网络环境长期可用；调用仍可能计费。"
            model_freshness = min(
                (provider_tests[provider.id]["freshness"] for provider in readiness_providers),
                key=lambda value: {"fresh": 0, "aging": 1}.get(value, 2),
            )
            model_evidence = {
                "tested_at": max(
                    (provider_tests[provider.id]["tested_at"] for provider in readiness_providers),
                    key=lambda value: value or "",
                ),
                "age_seconds": min(provider_tests[provider.id]["age_seconds"] for provider in readiness_providers),
                "latency_ms": min(
                    (provider_tests[provider.id]["latency_ms"] or 0 for provider in readiness_providers),
                    default=None,
                ),
            }
        elif configured_real_providers:
            model_state = (
                "not_verified"
                if not latest_provider_test or latest_provider_test["outcome"] != "failure"
                else "action_required"
            )
            model_summary = (
                "真实 Provider 已配置，但没有 24 小时内的成功测试记录。"
                if model_state == "not_verified"
                else "最近一次真实 Provider 测试失败。"
            )
            model_next = "在模型 API 页运行连通性测试；真实测试可能计费。"
            model_freshness = (latest_provider_test or {}).get("freshness", "missing")
            model_evidence = (
                {
                    "tested_at": latest_provider_test["tested_at"],
                    "age_seconds": latest_provider_test["age_seconds"],
                    "outcome": latest_provider_test["outcome"],
                }
                if latest_provider_test
                else {}
            )
        elif mock_providers:
            model_state = "mock_only"
            model_summary = "只有 Mock 模型；回复固定模板，不代表真实模型能力。"
            model_next = "需要真实回复时，请添加并测试非 Mock 的模型 Provider。"
            model_freshness = "not_applicable"
            model_evidence = {}
            warnings.append("模型配置步骤仅使用 Mock，不代表真实模型可用。")
        else:
            model_state = "action_required"
            model_summary = "尚未配置任何模型 Provider。"
            model_next = "在模型 API 页添加 Provider，并在确认计费风险后运行测试。"
            model_freshness = "missing"
            model_evidence = {}
        model_evidence = {
            **model_evidence,
            "real_providers": len(real_providers),
            "configured_real_providers": len(configured_real_providers),
            "tested_real_providers": len(readiness_providers),
        }
        steps.append(
            _step(
                "model",
                state=model_state,
                summary=model_summary,
                next_step=model_next,
                freshness=model_freshness,
                evidence=model_evidence,
            )
        )

        # 6. 群聊
        real_groups = [group for group in groups if group.account_id in real_account_ids]
        mock_groups = [group for group in groups if group.account_id in mock_account_ids]
        enabled_real_groups = [group for group in real_groups if group.enabled]
        if real_groups:
            groups_state = "done"
            groups_summary = f"已登记 {len(real_groups)} 个真实账号群聊，其中 {len(enabled_real_groups)} 个已启用。"
            groups_next = "确认群白名单与回复模式；回复模式变更需逐群显式保存。"
        elif mock_groups:
            groups_state = "mock_only"
            groups_summary = f"只有 {len(mock_groups)} 个 Mock 演示群。"
            groups_next = "真实接入需要在 QQ 接入页拉取或手动登记真实群。"
            warnings.append("群聊步骤仅包含 Mock 演示群，不代表真实群已登记。")
        else:
            groups_state = "action_required"
            groups_summary = "尚未登记任何群聊。"
            groups_next = "真实登录并确认身份后，在群聊管理页拉取或手动登记群。"
        steps.append(
            _step(
                "groups",
                state=groups_state,
                summary=groups_summary,
                next_step=groups_next,
                evidence={
                    "real_groups": len(real_groups),
                    "enabled_real_groups": len(enabled_real_groups),
                    "mock_groups": len(mock_groups),
                },
            )
        )

        # 7. 观察：配置 observe 不等于确实收到真实入站消息。
        real_observe_groups = [group for group in real_groups if group.enabled and group.reply_mode == "observe"]
        observed_real_observe_groups = [group for group in real_observe_groups if group.id in observed_group_ids]
        if observed_real_observe_groups:
            observe_state = "done"
            observe_summary = (
                f"已启用 {len(real_observe_groups)} 个真实观察群，"
                f"其中 {len(observed_real_observe_groups)} 个已记录入站消息。"
            )
            observe_next = "观察通过不等于回复策略已开启；开启回复前请检查限频与待审队列。"
        elif real_observe_groups:
            observe_state = "optional"
            observe_summary = "观察群已启用，但尚未记录到真实入站消息。"
            observe_next = "保持连接器在线，在受控群发送消息确认能够被记录。"
        elif real_groups:
            observe_state = "optional"
            observe_summary = "当前没有启用的真实观察群。"
            observe_next = "可先将一个群设为观察模式，确认消息接收正常后再开启回复。"
        elif mock_groups:
            observe_state = "optional"
            observe_summary = "Mock 演示群不产生真实入站消息证据。"
            observe_next = "真实接入后先观察群消息，再开启回复。"
        else:
            observe_state = "optional"
            observe_summary = "尚未登记群聊，无法观察消息。"
            observe_next = "先完成群聊登记。"
        steps.append(
            _step(
                "observe",
                state=observe_state,
                summary=observe_summary,
                next_step=observe_next,
                evidence={
                    "real_observe_groups": len(real_observe_groups),
                    "observed_currently": len(observed_real_observe_groups),
                },
            )
        )

        # 8. 开启回复
        enabled_providers_ordered = sorted(
            (provider for provider in providers if provider.enabled),
            key=lambda provider: (not provider.is_default, provider.created_at),
        )

        def resolve_provider(group: Group) -> LLMProvider | None:
            if group.llm_provider_id:
                return next((item for item in providers if item.id == group.llm_provider_id), None)
            return enabled_providers_ordered[0] if enabled_providers_ordered else None

        real_ready_groups: list[Group] = []
        real_manual_groups: list[Group] = []
        mock_ready_groups: list[Group] = []
        real_group_provider_problem = False
        live_real_account_ids = {account.id for account, _ in live_real_instances}
        for group in groups:
            if not group.enabled or group.paused or group.reply_mode == "observe":
                continue
            account = accounts_by_id.get(group.account_id)
            provider = resolve_provider(group)
            if group.account_id in real_account_ids:
                if account is not None and account.enabled and group.account_id in live_real_account_ids:
                    if provider is not None and provider.id in ready_real_providers:
                        if group.reply_mode == "manual_confirm":
                            real_manual_groups.append(group)
                        else:
                            real_ready_groups.append(group)
                    else:
                        real_group_provider_problem = True
                else:
                    real_group_provider_problem = True
            elif group.account_id in mock_account_ids:
                if (
                    account is not None
                    and account.enabled
                    and provider is not None
                    and provider.provider_type == "mock"
                ):
                    mock_ready_groups.append(group)

        if pause.get("paused"):
            enable_state = "blocked"
            enable_summary = "全局紧急暂停开启中，所有回复被阻止。"
            enable_next = "确认风险后，在系统设置页显式恢复。"
            blockers.append("全局紧急暂停已开启；任何群都不会自动发送回复。")
        elif real_ready_groups or real_manual_groups:
            enable_state = "done"
            if real_manual_groups and not real_ready_groups:
                enable_summary = "已就绪群使用手动确认模式；回复只会进入待审队列。"
                enable_next = "人工审核待审回复；不会自动发送。"
            else:
                enable_summary = (
                    f"{len(real_ready_groups) + len(real_manual_groups)} 个真实群已满足在线、Provider 与回复模式条件。"
                )
                enable_next = "首次真实发送仍需人工验收；失败或状态未知的消息不会自动重发。"
        elif mock_ready_groups:
            enable_state = "mock_only"
            enable_summary = f"{len(mock_ready_groups)} 个 Mock 演示群已启用回复；仅本地演示。"
            enable_next = "真实群开启回复前，需要真实在线账号与测试成功的真实 Provider。"
            warnings.append("开启回复步骤仅涉及 Mock 群，不代表真实回复已开启。")
        else:
            enable_state = "action_required"
            if real_group_provider_problem:
                enable_summary = "已有真实群启用回复，但账号未实时在线或 Provider 尚未通过新鲜测试。"
                enable_next = "检查群回复模式、账号在线状态与群级/默认模型配置。"
            else:
                enable_summary = "尚未有群满足开启回复的条件。"
                enable_next = "真实链路就绪后，再逐群选择回复模式；手动确认模式更安全。"
        steps.append(
            _step(
                "enable",
                state=enable_state,
                summary=enable_summary,
                next_step=enable_next,
                evidence={
                    "ready_real_groups": len(real_ready_groups),
                    "ready_manual_groups": len(real_manual_groups),
                    "ready_mock_groups": len(mock_ready_groups),
                    "global_paused": bool(pause.get("paused")),
                },
            )
        )

        mock_runnable = bool(mock_ready_groups) and any(
            _provider_config_complete(provider) and provider.enabled for provider in mock_providers
        )
        any_blocked = any(step["state"] == "blocked" for step in steps)
        if any_blocked:
            overall = "blocked"
        elif enable_state == "done":
            overall = "ready_real"
        elif enable_state == "mock_only" and mock_runnable:
            overall = "ready_mock_only"
        else:
            overall = "action_required"

        if overall == "ready_real":
            next_action = None
        else:
            next_step = next(
                (step for step in steps if step["state"] in {"blocked", "action_required", "not_verified"}),
                None,
            )
            if next_step is None:
                next_step = next((step for step in steps if step["state"] == "optional"), None)
            next_action = (
                {"key": next_step["key"], "label": next_step["title"], "route": next_step["route"]}
                if next_step is not None
                else None
            )

        notes = [
            "本向导只读：不会自动登录 QQ、自动测试模型、自动导入群或自动开启回复。",
            "实时在线来自后端内存适配器；历史测试证据可能过期，过期不会被视为通过。",
            "Mock 始终只是演示；真实 QQ 入站、出站与真实模型调用仍需用户自行验收。",
        ]
        return {
            "schema_version": "onboarding.v1",
            "checked_at": iso_utc(now),
            "overall": overall,
            "ready_for_replies": overall == "ready_real" and enable_state == "done",
            "mock_only": overall == "ready_mock_only",
            "global_paused": bool(pause.get("paused")),
            "steps": steps,
            "warnings": warnings,
            "blockers": blockers,
            "next_action": next_action,
            "notes": notes,
        }

    def _blocked_environment(self, now: datetime, reason: str) -> dict[str, Any]:
        steps = [
            _step(
                "backend",
                state="blocked",
                summary=reason,
                next_step="检查后端数据库配置与进程状态；诊断页可查看最新错误码。",
                evidence={"database": False, "credential_key_configured": self.cipher.available},
            )
        ]
        for key, _ in STEP_ORDER[1:]:
            steps.append(
                _step(
                    key,
                    state="blocked",
                    summary="本地数据库不可用，无法读取接入状态。",
                    next_step="先恢复后端数据库连接。",
                )
            )
        return {
            "schema_version": "onboarding.v1",
            "checked_at": iso_utc(now),
            "overall": "blocked",
            "ready_for_replies": False,
            "mock_only": False,
            "global_paused": False,
            "steps": steps,
            "warnings": [],
            "blockers": [reason],
            "next_action": {"key": "backend", "label": "运行环境", "route": "/diagnostics"},
            "notes": ["本向导只读，不会尝试修复数据库或执行任何外部动作。"],
        }


__all__ = ["OnboardingService", "STEP_ORDER"]

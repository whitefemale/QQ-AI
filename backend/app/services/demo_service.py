"""一键初始化 Mock 演示环境（幂等）。不会连接或发送到真实 QQ。"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select

from app.core.config import Settings
from app.db.session import Database
from app.models.account import Account, AdapterInstance
from app.models.group import Group
from app.models.persona import Persona
from app.models.provider import LLMProvider
from app.services.account_service import AccountService
from app.services.adapter_manager import AdapterManager
from app.services.audit import write_audit
from app.services.group_service import GroupService
from app.services.persona_store import PersonaStore
from app.services.provider_service import ProviderService
from app.services.settings_store import get_global_pause

logger = logging.getLogger(__name__)

DEMO_ACCOUNT_NAME = "演示账号（Mock）"
DEMO_PROVIDER_NAME = "Mock 模型（演示）"
DEMO_PERSONA_NAME = "演示人格（模板）"
DEMO_GROUP_ID = "100001"


class DemoService:
    def __init__(
        self,
        database: Database,
        settings: Settings,
        accounts: AccountService,
        groups: GroupService,
        personas: PersonaStore,
        providers: ProviderService,
        manager: AdapterManager,
    ) -> None:
        self.database = database
        self.settings = settings
        self.accounts = accounts
        self.groups = groups
        self.personas = personas
        self.providers = providers
        self.manager = manager

    async def bootstrap(self) -> dict[str, Any]:
        created: list[str] = []
        account = await self._ensure_account(created)
        await self._ensure_instance(account, created)
        persona = await self._ensure_persona(created)
        await self._ensure_provider(created)
        group = await self._ensure_group(account, persona, created)
        await self._connect_mock(account, created)
        await write_audit(
            self.database,
            action="demo.bootstrap",
            target_type="account",
            target_id=account.id,
            details={"created": created},
        )
        pause = await get_global_pause(self.database)
        return {
            "created": created,
            "account": await self.accounts.get_account(account.id),
            "persona": await self.personas.get_public(persona.id),
            "group": await self.groups.get_group(group.id),
            "provider": await self._provider_public(),
            "global_pause": pause,
            "notes": [
                "演示环境完全使用 Mock 连接器与 Mock 模型，不会连接真实 QQ。",
                "Mock 模型回复仅用于验证流程，不代表真实模型能力。",
                "在演示群发送 @机器人 的模拟事件即可看到完整闭环。",
            ],
        }

    async def _ensure_account(self, created: list[str]) -> Account:
        async with self.database.session() as session:
            account = await session.scalar(select(Account).where(Account.display_name == DEMO_ACCOUNT_NAME))
            if account is not None:
                return account
        data = await self.accounts.create_account(
            {
                "display_name": DEMO_ACCOUNT_NAME,
                "enabled": True,
                "allow_private": False,
                "notes": "由「一键初始化 Mock 演示环境」创建，不代表真实 QQ 账号。",
                "instance": {
                    "name": "Mock 连接器",
                    "connection_mode": "mock",
                    "auto_connect": True,
                    "enabled": True,
                },
            }
        )
        created.append("account")
        async with self.database.session() as session:
            account = await session.get(Account, data["id"])
        assert account is not None
        return account

    async def _ensure_instance(self, account: Account, created: list[str]) -> None:
        async with self.database.session() as session:
            instance = await session.scalar(
                select(AdapterInstance).where(
                    AdapterInstance.account_id == account.id,
                    AdapterInstance.connection_mode == "mock",
                )
            )
            if instance is not None:
                return
        await self.accounts.add_instance(
            account.id,
            {
                "name": "Mock 连接器",
                "connection_mode": "mock",
                "auto_connect": True,
                "enabled": True,
            },
        )
        created.append("mock_instance")

    async def _ensure_persona(self, created: list[str]) -> Persona:
        async with self.database.session() as session:
            persona = await session.scalar(select(Persona).where(Persona.name == DEMO_PERSONA_NAME))
            if persona is not None:
                return persona
        public = await self.personas.create_persona(
            {
                "name": DEMO_PERSONA_NAME,
                "mode": "template",
                "template_key": "friendly_helper",
                "growth_policy": "review",
                "growth_enabled": False,
                "learning_scope": "admin_only",
                "notes": "演示用模板人格；成长默认关闭。",
            }
        )
        created.append("persona")
        async with self.database.session() as session:
            persona = await session.get(Persona, public["id"])
        assert persona is not None
        return persona

    async def _ensure_provider(self, created: list[str]) -> None:
        async with self.database.session() as session:
            provider = await session.scalar(select(LLMProvider).where(LLMProvider.name == DEMO_PROVIDER_NAME))
            if provider is not None:
                return
            has_enabled = await session.scalar(select(LLMProvider.id).where(LLMProvider.enabled.is_(True)).limit(1))
            has_default = await session.scalar(select(LLMProvider.id).where(LLMProvider.is_default.is_(True)).limit(1))
        await self.providers.create_llm_provider(
            {
                "name": DEMO_PROVIDER_NAME,
                "provider_type": "mock",
                "model": "mock-model",
                "is_default": bool(has_enabled is None and has_default is None),
                "enabled": True,
            }
        )
        created.append("mock_provider")

    async def _ensure_group(self, account: Account, persona: Persona, created: list[str]) -> Group:
        async with self.database.session() as session:
            group = await session.scalar(
                select(Group).where(
                    Group.account_id == account.id,
                    Group.platform_group_id == DEMO_GROUP_ID,
                )
            )
            if group is not None:
                if group.persona_id is None:
                    group.persona_id = persona.id
                    await session.commit()
                return group
        public = await self.groups.create_group(
            {
                "account_id": account.id,
                "platform_group_id": DEMO_GROUP_ID,
                "name": "Mock 演示群",
                "enabled": True,
                "reply_mode": "mention_only",
                "persona_id": persona.id,
                "timezone": self.settings.default_timezone,
                "group_rules_text": "演示规则：仅在被 @ 时回复，保持简短。",
                "keywords": ["你好"],
            }
        )
        created.append("demo_group")
        async with self.database.session() as session:
            group = await session.get(Group, public["id"])
        assert group is not None
        return group

    async def _connect_mock(self, account: Account, created: list[str]) -> None:
        async with self.database.session() as session:
            instance = await session.scalar(
                select(AdapterInstance).where(
                    AdapterInstance.account_id == account.id,
                    AdapterInstance.connection_mode == "mock",
                )
            )
            instance_id = instance.id if instance else None
        if not instance_id:
            return
        adapter = self.manager.get_adapter(instance_id)
        if adapter is not None and adapter.status == "online":
            return
        await self.manager.connect_instance(instance_id)
        created.append("mock_connected")

    async def _provider_public(self) -> dict[str, Any] | None:
        async with self.database.session() as session:
            provider = await session.scalar(select(LLMProvider).where(LLMProvider.name == DEMO_PROVIDER_NAME))
            if provider is None:
                return None
            return {
                "id": provider.id,
                "name": provider.name,
                "provider_type": provider.provider_type,
                "model": provider.model,
                "is_default": provider.is_default,
                "is_mock": True,
            }

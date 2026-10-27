"""应用运行时：按依赖顺序装配所有服务，并管理后台任务生命周期。"""

from __future__ import annotations

import asyncio
import logging

from app.adapters.media.local_store import LocalMediaStore
from app.adapters.tools.executor import ToolExecutor, sync_tool_records
from app.adapters.tools.registry import build_default_tool_registry
from app.budgets.service import BudgetService
from app.core.config import Settings
from app.core.security import CredentialCipher
from app.db.session import Database
from app.media.capability_router import CapabilityRouter
from app.media.jobs import MediaJobService
from app.media.service import MediaService
from app.media.usage import MediaUsageService
from app.media.worker import MediaWorker
from app.pipeline.context import ContextBuilder
from app.pipeline.events import EventBus
from app.pipeline.llm_gateway import LLMGateway
from app.pipeline.orchestrator import MessagePipeline
from app.pipeline.outbox import OutboxService
from app.pipeline.persona_growth import PersonaGrowthService
from app.pipeline.policy import PolicyEngine
from app.pipeline.prompt import PromptBuilder
from app.plugins.registry import PluginService
from app.providers.registry import build_default_registry
from app.services.account_service import AccountService
from app.services.adapter_manager import AdapterManager, OutboxWorker
from app.services.backup_service import BackupService
from app.services.demo_service import DemoService
from app.services.group_service import GroupService
from app.services.memory_auto import MemoryAutoExtractionScheduler
from app.services.memory_extraction import MemoryExtractionService
from app.services.memory_service import MemoryService
from app.services.message_service import MessageService
from app.services.persona_store import PersonaStore
from app.services.playground_service import PlaygroundService
from app.services.provider_service import ProviderService
from app.services.query_service import DashboardService, MessageQueryService
from app.services.retention import RetentionScheduler, RetentionService

logger = logging.getLogger(__name__)


class AppRuntime:
    """进程内单例；所有服务共享数据库、事件总线与凭证加密器。"""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        settings.ensure_directories()
        self.started = False

        self.database = Database(settings)
        self.cipher = CredentialCipher(settings.credential_encryption_key)
        self.events = EventBus()

        self.plugins = PluginService(self.database, settings)
        self.tool_registry = build_default_tool_registry()
        self.tool_executor = ToolExecutor(
            self.database,
            self.tool_registry,
            settings,
            plugin_service=self.plugins,
        )

        self.provider_registry = build_default_registry()
        self.media_store = LocalMediaStore(
            settings.media_path,
            max_bytes=settings.max_media_bytes,
        )
        self.media_service = MediaService(self.database, self.media_store, settings)
        self.capability_router = CapabilityRouter(self.provider_registry)
        self.budgets = BudgetService(self.database, settings, events=self.events)
        self.media_usage = MediaUsageService(self.database)
        self.media_jobs = MediaJobService(
            self.database,
            self.capability_router,
            self.media_service,
            budgets=self.budgets,
            usage=self.media_usage,
        )
        self.media_worker = MediaWorker(
            self.media_jobs,
            interval_seconds=settings.media_worker_interval_seconds,
            batch_size=settings.media_worker_batch_size,
        )
        self.llm_gateway = LLMGateway(
            self.database,
            settings,
            self.cipher,
            self.budgets,
        )

        self.messages = MessageService(self.database)
        self.memories = MemoryService(self.database, settings)
        self.memory_extraction = MemoryExtractionService(
            self.database,
            settings,
            self.llm_gateway,
            self.memories,
        )
        self.memory_auto = MemoryAutoExtractionScheduler(
            self.database,
            self.memory_extraction,
            self.events,
        )
        self.context_builder = ContextBuilder(self.messages, settings)
        self.prompt_builder = PromptBuilder(settings)
        self.outbox = OutboxService(self.database, settings, self.messages, self.events)
        self.policy = PolicyEngine()
        self.pipeline = MessagePipeline(
            database=self.database,
            settings=settings,
            events=self.events,
            message_service=self.messages,
            context_builder=self.context_builder,
            prompt_builder=self.prompt_builder,
            llm_gateway=self.llm_gateway,
            outbox=self.outbox,
            policy=self.policy,
            tool_registry=self.tool_registry,
            tool_executor=self.tool_executor,
            memory_service=self.memories,
            media_jobs=self.media_jobs,
        )

        self.personas = PersonaStore(self.database)
        self.retention = RetentionService(
            self.database,
            settings,
            self.media_service,
            self.personas,
            self.memories,
        )
        self.retention_scheduler = RetentionScheduler(self.retention)
        self.growth = PersonaGrowthService(
            self.database,
            settings,
            self.llm_gateway,
            store=self.personas,
            events=self.events,
        )
        self.manager = AdapterManager(
            database=self.database,
            settings=settings,
            cipher=self.cipher,
            pipeline=self.pipeline,
            outbox=self.outbox,
            events=self.events,
            growth=self.growth,
        )
        self.worker = OutboxWorker(
            self.manager,
            self.database,
            self.outbox,
            interval=2.0,
        )

        self.accounts = AccountService(self.database, self.cipher, self.manager)
        self.groups = GroupService(self.database, settings)
        self.providers = ProviderService(
            self.database,
            self.cipher,
            self.llm_gateway,
            self.provider_registry,
        )
        self.queries = MessageQueryService(self.database)
        self.dashboard = DashboardService(
            self.database,
            settings,
            self.events,
            self.providers,
            self.budgets,
        )
        self.backups = BackupService(self.database, settings, self.manager)
        self.playground = PlaygroundService(self.database, self.pipeline, self.manager)
        self.demo = DemoService(
            self.database,
            settings,
            self.accounts,
            self.groups,
            self.personas,
            self.providers,
            self.manager,
        )
        self._stop_event = asyncio.Event()

    async def start(self) -> None:
        if self.started:
            return
        self.started = True
        self._stop_event.clear()
        try:
            await self.plugins.sync()
            await sync_tool_records(self.database, self.tool_registry)
            await self.providers.load_media_provider_state()
            await self.manager.start()
            await self.worker.start()
            await self.memory_auto.start()
            await self.retention_scheduler.start()
            if self.settings.media_worker_enabled:
                await self.media_worker.start()
            self.events.publish(
                "system.started",
                {
                    "version": self.settings.app_version,
                    "env": self.settings.app_env,
                    "credential_key_configured": self.cipher.available,
                },
            )
            logger.info("应用运行时已启动")
        except Exception:
            logger.exception("应用运行时启动失败")
            await self.stop()
            raise

    async def stop(self) -> None:
        if not self.started:
            return
        self.started = False
        self._stop_event.set()
        await self.media_worker.stop()
        await self.retention_scheduler.stop()
        await self.memory_auto.stop()
        await self.worker.stop()
        await self.manager.stop()
        await self.llm_gateway.close()
        await self.database.dispose()
        logger.info("应用运行时已停止")


__all__ = ["AppRuntime"]

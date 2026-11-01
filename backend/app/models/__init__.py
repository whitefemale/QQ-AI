"""所有 ORM 模型统一导入，确保 Alembic 能发现全部表。"""

from app.models.account import Account, AdapterInstance
from app.models.connector import ConnectorConfigSnapshot, ConnectorInstallation, ConnectorJob
from app.models.governance import (
    AuditLog,
    AutomationRule,
    BackupRecord,
    BudgetAlert,
    BudgetPolicy,
    ConversationEvalCase,
    ConversationEvalRun,
    PluginRegistry,
    RetentionPolicy,
    SystemSetting,
    TaskRun,
    UsageEvent,
)
from app.models.group import Group, Member
from app.models.media import MediaAsset, MediaJob, MediaProviderUsage, MediaTranscript
from app.models.memory import MEMORY_CANDIDATE_STATUSES, Memory, MemoryCandidate
from app.models.message import Message, OutboxMessage
from app.models.persona import (
    DEFAULT_PERSONA_THRESHOLDS,
    Persona,
    PersonaEvolutionEvent,
    PersonaTrait,
    PersonaVersion,
)
from app.models.provider import LLMProvider, LLMUsage, ProviderRegistry
from app.models.tool import ToolRecord, ToolRun

__all__ = [
    "DEFAULT_PERSONA_THRESHOLDS",
    "MEMORY_CANDIDATE_STATUSES",
    "Account",
    "AdapterInstance",
    "AuditLog",
    "AutomationRule",
    "BackupRecord",
    "BudgetAlert",
    "BudgetPolicy",
    "ConnectorConfigSnapshot",
    "ConnectorInstallation",
    "ConnectorJob",
    "ConversationEvalCase",
    "ConversationEvalRun",
    "Group",
    "LLMProvider",
    "LLMUsage",
    "MediaAsset",
    "MediaJob",
    "MediaProviderUsage",
    "MediaTranscript",
    "Member",
    "Memory",
    "MemoryCandidate",
    "Message",
    "OutboxMessage",
    "Persona",
    "PersonaEvolutionEvent",
    "PersonaTrait",
    "PersonaVersion",
    "PluginRegistry",
    "ProviderRegistry",
    "RetentionPolicy",
    "SystemSetting",
    "TaskRun",
    "ToolRecord",
    "ToolRun",
    "UsageEvent",
]

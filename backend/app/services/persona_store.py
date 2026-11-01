"""人格档案 CRUD、特征治理、版本快照与回滚。"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError, ErrorCode
from app.core.security import redact_text
from app.core.time import iso_utc, utcnow
from app.db.session import Database
from app.models.group import Group
from app.models.message import Message
from app.models.persona import (
    DEFAULT_PERSONA_THRESHOLDS,
    Persona,
    PersonaEvolutionEvent,
    PersonaTrait,
    PersonaVersion,
)
from app.services.audit import write_audit
from app.services.persona_service import PERSONA_MODE_LABELS, PERSONA_TEMPLATES

PERSONA_MODES = frozenset(PERSONA_MODE_LABELS)
GROWTH_POLICIES = frozenset({"auto", "review", "paused"})
LEARNING_SCOPES = frozenset({"admin_only", "group", "cross_group"})
TRAIT_CATEGORIES = frozenset({"style", "interest", "value", "habit", "skill", "other"})
TRAIT_STATUSES = frozenset({"candidate", "stable", "rejected"})
SELF_DESCRIPTION_FIELD = "self_description"
_MAX_DESCRIPTION = 4000
_MAX_OVERLAY = 2000

# 预览、版本差异与保存共用同一组字段；不要在这里加入 traits。
CONFIG_FIELDS: tuple[tuple[str, str], ...] = (
    ("name", "名称"),
    ("mode", "人格模式"),
    ("template_key", "模板"),
    ("self_description", "自我描述"),
    ("authored_fields", "设定字段"),
    ("system_prompt_overlay", "系统提示覆盖"),
    ("growth_policy", "成长策略"),
    ("growth_enabled", "启用自动成长"),
    ("learning_scope", "学习范围"),
    ("thresholds", "成长门槛"),
    ("locked_fields", "锁定字段"),
    ("enabled", "启用"),
    ("notes", "备注"),
)
FIELD_LABELS = dict(CONFIG_FIELDS)
_PERSONA_FIELDS = [field for field, _label in CONFIG_FIELDS]


def project_persona_update(
    snapshot: dict[str, Any],
    payload: dict[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """纯投影：校验 PATCH 字段并返回更新后的快照，不读写数据库。

    保存路径与预览接口都调用本函数，避免“预览一套、保存另一套”。
    """
    after = deepcopy(snapshot)
    if "name" in payload:
        name = _clean_str(payload.get("name"), 64)
        if not name:
            raise AppError(ErrorCode.VALIDATION_ERROR, "人格名称不能为空。", status_code=400)
        after["name"] = name
    if "mode" in payload:
        mode = str(payload.get("mode") or "").strip()
        if mode not in PERSONA_MODES:
            raise AppError(ErrorCode.VALIDATION_ERROR, "人格模式无效。", status_code=400)
        after["mode"] = mode
    if "template_key" in payload:
        template_key = _clean_str(payload.get("template_key"), 64) or None
        if template_key is not None and template_key not in PERSONA_TEMPLATES:
            raise AppError(ErrorCode.VALIDATION_ERROR, "人格模板不存在。", status_code=400)
        after["template_key"] = template_key
    if after.get("mode") == "template" and after.get("template_key") not in PERSONA_TEMPLATES:
        raise AppError(ErrorCode.VALIDATION_ERROR, "模板模式必须选择有效模板。", status_code=400)
    if "self_description" in payload:
        after["self_description"] = _clean_str(payload.get("self_description"), _MAX_DESCRIPTION) or None
    if "authored_fields" in payload:
        after["authored_fields"] = _clean_authored(payload.get("authored_fields"))
    if "system_prompt_overlay" in payload:
        after["system_prompt_overlay"] = _clean_str(payload.get("system_prompt_overlay"), _MAX_OVERLAY)
    if "growth_policy" in payload:
        policy = str(payload.get("growth_policy") or "").strip()
        if policy not in GROWTH_POLICIES:
            raise AppError(ErrorCode.VALIDATION_ERROR, "成长策略无效。", status_code=400)
        after["growth_policy"] = policy
    if "growth_enabled" in payload:
        after["growth_enabled"] = bool(payload.get("growth_enabled"))
    if "learning_scope" in payload:
        scope = str(payload.get("learning_scope") or "").strip()
        if scope not in LEARNING_SCOPES:
            raise AppError(ErrorCode.VALIDATION_ERROR, "学习范围无效。", status_code=400)
        after["learning_scope"] = scope
    if "thresholds" in payload:
        after["thresholds"] = sanitize_thresholds(payload.get("thresholds"))
    if "locked_fields" in payload:
        after["locked_fields"] = _clean_list(payload.get("locked_fields"))
    if "enabled" in payload:
        after["enabled"] = bool(payload.get("enabled"))
    if "notes" in payload:
        after["notes"] = _clean_str(payload.get("notes"), 2000) or None

    changes: list[dict[str, Any]] = []
    for field in _PERSONA_FIELDS:
        if field not in snapshot and field not in after:
            continue
        before_value = snapshot.get(field)
        after_value = after.get(field)
        if before_value != after_value:
            changes.append(
                {
                    "field": field,
                    "label": FIELD_LABELS[field],
                    "before": _display_value(before_value),
                    "after": _display_value(after_value),
                }
            )
    return after, changes


def apply_snapshot_config(persona: Persona, snapshot: dict[str, Any]) -> None:
    """把投影结果写回 ORM 对象；只处理配置字段，特征由版本/成长流程管理。"""
    if "name" in snapshot:
        persona.name = str(snapshot.get("name") or persona.name)[:64]
    if "mode" in snapshot:
        persona.mode = str(snapshot.get("mode") or persona.mode)[:32]
    if "template_key" in snapshot:
        value = snapshot.get("template_key")
        persona.template_key = str(value)[:64] if value else None
    if "self_description" in snapshot:
        value = snapshot.get("self_description")
        persona.self_description = str(value)[:_MAX_DESCRIPTION] if value else None
    if "authored_fields" in snapshot:
        persona.authored_fields_json = _clean_authored(snapshot.get("authored_fields"))
    if "system_prompt_overlay" in snapshot:
        value = snapshot.get("system_prompt_overlay")
        persona.system_prompt_overlay = str(value)[:_MAX_OVERLAY] if value else None
    if "growth_policy" in snapshot:
        persona.growth_policy = str(snapshot.get("growth_policy") or persona.growth_policy)[:16]
    if "growth_enabled" in snapshot:
        persona.growth_enabled = bool(snapshot.get("growth_enabled"))
    if "learning_scope" in snapshot:
        persona.learning_scope = str(snapshot.get("learning_scope") or persona.learning_scope)[:32]
    if "thresholds" in snapshot:
        persona.thresholds_json = sanitize_thresholds(snapshot.get("thresholds"))
    if "locked_fields" in snapshot:
        persona.locked_fields_json = _clean_list(snapshot.get("locked_fields"))
    if "enabled" in snapshot:
        persona.enabled = bool(snapshot.get("enabled"))
    if "notes" in snapshot:
        value = snapshot.get("notes")
        persona.notes = str(value)[:2000] if value else None


def snapshot_diff(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    """比较两个 `_snapshot` 结构；只返回可展示的差异，不包含消息正文。"""
    fields: list[dict[str, Any]] = []
    for field in _PERSONA_FIELDS:
        # 旧版本快照可能缺少后来新增的字段；缺失时不做比较，避免伪造差异。
        if field not in before or field not in after:
            continue
        old_value = before.get(field)
        new_value = after.get(field)
        if old_value != new_value:
            fields.append(
                {
                    "field": field,
                    "label": FIELD_LABELS[field],
                    "before": _display_value(old_value),
                    "after": _display_value(new_value),
                }
            )
    old_traits = _trait_map(before)
    new_traits = _trait_map(after)
    added: list[dict[str, Any]] = []
    changed: list[dict[str, Any]] = []
    removed: list[dict[str, Any]] = []
    for key in sorted(set(old_traits) | set(new_traits)):
        old_item = old_traits.get(key)
        new_item = new_traits.get(key)
        if old_item is None and new_item is not None:
            added.append(new_item)
        elif new_item is None and old_item is not None:
            removed.append(old_item)
        elif old_item != new_item:
            changed.append({"trait_key": key[0], "source_scope": key[1], "before": old_item, "after": new_item})
    scopes = sorted(
        {str(item.get("source_scope") or "global") for item in [*added, *(entry["after"] for entry in changed)]}
    )
    impact = {
        "field_changes": len(fields),
        "traits_added": len(added),
        "traits_changed": len(changed),
        "traits_removed": len(removed),
        "description_changed": any(item["field"] == "self_description" for item in fields),
        "scopes": scopes,
        "locked_fields": list(after.get("locked_fields") or before.get("locked_fields") or []),
        "skipped_locked": [],
    }
    return {"fields": fields, "traits": {"added": added, "changed": changed, "removed": removed}, "impact": impact}


def sanitized_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
    """版本详情不返回证据消息 ID；只保留可审核的配置与特征摘要。"""
    result = deepcopy(snapshot)
    traits = result.get("traits")
    if isinstance(traits, list):
        for item in traits:
            if isinstance(item, dict):
                item.pop("evidence_message_ids", None)
    return result


def _trait_map(snapshot: dict[str, Any]) -> dict[tuple[str, str], dict[str, Any]]:
    result: dict[tuple[str, str], dict[str, Any]] = {}
    for item in snapshot.get("traits") or []:
        if not isinstance(item, dict):
            continue
        key = str(item.get("trait_key") or "")
        scope = str(item.get("source_scope") or "global")
        result[(key, scope)] = {
            "trait_key": key,
            "trait_value": str(item.get("trait_value") or ""),
            "category": item.get("category"),
            "confidence": round(float(item.get("confidence") or 0.0), 2),
            "evidence_count": int(item.get("evidence_count") or 0),
            "source_scope": scope,
            "status": item.get("status"),
        }
    return result


def _display_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): str(item)[:500] for key, item in list(value.items())[:30]}
    if isinstance(value, list):
        return [str(item)[:200] for item in value[:50]]
    if isinstance(value, str):
        return value[:2000]
    return value


def _scrub_evidence_refs(value: Any, message_ids: set[str]) -> tuple[Any, bool]:
    """递归移除提案/版本快照中的证据消息 ID；不保存被删消息的任何引用。"""
    if isinstance(value, dict):
        changed = False
        output: dict[str, Any] = {}
        for key, item in value.items():
            if key in {"evidence_message_ids", "source_message_ids"} and isinstance(item, list):
                filtered = [entry for entry in item if str(entry) not in message_ids]
                changed = changed or len(filtered) != len(item)
                output[key] = filtered
            else:
                new_item, item_changed = _scrub_evidence_refs(item, message_ids)
                output[key] = new_item
                changed = changed or item_changed
        return output, changed
    if isinstance(value, list):
        changed = False
        items: list[Any] = []
        for item in value:
            new_item, item_changed = _scrub_evidence_refs(item, message_ids)
            items.append(new_item)
            changed = changed or item_changed
        return items, changed
    return value, False


def _clean_str(value: Any, limit: int) -> str:
    return str(value or "").strip()[:limit]


def _clean_list(value: Any, *, limit: int = 50, item_limit: int = 128) -> list[str]:
    if not isinstance(value, list):
        return []
    result: list[str] = []
    for item in value[:limit]:
        text = str(item or "").strip()[:item_limit]
        if text and text not in result:
            result.append(text)
    return result


def _clean_authored(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    result: dict[str, str] = {}
    for key, item in list(value.items())[:30]:
        text_key = str(key or "").strip()[:64]
        text_value = str(item or "").strip()[:1000]
        if text_key and text_value:
            result[text_key] = text_value
    return result


def sanitize_thresholds(value: Any) -> dict[str, float]:
    thresholds: dict[str, float] = {}
    if not isinstance(value, dict):
        return thresholds
    for key in DEFAULT_PERSONA_THRESHOLDS:
        if key not in value:
            continue
        try:
            number = float(value[key])
        except (TypeError, ValueError):
            continue
        if key == "min_confidence":
            thresholds[key] = min(max(number, 0.0), 1.0)
        else:
            thresholds[key] = min(max(int(number), 1), 100)
    return thresholds


def persona_thresholds(persona: Persona) -> dict[str, float]:
    merged = {key: float(value) for key, value in DEFAULT_PERSONA_THRESHOLDS.items()}
    merged.update(sanitize_thresholds(persona.thresholds_json or {}))
    return merged


def is_locked(persona: Persona, field: str) -> bool:
    locked = {str(item) for item in (persona.locked_fields_json or [])}
    return field in locked or f"trait:{field}" in locked


def trait_public(trait: PersonaTrait) -> dict[str, Any]:
    return {
        "id": trait.id,
        "persona_id": trait.persona_id,
        "trait_key": trait.trait_key,
        "trait_value": trait.trait_value,
        "category": trait.category,
        "confidence": round(trait.confidence, 2),
        "evidence_count": trait.evidence_count,
        "evidence_message_ids": list(trait.evidence_message_ids_json or []),
        "source_scope": trait.source_scope,
        "status": trait.status,
        "locked_by_user": trait.locked_by_user,
        "expires_at": trait.expires_at.isoformat() if trait.expires_at else None,
        "first_observed_at": trait.first_observed_at.isoformat() if trait.first_observed_at else None,
        "last_observed_at": trait.last_observed_at.isoformat() if trait.last_observed_at else None,
        "created_at": trait.created_at.isoformat() if trait.created_at else None,
    }


def version_public(version: PersonaVersion) -> dict[str, Any]:
    return {
        "id": version.id,
        "persona_id": version.persona_id,
        "version_no": version.version_no,
        "change_summary": version.change_summary,
        "created_by": version.created_by,
        "restorable": version.restorable,
        "created_at": version.created_at.isoformat() if version.created_at else None,
    }


def event_public(event: PersonaEvolutionEvent) -> dict[str, Any]:
    old_state = dict(event.old_state_json or {})
    new_state = dict(event.new_state_json or {})
    proposal = dict(event.proposal_json or {})
    diff = snapshot_diff(old_state, new_state)
    impact = diff["impact"]
    locked = {str(item) for item in (old_state.get("locked_fields") or new_state.get("locked_fields") or [])}
    skipped: list[str] = []
    for trait in proposal.get("proposed_traits") or []:
        if not isinstance(trait, dict):
            continue
        key = str(trait.get("trait_key") or "")
        if key and (key in locked or f"trait:{key}" in locked) and key not in skipped:
            skipped.append(key)
    if proposal.get("self_description") and (
        SELF_DESCRIPTION_FIELD in locked or f"trait:{SELF_DESCRIPTION_FIELD}" in locked
    ):
        skipped.append(SELF_DESCRIPTION_FIELD)
    impact["skipped_locked"] = skipped
    return {
        "id": event.id,
        "persona_id": event.persona_id,
        "batch_id": event.batch_id,
        "trigger_type": event.trigger_type,
        "trigger_message_id": event.trigger_message_id,
        "group_id": event.group_id,
        "summary": event.summary,
        "diff_summary": event.diff_summary,
        "evidence_summary": event.evidence_summary,
        "confidence": round(event.confidence, 2),
        "result": event.result,
        "rule_version": event.rule_version,
        "error_message": event.error_message,
        "reviewed_at": event.reviewed_at.isoformat() if event.reviewed_at else None,
        "created_at": event.created_at.isoformat() if event.created_at else None,
        "proposal": proposal,
        "old_state": sanitized_snapshot(old_state),
        "new_state": sanitized_snapshot(new_state),
        "diff": diff,
        "impact": impact,
    }


class PersonaStore:
    def __init__(self, database: Database) -> None:
        self.database = database

    async def list_personas(self) -> list[dict[str, Any]]:
        async with self.database.session() as session:
            personas = list((await session.execute(select(Persona).order_by(Persona.created_at))).scalars())
            result = [await self._public(session, persona) for persona in personas]
        return result

    async def get_persona(self, persona_id: str) -> Persona:
        async with self.database.session() as session:
            persona = await session.get(Persona, persona_id)
        if persona is None:
            raise AppError(ErrorCode.PERSONA_NOT_FOUND, "人格不存在。", status_code=404)
        return persona

    async def get_public(self, persona_id: str) -> dict[str, Any]:
        async with self.database.session() as session:
            persona = await session.get(Persona, persona_id)
            if persona is None:
                raise AppError(ErrorCode.PERSONA_NOT_FOUND, "人格不存在。", status_code=404)
            return await self._public(session, persona)

    async def detail(self, persona_id: str) -> dict[str, Any]:
        async with self.database.session() as session:
            persona = await session.get(Persona, persona_id)
            if persona is None:
                raise AppError(ErrorCode.PERSONA_NOT_FOUND, "人格不存在。", status_code=404)
            public = await self._public(session, persona)
            traits = list(
                (
                    await session.execute(
                        select(PersonaTrait)
                        .where(PersonaTrait.persona_id == persona_id)
                        .order_by(PersonaTrait.status, PersonaTrait.trait_key)
                    )
                ).scalars()
            )
            versions = list(
                (
                    await session.execute(
                        select(PersonaVersion)
                        .where(PersonaVersion.persona_id == persona_id)
                        .order_by(PersonaVersion.version_no.desc())
                    )
                ).scalars()
            )
            events = list(
                (
                    await session.execute(
                        select(PersonaEvolutionEvent)
                        .where(PersonaEvolutionEvent.persona_id == persona_id)
                        .order_by(PersonaEvolutionEvent.created_at.desc())
                        .limit(50)
                    )
                ).scalars()
            )
            groups = list((await session.execute(select(Group).where(Group.persona_id == persona_id))).scalars())
        public["traits"] = [trait_public(item) for item in traits]
        public["versions"] = [version_public(item) for item in versions]
        public["events"] = [event_public(item) for item in events]
        public["bound_groups"] = [
            {"id": group.id, "name": group.name, "platform_group_id": group.platform_group_id} for group in groups
        ]
        return public

    async def preview_update(self, persona_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        """纯读取投影；不打开写事务、不写版本、不写审计。"""
        async with self.database.session() as session:
            persona = await session.get(Persona, persona_id)
            if persona is None:
                raise AppError(ErrorCode.PERSONA_NOT_FOUND, "人格不存在。", status_code=404)
            before = await self._snapshot(session, persona)
        after, changes = project_persona_update(before, payload)
        before_view = sanitized_snapshot(before)
        after_view = sanitized_snapshot(after)
        return {
            "saved": False,
            "before": before_view,
            "after": after_view,
            "changes": changes,
            "diff": snapshot_diff(before, after),
            "note": "预览不会写入数据库；确认后仍需保存才会生成新版本。",
        }

    async def version_detail(self, persona_id: str, version_id: str) -> dict[str, Any]:
        async with self.database.session() as session:
            persona = await session.get(Persona, persona_id)
            if persona is None:
                raise AppError(ErrorCode.PERSONA_NOT_FOUND, "人格不存在。", status_code=404)
            version = await session.get(PersonaVersion, version_id)
            if version is None or version.persona_id != persona_id:
                raise AppError(ErrorCode.NOT_FOUND, "人格版本不存在。", status_code=404)
            current = await self._snapshot(session, persona)
            public = version_public(version)
            stored = dict(version.snapshot_json or {})
        return {
            **public,
            "snapshot": sanitized_snapshot(stored),
            "current": sanitized_snapshot(current),
            "diff": snapshot_diff(current, stored),
            "note": "差异方向为「当前状态 → 该版版本」；回滚会生成一个新版本，不会删除历史。",
        }

    async def event_evidence(self, persona_id: str, event_id: str) -> dict[str, Any]:
        """只返回提案引用且属于该人格绑定群的消息预览。"""
        async with self.database.session() as session:
            event = await session.get(PersonaEvolutionEvent, event_id)
            if event is None or event.persona_id != persona_id:
                raise AppError(ErrorCode.NOT_FOUND, "人格成长事件不存在。", status_code=404)
            proposal = dict(event.proposal_json or {})
            ids: list[str] = []
            for trait in proposal.get("proposed_traits") or []:
                if not isinstance(trait, dict):
                    continue
                for item in trait.get("evidence_message_ids") or []:
                    value = str(item)
                    if value and value not in ids:
                        ids.append(value)
            if not ids:
                return {"items": [], "note": "该提案没有可查看的消息证据。"}
            bound = list((await session.execute(select(Group).where(Group.persona_id == persona_id))).scalars())
            bound_ids = [group.id for group in bound]
            group_names = {group.id: group.name for group in bound}
            messages: dict[str, Message] = {}
            if bound_ids:
                rows = (
                    await session.execute(
                        select(Message).where(
                            Message.id.in_(ids),
                            Message.group_id.in_(bound_ids),
                            Message.direction == "inbound",
                            Message.is_self.is_(False),
                        )
                    )
                ).scalars()
                messages = {row.id: row for row in rows}
        items: list[dict[str, Any]] = []
        for message_id in ids:
            record = messages.get(message_id)
            if record is None:
                items.append(
                    {
                        "id": message_id,
                        "missing": True,
                        "sender_name": None,
                        "timestamp": None,
                        "group_id": None,
                        "group_name": None,
                        "preview": "",
                    }
                )
                continue
            items.append(
                {
                    "id": record.id,
                    "missing": False,
                    "sender_name": record.sender_name,
                    "timestamp": iso_utc(record.event_timestamp),
                    "group_id": record.group_id,
                    "group_name": group_names.get(record.group_id or ""),
                    "preview": redact_text(record.content_text)[:200],
                }
            )
        return {
            "items": items,
            "missing_count": sum(1 for item in items if item["missing"]),
            "note": "只展示该人格绑定群范围内的证据消息；已删除或越权的消息标记为缺失。",
        }

    async def create_persona(self, payload: dict[str, Any], *, actor: str = "local-admin") -> dict[str, Any]:
        name = _clean_str(payload.get("name"), 64)
        if not name:
            raise AppError(ErrorCode.VALIDATION_ERROR, "人格名称不能为空。", status_code=400)
        mode = str(payload.get("mode") or "emergent").strip()
        if mode not in PERSONA_MODES:
            raise AppError(ErrorCode.VALIDATION_ERROR, "人格模式无效。", status_code=400)
        template_key = _clean_str(payload.get("template_key"), 64) or None
        if mode == "template":
            if template_key not in PERSONA_TEMPLATES:
                raise AppError(ErrorCode.VALIDATION_ERROR, "请选择有效的人格模板。", status_code=400)
        elif template_key is not None and template_key not in PERSONA_TEMPLATES:
            raise AppError(ErrorCode.VALIDATION_ERROR, "人格模板不存在。", status_code=400)

        growth_policy = str(payload.get("growth_policy") or "review").strip()
        if growth_policy not in GROWTH_POLICIES:
            raise AppError(ErrorCode.VALIDATION_ERROR, "成长策略无效。", status_code=400)
        learning_scope = str(payload.get("learning_scope") or "admin_only").strip()
        if learning_scope not in LEARNING_SCOPES:
            raise AppError(ErrorCode.VALIDATION_ERROR, "学习范围无效。", status_code=400)

        self_description = _clean_str(payload.get("self_description"), _MAX_DESCRIPTION)
        if mode == "emergent":
            # 空白自成长人格必须从空白开始，不接受预置性格。
            if self_description or _clean_authored(payload.get("authored_fields")):
                raise AppError(
                    ErrorCode.PERSONA_MODE_INVALID,
                    "空白自成长人格不能预置自我描述或设定字段；请改用「用户编写」模式。",
                    status_code=400,
                )
        elif mode == "template" and not self_description and template_key:
            self_description = PERSONA_TEMPLATES[template_key]["self_description"]

        persona = Persona(
            name=name,
            mode=mode,
            template_key=template_key,
            self_description=self_description or None,
            authored_fields_json=_clean_authored(payload.get("authored_fields")),
            system_prompt_overlay=_clean_str(payload.get("system_prompt_overlay"), _MAX_OVERLAY),
            growth_policy=growth_policy,
            growth_enabled=bool(payload.get("growth_enabled", mode == "emergent")),
            learning_scope=learning_scope,
            thresholds_json=sanitize_thresholds(payload.get("thresholds")),
            locked_fields_json=_clean_list(payload.get("locked_fields")),
            enabled=bool(payload.get("enabled", True)),
            notes=_clean_str(payload.get("notes"), 2000) or None,
        )
        async with self.database.session() as session:
            session.add(persona)
            await session.flush()
            snapshot = await self._snapshot(session, persona)
            session.add(
                PersonaVersion(
                    persona_id=persona.id,
                    version_no=1,
                    change_summary="创建人格",
                    snapshot_json=snapshot,
                    created_by=actor[:64],
                )
            )
            await session.commit()
            await session.refresh(persona)
            public = await self._public(session, persona)
        await write_audit(
            self.database,
            action="persona.create",
            target_type="persona",
            target_id=persona.id,
            details={"name": name, "mode": mode},
            actor=actor,
        )
        return public

    async def update_persona(
        self,
        persona_id: str,
        payload: dict[str, Any],
        *,
        actor: str = "local-admin",
    ) -> dict[str, Any]:
        async with self.database.session() as session:
            persona = await session.get(Persona, persona_id)
            if persona is None:
                raise AppError(ErrorCode.PERSONA_NOT_FOUND, "人格不存在。", status_code=404)
            old_snapshot = await self._snapshot(session, persona)
            projected, changes = project_persona_update(old_snapshot, payload)
            apply_snapshot_config(persona, projected)

            await session.flush()
            new_snapshot = await self._snapshot(session, persona)
            summary = _clean_str(payload.get("change_summary"), 200) or "用户更新人格配置"
            await self._add_version(session, persona, summary=summary, actor=actor, snapshot=new_snapshot)
            await session.commit()
            await session.refresh(persona)
            public = await self._public(session, persona)
        await write_audit(
            self.database,
            action="persona.update",
            target_type="persona",
            target_id=persona_id,
            details={
                "changed_fields": [item["field"] for item in changes] or sorted(payload.keys()),
                "old": _snapshot_summary(old_snapshot),
            },
            actor=actor,
        )
        return public

    async def delete_persona(self, persona_id: str, *, actor: str = "local-admin") -> None:
        async with self.database.session() as session:
            persona = await session.get(Persona, persona_id)
            if persona is None:
                raise AppError(ErrorCode.PERSONA_NOT_FOUND, "人格不存在。", status_code=404)
            name = persona.name
            await session.delete(persona)
            await session.commit()
        await write_audit(
            self.database,
            action="persona.delete",
            target_type="persona",
            target_id=persona_id,
            details={"name": name},
            actor=actor,
        )

    async def list_traits(self, persona_id: str, *, status: str | None = None) -> list[dict[str, Any]]:
        async with self.database.session() as session:
            query = select(PersonaTrait).where(PersonaTrait.persona_id == persona_id)
            if status:
                query = query.where(PersonaTrait.status == status)
            traits = list((await session.execute(query.order_by(PersonaTrait.trait_key))).scalars())
        return [trait_public(trait) for trait in traits]

    async def set_trait_status(self, trait_id: str, status: str, *, actor: str) -> dict[str, Any]:
        if status not in TRAIT_STATUSES:
            raise AppError(ErrorCode.VALIDATION_ERROR, "特征状态无效。", status_code=400)
        async with self.database.session() as session:
            trait = await session.get(PersonaTrait, trait_id)
            if trait is None:
                raise AppError(ErrorCode.NOT_FOUND, "人格特征不存在。", status_code=404)
            persona = await session.get(Persona, trait.persona_id)
            if persona is None:
                raise AppError(ErrorCode.PERSONA_NOT_FOUND, "人格不存在。", status_code=404)
            if is_locked(persona, trait.trait_key):
                raise AppError(ErrorCode.PERSONA_LOCKED_FIELD, "该特征已被用户锁定。", status_code=409)
            trait.status = status
            if status == "stable":
                trait.locked_by_user = False
            await session.commit()
            await session.refresh(trait)
            public = trait_public(trait)
        await write_audit(
            self.database,
            action=f"persona.trait.{status}",
            target_type="persona_trait",
            target_id=trait_id,
            details={"persona_id": public["persona_id"], "trait_key": public["trait_key"]},
            actor=actor,
        )
        return public

    async def set_trait_locked(self, trait_id: str, locked: bool, *, actor: str) -> dict[str, Any]:
        async with self.database.session() as session:
            trait = await session.get(PersonaTrait, trait_id)
            if trait is None:
                raise AppError(ErrorCode.NOT_FOUND, "人格特征不存在。", status_code=404)
            trait.locked_by_user = locked
            await session.commit()
            await session.refresh(trait)
            public = trait_public(trait)
        await write_audit(
            self.database,
            action="persona.trait.lock" if locked else "persona.trait.unlock",
            target_type="persona_trait",
            target_id=trait_id,
            details={"persona_id": public["persona_id"], "trait_key": public["trait_key"]},
            actor=actor,
        )
        return public

    async def delete_trait(self, trait_id: str, *, actor: str) -> None:
        async with self.database.session() as session:
            trait = await session.get(PersonaTrait, trait_id)
            if trait is None:
                raise AppError(ErrorCode.NOT_FOUND, "人格特征不存在。", status_code=404)
            if trait.locked_by_user:
                raise AppError(ErrorCode.PERSONA_LOCKED_FIELD, "锁定中的特征不能删除，请先解锁。", status_code=409)
            persona_id = trait.persona_id
            trait_key = trait.trait_key
            await session.delete(trait)
            await session.commit()
        await write_audit(
            self.database,
            action="persona.trait.delete",
            target_type="persona_trait",
            target_id=trait_id,
            details={"persona_id": persona_id, "trait_key": trait_key},
            actor=actor,
        )

    async def delete_evidence(self, message_id: str, *, actor: str = "system") -> dict[str, Any]:
        """删除来源消息后清理特征证据；证据不足的稳定特征降级为候选。"""
        affected = 0
        demoted = 0
        async with self.database.session() as session:
            traits = list((await session.execute(select(PersonaTrait))).scalars())
            personas = {persona.id: persona for persona in (await session.execute(select(Persona))).scalars()}
            for trait in traits:
                evidence = list(trait.evidence_message_ids_json or [])
                if message_id not in evidence:
                    continue
                evidence = [item for item in evidence if item != message_id]
                trait.evidence_message_ids_json = evidence
                trait.evidence_count = len(evidence)
                affected += 1
                persona = personas.get(trait.persona_id)
                threshold = int(persona_thresholds(persona)["min_evidence_count"]) if persona else 3
                if trait.status == "stable" and len(evidence) < threshold:
                    trait.status = "candidate"
                    demoted += 1
            await session.commit()
        if affected:
            await write_audit(
                self.database,
                action="persona.evidence.delete",
                target_type="message",
                target_id=message_id,
                details={"affected_traits": affected, "demoted_traits": demoted},
                actor=actor,
            )
        return {"affected_traits": affected, "demoted_traits": demoted}

    async def prune_evidence(self, message_ids: set[str], *, actor: str = "system") -> dict[str, int]:
        """批量清理被删消息的人格证据、待审提案与版本快照引用。"""
        result = {
            "affected_traits": 0,
            "demoted_traits": 0,
            "events_updated": 0,
            "proposals_rejected": 0,
            "versions_updated": 0,
        }
        if not message_ids:
            return result
        async with self.database.session() as session:
            traits = list((await session.execute(select(PersonaTrait))).scalars())
            personas = {persona.id: persona for persona in (await session.execute(select(Persona))).scalars()}
            for trait in traits:
                evidence = [str(item) for item in (trait.evidence_message_ids_json or [])]
                if not set(evidence) & message_ids:
                    continue
                evidence = [item for item in evidence if item not in message_ids]
                trait.evidence_message_ids_json = evidence
                trait.evidence_count = len(evidence)
                result["affected_traits"] += 1
                persona = personas.get(trait.persona_id)
                threshold = int(persona_thresholds(persona)["min_evidence_count"]) if persona else 3
                if trait.status == "stable" and len(evidence) < threshold:
                    trait.status = "candidate"
                    result["demoted_traits"] += 1

            for event in (await session.execute(select(PersonaEvolutionEvent))).scalars():
                changed = False
                for attr in ("proposal_json", "old_state_json", "new_state_json"):
                    value = getattr(event, attr) or {}
                    new_value, scrubbed = _scrub_evidence_refs(value, message_ids)
                    if scrubbed:
                        setattr(event, attr, new_value)
                        changed = True
                if event.trigger_message_id and str(event.trigger_message_id) in message_ids:
                    event.trigger_message_id = None
                    changed = True
                if changed:
                    result["events_updated"] += 1
                if event.result == "pending_review":
                    proposal = dict(event.proposal_json or {})
                    traits_in_proposal = proposal.get("proposed_traits") or []
                    has_evidence = any(
                        (item or {}).get("evidence_message_ids")
                        for item in traits_in_proposal
                        if isinstance(item, dict)
                    )
                    if not has_evidence:
                        event.result = "rejected"
                        event.reviewed_at = utcnow()
                        event.error_message = "证据消息已被保留策略删除，提案自动拒绝。"
                        result["proposals_rejected"] += 1

            for version in (await session.execute(select(PersonaVersion))).scalars():
                snapshot, scrubbed = _scrub_evidence_refs(dict(version.snapshot_json or {}), message_ids)
                if scrubbed:
                    version.snapshot_json = snapshot
                    result["versions_updated"] += 1
            await session.commit()

        if any(result.values()):
            await write_audit(
                self.database,
                action="persona.evidence.batch_delete",
                target_type="message_batch",
                details={**result, "message_count": len(message_ids)},
                actor=actor,
            )
        return result

    async def list_events(self, persona_id: str, *, limit: int = 50) -> list[dict[str, Any]]:
        async with self.database.session() as session:
            events = list(
                (
                    await session.execute(
                        select(PersonaEvolutionEvent)
                        .where(PersonaEvolutionEvent.persona_id == persona_id)
                        .order_by(PersonaEvolutionEvent.created_at.desc())
                        .limit(max(1, min(limit, 200)))
                    )
                ).scalars()
            )
        return [event_public(event) for event in events]

    async def list_versions(self, persona_id: str) -> list[dict[str, Any]]:
        async with self.database.session() as session:
            versions = list(
                (
                    await session.execute(
                        select(PersonaVersion)
                        .where(PersonaVersion.persona_id == persona_id)
                        .order_by(PersonaVersion.version_no.desc())
                    )
                ).scalars()
            )
        return [version_public(version) for version in versions]

    async def rollback(
        self,
        persona_id: str,
        version_id: str,
        *,
        actor: str = "local-admin",
    ) -> dict[str, Any]:
        async with self.database.session() as session:
            persona = await session.get(Persona, persona_id)
            if persona is None:
                raise AppError(ErrorCode.PERSONA_NOT_FOUND, "人格不存在。", status_code=404)
            version = await session.get(PersonaVersion, version_id)
            if version is None or version.persona_id != persona_id:
                raise AppError(ErrorCode.NOT_FOUND, "人格版本不存在。", status_code=404)
            if not version.restorable:
                raise AppError(ErrorCode.PERSONA_VERSION_NOT_RESTORABLE, "该版本不可回滚。", status_code=409)
            snapshot = dict(version.snapshot_json or {})
            apply_snapshot_config(persona, snapshot)
            await session.execute(delete(PersonaTrait).where(PersonaTrait.persona_id == persona_id))
            for item in snapshot.get("traits") or []:
                session.add(
                    PersonaTrait(
                        persona_id=persona_id,
                        trait_key=str(item.get("trait_key") or "")[:128],
                        trait_value=str(item.get("trait_value") or "")[:1000],
                        category=str(item.get("category") or "style")[:64],
                        confidence=float(item.get("confidence") or 0.0),
                        evidence_count=int(item.get("evidence_count") or 0),
                        evidence_message_ids_json=list(item.get("evidence_message_ids") or []),
                        source_scope=str(item.get("source_scope") or "global")[:128],
                        status=str(item.get("status") or "candidate"),
                        locked_by_user=bool(item.get("locked_by_user")),
                        first_observed_at=_parse_dt(item.get("first_observed_at")),
                        last_observed_at=_parse_dt(item.get("last_observed_at")),
                    )
                )
            await session.flush()
            new_snapshot = await self._snapshot(session, persona)
            new_version = await self._add_version(
                session,
                persona,
                summary=f"回滚到版本 {version.version_no}",
                actor=actor,
                snapshot=new_snapshot,
            )
            await session.commit()
            await session.refresh(persona)
            public = await self._public(session, persona)
        await write_audit(
            self.database,
            action="persona.rollback",
            target_type="persona",
            target_id=persona_id,
            details={"restored_version": version.version_no, "new_version": new_version.version_no},
            actor=actor,
        )
        return public

    async def reset(self, persona_id: str, *, actor: str = "local-admin") -> dict[str, Any]:
        async with self.database.session() as session:
            persona = await session.get(Persona, persona_id)
            if persona is None:
                raise AppError(ErrorCode.PERSONA_NOT_FOUND, "人格不存在。", status_code=404)
            if persona.mode != "emergent":
                raise AppError(
                    ErrorCode.PERSONA_RESET_UNSUPPORTED,
                    "只有空白自成长人格支持重置。",
                    status_code=409,
                )
            persona.self_description = None
            await session.execute(delete(PersonaTrait).where(PersonaTrait.persona_id == persona_id))
            await session.flush()
            new_snapshot = await self._snapshot(session, persona)
            version = await self._add_version(
                session,
                persona,
                summary="重置为空白的自成长人格",
                actor=actor,
                snapshot=new_snapshot,
            )
            await session.commit()
            await session.refresh(persona)
            public = await self._public(session, persona)
        await write_audit(
            self.database,
            action="persona.reset",
            target_type="persona",
            target_id=persona_id,
            details={"version_no": version.version_no},
            actor=actor,
        )
        return public

    async def active_traits_for_prompt(
        self,
        persona_id: str,
        *,
        group_id: str | None = None,
        limit: int = 20,
    ) -> list[PersonaTrait]:
        scopes = ["global"]
        if group_id:
            scopes.append(group_id)
        async with self.database.session() as session:
            traits = list(
                (
                    await session.execute(
                        select(PersonaTrait)
                        .where(
                            PersonaTrait.persona_id == persona_id,
                            PersonaTrait.status == "stable",
                            PersonaTrait.source_scope.in_(scopes),
                        )
                        .order_by(PersonaTrait.confidence.desc())
                        .limit(limit)
                    )
                ).scalars()
            )
        return traits

    async def _public(self, session: AsyncSession, persona: Persona) -> dict[str, Any]:
        stable_count = int(
            await session.scalar(
                select(func.count(PersonaTrait.id)).where(
                    PersonaTrait.persona_id == persona.id,
                    PersonaTrait.status == "stable",
                )
            )
            or 0
        )
        candidate_count = int(
            await session.scalar(
                select(func.count(PersonaTrait.id)).where(
                    PersonaTrait.persona_id == persona.id,
                    PersonaTrait.status == "candidate",
                )
            )
            or 0
        )
        latest_version = await session.scalar(
            select(func.max(PersonaVersion.version_no)).where(PersonaVersion.persona_id == persona.id)
        )
        return {
            "id": persona.id,
            "name": persona.name,
            "mode": persona.mode,
            "mode_label": PERSONA_MODE_LABELS.get(persona.mode, persona.mode),
            "template_key": persona.template_key,
            "self_description": persona.self_description or "",
            "authored_fields": dict(persona.authored_fields_json or {}),
            "system_prompt_overlay": persona.system_prompt_overlay or "",
            "growth_policy": persona.growth_policy,
            "growth_enabled": persona.growth_enabled,
            "learning_scope": persona.learning_scope,
            "thresholds": persona_thresholds(persona),
            "locked_fields": list(persona.locked_fields_json or []),
            "enabled": persona.enabled,
            "notes": persona.notes or "",
            "last_growth_at": persona.last_growth_at.isoformat() if persona.last_growth_at else None,
            "stable_trait_count": stable_count,
            "candidate_trait_count": candidate_count,
            "latest_version": int(latest_version or 0),
            "created_at": persona.created_at.isoformat() if persona.created_at else None,
            "updated_at": persona.updated_at.isoformat() if persona.updated_at else None,
        }

    async def _snapshot(
        self,
        session: AsyncSession,
        persona: Persona,
        *,
        trait_status: str | None = None,
    ) -> dict[str, Any]:
        query = select(PersonaTrait).where(PersonaTrait.persona_id == persona.id)
        if trait_status:
            query = query.where(PersonaTrait.status == trait_status)
        traits = list(
            (await session.execute(query.order_by(PersonaTrait.trait_key, PersonaTrait.source_scope))).scalars()
        )
        return {
            "name": persona.name,
            "enabled": persona.enabled,
            "notes": persona.notes,
            "mode": persona.mode,
            "template_key": persona.template_key,
            "self_description": persona.self_description,
            "authored_fields": dict(persona.authored_fields_json or {}),
            "system_prompt_overlay": persona.system_prompt_overlay,
            "growth_policy": persona.growth_policy,
            "growth_enabled": persona.growth_enabled,
            "learning_scope": persona.learning_scope,
            "thresholds": dict(persona.thresholds_json or {}),
            "locked_fields": list(persona.locked_fields_json or []),
            "traits": [
                {
                    "trait_key": trait.trait_key,
                    "trait_value": trait.trait_value,
                    "category": trait.category,
                    "confidence": trait.confidence,
                    "evidence_count": trait.evidence_count,
                    "evidence_message_ids": list(trait.evidence_message_ids_json or []),
                    "source_scope": trait.source_scope,
                    "status": trait.status,
                    "locked_by_user": trait.locked_by_user,
                    "first_observed_at": trait.first_observed_at.isoformat() if trait.first_observed_at else None,
                    "last_observed_at": trait.last_observed_at.isoformat() if trait.last_observed_at else None,
                }
                for trait in traits
            ],
        }

    async def _add_version(
        self,
        session: AsyncSession,
        persona: Persona,
        *,
        summary: str,
        actor: str,
        snapshot: dict[str, Any],
    ) -> PersonaVersion:
        latest = await session.scalar(
            select(func.max(PersonaVersion.version_no)).where(PersonaVersion.persona_id == persona.id)
        )
        version = PersonaVersion(
            persona_id=persona.id,
            version_no=int(latest or 0) + 1,
            change_summary=summary[:500],
            snapshot_json=snapshot,
            created_by=actor[:64],
        )
        session.add(version)
        await session.flush()
        return version


def _parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return None


def _snapshot_summary(snapshot: dict[str, Any]) -> dict[str, Any]:
    return {
        "mode": snapshot.get("mode"),
        "self_description_length": len(str(snapshot.get("self_description") or "")),
        "trait_count": len(snapshot.get("traits") or []),
    }

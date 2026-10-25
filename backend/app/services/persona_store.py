"""人格档案 CRUD、特征治理、版本快照与回滚。"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError, ErrorCode
from app.db.session import Database
from app.models.group import Group
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
    return {
        "id": event.id,
        "persona_id": event.persona_id,
        "batch_id": event.batch_id,
        "trigger_type": event.trigger_type,
        "trigger_message_id": event.trigger_message_id,
        "group_id": event.group_id,
        "summary": event.summary,
        "evidence_summary": event.evidence_summary,
        "confidence": round(event.confidence, 2),
        "result": event.result,
        "rule_version": event.rule_version,
        "error_message": event.error_message,
        "reviewed_at": event.reviewed_at.isoformat() if event.reviewed_at else None,
        "created_at": event.created_at.isoformat() if event.created_at else None,
        "proposal": dict(event.proposal_json or {}),
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

            if "name" in payload:
                name = _clean_str(payload.get("name"), 64)
                if not name:
                    raise AppError(ErrorCode.VALIDATION_ERROR, "人格名称不能为空。", status_code=400)
                persona.name = name
            if "mode" in payload:
                mode = str(payload.get("mode") or "").strip()
                if mode not in PERSONA_MODES:
                    raise AppError(ErrorCode.VALIDATION_ERROR, "人格模式无效。", status_code=400)
                persona.mode = mode
            if "template_key" in payload:
                template_key = _clean_str(payload.get("template_key"), 64) or None
                if template_key is not None and template_key not in PERSONA_TEMPLATES:
                    raise AppError(ErrorCode.VALIDATION_ERROR, "人格模板不存在。", status_code=400)
                persona.template_key = template_key
            if persona.mode == "template" and persona.template_key not in PERSONA_TEMPLATES:
                raise AppError(ErrorCode.VALIDATION_ERROR, "模板模式必须选择有效模板。", status_code=400)
            if "self_description" in payload:
                persona.self_description = _clean_str(payload.get("self_description"), _MAX_DESCRIPTION) or None
            if "authored_fields" in payload:
                persona.authored_fields_json = _clean_authored(payload.get("authored_fields"))
            if "system_prompt_overlay" in payload:
                persona.system_prompt_overlay = _clean_str(payload.get("system_prompt_overlay"), _MAX_OVERLAY)
            if "growth_policy" in payload:
                policy = str(payload.get("growth_policy") or "").strip()
                if policy not in GROWTH_POLICIES:
                    raise AppError(ErrorCode.VALIDATION_ERROR, "成长策略无效。", status_code=400)
                persona.growth_policy = policy
            if "growth_enabled" in payload:
                persona.growth_enabled = bool(payload.get("growth_enabled"))
            if "learning_scope" in payload:
                scope = str(payload.get("learning_scope") or "").strip()
                if scope not in LEARNING_SCOPES:
                    raise AppError(ErrorCode.VALIDATION_ERROR, "学习范围无效。", status_code=400)
                persona.learning_scope = scope
            if "thresholds" in payload:
                persona.thresholds_json = sanitize_thresholds(payload.get("thresholds"))
            if "locked_fields" in payload:
                persona.locked_fields_json = _clean_list(payload.get("locked_fields"))
            if "enabled" in payload:
                persona.enabled = bool(payload.get("enabled"))
            if "notes" in payload:
                persona.notes = _clean_str(payload.get("notes"), 2000) or None

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
            details={"changed_fields": sorted(payload.keys()), "old": _snapshot_summary(old_snapshot)},
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
            persona.mode = str(snapshot.get("mode") or persona.mode)
            persona.template_key = snapshot.get("template_key")
            persona.self_description = snapshot.get("self_description")
            persona.authored_fields_json = dict(snapshot.get("authored_fields") or {})
            persona.system_prompt_overlay = snapshot.get("system_prompt_overlay")
            persona.growth_policy = str(snapshot.get("growth_policy") or persona.growth_policy)
            persona.learning_scope = str(snapshot.get("learning_scope") or persona.learning_scope)
            persona.thresholds_json = dict(snapshot.get("thresholds") or {})
            persona.locked_fields_json = list(snapshot.get("locked_fields") or [])
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

    async def _snapshot(self, session: AsyncSession, persona: Persona) -> dict[str, Any]:
        traits = list(
            (await session.execute(select(PersonaTrait).where(PersonaTrait.persona_id == persona.id))).scalars()
        )
        return {
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

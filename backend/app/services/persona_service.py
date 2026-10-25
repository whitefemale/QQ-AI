"""人格快照加载（提示词只使用已稳定、已授权的信息）。"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import select

from app.db.session import Database
from app.models.persona import DEFAULT_PERSONA_THRESHOLDS, Persona, PersonaTrait

PERSONA_MODE_LABELS = {
    "authored": "用户编写",
    "template": "模板",
    "emergent": "空白自成长",
}

PERSONA_TEMPLATES: dict[str, dict[str, str]] = {
    "friendly_helper": {
        "name": "热心助手",
        "description": "友好、耐心，优先给出清晰实用的建议，不抢话。",
        "self_description": "我乐于帮忙，说话直接但不冒犯，遇到不确定的事会坦白说明。",
    },
    "quiet_observer": {
        "name": "安静群友",
        "description": "只在被点名时回应，语气克制，不主动展开长篇。",
        "self_description": "我话不多，通常先听大家说，只在被问到时简洁回应。",
    },
    "playful_member": {
        "name": "活泼群友",
        "description": "轻松幽默，但不过度刷屏，不冒犯他人。",
        "self_description": "我喜欢用轻松的方式接话，也会注意分寸，不让玩笑变成打扰。",
    },
}


@dataclass
class PersonaSnapshot:
    persona_id: str | None = None
    name: str = "未配置人格"
    mode: str = "emergent"
    template_key: str | None = None
    self_description: str = ""
    authored_fields: dict[str, str] = field(default_factory=dict)
    system_prompt_overlay: str = ""
    stable_traits: list[dict[str, str | float]] = field(default_factory=list)
    locked_fields: list[str] = field(default_factory=list)
    growth_enabled: bool = False
    growth_policy: str = "paused"
    learning_scope: str = "admin_only"
    thresholds: dict[str, float] = field(default_factory=dict)

    @property
    def has_identity(self) -> bool:
        return bool(self.self_description.strip() or self.authored_fields or self.stable_traits)


def default_snapshot() -> PersonaSnapshot:
    return PersonaSnapshot()


async def load_persona_snapshot(
    database: Database,
    persona_id: str | None,
    *,
    group_internal_id: str | None = None,
) -> PersonaSnapshot:
    if not persona_id:
        return default_snapshot()
    async with database.session() as session:
        persona = await session.get(Persona, persona_id)
        if persona is None or not persona.enabled:
            return default_snapshot()
        scopes = ["global"]
        if group_internal_id:
            scopes.append(group_internal_id)
        traits = list(
            (
                await session.execute(
                    select(PersonaTrait)
                    .where(
                        PersonaTrait.persona_id == persona.id,
                        PersonaTrait.status == "stable",
                        PersonaTrait.source_scope.in_(scopes),
                    )
                    .order_by(PersonaTrait.confidence.desc(), PersonaTrait.trait_key)
                )
            ).scalars()
        )
        thresholds = {**DEFAULT_PERSONA_THRESHOLDS, **(persona.thresholds_json or {})}
        authored = {
            str(key): str(value)
            for key, value in (persona.authored_fields_json or {}).items()
            if value is not None and str(value).strip()
        }
        return PersonaSnapshot(
            persona_id=persona.id,
            name=persona.name,
            mode=persona.mode,
            template_key=persona.template_key,
            self_description=(persona.self_description or "").strip(),
            authored_fields=authored,
            system_prompt_overlay=(persona.system_prompt_overlay or "").strip(),
            stable_traits=[
                {
                    "key": trait.trait_key,
                    "value": trait.trait_value,
                    "category": trait.category,
                    "confidence": round(trait.confidence, 2),
                }
                for trait in traits
            ],
            locked_fields=list(persona.locked_fields_json or []),
            growth_enabled=persona.growth_enabled,
            growth_policy=persona.growth_policy,
            learning_scope=persona.learning_scope,
            thresholds={str(key): float(value) for key, value in thresholds.items()},
        )

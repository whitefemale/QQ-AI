"""人格成长提案 DTO（只保留可治理的结构化字段，不保存推理链）。"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class GrowthInteraction(BaseModel):
    """触发本次成长反思的最近一轮对话；只用于提示词，不落库。"""

    user_message: str = ""
    assistant_reply: str = ""
    message_id: str | None = None

    def sanitized(self, max_chars: int = 600) -> GrowthInteraction:
        return GrowthInteraction(
            user_message=self.user_message.strip()[:max_chars],
            assistant_reply=self.assistant_reply.strip()[:max_chars],
            message_id=(self.message_id or "").strip()[:128] or None,
        )


class TraitProposal(BaseModel):
    trait_key: str = ""
    trait_value: str = ""
    category: str = "style"
    confidence: float = 0.0
    evidence_message_ids: list[str] = Field(default_factory=list)


class PersonaProposal(BaseModel):
    self_description: str | None = None
    proposed_traits: list[TraitProposal] = Field(default_factory=list)
    summary: str = ""
    scope: str | None = None
    # 第一人称自然语言变化摘要；不保存推理过程或原始 diff。
    diff_summary: str | None = None


class ProposalDocument(BaseModel):
    """模型输出仅接受以下字段，其余内容一律丢弃。"""

    self_description: str | None = None
    proposed_traits: list[TraitProposal] = Field(default_factory=list)
    summary: str = ""
    scope: str | None = None
    diff_summary: str | None = None

    def sanitized(self, max_traits: int, max_description: int = 1500) -> dict[str, Any]:
        description = (self.self_description or "").strip()[:max_description] or None
        traits = []
        for trait in self.proposed_traits[:max_traits]:
            traits.append(
                {
                    "trait_key": trait.trait_key.strip(),
                    "trait_value": trait.trait_value.strip(),
                    "category": trait.category.strip(),
                    "confidence": trait.confidence,
                    "evidence_message_ids": list(dict.fromkeys(trait.evidence_message_ids)),
                }
            )
        return {
            "self_description": description,
            "proposed_traits": traits,
            "summary": self.summary.strip()[:500],
            "scope": (self.scope or "").strip()[:128] or None,
            "diff_summary": (self.diff_summary or "").strip()[:600] or None,
        }

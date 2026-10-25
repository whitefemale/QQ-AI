"""AI 记忆提取的结构化输出。"""

from __future__ import annotations

from pydantic import BaseModel, Field


class MemoryCandidateItem(BaseModel):
    content: str = ""
    memory_type: str = "fact"
    confidence: float = 0.0
    member_id: str | None = None
    evidence_message_ids: list[str] = Field(default_factory=list)


class MemoryExtractionDocument(BaseModel):
    items: list[MemoryCandidateItem] = Field(default_factory=list)

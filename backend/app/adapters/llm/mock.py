"""Mock LLM Provider：明确标记为模拟，不冒充真实模型。"""

from __future__ import annotations

import json
from typing import Any

from app.adapters.llm.base import BaseLLMProvider
from app.core.security import redact_text
from app.schemas.llm import LLMRequest, LLMResponse, LLMToolCall, ModelListResult


class MockLLMProvider(BaseLLMProvider):
    provider_type = "mock"
    is_mock = True

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._scripted_index = 0

    def _last_user_text(self, request: LLMRequest) -> str:
        for message in reversed(request.messages):
            if message.get("role") == "user":
                content = message.get("content")
                if isinstance(content, str):
                    return content[-2000:]
                if isinstance(content, list):
                    parts = [str(item.get("text", "")) for item in content if isinstance(item, dict)]
                    return "".join(parts)[-2000:]
        return ""

    def _estimate_tokens(self, text: str) -> int:
        return max(1, len(text) // 3)

    def _growth_response(self, request: LLMRequest) -> str:
        configured = self.config.get("mock_growth_proposal")
        evidence_ids = list(request.metadata.get("evidence_ids") or [])
        if configured:
            proposal = dict(configured)
            if not proposal.get("proposed_traits"):
                return json.dumps(proposal, ensure_ascii=False)
            for trait in proposal.get("proposed_traits", []):
                trait.setdefault("evidence_message_ids", evidence_ids[:5])
            return json.dumps(proposal, ensure_ascii=False)
        evidence = evidence_ids[:5]
        proposal = {
            "self_description": (
                "（Mock 模拟）在最近的交流中，我发现自己更习惯用轻松、简短的方式接话，也愿意先听大家说完再回应。"
            ),
            "proposed_traits": [
                {
                    "trait_key": "reply_style",
                    "trait_value": "偏好轻松、简短的回应方式",
                    "category": "style",
                    "confidence": 0.82,
                    "evidence_message_ids": evidence,
                    "reason_summary": "多次交流中均主动选择简短、轻松的表述。",
                }
            ],
            "summary": "Mock 模拟的人格自我提案，仅用于演示成长流程。",
            "scope": "global",
            "diff_summary": (
                "（Mock 模拟）我在这次对话中更清楚地意识到，自己习惯先听完大家的话，再用轻松简短的方式接话。"
            ),
        }
        return json.dumps(proposal, ensure_ascii=False)

    def _memory_extraction_response(self, request: LLMRequest) -> str:
        evidence_ids = [str(item) for item in request.metadata.get("evidence_ids") or []]
        configured = self.config.get("mock_memory_candidates")
        if isinstance(configured, list):
            items = [dict(item) for item in configured if isinstance(item, dict)]
            for item in items:
                if not item.get("evidence_message_ids"):
                    item["evidence_message_ids"] = evidence_ids[:2]
            return json.dumps({"items": items}, ensure_ascii=False)
        items = [
            {
                "content": "（Mock 模拟）群成员近期在讨论固定的项目同步节奏。",
                "memory_type": "project",
                "confidence": 0.72,
                "member_id": None,
                "evidence_message_ids": evidence_ids[:2],
            }
        ]
        return json.dumps({"items": items}, ensure_ascii=False)

    async def generate(self, request: LLMRequest) -> LLMResponse:
        if request.purpose == "persona_growth":
            text = self._growth_response(request)
        elif request.purpose == "memory_extraction":
            text = self._memory_extraction_response(request)
        else:
            scripted = self.config.get("scripted_replies") or []
            if scripted:
                index = min(self._scripted_index, len(scripted) - 1)
                text = str(scripted[index])
                self._scripted_index += 1
            elif request.purpose == "test":
                text = "Mock 模型连接正常。"
            else:
                last = redact_text(self._last_user_text(request)).strip()
                prefix = str(self.config.get("mock_prefix", "（模拟回复）"))
                template = str(self.config.get("reply_template", "{prefix}我收到了你的消息：{text}"))
                text = template.replace("{prefix}", prefix).replace("{text}", last[:120] or "（空消息）")
                text = text[: request.max_output_tokens * 4]

        tool_calls: list[LLMToolCall] = []
        if request.tools and self.config.get("emit_tool_call"):
            tool = request.tools[0]
            name = tool.get("function", {}).get("name") or tool.get("name") or "calculator"
            tool_calls.append(LLMToolCall(id="mock-call-1", name=name, arguments={"expression": "1+1"}))

        prompt_size = len(request.system_prompt) + sum(len(str(m)) for m in request.messages)
        return LLMResponse(
            text=text,
            tool_calls=tool_calls,
            input_tokens=self._estimate_tokens("x" * prompt_size),
            output_tokens=self._estimate_tokens(text),
            finish_reason="stop",
            request_id=f"mock-{id(request)}",
            raw={"mock": True},
        )

    async def list_models(self, timeout_seconds: float | None = None) -> ModelListResult:
        return ModelListResult(
            supported=False,
            state="mock",
            current_model_listed=None,
            message="Mock 模型没有远端模型列表；这不是真实服务商能力。",
            note="Mock 仅用于本地流程测试。",
        )

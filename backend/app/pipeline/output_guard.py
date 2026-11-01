"""回复输出审查：敏感内容、空文本、控制字符、全员 @ 与长度。

编排器、命令回复、人工批准与 outbox 发送前共用同一入口，避免某条路径绕过。
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.core.security import redact_text
from app.core.sensitive import contains_sensitive_secret

_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_MASS_MENTION = re.compile(r"@(?:全体成员|所有人|all(?![A-Za-z0-9_]))", re.IGNORECASE)

REASON_SENSITIVE = "sensitive_output"
REASON_EMPTY = "empty_output"
REASON_TOO_LONG = "output_too_long"


@dataclass(frozen=True)
class OutputInspection:
    text: str
    blocked: bool = False
    reason: str | None = None

    @property
    def ok(self) -> bool:
        return not self.blocked


def sanitize_reply(text: str, max_chars: int) -> str:
    """去控制字符、去除全员 @、限制长度，避免把 Markdown 原样发出。"""
    cleaned = _CONTROL_CHARS.sub("", str(text or ""))
    cleaned = _MASS_MENTION.sub("大家", cleaned)
    cleaned = re.sub(r"```[a-zA-Z0-9_-]*\n?", "", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
    cleaned = redact_text(cleaned)
    if len(cleaned) > max_chars:
        cleaned = cleaned[: max(0, max_chars - 1)].rstrip() + "…"
    return cleaned.strip()


def inspect_output(text: str, max_chars: int, *, truncate: bool = True) -> OutputInspection:
    """检查待发送文本。

    `truncate=True` 用于生成阶段：超长时安全截断。
    `truncate=False` 用于批准与真正发送前：超长直接拦截，避免旧队列绕过新上限。
    """
    raw = str(text or "")
    if contains_sensitive_secret(raw):
        return OutputInspection("", blocked=True, reason=REASON_SENSITIVE)
    cleaned = sanitize_reply(raw, max_chars if truncate else 10**9)
    if not cleaned:
        return OutputInspection("", blocked=True, reason=REASON_EMPTY)
    if not truncate and len(cleaned) > max_chars:
        return OutputInspection("", blocked=True, reason=REASON_TOO_LONG)
    return OutputInspection(cleaned)

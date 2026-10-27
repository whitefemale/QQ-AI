"""检测用户是否在询问 AI 群友的自我认知。

只做轻量文本匹配，不解析、不执行消息内容，也不调用模型：
- 仅用于在正常回复完成后决定是否安排一次受治理的人格反思；
- 跳过以 `/` 开头的管理命令；
- 限制消息长度并避免回溯型正则，防止 ReDoS；
- 命中不代表会修改人格，成长仍受证据、阈值、锁定字段与审核策略约束。
"""

from __future__ import annotations

import re

MAX_INQUIRY_CHARS = 200

# 先排除看起来像“你是谁做的/写的”这类询问开发者的问题。
_DEVELOPER_QUESTION = re.compile(r"你(?:到底|究竟)?(?:是|算)(?:谁|什么).{0,6}(?:写|做|开发|创建|训练|设计|构造|部署)的")
_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"你是谁",
        r"你(?:到底|究竟)?(?:是|算)(?:谁|什么(?:来头|角色|东西))",
        r"你(?:的)?(?:人设|设定|性格|角色设定|身份)(?:是(?:什么|啥)?|怎么样|如何|呢|吗)",
        r"你(?:有|有没有|有没)(?:人设|设定|性格)",
        r"(?:介绍|说说|讲讲|聊聊|描述)(?:一下)?(?:你(?:自己|的人设|的设定|的性格))",
        r"自我介绍",
        r"你(?:叫什么(?:名字)?|叫啥)",
        r"\bwho\s+are\s+you\b",
        r"\bwhat\s+are\s+you\b",
        r"\byour\s+(?:persona|personality|character|identity)\b",
        r"\b(?:describe|introduce)\s+yourself\b",
        r"\btell\s+me\s+about\s+yourself\b",
        r"\bwhat(?:'s|\s+is)\s+your\s+name\b",
        r"\bdo\s+you\s+have\s+a\s+(?:persona|personality)\b",
    )
)


def detect_self_inquiry(text: str | None, *, max_chars: int = MAX_INQUIRY_CHARS) -> bool:
    """判断一条用户消息是否在询问 AI 群友自身的人设/身份。

    管理命令（`/` 开头）与超长消息直接返回 False；匹配结果只用于调度成长反思。
    """
    if not text:
        return False
    stripped = text.strip()
    if not stripped or stripped[0] in {"/", "／"}:
        return False
    if len(stripped) > max_chars:
        return False
    if _DEVELOPER_QUESTION.search(stripped):
        return False
    return any(pattern.search(stripped) for pattern in _PATTERNS)


__all__ = ["MAX_INQUIRY_CHARS", "detect_self_inquiry"]

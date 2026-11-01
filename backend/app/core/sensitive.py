"""记忆写入与回复输出共用的敏感信息识别。

规则只匹配明确的凭证/验证码/证件号/银行卡/API Key 上下文，避免把普通长文本
当成敏感内容。输出侧命中后直接拦截，不做“自动打码后照常发送”。
"""

from __future__ import annotations

import re

SECRET_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(
        r"(?i)(密码|口令|验证码|支付密码|银行卡|身份证号|信用卡|cvv|password|passcode)"
        r"\s*[:：=是为]\s*\S+"
    ),
    # 银行卡：带上下文，或 4 位一组的分隔格式。裸的 16~19 位数字可能是订单号/时间戳，
    # 不应仅凭长度判定为凭证。
    re.compile(r"(?i)(银行卡|信用卡|卡号|bank\s*card|card\s*number)[^\n]{0,12}(?:\d[ -]?){16,19}(?!\d)"),
    re.compile(r"(?<!\d)(?:\d{4}[ -]){3}\d{3,4}(?!\d)"),
    # 身份证：要求“身份证/证件号”上下文，或 17 位数字 + X 校验位。
    re.compile(r"(?i)(身份证|证件号|id\s*card)[^\n]{0,8}(?:\d[ -]?){17}[\dXx]"),
    re.compile(r"(?<!\d)\d{17}[\dXx](?!\d)"),
    re.compile(r"(?i)\b(?:sk|pk|rk)-[A-Za-z0-9_-]{16,}\b"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
)


def contains_sensitive_secret(text: str) -> bool:
    """是否命中明确的敏感凭证模式。"""
    value = str(text or "")
    return any(pattern.search(value) for pattern in SECRET_PATTERNS)

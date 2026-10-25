"""凭证加密、掩码与日志脱敏。"""

from __future__ import annotations

import ipaddress
import re
from typing import Any

from cryptography.fernet import Fernet, InvalidToken

from app.core.errors import AppError, ErrorCode

_PREFIX = "enc:v1:"

_REDACT_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"(?i)(authorization\s*[:=]\s*)(bearer\s+)?[^\s,;\"']+"), r"\1\2[REDACTED]"),
    (re.compile(r"(?i)(access_token=)[^&\s\"']+"), r"\1[REDACTED]"),
    (
        re.compile(
            r"(?i)((?:api[_-]?key|token|password|secret|authorization)"
            r"[\"']?\s*[:=]\s*[\"']?)[^\s,;&\"'}]+"
        ),
        r"\1[REDACTED]",
    ),
    (re.compile(r"sk-[A-Za-z0-9_\-]{8,}"), "[REDACTED_API_KEY]"),
    (re.compile(r"(?i)(https?://[^:/\s]+:)[^@/\s]+(@)"), r"\1[REDACTED]\2"),
]


def redact_text(value: str) -> str:
    """对自由文本做防御性脱敏，供日志与诊断使用。"""
    redacted = value
    for pattern, replacement in _REDACT_PATTERNS:
        redacted = pattern.sub(replacement, redacted)
    return redacted


def redact_value(value: Any, *, depth: int = 0) -> Any:
    if depth > 6:
        return "[TRUNCATED]"
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, item in value.items():
            lowered = str(key).lower()
            secret_markers = ("token", "key", "secret", "password", "authorization", "credential")
            if any(secret in lowered for secret in secret_markers):
                result[str(key)] = "[REDACTED]"
            else:
                result[str(key)] = redact_value(item, depth=depth + 1)
        return result
    if isinstance(value, (list, tuple)):
        return [redact_value(item, depth=depth + 1) for item in value]
    return value


def mask_secret(value: str | None) -> str:
    if not value:
        return ""
    if len(value) <= 8:
        return "••••••••"
    return f"{value[:4]}••••{value[-4:]}"


def is_loopback_host(host: str | None) -> bool:
    if not host:
        return False
    if host in {"localhost", "testclient", "testserver"}:
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def is_private_host(host: str | None) -> bool:
    if not host:
        return False
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return False
    return address.is_loopback or address.is_private


class CredentialCipher:
    """使用 Fernet 对连接 Token / API Key 做应用层加密。"""

    def __init__(self, key: str) -> None:
        self._fernet: Fernet | None = None
        self._error: str | None = None
        if not key.strip():
            self._error = "未配置 CREDENTIAL_ENCRYPTION_KEY"
            return
        try:
            self._fernet = Fernet(key.strip().encode("utf-8"))
        except (ValueError, TypeError) as exc:
            self._error = f"CREDENTIAL_ENCRYPTION_KEY 格式无效: {type(exc).__name__}"

    @property
    def available(self) -> bool:
        return self._fernet is not None

    def _require(self) -> Fernet:
        if self._fernet is None:
            raise AppError(
                ErrorCode.CREDENTIAL_KEY_MISSING,
                "尚未配置本地凭证加密密钥，无法安全保存或使用 Token/API Key。"
                "请运行 scripts/gen_keys.py 生成密钥并写入 .env。",
                status_code=503,
                details={"reason": self._error},
            )
        return self._fernet

    def encrypt(self, value: str | None) -> str | None:
        if not value:
            return None
        token = self._require().encrypt(value.encode("utf-8")).decode("utf-8")
        return _PREFIX + token

    def decrypt(self, value: str | None) -> str | None:
        if not value:
            return None
        if not value.startswith(_PREFIX):
            raise AppError(
                ErrorCode.CREDENTIAL_DECRYPT_FAILED,
                "凭证格式无效，无法解密。",
                status_code=500,
            )
        try:
            return self._require().decrypt(value[len(_PREFIX) :].encode("utf-8")).decode("utf-8")
        except InvalidToken as exc:
            raise AppError(
                ErrorCode.CREDENTIAL_DECRYPT_FAILED,
                "凭证解密失败：加密密钥可能已更换或数据已损坏。",
                status_code=500,
            ) from exc

    def mask_encrypted(self, value: str | None) -> str:
        if not value:
            return ""
        try:
            return mask_secret(self.decrypt(value))
        except AppError:
            return "••••••••（无法解密）"

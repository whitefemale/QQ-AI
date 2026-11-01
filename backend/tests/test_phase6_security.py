"""阶段 6：HTTP 安全边界、CORS/Host 校验、SSRF 收紧、日志脱敏与工具白名单。"""

from __future__ import annotations

import logging
from pathlib import Path

import pytest
from app.adapters.tools.registry import build_default_tool_registry
from app.core.config import Settings
from app.core.errors import AppError
from app.core.logging import RedactionFilter
from app.core.security_headers import CSP_EXEMPT_PATHS
from app.main import create_app
from app.services.provider_service import normalize_base_url
from fastapi.testclient import TestClient


def _write_spa(settings: Settings) -> None:
    dist = Path(settings.frontend_dist)
    dist.mkdir(parents=True, exist_ok=True)
    (dist / "index.html").write_text("<!doctype html><title>控制台</title>", encoding="utf-8")


def test_security_headers_cover_html_and_json(settings: Settings) -> None:
    _write_spa(settings)
    app = create_app(settings)
    with TestClient(app) as client:
        html = client.get("/")
        assert html.status_code == 200
        assert html.headers["content-type"].startswith("text/html")
        assert html.headers["x-content-type-options"] == "nosniff"
        assert html.headers["x-frame-options"] == "DENY"
        assert html.headers["referrer-policy"] == "no-referrer"
        permissions = html.headers["permissions-policy"]
        assert "camera=()" in permissions
        assert "microphone=()" in permissions
        assert "geolocation=()" in permissions
        assert "clipboard-write=(self)" in permissions
        csp = html.headers["content-security-policy"]
        assert "default-src 'self'" in csp
        assert "script-src 'self'" in csp
        assert "object-src 'none'" in csp
        assert "frame-ancestors 'none'" in csp
        assert "connect-src 'self'" in csp

        api = client.get("/api/health")
        assert api.status_code == 200
        assert api.headers["x-content-type-options"] == "nosniff"
        assert api.headers["x-frame-options"] == "DENY"
        assert "content-security-policy" not in api.headers

        docs = client.get("/api/docs")
        assert docs.status_code == 200
        assert docs.headers["x-content-type-options"] == "nosniff"
        # Swagger 依赖 CDN 与内联脚本，文档页刻意跳过 CSP。
        assert "content-security-policy" not in docs.headers
        assert "/api/docs" in CSP_EXEMPT_PATHS


def test_trusted_host_rejects_unknown_and_allows_configured(settings: Settings) -> None:
    settings.allowed_hosts = "admin.example.test"
    app = create_app(settings)
    with TestClient(app) as client:
        rejected = client.get("/api/health", headers={"Host": "evil.example"})
        assert rejected.status_code == 400
        assert rejected.text == "Invalid host header"
        assert rejected.headers["x-content-type-options"] == "nosniff"
        allowed = client.get("/api/health", headers={"Host": "admin.example.test"})
        assert allowed.status_code == 200
        local = client.get("/api/health", headers={"Host": "127.0.0.1:8000"})
        assert local.status_code == 200


def test_cors_only_echoes_allowlisted_origins(settings: Settings) -> None:
    app = create_app(settings)
    with TestClient(app) as client:
        allowed = client.get("/api/health", headers={"Origin": "http://127.0.0.1:5173"})
        assert allowed.headers.get("access-control-allow-origin") == "http://127.0.0.1:5173"

        preflight = client.options(
            "/api/health",
            headers={
                "Origin": "http://localhost:5173",
                "Access-Control-Request-Method": "GET",
            },
        )
        assert preflight.status_code == 200
        assert preflight.headers.get("access-control-allow-origin") == "http://localhost:5173"

        unknown = client.get("/api/health", headers={"Origin": "https://evil.example"})
        assert "access-control-allow-origin" not in unknown.headers


@pytest.mark.parametrize(
    "value",
    [
        "*",
        "http://127.0.0.1:5173,,http://localhost:5173",
        "ftp://127.0.0.1:5173",
        "http://user:pass@localhost:5173",
        "http://localhost:5173/path",
        "localhost:5173",
    ],
)
def test_invalid_cors_origins_fail_at_startup(settings: Settings, value: str) -> None:
    settings.cors_origins = value
    with pytest.raises(RuntimeError):
        create_app(settings)


def test_remote_admin_guard_requires_explicit_token(settings: Settings) -> None:
    app = create_app(settings)
    with TestClient(app, client=("203.0.113.9", 50000)) as remote:
        denied = remote.get("/api/health")
        assert denied.status_code == 403
        assert denied.json()["error"]["code"] == "REMOTE_ADMIN_FORBIDDEN"

    settings.allow_remote_admin = True
    settings.admin_api_token = "remote-admin-secret"
    app = create_app(settings)
    with TestClient(app, client=("203.0.113.9", 50000)) as remote:
        missing = remote.get("/api/health")
        assert missing.status_code == 401
        assert missing.json()["error"]["code"] == "UNAUTHORIZED"
        wrong = remote.get("/api/health", headers={"X-Admin-Token": "wrong"})
        assert wrong.status_code == 401
        ok = remote.get("/api/health", headers={"X-Admin-Token": "remote-admin-secret"})
        assert ok.status_code == 200
        bearer = remote.get("/api/health", headers={"Authorization": "Bearer remote-admin-secret"})
        assert bearer.status_code == 200

    with TestClient(create_app(settings)) as local:
        assert local.get("/api/health").status_code == 200


@pytest.mark.parametrize(
    "url",
    [
        "http://169.254.169.254/latest/meta-data",
        "http://100.100.100.200/v1",
        "http://100.64.0.1/v1",
        "http://metadata.google.internal/v1",
        "http://METADATA.GOOGLE.INTERNAL./v1",
        "http://metadata.tencentyun.com/v1",
        "http://[fe80::1]/v1",
        "http://0.0.0.0/v1",
        "http://[::]/v1",
        "http://[::ffff:169.254.169.254]/v1",
    ],
)
def test_provider_base_url_rejects_metadata_and_link_local(url: str) -> None:
    with pytest.raises(AppError) as excinfo:
        normalize_base_url(url, "openai_compatible")
    assert excinfo.value.code == "VALIDATION_ERROR"
    assert excinfo.value.status_code == 400


@pytest.mark.parametrize(
    "url",
    [
        "http://localhost:11434/v1",
        "http://127.0.0.1:1234/v1",
        "http://192.168.1.10:8000/v1",
        "http://10.0.0.5/v1",
        "https://api.example.com/v1",
    ],
)
def test_provider_base_url_allows_local_and_private_models(url: str) -> None:
    assert normalize_base_url(url, "openai_compatible") == url


def test_redaction_filter_cleans_message_extra_and_exception_text() -> None:
    record = logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="API_KEY=sk-abcdefghijklmnop token=plain-secret",
        args=(),
        exc_info=None,
    )
    record.token = "plain-token-value"
    record.password = "hunter2"
    record.exc_text = "Authorization: Bearer abcdefghijklmnop"
    RedactionFilter().filter(record)

    rendered = record.getMessage()
    assert "sk-abcdefghijklmnop" not in rendered
    assert "plain-secret" not in rendered
    assert record.token == "[REDACTED]"
    assert record.password == "[REDACTED]"
    assert "abcdefghijklmnop" not in str(record.exc_text)


def test_spa_does_not_serve_files_outside_dist(settings: Settings, tmp_path: Path) -> None:
    secret = tmp_path / "secret.txt"
    secret.write_text("TOP-SECRET", encoding="utf-8")
    app = create_app(settings)
    with TestClient(app) as client:
        for path in ("/../secret.txt", "/%2e%2e%2fsecret.txt", "/..%2fsecret.txt"):
            response = client.get(path)
            assert response.status_code == 404, (path, response.status_code)
            assert "TOP-SECRET" not in response.text
        assert client.get("/assets/../secret.txt").status_code in {404, 405}


def test_tool_registry_exposes_only_builtin_safe_tools() -> None:
    registry = build_default_tool_registry()
    tools = {tool.name: tool for tool in registry.list_tools()}
    assert sorted(tools) == ["calculator", "current_datetime"]
    forbidden = {"shell", "powershell", "python", "file", "read_file", "write_file", "http", "fetch_url", "browser"}
    assert not forbidden & set(tools)
    for tool in tools.values():
        assert tool.risk_level in {"low", "medium"}

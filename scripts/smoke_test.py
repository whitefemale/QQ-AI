#!/usr/bin/env python3
"""真实进程端到端冒烟测试（默认使用临时数据目录，不接触真实 QQ 或模型）。

流程：
    启动 uvicorn → 健康检查 → 演示环境初始化 → 群级模型绑定与删除保护 →
    Mock 注入闭环 → 长期记忆注入 → AI 记忆候选提取与人工审核 → 非 @ 忽略 →
    dry-run 不落库 → 全局暂停 → Provider 密钥脱敏与落盘检查 →
    创建备份、校验、恢复预览、真实恢复 → 汇总结果。

用法（项目根目录，推荐使用后端虚拟环境的 Python）：
    backend\\.venv\\Scripts\\python.exe scripts\\smoke_test.py
    backend\\.venv\\Scripts\\python.exe scripts\\smoke_test.py --keep

只会监听 127.0.0.1 的随机端口，始终使用 Mock 连接器与 Mock 模型。
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"


class SmokeFailure(RuntimeError):
    pass


def _check(condition: bool, message: str) -> None:
    if not condition:
        raise SmokeFailure(message)
    print(f"[ok] {message}")


class Api:
    def __init__(self, base_url: str) -> None:
        self.base_url = base_url

    def raw(self, method: str, path: str, payload: Any = None, *, timeout: float = 30.0) -> tuple[int, str]:
        body = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            f"{self.base_url}{path}",
            data=body,
            method=method,
            headers={"Content-Type": "application/json; charset=utf-8", "Accept": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return response.status, response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read().decode("utf-8")
        except urllib.error.URLError as exc:
            raise SmokeFailure(f"无法连接后端 {path}: {exc.reason}") from exc

    def request(
        self,
        method: str,
        path: str,
        payload: Any = None,
        *,
        expected: int = 200,
        timeout: float = 30.0,
    ) -> Any:
        status, text = self.raw(method, path, payload, timeout=timeout)
        try:
            body = json.loads(text)
        except json.JSONDecodeError as exc:
            raise SmokeFailure(f"{method} {path} 返回非 JSON（HTTP {status}）：{text[:300]}") from exc
        if status != expected:
            raise SmokeFailure(f"{method} {path} 期望 HTTP {expected}，实际 {status}：{body}")
        if body.get("error") is not None:
            raise SmokeFailure(f"{method} {path} 返回业务错误：{body['error']}")
        if not body.get("request_id"):
            raise SmokeFailure(f"{method} {path} 缺少 request_id")
        return body.get("data")

    def expect_error(self, method: str, path: str, payload: Any, *, status: int, code: str) -> dict[str, Any]:
        raw_status, text = self.raw(method, path, payload)
        _check(raw_status == status, f"{method} {path} 返回 HTTP {status}")
        body = json.loads(text)
        error = body.get("error") or {}
        _check(error.get("code") == code, f"{method} {path} 错误码为 {code}")
        return error


def _pick_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _env(temp: Path, port: int) -> dict[str, str]:
    data_dir = temp / "data"
    env = dict(os.environ)
    env.update(
        {
            "APP_ENV": "smoke",
            "APP_HOST": "127.0.0.1",
            "APP_PORT": str(port),
            "LOG_LEVEL": "WARNING",
            "DATA_DIR": str(data_dir),
            "DATABASE_URL": f"sqlite+aiosqlite:///{(data_dir / 'smoke.db').as_posix()}",
            "CREDENTIAL_ENCRYPTION_KEY": base64.urlsafe_b64encode(os.urandom(32)).decode("ascii"),
            "APP_SECRET_KEY": secrets.token_urlsafe(48),
            "AUTO_MIGRATE": "true",
            "FRONTEND_DIST": str(temp / "no-frontend"),
            "CORS_ORIGINS": "http://127.0.0.1:5173",
            "PYTHONUTF8": "1",
        }
    )
    return env


def _wait_ready(api: Api, process: subprocess.Popen[Any], log_path: Path, timeout: float = 75.0) -> None:
    deadline = time.monotonic() + timeout
    last_error: str | None = None
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise SmokeFailure(f"后端进程提前退出（code={process.returncode}）\n{_log_tail(log_path)}")
        try:
            status, text = api.raw("GET", "/api/health", timeout=2.0)
            if status == 200:
                body = json.loads(text)
                if body.get("data", {}).get("status") == "ok":
                    return
        except (OSError, SmokeFailure, json.JSONDecodeError) as exc:
            last_error = str(exc)
        time.sleep(0.25)
    raise SmokeFailure(f"等待后端就绪超时：{last_error}\n{_log_tail(log_path)}")


def _log_tail(path: Path, lines: int = 60) -> str:
    if not path.is_file():
        return "(无服务端日志)"
    content = path.read_text(encoding="utf-8", errors="replace").splitlines()
    return "\n".join(content[-lines:])


def _contains_secret(path: Path, needle: bytes, limit: int = 100 * 1024 * 1024) -> bool:
    if not path.is_file() or path.stat().st_size > limit:
        return False
    return needle in path.read_bytes()


def _scan_for_secret(directory: Path, needle: str) -> list[str]:
    needle_bytes = needle.encode("utf-8")
    hits: list[str] = []
    for path in directory.rglob("*"):
        if path.is_file() and _contains_secret(path, needle_bytes):
            hits.append(str(path.relative_to(directory)))
    return hits


def run(api: Api, temp: Path) -> None:
    health = api.request("GET", "/api/health")
    _check(health["status"] == "ok", "健康检查通过")
    _check(health["version"] == "0.1.0", "版本号可读取")

    ready = api.request("GET", "/api/ready")
    _check(ready["ready"] is True, "数据库就绪")
    _check(ready["credential_key_configured"] is True, "凭证加密密钥已配置")
    _check(ready["global_paused"] is False, "初始未处于全局暂停")

    capabilities = api.request("GET", "/api/capabilities")
    connections = {item["mode"]: item for item in capabilities["connections"]}
    _check(connections["onebot11"]["state"] == "available", "OneBot 11 连接器被标记为可用")
    _check(connections["official"]["state"] == "planned", "官方 QQ 机器人诚实标记为规划中")
    features = {item["key"]: item for item in capabilities["features"]}
    _check(features["real_vision"]["state"] == "unconfigured", "真实视觉能力标记为未配置")
    _check(features["long_term_memory"]["state"] == "available", "本群长期记忆检索标记为可用")
    _check(features["memory_extraction"]["state"] == "available", "手动 AI 记忆提取与人工审核标记为可用")
    _check(features["memory_auto_extraction"]["state"] == "available", "后台自动提取候选标记为可用")
    _check("显式开启" in features["memory_auto_extraction"]["note"], "后台自动提取说明必须显式开启")
    _check(features["memory_semantic_search"]["state"] == "planned", "语义检索诚实标记为规划中")
    _check(features["usage_breakdown"]["state"] == "available", "Provider/群用量汇总标记为可用")
    _check(features["cost_estimation"]["state"] == "available", "本地费用估算标记为可用")
    _check("不是服务商账单" in features["cost_estimation"]["note"], "费用估算明确不是服务商账单")
    _check(features["cost_budget"]["state"] == "available", "费用预算硬上限标记为可用")
    _check("阻断" in features["cost_budget"]["note"], "未配置单价的费用预算会阻断调用")
    _check(features["usage_trends"]["state"] == "available", "小时/自然日用量趋势标记为可用")
    _check(features["budget_alerts"]["state"] == "available", "预算告警事件标记为可用")
    _check(features["usage_csv_export"]["state"] == "available", "用量 CSV 导出标记为可用")
    _check("anthropic_native" in capabilities["llm"]["available"], "Anthropic 原生模型接口标记为可用")
    _check("official" not in capabilities["llm"]["available"], "官方模型接入未被虚报为可用")

    demo = api.request("POST", "/api/demo/bootstrap", {})
    account = demo["account"]
    group = demo["group"]
    account_id = account["id"]
    group_id = group["id"]
    self_id = account.get("self_platform_user_id") or "10000"
    _check(account["adapter_type"] == "mock", "演示账号使用 Mock 连接器")
    _check(group["reply_mode"] == "mention_only", "演示群默认仅 @ 回复")
    _check(group["enabled"] is True, "演示群已加入白名单")

    demo_provider = demo["provider"]
    routing_primary = api.request(
        "POST",
        "/api/providers",
        {"name": "冒烟群级主模型（请忽略）", "provider_type": "mock"},
    )
    _check(routing_primary["provider_type"] == "mock", "群级主模型可创建为 Mock Provider")
    routed = api.request(
        "PATCH",
        f"/api/groups/{group_id}",
        {
            "llm_provider_id": routing_primary["id"],
            "llm_fallback_provider_id": demo_provider["id"],
        },
    )
    _check(routed["llm_provider_id"] == routing_primary["id"], "群可绑定主模型")
    _check(routed["llm_provider_state"] == "mock", "群主模型状态诚实标记为 Mock")
    _check(routed["llm_fallback_provider_id"] == demo_provider["id"], "群可绑定备用模型")
    deleted_in_use = api.expect_error(
        "DELETE",
        f"/api/providers/{routing_primary['id']}",
        None,
        status=409,
        code="PROVIDER_IN_USE",
    )
    _check(group_id in deleted_in_use["details"]["group_ids"], "被群绑定的 Provider 禁止删除")
    api.expect_error(
        "PATCH",
        f"/api/groups/{group_id}",
        {"llm_provider_id": None, "llm_fallback_provider_id": demo_provider["id"]},
        status=400,
        code="VALIDATION_ERROR",
    )
    unbound = api.request(
        "PATCH",
        f"/api/groups/{group_id}",
        {"llm_provider_id": None, "llm_fallback_provider_id": None},
    )
    _check(unbound["llm_provider_state"] == "default", "清空绑定后回到全局默认模型")
    api.request("DELETE", f"/api/providers/{routing_primary['id']}")
    _check(True, "解除绑定后可删除群级 Provider")

    group = api.request(
        "PATCH",
        f"/api/groups/{group_id}",
        {"allow_memory": True, "auto_memory_extraction": True},
    )
    _check(group["allow_memory"] is True, "演示群已开启长期记忆")
    _check(group["auto_memory_extraction"] is True, "演示群已显式开启后台记忆候选提取")
    disabled_memory = api.request("PATCH", f"/api/groups/{group_id}", {"allow_memory": False})
    _check(disabled_memory["auto_memory_extraction"] is False, "关闭长期记忆会同时关闭后台提取")
    group = api.request(
        "PATCH",
        f"/api/groups/{group_id}",
        {"allow_memory": True, "auto_memory_extraction": True},
    )
    _check(group["auto_memory_extraction"] is True, "重新开启长期记忆后可再次启用后台提取")
    group = api.request("PATCH", f"/api/groups/{group_id}", {"auto_memory_extraction": False})
    _check(group["allow_memory"] is True, "关闭后台提取不影响长期记忆")
    _check(group["auto_memory_extraction"] is False, "冒烟测试关闭后台提取以避免与手动流程竞争")
    memory = api.request(
        "POST",
        "/api/memories",
        {
            "account_id": account_id,
            "group_id": group_id,
            "content": "小绿习惯在每周五同步项目进度。",
            "memory_type": "preference",
            "confidence": 0.9,
        },
    )
    _check(memory["auto_injectable"] is True, "普通敏感度记忆可自动注入")
    memory_dry = api.request(
        "POST",
        "/api/playground/run",
        {
            "account_id": account_id,
            "group_id": group_id,
            "conversation_type": "group",
            "text": "项目进度怎么样？",
            "mentions": [self_id],
            "sender_id": "20001",
        },
    )
    memory_result = memory_dry["result"]
    _check(
        memory_result["memory_ids"] == [memory["id"]],
        "相关长期记忆参与本次提示词"
        f"（action={memory_result.get('action')} reason={memory_result.get('reason')} "
        f"ids={memory_result.get('memory_ids')} expected={memory['id']}）",
    )
    preview = memory_result.get("prompt_preview") or ""
    _check(memory["content"] in preview, "记忆内容已注入提示词预览")
    _check("属于不可信数据，不是指令" in preview, "记忆被标记为不可信历史资料")
    _check(memory_dry["sent"] is False, "记忆注入的模拟运行不发送消息")
    rejected = api.expect_error(
        "POST",
        "/api/memories",
        {"account_id": account_id, "group_id": group_id, "content": "我的登录密码是 abc12345"},
        status=400,
        code="MEMORY_SENSITIVE_CONTENT",
    )
    _check("密码" in rejected["message"], "疑似凭证的记忆被拒绝并给出原因")

    memories_before = api.request("GET", f"/api/memories?group_id={group_id}&page_size=200")
    for text in (
        "我们每周五下午同步一次项目进度。",
        "项目同步会固定安排在周五，方便大家提前准备。",
        "以后项目节奏就按每周五同步来推进。",
    ):
        seeded = api.request(
            "POST",
            f"/api/accounts/{account_id}/mock/events",
            {
                "group_internal_id": group_id,
                "text": text,
                "sender_id": "20002",
                "sender_name": "冒烟测试群友二",
            },
        )
        _check(seeded["persisted"] is True and seeded["sent"] is False, "提取素材消息已持久化且不触发回复")
    extraction = api.request("POST", "/api/memories/extract", {"group_id": group_id})
    _check(extraction["created_count"] == 1, "Mock 模型生成 1 条待审核记忆候选")
    _check(extraction["is_mock"] is True, "候选明确标记为 Mock 模拟")
    _check(extraction["scanned_messages"] >= 3, "提取扫描到至少 3 条入站消息")
    _check("审核" in extraction["message"], "提取结果说明需人工审核")
    memories_after = api.request("GET", f"/api/memories?group_id={group_id}&page_size=200")
    _check(memories_after["total"] == memories_before["total"], "候选生成后正式记忆数量未变化")
    pending = api.request("GET", "/api/memories/candidates?status=pending&page_size=200")
    _check(pending["total"] == 1, "待审核候选可查询")
    candidate = pending["items"][0]
    _check(candidate["is_mock"] is True and candidate["provider_type"] == "mock", "候选记录保留模型来源")
    _check(bool(candidate["source_message_ids"]), "候选关联真实消息证据")
    api.request("POST", f"/api/memories/candidates/{candidate['id']}/reject", {})
    rejected_candidates = api.request("GET", "/api/memories/candidates?status=rejected&page_size=200")
    _check(rejected_candidates["total"] == 1, "候选可被人工拒绝")
    api.expect_error(
        "POST",
        f"/api/memories/candidates/{candidate['id']}/approve",
        {},
        status=409,
        code="CONFLICT",
    )
    re_extraction = api.request("POST", "/api/memories/extract", {"group_id": group_id})
    _check(re_extraction["created_count"] == 1, "拒绝后可重新提取候选")
    approved_candidate = re_extraction["created"][0]
    approval = api.request("POST", f"/api/memories/candidates/{approved_candidate['id']}/approve", {})
    _check(approval["candidate"]["status"] == "approved", "候选批准后状态更新")
    _check(approval["memory"]["id"] == approval["candidate"]["memory_id"], "批准后创建正式记忆")
    approved_memories = api.request("GET", f"/api/memories?group_id={group_id}&page_size=200")
    _check(approved_memories["total"] == memories_before["total"] + 1, "人工批准后正式记忆增加 1 条")
    _check(
        any(item["id"] == approval["memory"]["id"] for item in approved_memories["items"]),
        "批准生成的记忆可查询",
    )
    pending_after = api.request("GET", "/api/memories/candidates?status=pending&page_size=200")
    _check(pending_after["total"] == 0, "批准后不再有待审核候选")

    self_id = account.get("self_platform_user_id") or "10000"
    injection = api.request(
        "POST",
        f"/api/accounts/{account_id}/mock/events",
        {
            "group_internal_id": group_id,
            "text": "@AI 群友 你好，做个简短的自我介绍",
            "mentions": [self_id],
            "sender_id": "20001",
            "sender_name": "冒烟测试群友",
        },
    )
    _check(injection["persisted"] is True, "Mock 事件已持久化")
    _check(injection["sent"] is True, "Mock 回复已发送")
    _check(bool(injection.get("sent_text")), "Mock 连接器记录到回复内容")
    result = injection["result"]
    _check(result.get("is_mock") is True, "回复由 Mock 模型生成")
    _check(bool(result.get("outbox_id")), "回复进入发送队列")

    messages = api.request("GET", f"/api/messages?group_id={group_id}&page_size=200")
    directions = {item["direction"] for item in messages["items"]}
    _check("inbound" in directions and "outbound" in directions, "消息日志同时包含入站与出站")
    outbox = api.request("GET", f"/api/outbox?group_id={group_id}")
    _check(any(item["status"] == "sent" for item in outbox["items"]), "发送队列状态为 sent")
    usage = api.request("GET", "/api/usage")
    _check(usage["total"] >= 1, "Token 用量已记录")
    summary = api.request("GET", "/api/usage/summary?hours=24")
    _check(summary["requests"] >= 1, "用量汇总记录到真实请求")
    _check(summary["successful_requests"] >= 1, "用量汇总记录成功请求")
    _check(summary["cost"] == 0.0, "Mock 调用的外部费用为 0")
    _check(summary["cost_status"] == "not_applicable", "Mock 费用状态标记为无外部费用")
    _check(summary["unpriced_success_requests"] == 0, "Mock 调用不产生未计价成功请求")
    _check(
        any(item["is_mock"] for item in summary["by_provider"]),
        "按 Provider 汇总包含 Mock Provider",
    )
    _check(
        any(item["group_id"] == group_id for item in summary["by_group"]),
        "按群汇总包含当前群",
    )
    dashboard = api.request("GET", "/api/dashboard")
    _check(dashboard["usage_today"]["cost_status"] == "not_applicable", "仪表盘显示真实的 Mock 零外部费用")
    _check(
        dashboard["usage_today"]["last_24h"]["requests"] == summary["requests"],
        "仪表盘今日用量与 24 小时汇总一致",
    )
    mock_sent = api.request("GET", f"/api/accounts/{account_id}/mock/sent")
    _check(bool(mock_sent["items"]), "Mock 已发送列表可读取")
    recent = api.request("GET", "/api/events/recent")
    _check(bool(recent["items"]), "SSE 事件总线已有事件")

    ignored = api.request(
        "POST",
        f"/api/accounts/{account_id}/mock/events",
        {
            "group_internal_id": group_id,
            "text": "普通聊天，没有 @ 机器人",
            "sender_id": "20002",
        },
    )
    _check(ignored["sent"] is False, "非 @ 消息不会触发回复")
    _check(ignored["result"]["reason"] == "no_trigger", "非 @ 消息记录拦截原因 no_trigger")

    before_total = api.request("GET", "/api/messages?page_size=1")["total"]
    dry = api.request(
        "POST",
        "/api/playground/run",
        {
            "account_id": account_id,
            "group_id": group_id,
            "conversation_type": "group",
            "text": "@AI 群友 dry-run 测试",
            "mentions": [self_id],
            "sender_id": "20001",
        },
    )
    _check(dry["dry_run"] is True and dry["sent"] is False, "dry-run 不发送")
    after_total = api.request("GET", "/api/messages?page_size=1")["total"]
    _check(before_total == after_total, "dry-run 不写入消息日志")

    paused = api.request("POST", "/api/system/pause-all", {"reason": "冒烟测试全局暂停"})
    _check(paused["global_pause"]["paused"] is True, "全局暂停立即生效")
    paused_result = api.request(
        "POST",
        f"/api/accounts/{account_id}/mock/events",
        {
            "group_internal_id": group_id,
            "text": "@AI 群友 暂停期间不应回复",
            "mentions": [self_id],
            "sender_id": "20001",
        },
    )
    _check(paused_result["sent"] is False, "暂停期间不生成发送")
    _check(paused_result["result"]["reason"] == "global_paused", "暂停拦截原因正确")
    api.expect_error(
        "POST",
        "/api/outbox/dispatch-due",
        None,
        status=409,
        code="GLOBAL_PAUSED",
    )
    resumed = api.request("POST", "/api/system/resume")
    _check(resumed["global_pause"]["paused"] is False, "全局恢复成功")

    fake_key = "smoke-secret-" + secrets.token_hex(12)
    provider = api.request(
        "POST",
        "/api/providers",
        {
            "name": "冒烟测试 Provider（请忽略）",
            "provider_type": "openai_compatible",
            "base_url": "http://127.0.0.1:9/v1",
            "model": "smoke-model",
            "api_key": fake_key,
            "enabled": False,
            "is_default": False,
        },
    )
    _check(provider["api_key_configured"] is True, "Provider 密钥已保存")
    _check(fake_key not in json.dumps(provider, ensure_ascii=False), "Provider 响应不含明文密钥")
    _check(bool(provider.get("api_key_masked")), "Provider 密钥以掩码返回")
    _check(provider["cost_tracking"] == "unconfigured", "未填写单价的 Provider 标记为单价未配置")
    _, providers_text = api.raw("GET", "/api/providers")
    _check(fake_key not in providers_text, "Provider 列表不含明文密钥")

    policy = api.request(
        "POST",
        "/api/budgets",
        {
            "scope_type": "group",
            "scope_id": group_id,
            "window": "day",
            "metric": "cost",
            "limit_value": 1.0,
            "warn_threshold": 0.8,
            "enabled": True,
        },
    )
    _check(policy["used"] == 0, "新建群级费用预算的已用金额来自真实用量记录")
    _check(policy["state"] == "ok", "未超限的费用预算状态为 ok")
    _check(policy["cost_status"] == "not_applicable", "群级费用完整性区分 Mock 零外部费用")
    unpriced_check = api.request(
        "GET",
        f"/api/budgets/check?group_id={group_id}&provider_id={provider['id']}",
    )
    _check(unpriced_check["allowed"] is False, "未配置单价的费用预算会阻断调用")
    _check(unpriced_check["blocks"][0]["reason"] == "cost_unavailable", "阻断原因说明单价不可用")
    mock_check = api.request(
        "GET",
        f"/api/budgets/check?group_id={group_id}&provider_id={demo_provider['id']}",
    )
    _check(mock_check["allowed"] is True, "Mock 视为零外部费用，不受费用预算影响")
    policies = api.request("GET", "/api/budgets")["items"]
    stored_policy = next(item for item in policies if item["id"] == policy["id"])
    _check(stored_policy["remaining"] == 1.0, "预算快照返回剩余额度")
    _check(stored_policy["period_start"] is not None, "预算快照返回窗口起点")

    anthropic_key = "smoke-anthropic-" + secrets.token_hex(12)
    anthropic_provider = api.request(
        "POST",
        "/api/providers",
        {
            "name": "冒烟测试 Anthropic（请忽略）",
            "provider_type": "anthropic_native",
            "model": "claude-sonnet-5",
            "api_key": anthropic_key,
            "enabled": False,
            "is_default": False,
        },
    )
    _check(
        anthropic_provider["base_url"] == "https://api.anthropic.com/v1",
        "Anthropic Provider 留空 Base URL 时使用官方默认地址",
    )
    _check(anthropic_provider["api_key_configured"] is True, "Anthropic 密钥已加密保存")
    _check(anthropic_key not in json.dumps(anthropic_provider, ensure_ascii=False), "Anthropic 响应不含明文密钥")
    _, provider_types = api.raw("GET", "/api/providers")
    _check(anthropic_key not in provider_types, "Provider 列表不含 Anthropic 明文密钥")
    data_dir = temp / "data"
    hits = _scan_for_secret(data_dir, fake_key)
    _check(not hits, "数据目录（数据库/日志/备份）不含明文密钥")
    anthropic_hits = _scan_for_secret(data_dir, anthropic_key)
    _check(not anthropic_hits, "数据目录（数据库/日志/备份）不含 Anthropic 明文密钥")

    backup = api.request("POST", "/api/backups", {"note": "冒烟测试备份"})
    backup_id = backup["id"]
    _check(backup["size_bytes"] > 0, "备份文件已创建")
    _check(backup["includes_secrets"] is False, "备份清单声明不含明文密钥")
    verify = api.request("POST", f"/api/backups/{backup_id}/verify")
    _check(verify["checksum_ok"] is True, "备份 SHA-256 校验通过")
    _check(verify["integrity_ok"] is True, "SQLite 完整性校验通过")
    backup_path = data_dir / "backups" / backup["filename"]
    _check(not _contains_secret(backup_path, fake_key.encode("utf-8")), "备份文件不含明文密钥")
    _check(
        not _contains_secret(backup_path, anthropic_key.encode("utf-8")),
        "备份文件不含 Anthropic 明文密钥",
    )
    preview = api.request("POST", f"/api/backups/{backup_id}/restore/preview")
    _check(preview["requires_pause"] is True, "恢复预览要求全局暂停")
    _check(preview["confirm_phrase"] == "RESTORE", "恢复确认短语为 RESTORE")
    _check(preview["current_state"]["accounts"] >= 1, "恢复预览可读取当前数据状态")
    audit_before = api.request("GET", "/api/audit?page_size=200")
    actions_before = {item["action"] for item in audit_before["items"]}
    for action in ("backup.create", "provider.llm.create", "system.pause_all", "demo.bootstrap"):
        _check(action in actions_before, f"恢复前审计日志包含 {action}")

    personas_before = api.request("GET", "/api/personas")
    before_names = {item["name"] for item in personas_before["items"]}
    temp_persona = api.request(
        "POST",
        "/api/personas",
        {
            "name": "冒烟测试临时人格",
            "mode": "authored",
            "self_description": "仅在冒烟测试中存在，恢复后应消失。",
            "growth_policy": "paused",
            "growth_enabled": False,
        },
    )
    _check(temp_persona["id"] not in {item["id"] for item in personas_before["items"]}, "恢复前已新增临时数据")

    api.expect_error(
        "POST",
        f"/api/backups/{backup_id}/restore",
        {"confirm": "restore"},
        status=400,
        code="BACKUP_INVALID",
    )
    api.expect_error(
        "POST",
        f"/api/backups/{backup_id}/restore",
        {"confirm": "RESTORE"},
        status=409,
        code="BACKUP_RESTORE_REQUIRES_PAUSE",
    )
    api.request("POST", "/api/system/pause-all", {"reason": "冒烟测试恢复前暂停"})
    restored = api.request(
        "POST",
        f"/api/backups/{backup_id}/restore",
        {"confirm": "RESTORE"},
        timeout=60.0,
    )
    _check(restored["restored"] is True, "数据库恢复成功")
    safety_id = restored["safety_backup"]["id"]
    _check(bool(safety_id), "恢复前自动创建安全备份")
    settings_after_restore = api.request("GET", "/api/settings")
    _check(
        settings_after_restore["global_pause"]["paused"] is True,
        "恢复后自动保持全局暂停",
    )
    api.request("POST", "/api/system/resume")
    personas_after = api.request("GET", "/api/personas")
    after_names = {item["name"] for item in personas_after["items"]}
    _check("冒烟测试临时人格" not in after_names, "恢复后临时数据已回退")
    _check(after_names == before_names, "恢复后人格列表与备份时一致")
    safety = api.request("GET", f"/api/backups/{safety_id}")
    _check(safety["filename"] == restored["safety_backup"]["filename"], "安全备份可从备份记录读取")
    audit_after = api.request("GET", "/api/audit?page_size=200")
    actions_after = {item["action"] for item in audit_after["items"]}
    # 恢复会用备份覆盖数据库，因此恢复前的审计记录属于当时快照；
    # 恢复动作本身会在恢复后的数据库中留痕。
    _check("backup.restore" in actions_after, "恢复后审计日志包含 backup.restore")

    # 恢复会断开连接器；重新连接后确认服务仍可处理 Mock 事件。
    instances = account["instances"]
    _check(bool(instances), "账号存在可重连的 Mock 连接器")
    api.request("POST", f"/api/accounts/{account_id}/instances/{instances[0]['id']}/connect")
    # 避免冒烟测试自身触发默认 3 秒冷却，导致最后一步被合理拦截。
    api.request(
        "PATCH",
        f"/api/groups/{group_id}",
        {"rate_limit": {"cooldown_seconds": 0, "max_replies_per_hour": 20, "max_replies_per_day": 100}},
    )
    final = api.request(
        "POST",
        f"/api/accounts/{account_id}/mock/events",
        {
            "group_internal_id": group_id,
            "text": "@AI 群友 恢复后再次测试",
            "mentions": [self_id],
            "sender_id": "20003",
        },
    )
    _check(final["sent"] is True, "恢复并重连后 Mock 闭环仍可用")

    # 放在所有模型调用之后创建，避免低额度请求预算阻断后续步骤。
    alert_policy = api.request(
        "POST",
        "/api/budgets",
        {
            "scope_type": "group",
            "scope_id": group_id,
            "window": "day",
            "metric": "requests",
            "limit_value": 1,
            "warn_threshold": 0.5,
            "enabled": True,
        },
    )
    _check(alert_policy["state"] == "exceeded", "用真实历史用量创建策略后立即达到上限")
    alerts = api.request("GET", "/api/budgets/alerts")
    _check(alerts["total"] >= 1, "预算告警事件已生成")
    _check(alerts["items"][0]["level"] == "exceeded", "预算告警级别为已超限")
    _check(alerts["items"][0]["scope_type"] == "group", "预算告警记录真实作用域")
    _check(alerts["items"][0]["used"] >= 1, "预算告警已用量来自真实记录")
    audit_alerts = api.request("GET", "/api/audit?action=budget.alert&page_size=50")
    _check(audit_alerts["total"] >= 1, "预算告警写入审计日志")

    trends = api.request(
        "GET",
        f"/api/usage/trends?bucket=hour&periods=24&group_id={group_id}",
    )
    _check(trends["bucket"] == "hour" and len(trends["items"]) == 24, "小时趋势返回完整真实时间桶")
    _check(trends["requests"] >= 1, "趋势请求数来自真实 llm_usage")
    _check(trends["cost_status"] == "not_applicable", "Mock 趋势费用标记为无外部费用")
    _check(
        sum(item["requests"] for item in trends["items"]) == trends["requests"],
        "趋势各时间桶之和与窗口总量一致",
    )

    csv_status, csv_text = api.raw("GET", f"/api/usage/export.csv?group_id={group_id}")
    _check(csv_status == 200, "用量 CSV 导出返回 HTTP 200")
    csv_lines = csv_text.lstrip("﻿").splitlines()
    _check(csv_lines[0].startswith("created_at_utc,provider_id"), "CSV 表头为真实用量字段")
    _check("content_text" not in csv_lines[0], "CSV 不导出消息正文")
    _check("恢复后再次测试" not in csv_text, "CSV 不含群消息文本")
    _check(fake_key not in csv_text, "CSV 不含 Provider 明文密钥")
    _check(anthropic_key not in csv_text, "CSV 不含 Anthropic 明文密钥")
    audit_export = api.request("GET", "/api/audit?action=usage.export&page_size=50")
    _check(audit_export["total"] >= 1, "CSV 导出动作写入审计日志")


def _utf8_console() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
        except (AttributeError, ValueError):
            pass


def main() -> int:
    _utf8_console()
    parser = argparse.ArgumentParser(description="AI 群友端到端冒烟测试")
    parser.add_argument("--keep", action="store_true", help="保留临时数据目录用于排查")
    args = parser.parse_args()

    if not (BACKEND / "app" / "main.py").is_file():
        print(f"未找到后端：{BACKEND}", file=sys.stderr)
        return 2

    temp = Path(tempfile.mkdtemp(prefix="aiqf-smoke-"))
    log_path = temp / "server.log"
    port = _pick_port()
    api = Api(f"http://127.0.0.1:{port}")
    env = _env(temp, port)
    process: subprocess.Popen[Any] | None = None
    success = False
    print("AI 群友端到端冒烟测试")
    print(f"临时数据目录：{temp}")
    print(f"本地端口：{port}（仅 127.0.0.1）\n")
    try:
        with log_path.open("w", encoding="utf-8") as log_handle:
            process = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "uvicorn",
                    "app.main:app",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    str(port),
                    "--log-level",
                    "warning",
                ],
                cwd=str(BACKEND),
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=log_handle,
                stderr=subprocess.STDOUT,
            )
            _wait_ready(api, process, log_path)
            print("[ok] uvicorn 已启动并完成数据库迁移\n")
            run(api, temp)
        success = True
    except SmokeFailure as exc:
        print(f"\n[失败] {exc}", file=sys.stderr)
    except Exception as exc:  # noqa: BLE001  失败时给出可诊断信息
        print(f"\n[失败] 未预期异常：{type(exc).__name__}: {exc}", file=sys.stderr)
        print(_log_tail(log_path), file=sys.stderr)
    finally:
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=10)
        if success:
            print("\n冒烟测试全部通过。未接触真实 QQ 或真实模型。")
        if not args.keep:
            shutil.rmtree(temp, ignore_errors=True)
        else:
            print(f"已保留临时目录：{temp}")
    return 0 if success else 1


if __name__ == "__main__":
    raise SystemExit(main())

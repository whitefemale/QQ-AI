# HTTP / SSE API 参考

管理 API 前缀默认 `/api`。交互式 OpenAPI 文档：

- Swagger UI：<http://127.0.0.1:8000/api/docs>
- OpenAPI JSON：<http://127.0.0.1:8000/api/openapi.json>

> 本文档是人工摘要；字段以实际 OpenAPI 与运行结果为准。所有示例均假定服务运行在 `http://127.0.0.1:8000`。

## 通用约定

### 响应包

成功：

```json
{
  "data": { "status": "ok" },
  "error": null,
  "request_id": "f1d2c3..."
}
```

失败：

```json
{
  "data": null,
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "请求参数不合法。",
    "details": { "fields": [] }
  },
  "request_id": "f1d2c3..."
}
```

所有响应带 `X-Request-ID`。客户端可传 `X-Request-ID`（只保留字母、数字、`-`、`_`，最长 64 字符）。

### 请求头

| 头 | 说明 |
| --- | --- |
| `Content-Type: application/json` | 写请求 |
| `X-Request-ID` | 可选，请求追踪 ID |
| `X-Admin-Token` 或 `Authorization: Bearer <token>` | 仅远程管理时需要 |

### 管理边界

- 默认只接受回环地址（`127.0.0.1`、`::1`、`localhost`）请求。
- 非本机请求在 `ALLOW_REMOTE_ADMIN=false` 时统一返回 HTTP 403 `REMOTE_ADMIN_FORBIDDEN`。
- 开启远程后必须配置强 `ADMIN_API_TOKEN`，否则返回 401 `UNAUTHORIZED`。远程访问应置于 HTTPS 反向代理之后。
- 前端管理 Token 只保存在 `sessionStorage`（键 `aiqf.adminToken`），不会写入 LocalStorage。

### 格式约定

- 时间：ISO 8601 UTC（如 `2026-10-25T03:00:00+00:00`）。
- ID：字符串 UUID。
- 分页：`page`（从 1 开始）、`page_size`（1–200）；响应通常含 `items`、`total`、`page`、`page_size`。
- 密钥永远不返回明文。Provider 返回 `api_key_configured` 与 `api_key_masked`；连接器 Token 返回掩码。
- 错误 `details` 经过脱敏。

### 主要错误码

| 类别 | 代码 |
| --- | --- |
| 通用 | `VALIDATION_ERROR`、`NOT_FOUND`、`CONFLICT`、`INTERNAL_ERROR`、`OPERATION_PLANNED` |
| 管理边界 | `FORBIDDEN`、`UNAUTHORIZED`、`REMOTE_ADMIN_FORBIDDEN` |
| 凭证 | `CREDENTIAL_KEY_MISSING`、`CREDENTIAL_DECRYPT_FAILED` |
| 连接器 | `ADAPTER_NOT_FOUND`、`ADAPTER_UNAVAILABLE`、`ADAPTER_REMOTE_FORBIDDEN`、`ADAPTER_CONNECT_FAILED`、`ADAPTER_AUTH_FAILED`、`ADAPTER_UNSUPPORTED_OPERATION` |
| 发送 | `SEND_FAILED`、`SEND_STATUS_UNKNOWN`、`GLOBAL_PAUSED` |
| 策略 | `POLICY_BLOCKED`、`GROUP_NOT_WHITELISTED` |
| 人格 | `PERSONA_*` |
| 模型 | `PROVIDER_*`、`LLM_TIMEOUT`、`LLM_NETWORK_ERROR`、`LLM_AUTH_FAILED`、`LLM_RATE_LIMITED`、`LLM_QUOTA_EXCEEDED`、`LLM_MODEL_NOT_FOUND`、`LLM_INVALID_RESPONSE`、`LLM_NOT_CONFIGURED` |
| 工具 / 媒体 / 插件 / 记忆 | `TOOL_*`、`MEDIA_*`、`PLUGIN_*`、`MEMORY_SENSITIVE_CONTENT` |
| 预算 / 备份 | `BUDGET_EXCEEDED`、`BACKUP_*`、`BACKUP_RESTORE_REQUIRES_PAUSE` |

## 系统与运行状态

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/health` | 存活检查，无需数据库查询 |
| GET | `/api/ready` | 数据库、加密密钥、全局暂停、SSE 订阅者 |
| GET | `/api/dashboard` | 仪表盘聚合数据与全局暂停 |
| GET | `/api/capabilities` | 连接器、模型与媒体能力状态（含 `planned` / `unconfigured`） |
| GET | `/api/settings` | 运行信息、保留策略、安全状态、隐私计数 |
| PUT | `/api/settings` | 更新 `retention` / `global_pause` |
| POST | `/api/system/pause-all` | 全局紧急暂停 |
| POST | `/api/system/resume` | 解除全局暂停 |
| GET | `/api/audit` | 审计日志分页查询 |
| GET | `/api/events/recent?limit=20` | 最近 SSE 事件 |
| GET | `/api/events/stream?replay=0` | SSE 实时事件流 |
| GET | `/api/policy-explain` | 流水线顺序与暂停状态 |

`POST /api/system/pause-all`：

```json
{ "reason": "账号出现验证码提示，立即暂停" }
```

返回：

```json
{
  "data": {
    "global_pause": { "paused": true, "reason": "...", "updated_at": "..." },
    "note": "全局暂停立即生效；后台发送队列将停止发送。"
  },
  "error": null,
  "request_id": "..."
}
```

暂停期间：

- 流水线在模型调用前拦截；
- `POST /api/outbox/dispatch-due` 返回 HTTP 409 `GLOBAL_PAUSED`；
- 恢复不会自动重发旧的未知状态消息。

### SSE

`GET /api/events/stream?replay=20`

```text
: connected

id: 42
event: message.received
data: {"seq":42,"type":"message.received","at":"2026-10-25T03:00:00+00:00","payload":{...}}

: ping
```

- 每 15 秒发送注释心跳。
- 支持浏览器 `EventSource` 自动重连；`replay` 只回放最近 50 条内存事件。
- 常见事件：`message.received`、`message.duplicate`、`message.intercepted`、`message.generated`、`outbox.sent`、`outbox.failed`、`adapter.status`、`adapter.event`、`system.paused`、`system.resumed`、`persona.proposal`、`persona.applied`。

## 演示环境

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/api/demo/bootstrap` | 幂等创建 Mock 账号、Mock 实例、Mock 模型、演示群、模板人格，并连接 Mock |
| POST | `/api/demo/reset-hint` | 固定返回 501 `OPERATION_PLANNED` |

`POST /api/demo/bootstrap` 空对象即可。返回 `created`、`account`、`group`、`persona`、`provider`、`global_pause`、`notes`。重复调用不会重复创建。

## QQ 账号与连接器

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/accounts` | 账号列表、连接方式选项、全局暂停 |
| POST | `/api/accounts` | 创建账号（可内嵌首个 `instance`） |
| POST | `/api/accounts/test-connection` | 测试未保存的连接配置 |
| GET | `/api/accounts/{account_id}` | 账号详情与实例 |
| PATCH | `/api/accounts/{account_id}` | 更新账号 |
| DELETE | `/api/accounts/{account_id}` | 删除账号（含实例与关联配置） |
| POST | `/api/accounts/{account_id}/instances` | 添加实例 |
| PATCH | `/api/accounts/{account_id}/instances/{instance_id}` | 更新实例 |
| DELETE | `/api/accounts/{account_id}/instances/{instance_id}` | 删除实例 |
| POST | `/api/accounts/{account_id}/instances/{instance_id}/connect` | 连接 |
| POST | `/api/accounts/{account_id}/instances/{instance_id}/disconnect` | 断开 |
| POST | `/api/accounts/{account_id}/instances/{instance_id}/test` | 已保存实例测试（可附带临时覆盖配置） |
| GET | `/api/accounts/{account_id}/instances/{instance_id}/groups` | 从连接器读取群列表 |
| GET | `/api/accounts/{account_id}/status` | 账号与实时连接器状态 |
| POST | `/api/accounts/{account_id}/mock/events` | 注入 Mock 事件（仅在线 Mock 实例） |
| GET | `/api/accounts/{account_id}/mock/sent?limit=20` | 当前进程内 Mock 已发送消息 |

创建账号示例：

```json
{
  "display_name": "运营助手号",
  "enabled": true,
  "allow_private": false,
  "notes": "仅用于白名单群",
  "instance": {
    "name": "NapCat 本机",
    "connection_mode": "onebot11",
    "endpoint": "ws://127.0.0.1:3001",
    "api_endpoint": "http://127.0.0.1:3000",
    "token": "your-independent-onebot-token",
    "allow_remote": false,
    "auto_connect": true,
    "enabled": true
  }
}
```

说明：

- `connection_mode`：`mock` / `onebot11` / `official`（`official` 当前不可用）。
- Token 加密保存，响应只返回掩码。
- 公网 WS/HTTP 地址在 `allow_remote=false` 时被拒绝（`ADAPTER_REMOTE_FORBIDDEN`）。
- 连接器实时状态只存在于当前进程；重启后需要重新连接。
- 当前不下载真实媒体，也不转发媒体文件。

注入 Mock 事件：

```json
{
  "group_internal_id": "<群内部 ID>",
  "text": "@AI 群友 你好",
  "segments": [
    { "type": "text", "text": "@AI 群友 你好" },
    { "type": "mention", "text": "10000", "metadata": { "qq": "10000" } }
  ],
  "mentions": ["10000"],
  "sender_id": "20001",
  "sender_name": "模拟群友",
  "reply_to_message_id": null
}
```

返回 `dry_run=false`、`persisted=true`、`sent`（**仅表示本次事件是否新增发送**）、`sent_text`、`result`。`result.action` 可能为 `reply` / `intercept` / `observe` / `error`。

## 群管理

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/groups?account_id=` | 群列表、回复模式、限速默认值 |
| POST | `/api/groups` | 创建群配置 |
| GET | `/api/groups/members?account_id=` | 成员状态 |
| POST | `/api/groups/import` | 导入群列表（默认关闭回复） |
| POST | `/api/groups/import-connector` | 从连接器读取并导入群 |
| GET | `/api/groups/{group_id}` | 群详情 |
| PATCH | `/api/groups/{group_id}` | 更新群配置 |
| DELETE | `/api/groups/{group_id}` | 删除群配置 |
| POST | `/api/groups/{group_id}/pause` | 暂停该群 AI 回复 |
| POST | `/api/groups/{group_id}/resume` | 恢复该群 |

群创建/更新关键字：

```json
{
  "account_id": "<account_id>",
  "platform_group_id": "123456789",
  "name": "测试群",
  "enabled": false,
  "reply_mode": "mention_only",
  "persona_id": "<persona_id>",
  "llm_provider_id": "<provider_id>",
  "llm_fallback_provider_id": "<provider_id>",
  "timezone": "Asia/Shanghai",
  "keywords": ["你好"],
  "admin_user_ids": ["10001"],
  "group_rules_text": "不要讨论敏感话题。",
  "quiet_hours": {
    "enabled": true,
    "start": "23:00",
    "end": "08:00",
    "timezone": "Asia/Shanghai"
  },
  "rate_limit": {
    "cooldown_seconds": 3,
    "max_replies_per_hour": 20,
    "max_replies_per_day": 100,
    "max_consecutive_replies": 3
  },
  "allow_tools": false,
  "allow_memory": false,
  "auto_memory_extraction": false,
  "allow_proactive": false
}
```

- 回复模式：`observe`、`mention_only`（默认）、`keyword`、`context`；`scheduled` 仅为推荐值中的规划项，当前不可设置。
- 导入的群默认 `enabled=false`，必须逐群确认。
- `allow_memory` 开启后，只会检索当前群与当前发送者的记忆；其他群、敏感记忆、过期记忆和被排除成员的成员级记忆不会注入。
- `auto_memory_extraction` 默认 `false`，且必须同时开启 `allow_memory`；关闭长期记忆会自动关闭后台提取。它只生成待审核候选，不会自动批准或注入。
- 群对象还返回 `memory_extraction_last_run_at`、`memory_extraction_last_error`、`memory_extraction_watermark_at`、`memory_extraction_watermark_message_id`，用于说明后台检查状态；错误信息已脱敏。
- 群工具默认关闭。
- `llm_provider_id` / `llm_fallback_provider_id` 为可选的群级模型绑定。未设置主模型时使用全局默认 Provider；备用模型必须依附主模型，且不能与主模型相同。绑定或修改时会校验 Provider 存在且已启用；事后被禁用的既有绑定不会阻止保存其他群配置。
- 群对象返回 `llm_provider_name`、`llm_provider_type`、`llm_provider_state` 以及对应的 `llm_fallback_*` 字段；`state` 为 `default`（未绑定）、`mock`、`configured`、`disabled` 或 `missing`。

### 群级模型路由与受控回退

- 路由优先级：显式内部 `provider_id`（测试/特殊调用）＞ 群级主模型 ＞ 全局默认 Provider。显式指定时不会启用群级备用模型。
- 备用模型仅在主模型产生以下**调用错误**时尝试一次：`LLM_TIMEOUT`、`LLM_NETWORK_ERROR`、`LLM_AUTH_FAILED`、`LLM_RATE_LIMITED`、`LLM_QUOTA_EXCEEDED`、`LLM_MODEL_NOT_FOUND`、`LLM_INVALID_RESPONSE`、`PROVIDER_UNHEALTHY`。
- 预算超限（`BUDGET_EXCEEDED`）、全局暂停、主模型 Provider 不存在/禁用、配置缺失、本地凭证解密失败等**不会**触发回退；也不会静默改用 Mock 或全局默认模型。
- 列表中的 `LLM_AUTH_FAILED` 指 Provider 在调用时拒绝 API Key，属于对端调用错误，可切换到使用独立凭证的备用 Provider；本地未配置 Key 或凭证解密失败属于 `LLM_NOT_CONFIGURED` / `CREDENTIAL_*`，不会回退。
- 群回复、记忆候选提取与人格成长都以群 ID 解析绑定；`/api/playground/run` 的 dry-run 结果和 `reply.generated` 事件会返回实际 `provider_id`、`fallback_used`、`primary_provider_id`、`primary_error_code` 与 `route_source`。

## 人格

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/personas` | 列表、模式、默认阈值、成长策略、学习范围 |
| GET | `/api/personas/templates` | 内置模板 |
| POST | `/api/personas` | 创建人格 |
| GET | `/api/personas/{persona_id}` | 详情、版本、特征、事件摘要 |
| PATCH | `/api/personas/{persona_id}` | 更新配置 |
| DELETE | `/api/personas/{persona_id}` | 删除人格 |
| GET | `/api/personas/{persona_id}/traits?status=` | 特征列表 |
| GET | `/api/personas/{persona_id}/events?limit=50` | 成长事件 |
| GET | `/api/personas/{persona_id}/versions` | 版本列表 |
| POST | `/api/personas/{persona_id}/versions/{version_id}/restore` | 回滚到版本 |
| POST | `/api/personas/{persona_id}/reset` | 重置空白自成长人格（仅 `emergent`；前端二次确认） |
| POST | `/api/personas/{persona_id}/growth/analyze` | 手动触发成长分析 |
| GET | `/api/personas/{persona_id}/growth/pending` | 该人格待审核提案 |
| GET | `/api/personas/growth/pending?persona_id=` | 全部待审核提案 |
| POST | `/api/personas/growth/{event_id}/review` | 审核提案 |
| POST | `/api/personas/evidence/{message_id}/delete` | 删除证据消息并清理引用 |
| GET | `/api/personas/traits/{trait_id}` | 特征详情 |
| PATCH | `/api/personas/traits/{trait_id}` | 修改状态或锁定 |
| DELETE | `/api/personas/traits/{trait_id}` | 删除特征 |
| POST | `/api/personas/{persona_id}/test` | dry-run 测试人格 |

创建人格示例：

```json
{
  "name": "空白成长助手",
  "mode": "emergent",
  "growth_policy": "review",
  "growth_enabled": true,
  "learning_scope": "group",
  "thresholds": {
    "min_evidence_count": 3,
    "min_conversations": 2,
    "min_confidence": 0.65
  },
  "locked_fields": ["self_description"],
  "notes": "从空白开始，人工审核"
}
```

- `mode`：`authored` / `template` / `emergent`。
- `emergent` 不允许预置 `self_description` 或 `authored_fields`。
- `growth_policy`：`auto` / `review` / `paused`。
- `learning_scope`：`admin_only`（默认）/ `group` / `cross_group`（默认关闭）。
- 审核请求：`{ "approve": true }`。

测试人格等同于 `/api/playground/run`，必须提供 `account_id` 与 `group_id`，不发送、不落库。

## 模型 Provider 与媒体能力

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/providers` | 模型 Provider 列表与类型 |
| POST | `/api/providers` | 创建 Provider |
| GET | `/api/providers/{provider_id}` | 详情 |
| PATCH | `/api/providers/{provider_id}` | 更新 |
| DELETE | `/api/providers/{provider_id}` | 删除 |
| POST | `/api/providers/{provider_id}/test` | 测试连接，错误分类 |
| GET | `/api/media/providers` | 媒体 Provider 与健康状态 |
| GET | `/api/media/capabilities` | 能力概览 |
| POST | `/api/media/providers/{provider_id}/enable` | 启用/禁用媒体 Provider |
| POST | `/api/media/providers/{provider_id}/test` | 媒体 Provider 测试 |
| GET | `/api/media/jobs?status=&limit=` | 媒体任务队列 |
| POST | `/api/media/jobs/{job_id}/cancel` | 取消任务 |
| POST | `/api/media/jobs/{job_id}/retry` | 重试任务 |
| POST | `/api/media/jobs/process-due` | 处理到期任务（Mock） |

创建 OpenAI 兼容 Provider：

```json
{
  "name": "本机兼容网关",
  "provider_type": "openai_compatible",
  "base_url": "https://example.com/v1",
  "model": "your-model-id",
  "api_key": "sk-...",
  "timeout_seconds": 45,
  "max_output_tokens": 800,
  "temperature": 0.7,
  "enabled": true,
  "is_default": true,
  "config": {
    "input_price_per_1k": 0,
    "output_price_per_1k": 0
  }
}
```

响应示例（**不含明文 Key**）：

```json
{
  "id": "...",
  "name": "本机兼容网关",
  "provider_type": "openai_compatible",
  "base_url": "https://example.com/v1",
  "model": "your-model-id",
  "api_key_configured": true,
  "api_key_masked": "sk-1••••abcd",
  "status": "configured",
  "is_default": true,
  "enabled": true
}
```

- `provider_type` 支持 `mock`、`openai_compatible` 与 `anthropic_native`。
- 创建 `anthropic_native` 时可省略 `base_url`，服务会保存官方默认地址 `https://api.anthropic.com/v1`；也可填写可信代理。必须提供真实 API Key 与模型 ID。
- Anthropic 适配器只发送 `system`、`user`、`assistant` 消息；通用消息中的 system 会合并到顶层 `system`，连续同角色消息会合并，工具定义转换为 `input_schema`。温度会被限制在 0–1。
- 旧的 `anthropic` / `claude` / `openai` / `official` 类型返回 400，并提示改用 `anthropic_native` 或 `openai_compatible`。
- 删除仍被任一群绑定为主模型或备用模型的 Provider 会返回 HTTP 409 `PROVIDER_IN_USE`，并在 `details.group_ids` 中列出（最多 20 个）受影响群；请先在群管理中解除绑定。
- 真实视觉/语音等媒体 Provider 尚未实现；请勿把 Mock 媒体任务当作真实识别结果。

## 模拟测试

### dry-run

`POST /api/playground/run`

```json
{
  "account_id": "...",
  "group_id": "...",
  "conversation_type": "group",
  "persona_id": null,
  "text": "@AI 群友 你好",
  "segments": [
    { "type": "text", "text": "@AI 群友 你好" },
    { "type": "mention", "text": "10000", "metadata": { "qq": "10000" } }
  ],
  "mentions": ["10000"],
  "sender_id": "20001",
  "sender_name": "模拟群友",
  "reply_to_message_id": null
}
```

返回：

```json
{
  "dry_run": true,
  "sent": false,
  "persisted": false,
  "note": "模拟运行不会发送到 QQ，也不会写入消息日志。",
  "result": {
    "accepted": true,
    "action": "reply",
    "reason": "mentioned",
    "reply": "……",
    "is_mock": true,
    "latency_ms": 0,
    "prompt_preview": "（脱敏后的提示词预览）"
  }
}
```

- dry-run 不发送、不落库、不修改状态。
- `result.reason` 是排查关键：`no_trigger`、`cooldown`、`hourly_limit`、`global_paused`、`quiet_hours`、`persona_missing`、`budget_exceeded` 等。
- 媒体段只产生「未配置识别能力」的降级说明。

### 选项

`GET /api/playground/options` 返回可选账号（含 `has_mock`）、群与人格。

## 消息、发送队列、用量与预算

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/messages` | 消息日志，支持分页与筛选 |
| GET | `/api/outbox` | 发送队列 |
| POST | `/api/outbox/dispatch-due` | 派发到期消息（暂停时 409） |
| GET | `/api/usage` | 模型调用明细 |
| GET | `/api/usage/summary?hours=24` | 按 Provider / 群的时间窗用量与费用完整性汇总 |
| GET | `/api/usage/trends?bucket=hour&periods=24` | 按配置时区的小时/自然日真实用量趋势；可选 `group_id`、`provider_id` |
| GET | `/api/usage/export.csv` | 导出真实调用元数据 CSV；可选 `since`、`until`、`group_id`、`provider_id`、`status`、`purpose` |
| GET | `/api/budgets` | 预算策略及当前窗口用量快照 |
| POST | `/api/budgets` | 新建/提交预算策略 |
| PUT | `/api/budgets/{policy_id}` | 更新预算策略 |
| GET | `/api/budgets/{policy_id}` | 详情（含真实用量快照） |
| GET | `/api/budgets/check?group_id=&provider_id=` | 检查预算；返回阻断原因与说明 |
| GET | `/api/budgets/alerts` | 预算告警事件历史；支持 `level`、`scope_type`、`scope_id`、`since` 与分页 |
| GET | `/api/memories` | 记忆列表；支持 `account_id`、`group_id`、`member_id`、`memory_type`、`search`、`include_expired` |
| POST | `/api/memories` | 手动添加记忆；拒绝疑似密码/验证码/证件号/银行卡号/密钥 |
| POST | `/api/memories/extract` | 手动触发 AI 候选提取；body `{group_id}`；只生成待审核候选 |
| GET | `/api/memories/candidates` | 候选列表；支持 `account_id`、`group_id`、`status`、`page`、`page_size` |
| POST | `/api/memories/candidates/{candidate_id}/approve` | 人工批准候选并创建正式记忆 |
| POST | `/api/memories/candidates/{candidate_id}/reject` | 人工拒绝候选 |
| GET | `/api/memories/{memory_id}` | 记忆详情 |
| PATCH | `/api/memories/{memory_id}` | 更新内容、类型、敏感度、置信度、固定、过期时间或来源 |
| DELETE | `/api/memories/{memory_id}` | 删除记忆 |
| GET | `/api/policy-explain` | 流水线硬规则顺序 |

记忆检索规则：

- 只有群开启 `allow_memory` 时，群聊才会检索并注入记忆。
- 范围严格限定为当前 `account_id + group_id`，并只包含群级记忆或当前发送者的成员级记忆。
- 只自动使用 `sensitivity=normal` 且未过期的记忆；`sensitive` 记忆可在控制台管理但不会自动注入。
- 被标记 `excluded_from_memory` 的成员，其成员级记忆不会自动注入。
- 排序为：固定优先 → 关键词/中文二元词相关度 → 置信度 → 记录时间。
- 注入内容带有“不可信历史资料”标记；记忆永远不能成为系统或管理员指令。

AI 候选提取与审核：

- `POST /api/memories/extract` 只读取指定群最近入站文本消息（默认最多 40 条，至少 3 条）；群必须开启 `allow_memory`，已排除记忆的成员不参与。
- 模型输出只写入 `pending` 候选，返回 `created`、`scanned_messages`、`skipped`、`skipped_reasons`、Provider/模型与 `is_mock`。**候选不会自动保存为正式记忆，也不会注入提示词。**
- 候选必须引用输入中真实存在的消息 ID；敏感内容、未知成员、低置信度、重复内容与超出上限的候选会被跳过。
- `GET /api/memories/candidates` 默认 `status=pending`；可选 `pending`、`approved`、`rejected`。
- `POST .../approve` 可传可选覆盖字段 `content`、`memory_type`、`confidence`，批准后创建普通敏感度、未固定的正式记忆并保留证据引用；非 pending 候选返回 409。
- `POST .../reject` 只拒绝 pending 候选；不会创建记忆，之后可重新触发提取。
- 群开启 `auto_memory_extraction` 后，调度器按 `MEMORY_AUTO_EXTRACTION_INTERVAL_SECONDS`（默认 300 秒）扫描新入站消息；以 `(memory_extraction_watermark_at, memory_extraction_watermark_message_id)` 做增量游标，从旧到新分批读取，至少 3 条新消息才会调用模型。只生成 `pending` 候选，全局紧急暂停时停止；全局设置或群的 `enabled`/`paused` 任一不满足即跳过。成功产生候选时写审计 `memory.extract.auto`，事件总线发出 `memory.auto_extraction`。首次扫描只取最近 `MEMORY_EXTRACTION_MAX_MESSAGES` 条；积压消息按游标分批推进，不会因只取最新一批而跳过。
- Mock 提取的候选 `is_mock=true`，仅用于演示，不代表真实模型质量。摘要压缩、向量语义检索与冲突检测仍为规划能力。

`GET /api/messages` 参数：

- `page`、`page_size`
- `account_id`、`group_id`、`conversation_id`
- `direction`：`inbound` / `outbound`
- `status`
- `search`
- `since`、`until`：ISO 8601 时间

`GET /api/outbox` 参数：`page`、`page_size`、`status`、`group_id`。

发送队列状态包括 `pending`、`sending`、`sent`、`failed`、`unknown`。**`unknown` 表示发送结果无法确认，系统不会自动重发。**

预算示例：

```json
{
  "scope_type": "group",
  "scope_id": "<group_id>",
  "window": "day",
  "metric": "requests",
  "limit_value": 100,
  "warn_threshold": 0.8,
  "action": "pause",
  "enabled": true
}
```

- `scope_type`：`global` / `group` / `provider`。`group` / `provider` 必须引用真实存在的实体，创建/更新时会校验。
- `window`：`hour` / `day` / `week` / `month` / `all`。
- `metric`：`requests` / `tokens` / `cost`。
- `warn_threshold`：0–1，按上限比例生成 `warning` 告警；0 表示关闭接近上限告警。达到或超过上限生成 `exceeded` 告警。
- 超限时一律阻断模型调用；告警不是「仅告警」策略，不会改变这一强制行为。`action` 字段会保存，但不会改变阻断。预算按已记录的本地用量执行，单次调用可能使累计用量略超上限。
- 预算快照包含 `used`、`remaining`、`usage_ratio`、`state`（`ok` / `warning` / `exceeded` / `disabled`）与 `period_start`。`metric=cost` 时还包含 `cost_status` 与 `unpriced_success_requests`。
- 保存策略后会立即按当前真实用量评估一次；模型调用记录用量后也会评估。新告警写入 `budget_alerts`，同一 `policy_id + period_key + level` 只保留一条；每个新事件写审计 `budget.alert.warning` / `budget.alert.exceeded`，并通过 SSE 发布 `budget.alert`。只读的 `/api/budgets/check` 不会生成告警。

`GET /api/budgets/alerts` 返回 `items`、`total`、`page`、`page_size` 与 `note`。事件包含策略 ID、作用域名称、窗口、指标、级别、周期键、已用/上限、比例、中文说明与创建时间。`level` 只接受 `warning` / `exceeded`；`scope_type` 只接受 `global` / `group` / `provider`。

`GET /api/usage/trends` 参数：

- `bucket`：`hour`（最多 744）或 `day`（最多 365）。
- `periods`：时间桶数量，包含当前未结束的小时/自然日。
- `group_id`、`provider_id`：可选真实实体过滤。

返回 `bucket`、`periods`、`timezone`（配置时区，默认 `Asia/Shanghai`）、`window_start`、`window_end`、`items`、窗口总量与 `cost_note`。每个 `item` 包含 `bucket_start`、`bucket_end`、`bucket_label`、请求/成功/失败、Token、`cost`（未知为 `null`）、`cost_status` 与计价覆盖数。聚合在应用层按配置时区完成，空桶保留为 0。

`GET /api/usage/export.csv` 返回原始 `text/csv; charset=utf-8`（带 UTF-8 BOM，非 `{data,error}` 包装）。列为：

`created_at_utc, provider_id, provider_type, model, purpose, group_id, conversation_id, message_id, status, error_code, input_tokens, output_tokens, total_tokens, latency_ms, estimated_cost, currency, request_id`

- 只导出真实 `llm_usage` 元数据；**不含消息正文、提示词、模型输出、API Key 或任何凭证**。未知费用留空。
- 文本字段若以 `= + - @`、制表符或回车开头，会加单引号前缀，降低表格软件公式注入风险。
- 响应头包含 `Content-Disposition: attachment`、`Cache-Control: no-store` 与 `X-Content-Type-Options: nosniff`。
- 每次导出写审计 `usage.export`，记录筛选条件与行数；`since` 晚于 `until` 返回 400。

费用计算与阻断：

- 费用由本地按 Provider 的 `config.input_price_per_1k` / `config.output_price_per_1k` 与记录的 Token 估算，**不是服务商账单**。
- Mock Provider 的外部费用视为 0，状态为 `not_applicable`。
- 未配置单价的成功调用不可计价；Provider 响应未返回完整的输入/输出 Token 时同样不可计价。只要窗口内存在这类调用，汇总的 `cost` 为 `null`，`cost_status` 为 `partial`（部分可计价）或 `unconfigured`（全部不可计价），不会把未知成本显示为 0。
- 当 `metric=cost` 的预算适用于当前调用、但当前 Provider 未配置单价时，`/api/budgets/check` 返回 `allowed=false`，阻断原因为 `cost_unavailable`；实际调用会以 `BUDGET_EXCEEDED` 中止。Mock 与已配置单价的 Provider 不受此限制。
- 费用预算按已记录的成本执行；如果 Provider 配置了单价但响应未返回 Token 用量，该次调用不可计价，也不会增加费用已用额度。请选用会返回 `usage` 的 Provider；控制台会把这类调用标记为不可计价，便于发现。

`GET /api/usage/summary` 返回：

- 总量：`requests`、`successful_requests`、`failed_requests`、`tokens`、`cost`（可为 `null`）、`currency`、`priced_success_requests`、`unpriced_success_requests`、`cost_status`、`cost_note`、`window_start`、`window_end`。
- `by_provider`：包含所有已知 Provider（零调用也返回）及已删除/未知 Provider 占位行；字段包括 Provider 名称/类型/模型、`is_mock`、`cost_tracking`（`configured` / `mock_zero` / `unconfigured`）、请求/成功/失败、Token、费用与成本完整性。
- `by_group`：包含所有已知群（零调用也返回）及已删除/未关联群占位行；字段包括群名称、请求/成功/失败、Token、费用与成本完整性。
- `cost_status`：`complete`（窗口内全部成功调用可计价）、`partial`（部分不可计价）、`unconfigured`（全部不可计价）、`not_applicable`（只有 Mock 零外部费用）、`no_calls`（没有成功调用；失败调用不产生费用，因此费用列为 `null`）。
- `/api/dashboard` 的 `usage_today` 复用同一聚合结构，并额外提供 `last_24h`，全部来自本地数据库。

## 工具、插件与预算之外的扩展

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/tools` | 内置工具、风险等级、启用状态 |
| POST | `/api/tools/sync` | 同步工具记录 |
| POST | `/api/tools/{tool_name}/test` | 安全测试（仅低风险） |
| PATCH | `/api/tools/{tool_name}` | 启用/禁用 |
| GET | `/api/plugins` | 插件清单与加载错误 |
| POST | `/api/plugins/sync` | 重新读取清单 |
| GET | `/api/plugins/{plugin_id}` | 详情 |
| GET | `/api/plugins/{plugin_id}/health` | 健康检查 |
| POST | `/api/plugins/{plugin_id}/enable` | 启用/禁用（仅内置） |
| POST | `/api/plugins/{plugin_id}/approve` | 批准/撤销权限 |

工具测试请求：`{ "arguments": { "expression": "1+2*3" } }`。不存在任意 Shell、文件读写或任意网络请求工具。

## 备份与恢复

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/backups` | 备份记录 |
| POST | `/api/backups` | 创建备份，可带 `note` |
| GET | `/api/backups/{backup_id}` | 记录详情 |
| POST | `/api/backups/{backup_id}/verify` | SHA-256 与 SQLite 完整性校验 |
| POST | `/api/backups/{backup_id}/restore/preview` | 恢复预览 |
| POST | `/api/backups/{backup_id}/restore` | 恢复（需全局暂停 + `RESTORE`） |
| DELETE | `/api/backups/{backup_id}` | 删除备份 |
| GET | `/api/backups/{backup_id}/download` | 下载备份文件 |

恢复预览：

```json
{
  "backup": { "id": "...", "filename": "...", "sha256": "..." },
  "verification": {
    "checksum_ok": true,
    "integrity_ok": true,
    "schema_version": "a1f5c2d7e901",
    "tables": { "accounts": 1, "groups": 1 }
  },
  "current_state": { "accounts": 1 },
  "requires_pause": true,
  "paused": false,
  "confirm_phrase": "RESTORE",
  "warnings": ["..."]
}
```

恢复请求：

```json
{ "confirm": "RESTORE" }
```

- 未暂停：HTTP 409 `BACKUP_RESTORE_REQUIRES_PAUSE`。
- 确认短语错误：HTTP 400 `BACKUP_INVALID`。
- 成功恢复会自动创建安全备份、断开全部连接器、保持全局暂停。
- 备份不含媒体、日志与 `CREDENTIAL_ENCRYPTION_KEY`。

## 运维建议

1. 对外仅暴露反向代理 HTTPS，不直接暴露管理端口。
2. 定期创建并校验备份，同时在异地保存一份（备份本身仍含加密后的凭证字段）。
3. 恢复前先在控制台全局暂停；恢复后逐群确认配置再恢复回复。
4. 更换 `CREDENTIAL_ENCRYPTION_KEY` 前先记录并迁移已保存的 Token/API Key。

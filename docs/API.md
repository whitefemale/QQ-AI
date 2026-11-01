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

所有响应带 `X-Request-ID`。客户端可传 `X-Request-ID`（只保留字母、数字、`-`、`_`，最长 64 字符）。所有响应带 `X-Content-Type-Options: nosniff`、`X-Frame-Options: DENY`、`Referrer-Policy: no-referrer` 与 `Permissions-Policy`（关闭摄像头、麦克风、定位等，仅允许同源写入剪贴板）；HTML 响应额外带 CSP，Swagger 文档页豁免 CSP，JSON 响应不加 CSP。

### 请求头

| 头 | 说明 |
| --- | --- |
| `Content-Type: application/json` | 写请求 |
| `X-Request-ID` | 可选，请求追踪 ID |
| `X-Admin-Token` 或 `Authorization: Bearer <token>` | 仅远程管理时需要 |

### 管理边界

- 默认只接受回环地址（`127.0.0.1`、`::1`、`localhost`）请求。
- `Host` 必须命中 TrustedHost 允许列表：默认始终允许本机地址，反向代理或远程部署需在 `ALLOWED_HOSTS` 中显式加入代理域名；未命中返回 400 `Invalid host header`。显式 `*` 会关闭校验。
- CORS 只接受 `CORS_ORIGINS` 中的显式来源，必须带 scheme，不接受 `*`、空项或无 scheme；配置非法时后端启动失败。
- 非本机请求在 `ALLOW_REMOTE_ADMIN=false` 时统一返回 HTTP 403 `REMOTE_ADMIN_FORBIDDEN`。
- 开启远程后必须配置强 `ADMIN_API_TOKEN`，否则返回 401 `UNAUTHORIZED`。远程访问应置于 HTTPS 反向代理之后。
- 删除与清理等破坏性操作需要服务端确认词：删除使用 `?confirm=DELETE` 或 body 中的确认字段；保留清理与记忆清理使用 `confirm=CLEANUP`；恢复使用 `RESTORE`。缺失或不匹配返回 400 `CONFIRMATION_REQUIRED` / `BACKUP_INVALID`。
- 前端管理 Token 只保存在 `sessionStorage`（键 `aiqf.adminToken`），不会写入 LocalStorage。
- 前端 API 客户端默认 20 秒超时，可用 `timeoutMs` 覆盖；超时抛出 `ApiError(code="TIMEOUT", status=0)`，调用方主动取消仍保留 `AbortError`。超时不会自动重试写操作，避免重复发送。

### 格式约定

- 时间：ISO 8601 UTC（如 `2026-10-25T03:00:00+00:00`）。
- ID：字符串 UUID。
- 分页：`page`（从 1 开始）、`page_size`（1–200）；响应通常含 `items`、`total`、`page`、`page_size`。
- 密钥永远不返回明文。Provider 返回 `api_key_configured` 与 `api_key_masked`；连接器 Token 返回掩码。
- 错误 `details` 经过脱敏。

### 主要错误码

| 类别 | 代码 |
| --- | --- |
| 通用 | `VALIDATION_ERROR`、`NOT_FOUND`、`CONFLICT`、`INTERNAL_ERROR`、`OPERATION_PLANNED`、`CONFIRMATION_REQUIRED` |
| 管理边界 | `FORBIDDEN`、`UNAUTHORIZED`、`REMOTE_ADMIN_FORBIDDEN` |
| 凭证 | `CREDENTIAL_KEY_MISSING`、`CREDENTIAL_DECRYPT_FAILED` |
| 连接器 | `ADAPTER_NOT_FOUND`、`ADAPTER_UNAVAILABLE`、`ADAPTER_REMOTE_FORBIDDEN`、`ADAPTER_CONNECT_FAILED`、`ADAPTER_AUTH_FAILED`、`ADAPTER_IDENTITY_UNVERIFIED`、`ADAPTER_UNSUPPORTED_OPERATION` |
| 受管连接器 | `CONNECTOR_NOT_FOUND`、`CONNECTOR_NOT_MANAGED`、`CONNECTOR_PATH_UNSAFE`、`CONNECTOR_VERSION_UNSUPPORTED`、`CONNECTOR_JOB_CONFLICT`、`CONNECTOR_JOB_NOT_FOUND`、`CONNECTOR_CONFIRMATION_REQUIRED`、`CONNECTOR_LOCAL_ONLY`、`CONNECTOR_PORT_CONFLICT`、`CONNECTOR_PROCESS_UNSUPPORTED`、`CONNECTOR_PROCESS_NOT_TRACKED`、`CONNECTOR_INSUFFICIENT_DISK`、`CONNECTOR_ROLLBACK_FAILED`、`CONNECTOR_CREDENTIAL_KEY_MISSING`、`CONNECTOR_GLOBAL_PAUSE`、`CONNECTOR_IDENTITY_MISMATCH` |
| 发送 | `SEND_FAILED`、`SEND_STATUS_UNKNOWN`、`GLOBAL_PAUSED` |
| 策略 | `POLICY_BLOCKED`、`GROUP_NOT_WHITELISTED` |
| 人格 | `PERSONA_*` |
| 模型 | `PROVIDER_*`、`LLM_TIMEOUT`、`LLM_NETWORK_ERROR`、`LLM_AUTH_FAILED`、`LLM_RATE_LIMITED`、`LLM_QUOTA_EXCEEDED`、`LLM_MODEL_NOT_FOUND`、`LLM_INVALID_RESPONSE`、`LLM_NOT_CONFIGURED` |
| 工具 / 媒体 / 插件 / 记忆 | `TOOL_*`、`MEDIA_*`、`PLUGIN_*`、`MEMORY_SENSITIVE_CONTENT` |
| 预算 / 备份 | `BUDGET_EXCEEDED`、`BACKUP_*`、`BACKUP_RESTORE_REQUIRES_PAUSE`、`BACKUP_SCHEMA_INCOMPATIBLE` |

## 系统与运行状态

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/health` | 存活检查，无需数据库查询 |
| GET | `/api/ready` | 数据库、加密密钥、全局暂停、SSE 订阅者 |
| GET | `/api/dashboard` | 仪表盘聚合数据与全局暂停 |
| GET | `/api/capabilities` | 连接器、模型与媒体能力状态（含 `planned` / `unconfigured` / 执行方式） |
| GET | `/api/extensions/capabilities` | 扩展契约矩阵：五类接口、实现、执行方式、流水线依赖与安全保证 |
| GET | `/api/settings` | 运行信息、保留策略与真实清理状态（`retention_status`）、安全状态、隐私计数 |
| PUT | `/api/settings` | 更新 `retention` / `retention_auto` / `global_pause` |
| GET | `/api/system/retention/status` | 清理是否运行、自动清理开关与来源、调度器下次运行、上次摘要 |
| GET | `/api/system/retention/preview` | 只读预览将删除的消息/媒体/日志/记忆数量；不写审计、不改数据 |
| POST | `/api/system/retention/run` | 立即执行一次清理；body 必须带 `{"confirm":"CLEANUP"}`；并发运行返回 409 `CONFLICT` |
| POST | `/api/system/pause-all` | 全局紧急暂停 |
| POST | `/api/system/resume` | 解除全局暂停 |
| GET | `/api/audit` | 审计日志分页查询 |
| GET | `/api/events/recent?limit=20` | 最近 SSE 事件 |
| GET | `/api/events/stream?replay=0` | SSE 实时事件流 |
| GET | `/api/policy-explain` | 流水线顺序与暂停状态 |
| GET | `/api/onboarding` | 只读接入向导：八步状态、整体结论、下一步与警告（`onboarding.v1`） |
| GET | `/api/diagnostics` | 只读脱敏诊断摘要与可复制文本（`diagnostics.v1`） |

`POST /api/system/pause-all`：

```json
{ "reason": "账号出现验证码提示，立即暂停" }
```

`PUT /api/settings` 的保留相关示例（自动清理默认关闭，开启会写审计）：

```json
{
  "retention": { "log_retention_days": 30, "message_retention_days": 90, "media_retention_days": 30, "memory_retention_days": 0 },
  "retention_auto": { "enabled": false }
}
```

清理状态与执行：

- `GET /api/system/retention/status` 返回 `auto`（`enabled` / `source` / 配置默认值）、`running`、间隔与批次上限、保留天数、`scheduler`（是否运行、下次运行时间）与 `last_run`。
- `GET /api/system/retention/preview` 是只读快照：返回 `generated_at`、`running`、`retention_days`、`counts`（`messages_expired`、`messages_will_delete`、`messages_remaining_after`、`media_expired`、`media_from_messages`、`messages_with_media`、`logs`、`memories` 等）、`memory_retention_enabled`、`limits`、`truncated` 与 `notes`。它不取清理锁、不写审计、不更新 `last_run`。`messages_will_delete` 已按批次上限截断，实际运行数量可能因新消息写入而不同。
- `POST /api/system/retention/run` 立即执行一次，body 必须为 `{"confirm":"CLEANUP"}`，缺失或不匹配返回 400 `CONFIRMATION_REQUIRED` 且无任何副作用；调度器自动触发不需要确认词。返回与 `last_run` 相同的摘要：`status`、`trigger`、`actor`、起止时间、`global_pause`、`truncated`、`retention_days`、各类 `counts` 与脱敏 `error`。并发执行返回 409 `CONFLICT`。
- 自动清理只删除超过保留期限的消息、媒体资产、转写、媒体任务、`app.log.*` 轮转日志、人格证据/版本快照中的证据引用、记忆来源 ID 与超期未固定记忆；不会删除 outbox、审计、备份或当前 `app.log`，不会调用模型或发送消息。全局暂停不阻止本地清理。消息清理不会改写记忆正文，记忆正文只由记忆保留期清理删除。
- `memory_retention_days` 允许 `0` 或 `1–3650`；`0` 表示不自动删除记忆，不能被通用保留天数归一化改写为默认值。`last_run.counts` 包含 `memories_deleted`。

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

### 接入向导 `GET /api/onboarding`

只读聚合接口，不写审计、不触发模型/QQ/连接器网络或进程动作。连接器只读取已有检测结果，扫描必须由连接器页显式发起。

```json
{
  "schema_version": "onboarding.v1",
  "checked_at": "2026-10-31T00:00:00+00:00",
  "overall": "ready_real | ready_mock_only | action_required | blocked",
  "ready_for_replies": false,
  "mock_only": false,
  "global_paused": false,
  "steps": [
    {
      "key": "connector",
      "order": 2,
      "title": "连接器准备",
      "state": "done | action_required | optional | blocked | mock_only | not_verified",
      "summary": "……",
      "next_step": "……",
      "route": "/connectors",
      "freshness": "fresh | aging | stale | missing | not_applicable",
      "evidence": { "onebot_instances": 1 }
    }
  ],
  "warnings": [],
  "blockers": [],
  "next_action": { "key": "connector", "label": "连接器准备", "route": "/connectors" },
  "notes": []
}
```

- 固定八步：`backend, connector, qq_login, connection_test, model, groups, observe, enable`；`route` 只使用硬编码内部路径。
- `qq_login` 的在线事实来自当前进程内适配器健康状态（`public_health`），持久化状态只用于配置与历史证据；Mock 在线不计为真实在线。
- `connection_test` 只采用可归属到当前实例、模式为 `onebot11`、且测试后没有更新配置的 `connector.diagnose` 或 `account.instance.test` 审计；`account.instance.test_unsaved` 永远不作为证据。最新失败覆盖更早成功，超过 24 小时不满足步骤。
- `model` 只采用非 Mock、配置完整、测试结果成功且不超过 24 小时的 Provider；不读取模型名、消息或预览。
- `observe` 需要已启用的真实观察群中确实存在持久化入站消息；仅配置观察不等于已观察到消息。
- `enable` 要求全局未暂停、真实群已启用且非观察、账号实时在线，并解析到测试新鲜成功的真实 Provider；`manual_confirm` 视为开启但回复只进入待审队列。Mock 群永远不能使 `ready_for_replies` 为真。
- 响应只含计数、枚举、布尔值、时间与固定文案，不返回 QQ 号、昵称、群号/群名、账号名、端点、Provider 名、Base URL、模型 ID、Token、API Key、错误消息、审计 details 或路径。

### 诊断摘要 `GET /api/diagnostics`

只读 allowlist 构造的新对象，不读取日志正文、不返回文件路径、不触发网络或第三方动作。顶层字段固定为：

`schema_version, generated_at, excluded, app, readiness, counts, accounts, connectors, providers, groups, messages, connection_test, recent_audit_actions, text`

- `accounts` 的在线数来自 `public_health()`；Mock 不计入真实在线。
- `connectors.real_qq_verified` 固定为 `false`，自动化诊断不能替代真实 QQ 验收。
- `connection_test.message_send_attempted` 固定为 `false`。
- `recent_audit_actions` 只含最近 200 条审计的动作名与计数，不含 target、details、IP 或逐行时间。
- `text` 由后端用同一批字段与固定中文标签生成，供前端直接复制；`excluded` 与文本末尾明确列出已排除的 Token/API Key/Authorization/Cookie、QQ 身份、群成员与消息正文、路径/PID/端口/端点、模型地址/名称、审计 details 与日志行等。
- 不提供日志下载或日志 HTTP 接口；完整日志只保存在本机，桌面版可通过既有 IPC 打开日志目录。

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
- 常见事件：`message.received`、`message.duplicate`、`message.intercepted`、`message.generated`、`reply.awaiting_approval`、`outbox.sent`、`outbox.failed`、`adapter.status`、`adapter.event`、`system.paused`、`system.resumed`、`persona.proposal`、`persona.applied`。

## 演示环境

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/api/demo/bootstrap` | 幂等创建 Mock 账号、Mock 实例、Mock 模型、演示群、模板人格，并连接 Mock |

`POST /api/demo/bootstrap` 空对象即可。返回 `created`、`account`、`group`、`persona`、`provider`、`global_pause`、`notes`。重复调用不会重复创建。

## 受管连接器（仅本机）

整个 `/api/connectors/*` 要求回环客户端、回环 `Host`，拒绝非本机 `Origin`；**独立于
`ALLOW_REMOTE_ADMIN`**，远程管理即使开启也不能访问。所有写操作需要精确确认词，并写审计
（不含 Token、配置正文或完整路径）。`GET` 响应可能包含本机受管路径，因此同样仅限本机。

| 方法 | 路径 | 说明 | 确认词 |
| --- | --- | --- | --- |
| GET | `/api/connectors` | 安装、状态、最近任务与关联实例摘要 | — |
| GET | `/api/connectors/capabilities` | 平台支持、本机限定与诚实限制 | — |
| GET | `/api/connectors/installations` | 已检测安装列表（含外部只读） | — |
| POST | `/api/connectors/scan` | 重新扫描受管根目录 | — |
| GET | `/api/connectors/installations/{id}` | 单个安装详情与证据 | — |
| GET | `/api/connectors/releases` | 最近可用版本（不下载） | — |
| GET | `/api/connectors/check-release` | 查询最新/指定版本元数据 | — |
| POST | `/api/connectors/install` | 创建下载/校验/解压任务 | `INSTALL` |
| GET | `/api/connectors/jobs/{id}` | 任务进度、阶段、脱敏日志尾部 | — |
| POST | `/api/connectors/jobs/{id}/cancel` | 取消任务 | `CANCEL` |
| POST | `/api/connectors/installations/{id}/run-installer` | 启动官方安装器 | `RUN INSTALLER` |
| POST | `/api/connectors/installations/{id}/start` | 启动受管连接器 | `START NAPCAT` |
| POST | `/api/connectors/installations/{id}/stop` | 停止本会话进程树 | `STOP NAPCAT` |
| GET | `/api/connectors/installations/{id}/config/preview` | 配置预览，Token 掩码 | — |
| POST | `/api/connectors/installations/{id}/config/apply` | 快照 + 原子写入 + 创建实例 | `WRITE CONFIG` |
| GET | `/api/connectors/installations/{id}/snapshots` | 加密快照元数据 | — |
| POST | `/api/connectors/installations/{id}/config/rollback` | 恢复配置与实例 Token | `RESTORE CONFIG` |
| POST | `/api/connectors/installations/{id}/activate` | 切换活动版本 | `SWITCH VERSION` |
| POST | `/api/connectors/installations/{id}/diagnose` | 诊断，优先复用在线适配器 | — |
| POST | `/api/connectors/accounts/{account_id}/confirm-identity` | 记录 QQ 身份确认 | `CONFIRM IDENTITY` |
| POST | `/api/connectors/import-config` | 只读导入 `onebot11*.json` | `IMPORT CONFIG` |

请求体示例：

```json
{ "version": "v4.18.42", "confirm_text": "INSTALL" }
```

```json
{ "user_id": "10001", "confirm_text": "CONFIRM IDENTITY" }
```

```json
{ "text": "{\"network\":{...}}", "display_name": "导入的 NapCat", "confirm_text": "IMPORT CONFIG" }
```

关键响应字段与语义：

- 安装列表项包含 `state`（含 `evidence`、`observed_at`、`severity`、`next_steps`）、
  `managed`、`active`、`version_compatibility`、`real_traffic_verified`、
  `process`、`installer`、`ports`、以及关联实例摘要。
- `real_traffic_verified` 只有在身份确认后存在非 Mock 持久化入站消息与成功出站时才为
  `true`；安装、进程、WS 连接和诊断不能触发。
- 配置预览/写入/回滚响应只返回掩码 Token；快照正文永不返回。
- `diagnose` 响应额外含 `reused_live_adapter` 与 `diagnostic_source`
  （`live_adapter` / `ephemeral_diagnostic`），并固定 `message_send_attempted=false`。
- 全局紧急暂停时启动、运行安装器与写配置返回 409 `CONNECTOR_GLOBAL_PAUSE`。
- 不提供自动更新、自动卸载、任意路径、任意命令或外部进程接管。

## QQ 账号与连接器

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/accounts` | 账号列表、连接方式选项、全局暂停 |
| POST | `/api/accounts` | 创建账号（可内嵌首个 `instance`） |
| POST | `/api/accounts/test-connection` | 测试未保存的连接配置 |
| GET | `/api/accounts/{account_id}` | 账号详情与实例 |
| PATCH | `/api/accounts/{account_id}` | 更新账号 |
| DELETE | `/api/accounts/{account_id}?confirm=DELETE` | 删除账号及群/成员/消息/记忆/队列，并清理未被共享引用的媒体 |
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
- 连接器实时状态只存在于当前进程；重启后需要重新连接；启动时会把数据库中残留的
  `online` / `connected_unverified` / `reconnecting` / `connecting` / `error` 重置为
  `disconnected`。
- 当前不下载真实媒体，也不转发媒体文件。

### 连接状态语义

```text
unconfigured → disconnected → connecting → connected_unverified → online
                                      ↘ reconnecting ↗
                                      ↘ error
```

- `connected_unverified`：WS 握手成功，但 `get_login_info` 尚未返回 `user_id`。
  **不允许发送**，不派发 outbox，也不能拉取群列表或导入群。
- `online`：WS 存在、状态为 `online` 且身份已验证。只有该状态可以发送与拉群。
- 心跳、`lifecycle` 事件和发送成功都不会把 `connected_unverified` 提升为 `online`；
  只有身份验证成功才升级。
- 发送状态未知的消息保持 `unknown`，不会自动重发。

### 测试连接 / 诊断结果

`POST /api/accounts/test-connection` 与
`POST /api/accounts/{account_id}/instances/{instance_id}/test` 返回同一结构：

```json
{
  "data": {
    "ok": true,
    "state": "identity_verified",
    "connection_mode": "onebot11",
    "is_mock": false,
    "tested_at": "2026-10-31T03:00:00+00:00",
    "latency_ms": 128,
    "login": {"user_id": "10001", "nickname": "机器人"},
    "groups": [{"group_id": "100001", "group_name": "测试群"}],
    "group_count": 1,
    "checks": [
      {"id": "config", "label": "配置校验", "state": "ok", "detail": "…", "error_code": null, "duration_ms": null, "next_step": null, "source": "live_diagnostic"},
      {"id": "websocket", "label": "WebSocket 握手", "state": "ok", "detail": "…"},
      {"id": "auth", "label": "OneBot 鉴权", "state": "ok", "detail": "…"},
      {"id": "identity", "label": "QQ 登录身份", "state": "ok", "detail": "…"},
      {"id": "action", "label": "动作通道", "state": "ok", "detail": "…"},
      {"id": "groups", "label": "群列表读取", "state": "ok", "detail": "…"},
      {"id": "event_stream", "label": "事件流/心跳", "state": "ok", "detail": "…"},
      {"id": "real_inbound", "label": "真实入站消息", "state": "not_verified", "detail": "…"},
      {"id": "real_outbound", "label": "真实发送", "state": "not_verified", "detail": "…"}
    ],
    "identity_verified": true,
    "action_path_verified": true,
    "group_list_verified": true,
    "real_inbound_verified": false,
    "real_outbound_verified": false,
    "message_send_attempted": false,
    "verified_scope": ["config", "websocket", "auth", "identity", "action", "groups", "event_stream"],
    "unverified_scope": ["connector_runtime", "real_inbound", "real_outbound"],
    "error_code": null,
    "error_message": null,
    "next_step": "在真实环境中完成受控消息收发验收；自动化诊断不能代替该步骤。",
    "note": "连接与身份检查不等于真实 QQ 群消息收发验证；本测试不发送任何消息。"
  },
  "error": null,
  "request_id": "…"
}
```

检查项固定 9 个：`config`、`websocket`、`auth`、`identity`、`action`、`groups`、
`event_stream`、`real_inbound`、`real_outbound`。

- 检查状态：`ok` / `warning` / `failed` / `skipped` / `not_verified`。
- 总状态：`failed` / `identity_verified` / `mock_only`。
- **`ok` 或 `identity_verified` 只代表必需检查通过，不代表真实 QQ 收发已验证。**
- `real_outbound` 始终为 `not_verified`，`message_send_attempted` 始终为 `false`；
  诊断不发送任何消息。
- 群列表读取失败只会让 `groups` 降为 `warning`，不会推翻已成功的身份验证。
- 未配置 Token 时 `auth` 为 `warning`；握手或身份鉴权失败时按错误码返回 `failed`。
- Mock 连接返回 `state: "mock_only"`、`is_mock: true`，不建立真实 WS。
- 配置非法或连接失败时仍返回 HTTP 200 的结构化失败报告，便于前端逐项展示；
  真正的网络中断、鉴权失败等不会变成无信息的 500。
- 诊断结果不包含 Token；`login` 只含脱敏后的账号与昵称。
- 是否在线以进程内适配器为准；列表中的 `status` 是数据库快照，`live_health` 提供
  `status_source`、`observed_at`、`identity_verified` 等当前进程证据。

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
| GET | `/api/groups?account_id=` | 群列表、五档回复模式（含默认观察）、限速默认值 |
| POST | `/api/groups` | 创建群配置；未指定时 `reply_mode=observe`、`enabled=false` |
| GET | `/api/groups/members?account_id=` | 成员状态 |
| POST | `/api/groups/import` | 导入群列表（新建行默认观察且关闭回复；已存在的群保留原模式） |
| POST | `/api/groups/import-connector` | 从连接器读取并导入群；必须带与在线非 Mock 适配器一致的 `confirm_self_user_id` |
| GET | `/api/groups/{group_id}` | 群详情 |
| PATCH | `/api/groups/{group_id}` | 更新群配置 |
| DELETE | `/api/groups/{group_id}?confirm=DELETE` | 删除群配置；保留历史消息但解除群关联，取消待发送消息 |
| POST | `/api/groups/{group_id}/pause` | 暂停该群 AI 回复 |
| POST | `/api/groups/{group_id}/resume` | 恢复该群 |

群创建/更新关键字：

```json
{
  "account_id": "<account_id>",
  "platform_group_id": "123456789",
  "name": "测试群",
  "enabled": false,
  "reply_mode": "observe",
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
    "max_replies_per_member_per_hour": 10,
    "max_replies_per_member_per_day": 50,
    "max_consecutive_replies": 3
  },
  "max_reply_chars": null,
  "context_message_limit": null,
  "allow_tools": false,
  "allow_memory": false,
  "auto_memory_extraction": false,
  "allow_proactive": false
}
```

- 回复模式：
  - `observe`：只记录与做安全判断，不生成回复；**新建与导入的新群默认值**。
  - `mention_only`：仅被 @ 或回复机器人消息时生成回复。
  - `manual_confirm`：触发条件同 `mention_only`，但生成后只进入 `pending_approval`，必须人工通过，绝不自动发送。
  - `always`：所有通过硬规则的消息均生成回复。
  - `keyword`：命中 `keywords`，或被 @ / 回复机器人时生成回复（高级）。
  - `context` 与 `scheduled` 仍返回 `state: "planned"`，提交会被拒绝（`VALIDATION_ERROR`），前端禁用。
- **已有群不会被静默迁移**；导入时若群已存在，保留其原 `reply_mode`。
- 导入的群默认 `enabled=false`，必须逐群确认。
- `allow_memory` 开启后，只会检索当前群与当前发送者的记忆；其他群、敏感记忆、过期记忆和被排除成员的成员级记忆不会注入。
- `auto_memory_extraction` 默认 `false`，且必须同时开启 `allow_memory`；关闭长期记忆会自动关闭后台提取。它只生成待审核候选，不会自动批准或注入。
- 群对象还返回 `memory_extraction_last_run_at`、`memory_extraction_last_error`、`memory_extraction_watermark_at`、`memory_extraction_watermark_message_id`，用于说明后台检查状态；错误信息已脱敏。
- `rate_limit` 同时支持群级与每成员限频。群级按出站 Message 统计；每成员限频按 outbox 中 `sent`/`unknown` 的 AI 回复统计，命令回复与 `pending_approval` 草稿不计入。缺失来源成员的历史记录不归属到成员额度。
- `max_reply_chars` 可选，范围 50–2000；`context_message_limit` 可选，范围 1–100。为 `null` 时使用全局设置，群对象返回 `*_effective` 实际生效值。
- 群工具默认关闭。
- `llm_provider_id` / `llm_fallback_provider_id` 为可选的群级模型绑定。未设置主模型时使用全局默认 Provider；备用模型必须依附主模型，且不能与主模型相同。绑定或修改时会校验 Provider 存在且已启用；事后被禁用的既有绑定不会阻止保存其他群配置。
- 群对象返回 `llm_provider_name`、`llm_provider_type`、`llm_provider_state` 以及对应的 `llm_fallback_*` 字段；`state` 为 `default`（未绑定）、`mock`、`configured`、`disabled` 或 `missing`。

### 删除语义

所有删除端点都要求 `?confirm=DELETE`（精确大写），缺失或大小写不符返回 400 `CONFIRMATION_REQUIRED`，数据保持不变。

- **删除账号**：同一事务内清理其群、成员、消息、记忆与候选、outbox 与适配器实例；先擦除人格证据引用与记忆来源 ID，避免悬空引用。账号名下的媒体资产按引用检查：仍被其他账号消息引用时保留，否则删除文件并标记 `status=deleted`、`storage_path=null`、`deleted_at`。媒体文件删除失败只记录计数与日志，不掩盖账号删除结果。审计 `account.delete` 记录各计数，不含消息正文或路径。
- **删除群**：记忆与候选随之删除；历史消息保留，但 `group_id` 置 `NULL`，不再关联该群，也不会被该群配置使用。`pending` / `pending_approval` 的待发消息改为 `cancelled`、清空 `next_attempt_at`、`last_error_code=POLICY_BLOCKED`，不会继续发送；`sending` 在途消息不改状态，交由发送结果未知/失败路径处理。审计 `group.delete` 记录保留消息数、删除记忆数、取消队列数与群名。
- **删除人格**：版本、特征与成长事件一并删除，绑定群的 `persona_id` 置空；已产生的人格不会因删除账号而连带删除。
- **删除备份**：仅删除该备份记录与其文件，写 `backup.delete` 审计（文件名与 ID，不含完整路径）。

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
| POST | `/api/personas/{persona_id}/preview` | 与 PATCH 相同字段；纯投影返回 `{saved:false,before,after,changes,diff}`，不写库、不增版本、不写审计 |
| DELETE | `/api/personas/{persona_id}?confirm=DELETE` | 删除人格及版本/特征/事件；绑定群 `persona_id` 置空 |
| GET | `/api/personas/{persona_id}/traits?status=` | 特征列表 |
| GET | `/api/personas/{persona_id}/events?limit=50` | 成长事件 |
| GET | `/api/personas/{persona_id}/events/{event_id}/evidence` | 该提案引用且属于绑定群范围的证据预览；缺失项标记 `missing` |
| GET | `/api/personas/{persona_id}/versions` | 版本列表 |
| GET | `/api/personas/{persona_id}/versions/{version_id}` | 版本脱敏快照、当前状态与字段/特征差异 |
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
- 候选提案在批准前不会物化为 `PersonaTrait`，因此拒绝不会留下候选特征行；批准时才写入 `stable` 特征。历史遗留的未锁定候选行在拒绝时会被清理。
- 成长事件与待审核提案返回 `diff_summary`：由模型以第一人称生成的自然语言变化摘要（最多 600 字），旧事件可能为 `null`。同时返回脱敏的 `old_state`、`new_state` 与结构化 `diff`/`impact`（字段变更、特征增/改/删、作用域、锁定跳过项）；不返回推理步骤或思维链。
- 成长提案若要求忽略、绕过、关闭或修改安全规则、系统提示、白名单、管理员权限、预算、群规或工具权限，会被拒绝并记录为 `rejected_invalid`；成长永远不会写入群配置、账号、预算策略或工具配置。
- 预览与版本差异是纯读取/投影结果；前端在保存前先展示差异，回滚前也先查看版本差异。
- `trigger_type` 包含 `auto`（回复后常规触发）、`self_inquiry`（用户询问“你是谁/你的人设/介绍你自己”等）、`manual`（管理员手动分析）与 `review`（审核后应用）。`self_inquiry` 只豁免成长最小间隔，不豁免证据数量、会话数、置信度、锁定字段与范围治理。
- 成长在回复完成后异步执行，同一人格与群的并发成长会合并，不阻塞正常回复。

测试人格等同于 `/api/playground/run`，必须提供 `account_id` 与 `group_id`，不发送、不落库。

## 模型 Provider 与媒体能力

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/providers` | 模型 Provider 列表与类型 |
| POST | `/api/providers` | 创建 Provider |
| GET | `/api/providers/{provider_id}` | 详情 |
| PATCH | `/api/providers/{provider_id}` | 更新 |
| DELETE | `/api/providers/{provider_id}` | 删除；被群绑定时返回 409 |
| GET | `/api/providers/{provider_id}/models` | 实时模型列表（只读能力发现，不写用量） |
| POST | `/api/providers/{provider_id}/test` | 连通性测试（极短真实请求，Mock 除外） |
| POST | `/api/providers/{provider_id}/test-generation` | 自定义提示词的真实生成测试 |
| POST | `/api/providers/{provider_id}/operations/{operation_id}/cancel` | 取消本地等待中的测试 |
| GET | `/api/media/providers` | 媒体 Provider 与健康状态 |
| GET | `/api/media/capabilities` | 能力概览（状态、执行方式、来源、检查时间、下一步） |
| POST | `/api/media/providers/{provider_id}/enable` | 启用/禁用媒体 Provider；停用会取消对应能力下排队与运行中的任务 |
| POST | `/api/media/providers/{provider_id}/test` | 媒体 Provider 测试 |
| GET | `/api/media/usage?hours=&provider_id=&capability=&account_id=&group_id=` | 媒体 Provider 用量聚合（请求数、成功/失败、Mock 数、平均延迟、外部费用完整性） |
| GET | `/api/media/jobs?status=&limit=` | 媒体任务队列 |
| POST | `/api/media/jobs/{job_id}/cancel` | 取消排队或运行中的任务（写审计） |
| POST | `/api/media/jobs/{job_id}/retry` | 重试已失败任务；当前没有可用 Provider 时返回 400（写审计） |
| POST | `/api/media/jobs/process-due` | 处理到期任务（Mock） |
| GET | `/api/extensions/capabilities` | 统一扩展契约矩阵、媒体能力、工具与插件状态 |

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
- `base_url` 必须是无 userinfo、查询与片段的绝对 `http(s)` 地址；不能带已知端点后缀。服务会拒绝云元数据地址（如 `169.254.169.254`、`metadata.google.internal`、`100.100.100.200`）、链路本地、组播、未指定地址与 `100.64.0.0/10` 共享地址，返回 400 `VALIDATION_ERROR`。回环与 RFC1918 私网地址允许使用，以支持 Ollama / LM Studio 等自建模型。校验只基于字面量与主机名，不解析 DNS，仍存在 DNS rebinding 残留风险；适配器不跟随重定向。
- 删除仍被任一群绑定为主模型或备用模型的 Provider 会返回 HTTP 409 `PROVIDER_IN_USE`，并在 `details.group_ids` 中列出（最多 20 个）受影响群；请先在群管理中解除绑定。
- 真实视觉/语音等媒体 Provider 尚未实现；请勿把 Mock 媒体任务当作真实识别结果。媒体契约（inspect / rerank / video）与确定性 Mock 已提供，但未接入业务回复管线。
- 媒体任务在收到图片/语音/文件片段时只入队，由应用内后台 worker 处理，不阻塞 QQ 事件；未配置时返回诚实的“未配置/处理中”说明。每次 Provider 调用（含失败）写一条媒体用量；Mock 外部费用为 0，真实/未知为 `null`，不会伪造金额。媒体用量不含媒体内容、转写文本或提示词。
- `GET /api/media/usage` 返回窗口总量、`by_provider` 与 `by_capability`，费用状态为 `complete` / `partial` / `unknown` / `no_calls`。
- `GET /api/media/capabilities` 的每一项包含 `execution`：`job` 表示任务队列真实执行（`image.describe`、`ocr.extract`、`audio.transcribe`、`text.embed`），`contract_only` 表示仅有接口契约与 Mock、队列不会调用（`audio.synthesize`、`media.inspect`、`text.rerank`、`video.describe`）。同时返回 `source`（`provider_registry`）、`checked_at`、`enabled_provider_ids`、`last_error`、`note` 与 `next_step`。仅有已停用的可执行实现时状态为 `unconfigured`，不会谎报为 `planned`。
- `POST /api/media/providers/{provider_id}/enable` 返回 Provider 公开字段以及 `cancelled_jobs`、`cancelled_capabilities`、`cancellation_error`。停用时若某能力不再有任何启用的 Provider，该能力下 `queued` 与 `running` 任务立即置为 `cancelled`（错误码 `PROVIDER_CAPABILITY_MISSING`）；运行中 Provider 迟到的成功结果不会写入转写/输出，迟到失败也不会覆盖取消状态。审计动作 `provider.media.toggle` 记录取消数量与 actor；取消任务失败会在响应与审计中如实报告，不伪装成功。
- `POST /api/media/jobs/{job_id}/cancel` 支持取消 `queued` 与 `running` 任务，写入 `media.job.cancel` 审计；已结束任务返回不可取消错误。`POST /api/media/jobs/{job_id}/retry` 仅在已失败且仍有可用 Provider 时重新排队，否则返回 400 `PROVIDER_CAPABILITY_MISSING`；写入 `media.job.retry` 审计。
- `GET /api/extensions/capabilities` 返回 `contracts`（`chat_adapter`、`llm_provider`、`media_provider`、`tool`、`plugin`）、`media`、`tools`、`plugins`、`checked_at` 与 `notes`。每类契约列出接口名、状态、执行方式、实现列表、流水线依赖与安全保证。工具列表严格只有 `calculator` 与 `current_datetime`；第三方插件 `execution` 为 `not_executed`，并列出未来运行时必须满足的八项要求。该接口只读，不触发 Provider、连接器或模型调用。

### 模型测试、模型列表与取消

- Provider 对象新增 `config_complete`、`last_test`、`last_generation`。`last_test/last_generation` 只含白名单元数据（结果、错误码、延迟、模型、Mock 标记、Token、费用状态、上游 request id、截断预览），不含 Key、提示词或完整响应体。
- `POST /test` 默认提示“请只回复 OK”，最多 8 Token；`POST /test-generation` 的 `prompt` 为 1–2000 字符、`max_output_tokens` 为 1–128，可选 `temperature`。可在 body 中传 8–64 位 `[A-Za-z0-9_-]` 的 `operation_id` 供取消端点使用。
- 测试调用是真实计费调用（Mock 除外），写入 `LLMUsage`（`purpose=test`、`feature=provider_test`）并经过预算检查；单次尝试，不自动重试、不回退。Provider 不存在返回 404；body 校验失败返回 400；预算阻断返回 429；同一操作并发冲突返回 409；取消不存在或已结束的操作返回 200 `found=false`。
- 认证、额度、限流、超时、网络、配置等“测试结果”返回 **HTTP 200 + `ok=false`**，保留 `error_code`、`next_step`、`retryable` 与 `retry_after_seconds`。Mock 结果 `is_mock=true`、`billable=false`、`cost_status=mock_zero`，不能证明真实 API 可用。
- 测试响应字段：`ok/kind/outcome/provider_id/provider_type/provider_enabled/model/is_mock/billable/operation_id/message/error_code/next_step/retryable/retry_after_seconds/tested_at/latency_ms/attempts/reply_preview/text/upstream_request_id/usage`。`usage.cost_status` 为 `estimated` / `mock_zero` / `unavailable`；未知费用为 `null`，不会补 0。
- 取消只停止本地等待；服务商可能继续生成并计费。浏览器断线不会自动取消服务端任务。
- `GET /models` 的 `state` 为 `available`、`unsupported`（404/405/501）、`mock`、`not_configured`、`auth_failed`、`rate_limited`、`network_error`、`timeout`、`invalid_response` 或 `error`。OpenAI 兼容读取 `{"data": [...]}` 或顶层数组；Anthropic 按 `after_id/has_more` 分页，最多 500 条。模型 ID 始终可手动填写。
- 修改 `provider_type/base_url/model/api_key/timeout_seconds/max_output_tokens/temperature` 或显式清空 Key（`PATCH {"api_key": ""}`）会清除两份测试证据与 `last_error/last_tested_at`，并将状态重置为 `configured/unconfigured`（Mock 为 `available`）。`api_key` 传 `null` 会被拒绝，必须传空字符串才能清除。

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
| GET | `/api/messages/export.csv` | 按同一筛选导出消息 CSV（UTF-8 BOM、公式转义、最多 50,000 行） |
| GET | `/api/outbox` | 发送队列 |
| POST | `/api/outbox/{outbox_id}/approve` | 批准待确认回复；body `{content?}`；可选编辑内容，先做完整批准前检查，原子切换后立即尝试发送一次 |
| POST | `/api/outbox/{outbox_id}/reject` | 拒绝待确认回复；body `{reason?}`；条件更新为 `rejected` |
| POST | `/api/outbox/dispatch-due` | 派发到期消息（暂停时 409；只派发 `pending`，绝不发送 `pending_approval`） |
| GET | `/api/usage` | 模型调用明细 |
| GET | `/api/usage/summary?hours=24` | 按 Provider / 群的时间窗用量与费用完整性汇总 |
| GET | `/api/usage/trends?bucket=hour&periods=24` | 按配置时区的小时/自然日真实用量趋势；可选 `group_id`、`provider_id` |
| GET | `/api/usage/export.csv` | 导出真实调用元数据 CSV；可选 `since`、`until`、`group_id`、`provider_id`、`status`、`purpose` |
| GET | `/api/budgets` | 预算策略及当前窗口用量快照 |
| POST | `/api/budgets` | 新建/提交预算策略 |
| PUT | `/api/budgets/{policy_id}` | 更新预算策略 |
| GET | `/api/budgets/{policy_id}` | 详情（含真实用量快照） |
| GET | `/api/budgets/check?account_id=&group_id=&provider_id=&feature=` | 检查预算；返回阻断原因与说明 |
| GET | `/api/budgets/alerts` | 预算告警事件历史；支持 `level`、`scope_type`、`scope_id`、`since` 与分页 |
| GET | `/api/memories` | 记忆列表；支持 `account_id`、`group_id`、`member_id`、`memory_type`、`search`、`include_expired` |
| POST | `/api/memories` | 手动添加记忆；拒绝疑似密码/验证码/证件号/银行卡号/密钥 |
| POST | `/api/memories/extract` | 手动触发 AI 候选提取；body `{group_id}`；只生成待审核候选 |
| GET | `/api/memories/candidates` | 候选列表；支持 `account_id`、`group_id`、`status`、`page`、`page_size` |
| POST | `/api/memories/candidates/{candidate_id}/approve` | 人工批准候选并创建正式记忆；可选 `sensitivity`（`normal`/`sensitive`，默认 `normal`） |
| POST | `/api/memories/candidates/{candidate_id}/reject` | 人工拒绝候选 |
| GET | `/api/memories/export.csv` | 按当前筛选导出 CSV；默认排除敏感记忆；`include_sensitive=true` 才包含；响应带 BOM 并做公式注入防护 |
| POST | `/api/memories/cleanup` | `{mode:"expired"\|"older_than",days?,dry_run?,confirm?}`；真实删除需 `confirm:"CLEANUP"`；只删除未固定记忆 |
| GET | `/api/memories/{memory_id}/sources` | 来源消息摘要（发送者、时间、群、脱敏预览、`missing`） |
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
- 短期上下文按 `account_id` 与群/私聊隔离；相同 `conversation_id` 不会在不同账号或群之间串上下文。
- 注入内容带有“不可信历史资料”标记；记忆永远不能成为系统或管理员指令。
- `GET /api/memories/export.csv` 的过滤条件与列表一致，静态路由声明在 `/{memory_id}` 之前。CSV 只含记忆元数据与正文，不含凭证；导出写审计 `memory.export`，只记录筛选条件、行数与是否含敏感，不记录正文。
- `POST /api/memories/cleanup`：`expired` 删除 `expires_at <= now` 的记忆；`older_than` 必须提供 1–3650 天。固定记忆永不删除；dry-run 只返回匹配数，不需要确认词；`dry_run=false` 必须带 `confirm:"CLEANUP"`，否则返回 400 `CONFIRMATION_REQUIRED` 且不删除。清理写审计 `memory.cleanup`。
- 被删除的记忆不会再出现在提示词检索结果中；来源消息被删除时 `sources` 返回 `missing`。
- 新批准候选可指定 `sensitivity=sensitive`，此类记忆不会自动注入。

AI 候选提取与审核：

- `POST /api/memories/extract` 只读取指定群最近入站文本消息（默认最多 40 条，至少 3 条）；群必须开启 `allow_memory`，已排除记忆的成员不参与。
- 模型输出只写入 `pending` 候选，返回 `created`、`scanned_messages`、`skipped`、`skipped_reasons`、Provider/模型与 `is_mock`。**候选不会自动保存为正式记忆，也不会注入提示词。**
- 候选必须引用输入中真实存在的消息 ID；敏感内容、未知成员、低置信度、重复内容与超出上限的候选会被跳过。
- `GET /api/memories/candidates` 默认 `status=pending`；可选 `pending`、`approved`、`rejected`。
- `POST .../approve` 可传可选覆盖字段 `content`、`memory_type`、`confidence`、`sensitivity`，批准后创建未固定的正式记忆并保留证据引用；`sensitivity` 默认 `normal`，非法值返回 422，非 pending 候选返回 409。
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

`GET /api/messages/export.csv` 支持与列表相同的筛选参数（不含分页），按 `event_timestamp` 升序导出，返回原始 `text/csv; charset=utf-8`（带 UTF-8 BOM，非 `{data,error}` 包装）。列为：

`message_id, platform_message_id, account_name, group_name, conversation_type, sender_id, sender_name, is_self, direction, content_text, event_timestamp, processing_status, trigger_reason, model_latency_ms, input_tokens, output_tokens, created_at`

- **包含消息正文与发送者/群标识**；不含 segments/媒体引用、提示词、模型输出、Token 或任何凭证。请按本机敏感数据处理导出文件。
- 以 `= + - @`、制表符或回车开头的文本加单引号前缀，降低表格软件公式注入风险。
- 最多导出 50,000 行，超过返回 413 `VALIDATION_ERROR`；`since` 晚于 `until` 返回 400。
- 响应头包含 `Content-Disposition: attachment`、`Cache-Control: no-store` 与 `X-Content-Type-Options: nosniff`。
- 每次导出写审计 `message.export`，只记录行数、筛选条件与 `has_search`，**不记录搜索词、正文或发送者标识**。

`GET /api/outbox` 参数：`page`、`page_size`、`status`、`group_id`。

发送队列状态包括 `pending`、`pending_approval`、`sending`、`sent`、`rejected`、`failed`、`unknown`、`cancelled`。**`unknown` 表示发送结果无法确认，系统不会自动重发**；`cancelled` 由删除群等策略原因产生，同样不会发送。

- `manual_confirm` 模式下生成的回复以 `pending_approval` 入队，来源消息状态为 `awaiting_approval`，并发出 `reply.awaiting_approval` 事件。
- `approve` 只接受 `pending_approval`：先做全局暂停、账号/群启用与暂停、安静时段、成员静音、群级与每成员限频、有效长度与敏感内容检查；失败返回 409 且记录保持待审。成功用条件 UPDATE 原子切换为 `pending` 并立即尝试发送一次；重复或并发批准只有一个成功，其余返回 409。
- 批准时可编辑内容，但仍会重新清洗、检查敏感信息与长度；审计 `outbox.approve` 只记录长度与 SHA-256 摘要、操作者与结果，不写正文。
- `reject` 只接受 `pending_approval`，切换为 `rejected` 并写审计 `outbox.reject`。
- outbox 记录返回 `origin_member_platform_user_id` 与 `reply_kind`（`reply`/`command`）。发送前会重新检查群级长度与敏感输出；命中敏感内容时转为终态失败，不再排期重试。

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

- `scope_type`：`global` / `account` / `group` / `provider` / `feature`。`account` / `group` / `provider` 的 `scope_id` 必须引用真实存在的实体；`feature` 的 `scope_id` 只接受固定功能键：`chat`、`persona_growth`、`memory_extraction`、`media.image.describe`、`media.ocr.extract`、`media.audio.transcribe`、`media.text.embed`、`media.inspect`、`media.text.rerank`、`media.video.describe`。旧的 `reply` 在预算层归一化为 `chat`，不改写模型调用内部的 `purpose`。
- 预算检查可同时传 `account_id`、`group_id`、`provider_id` 与 `feature`；只有与调用实际匹配的策略才会阻断。媒体任务同样在调用前检查预算，耗尽时任务终态失败且不自动重排。
- `window`：`hour` / `day` / `week` / `month` / `all`。
- `metric`：`requests` / `tokens` / `cost`。
- `warn_threshold`：0–1，按上限比例生成 `warning` 告警；0 表示关闭接近上限告警。达到或超过上限生成 `exceeded` 告警。
- 超限时一律阻断模型调用；告警不是「仅告警」策略，不会改变这一强制行为。`action` 字段会保存，但不会改变阻断。预算按已记录的本地用量执行，单次调用可能使累计用量略超上限。
- 预算快照包含 `used`、`remaining`、`usage_ratio`、`state`（`ok` / `warning` / `exceeded` / `disabled`）与 `period_start`。`metric=cost` 时还包含 `cost_status` 与 `unpriced_success_requests`。
- 保存策略后会立即按当前真实用量评估一次；模型调用记录用量后也会评估。新告警写入 `budget_alerts`，同一 `policy_id + period_key + level` 只保留一条；每个新事件写审计 `budget.alert.warning` / `budget.alert.exceeded`，并通过 SSE 发布 `budget.alert`。只读的 `/api/budgets/check` 不会生成告警。

`GET /api/budgets/alerts` 返回 `items`、`total`、`page`、`page_size` 与 `note`。事件包含策略 ID、作用域名称、窗口、指标、级别、周期键、已用/上限、比例、中文说明与创建时间。`level` 只接受 `warning` / `exceeded`；`scope_type` 接受 `global` / `account` / `group` / `provider` / `feature`。账号与功能作用域的名称由服务端解析为账号名/功能中文名。

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
| GET | `/api/plugins/{plugin_id}/health` | 本地登记健康状态；第三方插件为 `runtime_planned`，不执行外部检查 |
| POST | `/api/plugins/{plugin_id}/enable` | 启用/禁用（仅内置） |
| POST | `/api/plugins/{plugin_id}/approve` | 批准/撤销权限 |
| GET | `/api/extensions/capabilities` | 五类扩展契约、真实执行状态与安全保证 |

工具测试请求：`{ "arguments": { "expression": "1+2*3" } }`。工具记录包含 `execution: "in_process"`、`registration: "fixed_at_startup"` 与 `authorization`，固定注册 `calculator` 与 `current_datetime`；不存在任意 Shell、文件读写或任意网络请求工具，也不接受第三方工具注册。

插件记录包含可选的 `healthcheck` 声明：`type`（`builtin` / `http`）、站内相对 `path`（空或以 `/` 开头，拒绝协议、凭据、查询、片段与目录穿越）、`interval_seconds`（30–86400）与 `timeout_seconds`（1–30）。该字段**只是清单声明**，`healthcheck_note` 会明确说明本版本不执行第三方健康检查或任意网络请求。`POST .../approve` 只改变本地高风险权限登记状态；第三方插件启用仍返回 `OPERATION_PLANNED`，不会加载或执行代码。

插件记录新增 `execution` 与 `runtime_requirements`：内置插件为 `builtin_in_process` 且要求列表为空；第三方插件为 `not_executed`，并列出未来开放执行前必须同时满足的 `sandbox`、`permission_manifest`、`user_confirmation`、`signature_verification`、`timeout`、`resource_limits`、`audit`、`disable` 八项要求。当前任何一项都未实现，因此不提供执行入口。

## 备份与恢复

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/backups` | 备份记录 |
| POST | `/api/backups` | 创建备份，可带 `note` |
| GET | `/api/backups/{backup_id}` | 记录详情 |
| POST | `/api/backups/{backup_id}/verify` | SHA-256 与 SQLite 完整性校验 |
| POST | `/api/backups/{backup_id}/restore/preview` | 恢复预览 |
| POST | `/api/backups/{backup_id}/restore` | 恢复（需全局暂停 + `RESTORE`） |
| DELETE | `/api/backups/{backup_id}?confirm=DELETE` | 删除备份记录与文件，写 `backup.delete` 审计 |
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
  "schema": {
    "status": "compatible",
    "restore_allowed": true,
    "backup_revision": "a1f5c2d7e901",
    "current_revision": "a1f5c2d7e901",
    "head_revision": "a1f5c2d7e901",
    "message": "备份 Schema 与当前程序一致。"
  },
  "app_version": { "backup": "0.2.1", "current": "0.2.1" },
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
- Schema 门禁：只有备份与当前代码的 Alembic head 都已知且备份版本不等于 head 时才判定 `incompatible`，恢复返回 409 `BACKUP_SCHEMA_INCOMPATIBLE`，此时**不会创建安全备份，也不会改动数据库**。备份版本等于 head 时即使数据库当前版本不同也允许（恢复后即为程序所需 Schema）。备份缺少 `alembic_version` 或无法读取 head 时为 `unknown`，允许恢复但带显著警告，仅适合开发/测试库。
- 成功恢复会自动创建安全备份、断开全部连接器、保持全局暂停，并在审计 `backup.restore` 中记录 `schema_status`、`backup_schema`、`current_schema`、`head_schema`。
- 备份不含媒体、日志与 `CREDENTIAL_ENCRYPTION_KEY`；换用不同加密密钥的实例恢复后，旧凭证无法解密。删除备份需要 `?confirm=DELETE` 并写 `backup.delete` 审计。

## 运维建议

1. 对外仅暴露反向代理 HTTPS，不直接暴露管理端口。
2. 定期创建并校验备份，同时在异地保存一份（备份本身仍含加密后的凭证字段）。
3. 恢复前先在控制台全局暂停；恢复后逐群确认配置再恢复回复。
4. 更换 `CREDENTIAL_ENCRYPTION_KEY` 前先记录并迁移已保存的 Token/API Key。

# 软件设计说明

本文档描述 AI 群友 P0 MVP 的架构、关键流程、数据模型与扩展点。产品范围与验收见 [ROADMAP.md](ROADMAP.md)，接口见 [API.md](API.md)，安全边界见 [SECURITY.md](SECURITY.md)。

## 1. 设计目标

1. **本地优先**：默认单机运行，数据保存在本地 SQLite；未经配置不向外部发送数据。
2. **不接触 QQ 凭证**：只连接用户自建的 OneBot 11 连接器。
3. **保守默认**：空白白名单、仅 @ 回复、群工具关闭、跨群学习关闭、全局暂停最高优先。
4. **能力诚实**：界面区分真实可用、已配置、Mock、未配置与规划中。
5. **可治理人格**：空白自成长必须经过证据、锁定字段、版本与回滚。
6. **可恢复**：发送队列幂等；未知发送状态不重发；备份可校验、恢复需暂停与二次确认。
7. **模块化单体**：P0 避免过度拆分，服务边界清晰，便于后续拆分或扩展。

## 2. 总体架构

```text
┌────────────────────────── Vue 控制台（Element Plus） ──────────────────────────┐
│ 仪表盘 / QQ 接入 / 模型 / 能力 / 人格 / 群 / 消息 / 模拟 / 扩展 / 设置         │
└───────────────▲───────────────────────────────▲───────────────────────────────┘
                │ REST /api                      │ SSE /api/events/stream
┌───────────────┴───────────────────────────────┴───────────────────────────────┐
│ FastAPI：路由、依赖注入、统一响应、错误处理、管理边界、静态前端托管            │
│ AppRuntime：装配数据库、服务、适配器管理器、流水线、事件总线                    │
└───────┬───────────────────────┬────────────────────────┬──────────────────────┘
        │                       │                        │
┌───────▼────────┐   ┌──────────▼──────────┐   ┌─────────▼──────────────┐
│ 服务层          │   │ 流水线               │   │ 适配器                  │
│ 账号/群/Provider│   │ 策略/去重/上下文     │   │ QQ: Mock / OneBot 11    │
│ 人格/备份/审计  │   │ 提示词/LLM/工具/outbox│   │ LLM: Mock / OpenAI兼容  │
│ 查询/设置/演示  │   │ 人格成长/事件总线     │   │ 媒体: Mock / LocalStore │
└───────┬────────┘   └──────────┬──────────┘   └─────────┬──────────────┘
        │                       │                        │
┌───────▼───────────────────────▼────────────────────────▼──────────────┐
│ SQLAlchemy 2 async + aiosqlite（默认 data/ai_group_friend.db）          │
│ Alembic 迁移；Fernet 凭证加密；本地日志、媒体、备份目录                  │
└───────────────────────────────────────────────────────────────────────┘
```

前端开发态由 Vite 代理 `/api` 到 `127.0.0.1:8000`；生产构建后由 FastAPI 托管 `frontend/dist`，SPA 回退到 `index.html`。

## 3. 运行时装配

`backend/app/runtime.py` 在 FastAPI lifespan 中创建：

- `Database`：异步引擎与 session 工厂。
- 核心服务：账号、群、Provider、人格、备份、审计、查询、设置、演示环境。
- `AdapterManager`：实例 ID → 运行中适配器；负责连接、断开、状态回写。
- `MessagePipeline`：策略、上下文、提示词、LLM 网关、工具、outbox、媒体任务。
- `EventBus`：进程内有界事件队列与最近事件缓存，供 SSE 使用。
- `CredentialCipher`：Fernet 封装；缺少/错误密钥时显式失败。

启动顺序：创建数据目录 → 初始化日志 → 自动迁移 → 装配运行时 → 恢复已启用且 `auto_connect` 的连接器。停止时断开适配器并释放数据库。

> 数据目录必须在日志初始化之前创建；`scripts/smoke_test.py` 与集成测试覆盖了全新安装的启动路径。

## 4. 消息模型与适配器

### CanonicalMessage

平台无关的统一消息模型：

- `conversation_type`：`group` / `private`
- `segments`：`text`、`mention`、`reply`、`image`、`audio`、`video`、`file`、`sticker`、`unknown`
- `mentions`、`reply_to_message_id`、`sender_id/name`
- `message_id`、`event_id`、时间戳、来源适配器
- 媒体段只保存 `media_ref` 与安全元数据（不保存易过期 URL 与本地路径）

### QQAdapter

```python
class BaseQQAdapter:
    def capabilities() -> AdapterCapabilities
    async def connect() / disconnect()
    async def send_text(conversation_id, text, *, conversation_type, reply_to_message_id)
    async def next_event() -> CanonicalMessage
    def queue_event(message)
    async def health_check()
    async def get_group_list() / get_login_info()
```

能力由适配器声明，业务层不假设平台能力。当前：

- **Mock**：立即在线；可注入文本、@、引用、图片/语音演示段；记录已发送消息；永远不会访问网络。
- **OneBot 11**：正向 WS 接收，HTTP action 优先（WS action 回退）；Bearer Token；`lifecycle`/`heartbeat` 更新状态；指数退避重连；宽松解析未知段；默认只允许回环/私网地址。
- **官方 QQ 机器人**：仅接口占位，状态 `planned`。

事件队列有界；满时丢弃最旧事件并记录告警。适配器状态只存在当前进程，重启后需重连。

## 5. 消息流水线

`MessagePipeline.handle()` 的顺序：

1. **持久化与去重**：入站消息先写库；唯一约束冲突视为重复事件，直接拦截。
2. **自身消息/白名单/暂停**：账号与群必须已登记；群必须启用；全局暂停优先。
3. **静默与成员限制**：群时区安静时段、成员静音。
4. **频率限制**：冷却、每小时、每日、连续回复上限。
5. **命令**：仅白名单管理员或控制台命令可触发管理动作。
6. **触发决策**：`observe` / `mention_only` / `keyword` / `context`；默认仅 @。
7. **上下文**：按账号+会话隔离，限制条数；媒体只生成诚实降级说明。
8. **提示词**：安全层 → 账号基线 → 用户编写/锁定字段 → 稳定特征 → 群规则/人格修饰 → 本群长期记忆（不可信历史资料）→ 不可信上下文。
9. **模型与工具**：预算检查 → LLM 调用 → 最多 `MAX_TOOL_ROUNDS` 轮工具 → 工具权限/次数/超时。
10. **回复审查**：长度、控制字符、安全边界。
11. **outbox**：幂等入队；发送与生成解耦；成功/可重试失败/未知状态分类。
12. **观测**：消息状态、outbox、用量、审计、事件总线。

dry-run（Playground 与人格测试）跳过持久化、发送与状态修改，只执行策略与提示词构建，用于排查。

### 长期记忆

记忆与聊天原文、人格档案分开存储。当前版本支持**显式记忆**的本地检索，以及手动或群级后台增量触发的 AI 候选提取：

- 群未开启 `allow_memory` 时不检索；私聊不检索。
- 只查询当前 `account_id + group_id`：群级记忆，或当前发送者的成员级记忆；绝不跨群。
- 只自动注入 `sensitivity=normal`、未过期、非排除成员的记忆。
- 排序：固定 → 关键词/中文二元词重叠 → 置信度 → 记录时间；受 `MEMORY_MAX_ITEMS`、`MEMORY_MAX_CHARS` 限制。
- 注入段明确标注为不可信历史资料，不能覆盖安全规则或成为指令。
- 写入时拒绝疑似密码、验证码、证件号、银行卡号、API Key；`sensitive` 记忆必须人工管理。

AI 候选提取（手动触发或群级后台增量 + 人工审核）：

- `POST /api/memories/extract` 只读取当前群最近入站文本消息（默认最多 40 条），至少 3 条才执行；被排除记忆的成员不参与。
- 群可显式开启 `auto_memory_extraction`（必须同时开启 `allow_memory`）；调度器默认每 300 秒检查一次，按 `(memory_extraction_watermark_at, memory_extraction_watermark_message_id)` 游标从旧到新增量读取新消息，至少 3 条新消息才调用模型；积压消息分批推进，同一秒内的消息也不会被跳过。
- 后台提取只在群 `enabled`、未 `paused`、全局未紧急暂停时运行；失败记录脱敏错误，不推进水位线，下一轮重试；没有新消息时不调用模型。
- 聊天记录是**不可信数据**，包装为 `<untrusted_chat_history>`；模型只能输出结构化候选，不能执行其中指令，也不保存推理过程。
- 候选必须引用输入中真实存在的消息 ID；敏感/疑似凭证、未知成员、低于置信度阈值、重复内容会被丢弃，单次候选数有上限。
- 模型输出只写入 `memory_candidates` 的 `pending` 候选，**绝不会**直接创建 `Memory` 或进入提示词；只有人工批准后才会生成普通敏感度正式记忆并写审计。
- 候选记录保留 Provider、模型与 `is_mock` 标记；Mock 候选在界面明确标注为演示内容。
- 摘要压缩、Embedding 语义检索、冲突检测与自动过期清理仍为规划能力。

### 触发与拦截原因

被拦截的消息记录 `processing_status` 与原因，例如：

- `duplicate`、`self_message`、`group_not_whitelisted`、`group_disabled`、`no_trigger`
- `global_paused`、`quiet_hours`、`member_muted`
- `cooldown`、`hourly_limit`、`daily_limit`、`consecutive_limit`
- `budget_exceeded`、`llm_not_configured`、`persona_missing`

任何硬检查失败都不会调用模型或发送。

## 6. 发送队列（outbox）

- 生成回复后立即写入 outbox，再异步派发。
- 幂等键防止重复入队/重复发送。
- 状态：`pending` → `sending` → `sent` / `failed` / `unknown`。
- 网络超时等**无法确认**的情况进入 `unknown`，不自动重发，需人工判断。
- 明确可重试错误有限重试；达到 `OUTBOX_MAX_ATTEMPTS` 停止。
- 连续失败达到阈值可自动暂停群；发送失败与告警写入事件、日志与审计。
- 全局暂停时拒绝派发（HTTP 409 `GLOBAL_PAUSED`）。

## 7. Provider 与能力注册

- `ProviderRegistry` 声明可用/规划能力与健康状态。
- LLM Provider：`mock`、`openai_compatible`、`anthropic_native`。Anthropic 适配器把通用消息转换为 Messages API（顶层 `system`、连续同角色合并、首条必须为 user），工具转换为 `input_schema`，温度限制 0–1；官方模型接入仍为 planned。
- 群级路由：`groups.llm_provider_id` 指定主模型，`groups.llm_fallback_provider_id` 指定可选备用模型。路由解析集中在 `LLMGateway`，回复、记忆候选提取与人格成长都按 `group_id` 获取同一绑定；未绑定或显式调用时回落到原有默认 Provider 逻辑。
- 受控回退：只有主 Provider 的调用错误（超时、网络、认证、限流、额度、模型不存在、无效响应、Provider 不健康）才尝试备用模型一次。预算超限、全局暂停、Provider 禁用/缺失、配置或凭证错误直接失败，不允许借回退绕过控制。备用调用失败时错误详情同时保留主/备用错误码。
- 回退结果仍走同一条回复审查与 outbox 入队路径，因此不会因此重复发送；用量按 Provider 分别记录，`reply.generated` 事件与 dry-run 结果携带 `fallback_used`、`primary_provider_id`、`primary_error_code`、`route_source`。
- 删除被群绑定的 Provider 会被 409 拒绝，避免产生静默的悬空绑定。
- 媒体 Provider：Mock 与接口骨架；真实 Vision/OCR/ASR/TTS/Embedding 未配置。
- 能力状态：`available` / `configured` / `disabled` / `unsupported_by_adapter` / `mock_only` / `unconfigured` / `planned`。
- 前端能力页对 `mock_only`、`unconfigured`、`planned` 使用非成功色并给出解释。
- 测试连接按错误类型分类，不静默回退到 Mock 生成虚假回复。

## 8. 人格子系统

### 模式

| 模式 | 起点 | 约束 |
| --- | --- | --- |
| `authored` | 用户编写自我描述/字段 | 成长可选；锁定字段不可被覆盖 |
| `template` | 内置模板 | 可继续编辑；有初始描述 |
| `emergent` | 完全空白 | 不允许预置自我描述/设定字段 |

### 成长流程

```text
聊天记录 → 手动/调度分析 → 模型结构化提案
        → 治理校验（Schema/证据/会话数/置信度/范围/锁定字段）
        → auto 生成版本 | review 待审核 | paused 不处理
        → 特征 candidate → stable/rejected
        → 版本快照 + 变更事件（可回滚）
```

- 默认阈值：≥3 条一致证据、≥2 个不同会话、置信度 ≥0.6（可配置）。
- 单条消息不能改变人格。
- 跨群学习默认关闭；默认范围 `admin_only`。
- 不保存思维链；只保存结构化提案与证据摘要。
- 锁定字段、系统安全规则、群规、工具权限不可被成长覆盖。
- 删除证据消息会清理相关引用/派生特征。

## 9. 工具与插件

### 工具

```python
class Tool:
    name, description, risk_level, input_schema
    async def run(arguments, context) -> ToolResult
```

- 权限引擎按来源、风险等级、群开关、次数与超时授权。
- 内置：计算器、日期时间。
- 无任意 Shell/PowerShell/Python、文件读写、任意 HTTP 请求。
- 管理端测试仅执行低风险工具并写审计。

### 插件

- 校验 Manifest（ID、版本、权限、兼容性），同步到注册表，默认禁用。
- 只登记与健康检查，**不加载、不执行第三方代码**；权限批准单独记录。
- 加载失败被隔离，不影响核心流水线。

## 10. 预算与用量

- 作用域：`global` / `group` / `provider`；窗口：小时/日/周/月/全部；指标：请求、Token、成本。
- 模型调用前检查硬上限；超限返回 `BUDGET_EXCEEDED`，不调用 Provider。预算按已记录的本地用量执行，单次调用可能让累计用量略超上限。
- `usage_events` 是调用前的执行账本；`llm_usage` 是每次调用的明细账本（Provider、群、输入/输出 Token、耗时、估算成本、状态、错误码）。重试与工具轮次计入。
- `usage_summary` 按 Provider 与群聚合 `llm_usage`，包含零调用行与已删除/未知 ID 占位行，供仪表盘与扩展页展示真实用量。
- `usage_trends` 在应用层按 `DEFAULT_TIMEZONE`（默认 `Asia/Shanghai`）把真实 `llm_usage` 归入当前结束的小时/自然日桶；空桶补 0，未知成本保持 `null`。小时最多 744 桶，自然日最多 365 桶，可筛选群/Provider。不依赖 SQLite 的时区函数，也不调用外部服务。
- 费用只按用户在 Provider 中填写的 `input_price_per_1k` / `output_price_per_1k` 与本地 Token 估算，**不是服务商账单**。Mock 的外部费用视为 0；未配置单价或 Provider 未返回完整 Token 用量的成功调用记为不可计价，统计返回 `partial` / `unconfigured`，`cost` 为 `null`，绝不伪造为 0。
- 费用预算仅在当前 Provider 已配置单价（或为 Mock）时允许调用；否则以 `cost_unavailable` 阻断，避免无法计费的调用绕过上限。费用预算同样不触发模型回退。
- 已知限制：费用上限按已记录成本执行。若 Provider 配置了单价但响应缺少 Token 用量，该次调用会被标记为不可计价，也无法计入费用额度；应在 UI 中暴露这一状态并建议更换会返回 `usage` 的 Provider。
- 预算告警：`record()` 写入用量事件后评估适用于当前群/Provider 的启用策略；保存策略时也按当前真实用量评估一次。达到 `warn_threshold` 生成 `warning`，达到/超过上限生成 `exceeded`。事件写入 `budget_alerts`，唯一键 `(policy_id, period_key, level)` 去重；`period_key` 按本地小时/自然日/ISO 周/月/`all` 对齐，避免滚动小时窗口每次变化都重复告警。新事件写审计并发布 `budget.alert` SSE。告警评估失败只记日志，不回滚已发生的调用或用量记录；只读的预算检查不产生副作用。
- 当前 `action` 字段会保存，但超限行为一律阻断；告警不是“仅告警”策略，不改变阻断。
- CSV 导出直接查询 `llm_usage` 并输出固定列；不拼接消息正文或提示词。使用 UTF-8 BOM、标准 CSV、公式注入前缀防护与 `no-store` / `nosniff` 响应头；每次导出写 `usage.export` 审计。

## 11. 数据模型（主要表）

| 表 | 用途 |
| --- | --- |
| `accounts` / `adapter_instances` | QQ 账号与连接器实例；Token 加密 |
| `groups` / `members` | 白名单群配置、成员必要字段、静默 |
| `messages` / `outbox_messages` | 入站/出站消息与发送队列 |
| `personas` / `persona_versions` / `persona_traits` / `persona_evolution_events` | 人格、版本、特征、成长事件 |
| `llm_providers` / `llm_usage` | 模型 Provider 与用量；群表记录主/备用 Provider 绑定 |
| `tools` / `tool_runs` | 工具注册与执行记录 |
| `media_assets` / `media_processing_jobs` / `media_transcripts` / `provider_registry` | 媒体与能力注册 |
| `memories` | 长期记忆：作用域、来源、置信度、敏感度、过期与固定状态 |
| `memory_candidates` | AI 提取候选：证据消息、置信度、Provider/模型、审核状态与生成的记忆引用 |
| `plugin_registry` / `budget_policies` / `usage_events` | 插件、预算、调用前用量账本 |
| `budget_alerts` | 预算阈值告警事件：作用域、周期、级别、已用/上限与去重唯一键 |
| `audit_logs` / `system_settings` / `retention_policies` / `backup_records` | 治理与运维 |
| `automation_rules` / `conversation_eval_cases` / `conversation_eval_runs` | P1 骨架 |

所有表含创建/更新时间；时间以 UTC 存储，展示/安静时段按群时区换算。数据库结构变更必须附 Alembic 迁移。

## 12. 备份与恢复

- SQLite `backup()` API 生成一致性快照；计算 SHA-256 与 `PRAGMA integrity_check`；记录清单、版本、表计数。
- 恢复前置条件：全局暂停 + 备份校验通过 + 输入 `RESTORE`。
- 恢复动作：创建安全备份 → 断开全部连接器 → dispose 数据库 → 覆盖文件 → 删除 WAL/SHM → 校验 → 重建备份记录 → 审计 → 保持暂停。
- 备份范围：数据库 only；排除媒体、日志、加密密钥。
- 恢复后的凭证仍需原 `CREDENTIAL_ENCRYPTION_KEY` 才能解密。

## 13. 前端设计

- Vue 3 `<script setup>` + TypeScript + Element Plus；Pinia 管理应用状态与事件；Vue Router 十一个页面（含长期记忆管理）。
- `src/api/client.ts` 统一封装 `{data,error,request_id}`、超时、错误提示与 `X-Request-ID`。
- 管理 Token 仅存 `sessionStorage`；API 客户端按需附带。
- SSE 事件流用于仪表盘实时事件；断线由浏览器自动重连。
- 所有页面具备加载、空、错误状态；破坏性操作使用二次确认；密钥只显示掩码。
- 能力状态使用统一 `StateTag`/`stateLabel`，Mock/规划中采用警告或信息色，绝不使用成功色。
- 当前 Element Plus 全量引入，构建有 chunk 体积警告，不影响功能；后续可改为按需引入。

## 14. 错误处理与可观测性

- 统一错误码映射到 HTTP 状态与中文消息；`details` 脱敏。
- 未处理异常返回通用 500，不泄露堆栈；完整异常写本地日志。
- 请求上下文包含 `request_id`，响应头回传。
- 结构化日志包含 `event`、错误码等字段；敏感值由脱敏过滤器处理。
- 审计表记录管理动作、Actor、目标、时间、IP 与请求 ID。
- SSE 事件总线有界，慢客户端不阻塞流水线；保留最近事件供页面初始化。

## 15. 测试策略

| 层级 | 覆盖 |
| --- | --- |
| 单元 | 策略、分段解析、上下文、提示词、工具权限、预算、媒体任务、人格治理 |
| 集成 | Mock 全链路、@/非 @、白名单、去重、暂停、限速、dry-run、OneBot 假服务器、记忆候选提取与审核、备份恢复原子替换与恢复后强制暂停 |
| API | ASGI 生命周期、迁移、统一响应、错误码、密钥掩码、备份预览、SPA 回退、全新目录启动、候选批准/拒绝 |
| 端到端 | `scripts/smoke_test.py` 启动真实 uvicorn + 临时数据库，验证 Mock 闭环、记忆候选审核、暂停、密钥落盘、备份真实恢复、重连 |
| 前端 | vue-tsc 类型检查、Vitest 格式/状态逻辑、Vite 生产构建 |

测试使用临时文件 SQLite，不依赖本机数据与前端构建产物；不接触真实 QQ 或真实模型。

## 16. 扩展点

- 新连接器：实现 `BaseQQAdapter` 并在账号服务中注册连接方式与能力声明。
- 新模型：实现 `LLMProvider`，通过 ProviderRegistry 暴露与测试。
- 新工具：实现 `Tool` + Schema + 风险等级；默认禁用，需显式授权。
- 新媒体能力：实现 Provider 契约与任务处理器，同时在能力中心诚实标注状态。
- 新成长策略：在治理层增加策略，但不得绕过证据、锁定字段、版本与审计。
- 新前端页面：沿用 `api/client.ts`、`PageHeader`、`StateTag` 与统一状态处理。

## 17. 已知技术债

- 数据保留策略未自动执行；需要可恢复的后台调度。
- 真实媒体下载/转存与真实多模态 Provider 未实现；长期记忆支持手动录入、手动或群级后台增量候选提取与关键词/二元词检索，但没有摘要压缩或向量语义检索。后台提取只生成待审核候选，不自动批准。
- 模型路由目前仅支持群级主/备用绑定与单次调用回退，不支持按功能拆分模型或基于成本/延迟/健康度的自动路由。
- Element Plus 全量打包导致构建产物偏大。
- OneBot 真实 NapCat 版本差异仍需用户联调。
- 当前仅单进程内存适配器状态与事件缓存；多进程部署需要外部化。
- SQLite 适合单机规模；并发与大数据量需重新评估。

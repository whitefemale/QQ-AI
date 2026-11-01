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
┌──────────────────────── Electron 桌面壳（可选，本机一键启动） ─────────────────┐
│ main.js：窗口/托盘/IPC/后端进程生命周期    preload.js：白名单桥接               │
│ shell/：启动向导与控制页                   lib/：设置、端口、健康检查、向导       │
└───────────────┬───────────────────────────────────────────────────────────────┘
                │ spawn（backend/.venv/python -m uvicorn），同源加载
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
│ 连接器管理器    │   │                      │   │                         │
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
- `ConnectorManager`：受管连接器检测、安装任务、进程所有权、加密配置快照/回滚、版本切换、诊断复用与审计；只扫描 `CONNECTORS_DIR`，不接受任意路径。
- `MessagePipeline`：策略、上下文、提示词、LLM 网关、工具、outbox、媒体任务。
- `EventBus`：进程内有界事件队列与最近事件缓存，供 SSE 使用。
- `CredentialCipher`：Fernet 封装；缺少/错误密钥时显式失败。
- `OnboardingService` / `DiagnosticsService`：只读聚合。前者把配置、内存适配器实时状态与既有审计证据推导成八步接入状态；后者按显式 allowlist 生成诊断摘要与可复制文本。两者共用 `system_evidence`，GET 不写审计、不触发网络/模型/连接器动作。

启动顺序：创建数据目录 → 初始化日志 → 自动迁移 → 装配运行时 → `ConnectorManager.start()`（把未完成任务标为中断、只读扫描，不启动任何第三方进程）→ 恢复已启用且 `auto_connect` 的连接器。停止时取消运行中安装任务、丢弃进程所有权，但**不自动杀死 NapCat**，避免静默结束用户的 QQ 会话。

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

适配器通过 `QQAdapterFactory` 以模式注册；`AdapterManager` 只向工厂请求构建，账号页与能力页的连接方式列表也从工厂派生，因此新增适配器不需要修改 `build_adapter` 分支或消息流水线。能力由适配器声明，业务层不假设平台能力。当前：

- **Mock**：立即在线；可注入文本、@、引用、图片/语音演示段；记录已发送消息；永远不会访问网络。
- **OneBot 11**：正向 WS 接收，HTTP action 优先（WS action 回退）；Bearer Token；
  `lifecycle`/`heartbeat` 只更新时间并触发节流身份重试；指数退避重连；宽松解析未知段；
  默认只允许回环/私网地址；`https://` 会安全转换为 `wss://`。
- **官方 QQ 机器人**：仅接口占位，状态 `planned`。

事件队列有界；满时丢弃最旧事件并记录告警。适配器状态只存在当前进程，重启后需重连；
启动时会把数据库中的残留运行时状态重置为 `disconnected`。

### 连接状态机与身份门控

```text
unconfigured → disconnected → connecting → connected_unverified → online
                                      ↘ reconnecting ↗
                                      ↘ error
```

- WS 握手成功只进入 `connected_unverified`。此时允许执行身份查询等无害动作，但
  `send_text` 会抛出可重试的 `SEND_FAILED`，outbox 解析不到在线适配器，不派发消息。
- `_verify_identity()` 以 8 秒上限调用 `get_login_info`；成功且返回 `user_id` 才设置
  `self_platform_user_id` 并进入 `online`。鉴权错误进入 `error`；其他错误保持
  `connected_unverified` 并记录 `ADAPTER_IDENTITY_UNVERIFIED`。
- 身份任务与重连解耦：重连后创建身份任务继续 `recv`，不在接收循环内 `await` 动作，
  避免同一 WS 响应通道死锁。每条连接递增 epoch，过期的身份结果会被丢弃。
- 心跳、lifecycle、发送成功都不会提升状态；只有身份验证成功可以进入 `online`。
- `online` 属性同时要求状态、已验证标记与 WS 存在。
- `AdapterManager.test_connection()` 通过 `connection_diagnostics` 返回结构化报告：
  9 项检查、`state`、`verified_scope` / `unverified_scope`、`next_step` 与脱敏登录信息。
  群列表失败只警告；真实入站仅在测试窗口内实际收到时标记；真实出站永远未验证。
  配置/网络/鉴权失败也返回结构化失败报告，不让前端只看到 500。
- UI 展示 `connected_unverified` 为「已连接 · 身份未验证」，并明确诊断通过不等于
  真实 QQ 收发通过。

### 受管连接器状态机与进程边界

`backend/app/connectors/` 用 `ConnectorProfile` 抽象隔离具体连接器；当前只实现 NapCat
profile，业务层不直接依赖 NapCat 细节。

```text
not_installed → installing → installer_ready → installer_running
              → installed_not_started → starting → waiting_login*
              → logged_in_not_connected* → connected_traffic_unverified → traffic_verified
```

其他状态：`interrupted`、`running_unmanaged`、`auth_failed`、`incompatible`、
`external_readonly`、`unknown_error`。带 `*` 的「登录」判断是推断，必须有端口/身份证据；
UI 会明确标注。`traffic_verified` 仅由身份确认后的非 Mock 持久化入站消息 + 成功 outbox
记录推导，安装成功、进程存活、WS 连接和诊断都不参与。

- **状态引擎**是纯函数，输入安装清单、适配器状态、本会话进程、端口探测、身份确认时间与
  收发证据，输出状态、`evidence[]`、观测时间、严重级别与下一步动作。
- **安装任务**以固定参数调用 `scripts/install_napcat.py`，解析 NDJSON 事件，单任务互斥；
  取消只终止本任务拥有的子进程。成功仅表示包已解压并通过 manifest 校验。
- **安装器/进程**只能从受管目录启动固定文件，`shell=False`、无用户参数、可见控制台；
  安装器启动前重新核对 SHA-256。停止只结束本会话跟踪的进程树，不按端口或名称杀进程。
- **配置写入**只针对受管且版本兼容的安装，写入前要求进程停止并二次检查端口；先加密
  快照（Fernet），再同目录临时文件 + `fsync` + `os.replace`，回读校验后更新实例。任一步
  失败恢复文件与实例 Token；恢复失败返回 `CONNECTOR_ROLLBACK_FAILED`。
- **秘密隔离**：子进程环境使用允许列表，不继承加密密钥、管理 Token 或数据库 URL；API、
  日志、审计和快照列表都不返回 Token 或配置正文。
- **本机边界**：`/api/connectors/*` 独立于 `ALLOW_REMOTE_ADMIN`，要求回环客户端与回环
  Host，拒绝非本机 Origin，避免远程触发本机可执行程序或泄露路径。

## 5. 消息流水线

`MessagePipeline.handle()` 的顺序：

1. **持久化与去重**：入站消息先写库；唯一约束冲突视为重复事件，直接拦截。
2. **自身消息/白名单/暂停**：账号与群必须已登记；群必须启用；全局暂停优先。
3. **静默与成员限制**：群时区安静时段、成员静音。
4. **频率限制**：群级冷却、每小时、每日、连续回复上限，以及每成员每小时/每日 AI 回复上限。
5. **无效与回环事件**：无文本且无媒体的空消息拦截为 `invalid_message`；同一会话同一发送者 60 秒内至少 4 条完全相同的非空文本拦截为 `repeat_loop`（进程内启发式，重启清零）。
6. **命令**：仅白名单管理员或控制台命令可触发管理动作；命令回复同样经过输出清洗与敏感检查。
7. **触发决策**：`observe`（新群默认）/ `mention_only` / `manual_confirm` / `always` / `keyword`；`manual_confirm` 生成后只进入待审核队列。`context` 与 `scheduled` 仍为规划中，提交会被拒绝。
8. **上下文**：按账号+群/私聊隔离，条数使用群级或全局有效值；图片/语音/文件片段只登记 `media_ref` 并入队媒体任务，不阻塞事件消费；已有转写可作为不可信资料注入，未配置或处理中时只生成诚实降级说明。
9. **提示词**：安全层 → 账号基线 → 用户编写/锁定字段 → 稳定特征 → 群规则/人格修饰 → 本群长期记忆（不可信历史资料）→ 不可信上下文。
10. **模型与工具**：预算检查 → LLM 调用 → 最多 `MAX_TOOL_ROUNDS` 轮工具 → 工具权限/次数/超时。
11. **输出审查**：先检查疑似密码/验证码/证件号/银行卡/API Key（命中为 `sensitive_output`），再清洗控制字符、全员 @、代码块与长度；清洗后为空为 `empty_output`。长度使用群级或全局有效上限。
12. **outbox**：幂等入队；普通回复入 `pending`，手动确认入 `pending_approval`；发送前再次检查敏感内容、有效长度与最终发送门禁；成功/可重试失败/未知状态分类。
13. **观测**：消息状态、outbox、用量、审计、事件总线。

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
- 模型输出只写入 `memory_candidates` 的 `pending` 候选，**绝不会**直接创建 `Memory` 或进入提示词；只有人工批准后才会生成正式记忆并写审计，批准时可选择 `normal` 或 `sensitive`。
- 候选记录保留 Provider、模型与 `is_mock` 标记；Mock 候选在界面明确标注为演示内容。
- 短期上下文按 `account_id` 与群/私聊过滤，不会因相同 `conversation_id` 串上下文。
- 记忆可导出为 CSV（默认排除敏感记忆，带 BOM 与公式注入防护）、查看来源消息脱敏预览，并支持按过期或创建时间清理未固定记忆（含 dry-run）。删除后的记忆不再参与检索。
- 摘要压缩、Embedding 语义检索与冲突检测仍为规划能力；检索继续使用关键词/中文二元词。

### 触发与拦截原因

被拦截的消息记录 `processing_status` 与原因，例如：

- `duplicate`、`self_message`、`group_not_whitelisted`、`group_disabled`、`no_trigger`
- `global_paused`、`quiet_hours`、`member_muted`
- `cooldown`、`hourly_limit`、`daily_limit`、`consecutive_limit`
- `budget_exceeded`、`llm_not_configured`、`persona_missing`

任何硬检查失败都不会调用模型或发送。

## 6. 发送队列（outbox）

- 生成回复后立即写入 outbox，再异步派发。手动确认模式写入 `pending_approval`，来源消息标记 `awaiting_approval`。
- 派发前解析的适配器必须是严格 `online`（OneBot 还需身份已验证）；`connected_unverified`
  或重连中的连接不会发送。
- 幂等键防止重复入队/重复发送。
- 状态：`pending` → `sending` → `sent` / `failed` / `unknown`；手动确认另有 `pending_approval` → `rejected` 或经批准切换为 `pending`。
- `send_due` 只取 `pending`，绝不自发送待确认消息。
- 批准接口先复用全局暂停、账号/群启用与暂停、安静时段、成员静音、群级与每成员限频、有效长度与敏感内容检查，再用条件 UPDATE 从 `pending_approval` 原子切换；重复或并发批准返回 409。批准后可立即尝试发送一次，适配器不可用时保留 `pending` 由 worker 正常处理。
- 每成员限频按 `account_id + group_id + origin_member_platform_user_id + reply_kind=reply` 统计 `sent`/`unknown`，时间取 `coalesce(sent_at, created_at)`；待审核草稿与命令回复不计入。
- 发送前从群配置重新获取有效长度并复查内容；命中敏感内容会转为终态失败，不排期重试。
- 网络超时等**无法确认**的情况进入 `unknown`，不自动重发，需人工判断。
- 明确可重试错误有限重试；达到 `OUTBOX_MAX_ATTEMPTS` 停止。
- 连续失败达到阈值可自动暂停群；发送失败与告警写入事件、日志与审计。
- 全局暂停时拒绝派发（HTTP 409 `GLOBAL_PAUSED`）；发送前最终门禁会再次检查安静时段。

## 7. Provider 与能力注册

- `ProviderRegistry` 声明可用/规划能力与健康状态。
- LLM Provider：`mock`、`openai_compatible`、`anthropic_native`。Anthropic 适配器把通用消息转换为 Messages API（顶层 `system`、连续同角色合并、首条必须为 user），工具转换为 `input_schema`，温度限制 0–1；官方模型接入仍为 planned。
- 群级路由：`groups.llm_provider_id` 指定主模型，`groups.llm_fallback_provider_id` 指定可选备用模型。路由解析集中在 `LLMGateway`，回复、记忆候选提取与人格成长都按 `group_id` 获取同一绑定；未绑定或显式调用时回落到原有默认 Provider 逻辑。
- 受控回退：只有主 Provider 的调用错误（超时、网络、认证、限流、额度、模型不存在、无效响应、Provider 不健康）才尝试备用模型一次。预算超限、全局暂停、Provider 禁用/缺失、配置或凭证错误直接失败，不允许借回退绕过控制。备用调用失败时错误详情同时保留主/备用错误码。真实主 Provider 失败时禁止回退到 Mock 备用 Provider（409 `PROVIDER_FALLBACK_MOCK_FORBIDDEN`），避免用模拟回复掩盖真实故障。
- 调用保护：`ProviderLimiter` 提供单进程内每 Provider 并发上限与最小请求间隔（Mock 跳过）；HTTP 客户端不跟随重定向、每次请求显式超时。安全重试仅覆盖 429、5xx 与连接建立失败/连接超时，并遵守 `Retry-After`；读/写超时与协议中断默认标记为 ambiguous 且不重试，认证、额度、模型不存在、参数、预算与取消永不重试。重试只重发单次模型请求，不重放工具或 QQ 消息。
- 操作取消：测试请求可携带客户端生成的 `operation_id`，网关用内存注册表保存内部模型调用任务；取消端点取消该任务，原请求返回 `outcome=cancelled` 并在 `finally` 写入取消用量。取消只停止本地等待，不保证上游停止生成或计费，进程重启即清空注册表。
- 测试与模型发现：`POST /providers/{id}/test` 做极短连通性请求，`POST /providers/{id}/test-generation` 做自定义提示词生成；两者单次尝试、不重试、不回退，经过预算并写 `LLMUsage`（`feature=provider_test`）。证据只持久化白名单元数据到 `last_test_json`/`last_generation_json`，配置敏感字段变更或清空 Key 时失效。`GET /providers/{id}/models` 是只读发现，不写用量；OpenAI 兼容兼容两种列表结构，Anthropic 分页最多 500 条，404/405/501 视为不支持，手动模型 ID 始终保留。
- 回退结果仍走同一条回复审查与 outbox 入队路径，因此不会因此重复发送；用量按 Provider 分别记录，`reply.generated` 事件与 dry-run 结果携带 `fallback_used`、`primary_provider_id`、`primary_error_code`、`route_source`。
- 删除被群绑定的 Provider 会被 409 拒绝，避免产生静默的悬空绑定。
- 媒体 Provider：`MediaProcessor`（inspect）、`RerankerProvider`（text.rerank）与 `VideoProcessor`（video.describe）已定义契约并注册确定性 Mock；媒体任务状态机、应用内后台 worker、启停/健康状态持久化与用量聚合已实现。真实 Vision/OCR/ASR/TTS/Embedding/视频 Provider 未配置，inspect/rerank/video 尚未接入业务回复管线，界面如实标注 `mock_only` / `unconfigured`。
- 能力概览把「实现是否存在」与「任务队列是否真的执行」分开表达：`execution=job` 仅用于 `image.describe`、`ocr.extract`、`audio.transcribe`、`text.embed`；其余为 `contract_only`，即使启用 Mock，队列也会以 `PROVIDER_CAPABILITY_MISSING` 失败，不会调用未接通的处理器。只有全部实现都是规划占位时状态才为 `planned`；有可执行实现但全部停用时为 `unconfigured`。
- 停用止损：`ProviderService.set_media_provider_enabled()` 在停用前计算该 Provider 负责的能力，停用后对不再有任何可用 Provider 的能力调用 `MediaJobService.cancel_jobs_for_unavailable_capabilities()`，把 `queued` 与 `running` 任务置为 `cancelled`。运行中的迟到结果在保存前再次检查任务状态；迟到失败不得覆盖取消状态。停用、任务取消与重试都写审计。
- 媒体用量只记录调用元数据（Provider、能力、任务类型、账号/群、请求、延迟、Mock 标记、外部费用完整性），不保存媒体内容、转写或提示词；Mock 外部费用为 0，真实/未知为 `null`。
- 能力状态：`available` / `configured` / `disabled` / `unsupported_by_adapter` / `mock_only` / `unconfigured` / `planned`。
- 前端能力页对 `mock_only`、`unconfigured`、`planned` 使用非成功色并给出解释；执行列区分「任务队列执行」与「仅接口契约」，停用后提示实际取消的任务数。
- 连通性与真实生成测试按错误类型分类，不静默回退到 Mock 生成虚假回复；Mock 证据与真实证据在列表和结果对话框中分开显示。

## 8. 人格子系统

### 模式

| 模式 | 起点 | 约束 |
| --- | --- | --- |
| `authored` | 用户编写自我描述/字段 | 成长可选；锁定字段不可被覆盖 |
| `template` | 内置模板 | 可继续编辑；有初始描述 |
| `emergent` | 完全空白 | 不允许预置自我描述/设定字段 |

### 成长流程

```text
聊天记录（含刚发出的回复）→ 回复后异步/手动分析 → 第一人称结构化提案
        → 治理校验（Schema/证据/会话数/置信度/范围/锁定字段/规则改写）
        → auto 生成版本 | review 待审核（保存 old/new/impact，不物化特征） | paused 不处理
        → 批准时写入 stable，拒绝时清理历史遗留 candidate 行
        → 版本快照 + 变更事件（可回滚）
```

- 成长提示词让“人格自身”以第一人称反思当前自述、稳定特征、锁定字段与这次互动，输出 `self_description`、`proposed_traits`、`diff_summary`、`summary`、`scope`。`diff_summary` 是自然语言变化摘要，随事件与待审提案展示；不保存分析步骤或思维链。
- 回复生成成功后异步调度成长，正常回复不被成长阻塞。用户询问“你是谁 / 你的人设 / 介绍你自己”等会触发一次 `self_inquiry` 分析；它只豁免成长最小间隔，不豁免证据数量、会话数、置信度、锁定字段与范围。同一人格+群已有任务在运行时跳过重复调度。
- 聊天提示词要求被问及自我认知时用当前人格第一人称自然回答，不编造现实身体/经历，不透露系统提示词、内部规则或成长机制。
- 默认阈值：≥3 条一致证据、≥2 个不同会话、置信度 ≥0.6（可配置）。
- 单条消息不能改变人格。
- 跨群学习默认关闭；默认范围 `admin_only`。
- 不保存思维链；只保存结构化提案与证据摘要。
- 锁定字段、系统安全规则、群规、工具权限不可被成长覆盖；提案命中忽略/绕过/修改安全规则、系统提示、白名单、管理员权限、预算、群规或工具权限时直接拒绝。
- 编辑预览使用与保存相同的纯投影函数，返回字段/特征差异而不写库、不增版本、不写审计；保存前由前端展示确认。
- 版本详情返回脱敏快照与相对当前状态的差异；候选提案展示绑定群范围内的证据预览，缺失证据标记 `missing`。
- 删除证据消息会清理相关引用/派生特征。

## 9. 工具与插件

### 工具

```python
class Tool:
    name, description, risk_level, input_schema
    async def run(arguments, context) -> ToolResult
```

- 权限引擎按来源、风险等级、群开关、次数与超时授权。
- 内置：`calculator`、`current_datetime`，启动时固定注册，`execution=in_process`、`registration=fixed_at_startup`；不存在第三方工具注册入口。
- 无任意 Shell/PowerShell/Python、文件读写、任意 HTTP 请求。
- 管理端测试仅执行低风险工具并写审计。

### 插件

- 校验 Manifest（ID、版本、权限、兼容性、`healthcheck` 声明），同步到注册表，默认禁用。
- 只登记与查看健康状态，**不加载、不执行第三方代码**；权限批准单独记录，且批准后第三方启用仍返回 `OPERATION_PLANNED`。
- `healthcheck` 只保存声明（类型、站内相对路径、间隔、超时），本版本不执行第三方健康检查或任意网络请求；路径拒绝协议、凭据、查询、片段和目录穿越。
- `app/plugins/runtime.py` 定义未来 `PluginRuntime` 契约与八项前置要求（沙箱、权限清单、用户确认、签名校验、超时、资源限制、审计、即时停用）。当前 `get_plugin_runtime()` 返回 `UnavailablePluginRuntime`，任何执行请求都返回 `OPERATION_PLANNED`，不产生伪造结果。
- 插件公开记录包含 `execution`（内置为 `builtin_in_process`，第三方为 `not_executed`）与 `runtime_requirements`，前端同时展示执行方式与未实现要求。
- 加载失败被隔离，不影响核心流水线。

## 10. 预算与用量

- 作用域：`global` / `account` / `group` / `provider` / `feature`；窗口：小时/日/周/月/全部；指标：请求、Token、成本。功能作用域只接受固定键（`chat`、`persona_growth`、`memory_extraction`、`media.*`），`reply` 在预算层归一化为 `chat`。
- 模型调用与媒体任务调用前检查硬上限；超限返回 `BUDGET_EXCEEDED`，不调用 Provider。媒体任务预算耗尽时终态失败，不自动重排，手动重试仍受同一预算约束。预算按已记录的本地用量执行，单次调用可能让累计用量略超上限。
- `usage_events` 是调用前的执行账本；`llm_usage` 是每次调用的明细账本（Provider、账号、群、输入/输出 Token、耗时、估算成本、状态、错误码）。重试与工具轮次计入。媒体调用另记 `media_provider_usage`，只含元数据与外部费用完整性。
- `usage_summary` 按 Provider 与群聚合 `llm_usage`，包含零调用行与已删除/未知 ID 占位行，供仪表盘与扩展页展示真实用量。
- `usage_trends` 在应用层按 `DEFAULT_TIMEZONE`（默认 `Asia/Shanghai`）把真实 `llm_usage` 归入当前结束的小时/自然日桶；空桶补 0，未知成本保持 `null`。小时最多 744 桶，自然日最多 365 桶，可筛选群/Provider。不依赖 SQLite 的时区函数，也不调用外部服务。
- 费用只按用户在 Provider 中填写的 `input_price_per_1k` / `output_price_per_1k` 与本地 Token 估算，**不是服务商账单**。Mock 的外部费用视为 0；未配置单价或 Provider 未返回完整 Token 用量的成功调用记为不可计价，统计返回 `partial` / `unconfigured`，`cost` 为 `null`，绝不伪造为 0。
- 费用预算仅在当前 Provider 已配置单价（或为 Mock）时允许调用；否则以 `cost_unavailable` 阻断，避免无法计费的调用绕过上限。费用预算同样不触发模型回退。
- 已知限制：费用上限按已记录成本执行。若 Provider 配置了单价但响应缺少 Token 用量，该次调用会被标记为不可计价，也无法计入费用额度；应在 UI 中暴露这一状态并建议更换会返回 `usage` 的 Provider。
- 预算告警：`record()` 写入用量事件后评估适用于当前群/Provider 的启用策略；保存策略时也按当前真实用量评估一次。达到 `warn_threshold` 生成 `warning`，达到/超过上限生成 `exceeded`。事件写入 `budget_alerts`，唯一键 `(policy_id, period_key, level)` 去重；`period_key` 按本地小时/自然日/ISO 周/月/`all` 对齐，避免滚动小时窗口每次变化都重复告警。新事件写审计并发布 `budget.alert` SSE。告警评估失败只记日志，不回滚已发生的调用或用量记录；只读的预算检查不产生副作用。
- 当前 `action` 字段会保存，但超限行为一律阻断；告警不是“仅告警”策略，不改变阻断。
- CSV 导出直接查询 `llm_usage` 并输出固定列；不拼接消息正文或提示词。使用 UTF-8 BOM、标准 CSV、公式注入前缀防护与 `no-store` / `nosniff` 响应头；每次导出写 `usage.export` 审计。

### 数据保留与清理

- `RetentionService` 按 `log_retention_days` / `message_retention_days` / `media_retention_days` / `memory_retention_days` 分批删除过期数据，`RetentionScheduler` 按固定间隔触发；自动清理默认关闭，开关保存在 `system_settings`，可在设置页显式开启。`memory_retention_days=0` 表示不自动删除记忆，单独归一化，不能被通用默认值改写。
- 手动与自动运行共用 `asyncio.Lock`：并发手动请求返回 409，调度器重叠运行跳过。每轮有批次上限，摘要标记 `truncated`；运行结果写入 `system_settings` 与审计，下一次重复运行计数为 0。
- 消息清理先擦除人格特征/提案/事件/版本快照中的证据引用与记忆/候选的来源 ID，再删除消息；证据不足时降级 stable，无证据待审提案标记 rejected。消息清理不改写记忆正文。
- 记忆保留清理额外删除超过 `memory_retention_days` 且未固定的记忆，摘要记录 `memories_deleted`；被删除记忆不再被检索。
- 手动记忆清理端点支持 `dry_run` 与 `expired` / `older_than` 两种模式；固定记忆永远保留。
- 媒体删除前解析仍被保留消息引用的资产；按 SHA 去重时仅清理来源引用，不删除共享文件。日志只删除 `logs` 目录下 `app.log.*` 轮转文件，当前 `app.log` 始终保留。
- 清理不发送消息、不调用模型、不处理媒体任务、不出网；全局暂停不阻止清理。不覆盖 outbox、审计、备份；自动清理没有 dry-run。

## 11. 数据模型（主要表）

| 表 | 用途 |
| --- | --- |
| `accounts` / `adapter_instances` | QQ 账号与连接器实例；Token 加密；实例可关联受管安装、记录身份确认时间与 QQ 号 |
| `connector_installations` / `connector_jobs` / `connector_config_snapshots` | 受管连接器安装、安装/升级任务与加密配置快照；不含进程 PID |
| `groups` / `members` | 白名单群配置（含回复模式、群级长度与限频）、成员必要字段、静默 |
| `messages` / `outbox_messages` | 入站/出站消息与发送队列（含来源成员、`reply_kind`、待确认状态） |
| `personas` / `persona_versions` / `persona_traits` / `persona_evolution_events` | 人格、版本、特征、成长事件 |
| `llm_providers` / `llm_usage` | 模型 Provider 与用量；群表记录主/备用 Provider 绑定 |
| `tools` / `tool_runs` | 工具注册与执行记录 |
| `media_assets` / `media_processing_jobs` / `media_transcripts` / `media_provider_usage` / `provider_registry` | 媒体、任务、转写、用量与能力注册 |
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

- Vue 3 `<script setup>` + TypeScript + Element Plus；Pinia 管理应用状态与事件；Vue Router 十四个页面（含长期记忆、受管连接器、接入向导与诊断中心）。
- `src/api/client.ts` 统一封装 `{data,error,request_id}`、超时、错误提示与 `X-Request-ID`。
- 管理 Token 仅存 `sessionStorage`；API 客户端按需附带。
- SSE 事件流用于仪表盘实时事件；断线由浏览器自动重连。
- 所有页面具备加载、空、错误状态；破坏性操作使用二次确认；密钥只显示掩码。
- 能力状态使用统一 `StateTag`/`stateLabel`，Mock/规划中采用警告或信息色，绝不使用成功色。
- 当前 Element Plus 全量引入，构建有 chunk 体积警告，不影响功能；后续可改为按需引入。
- 视觉体系采用蓝白橙：深蓝侧栏、白色卡片、浅蓝内容底、橙色强调；成功/危险/警告仍使用绿/红/橙语义色，避免把未知或未配置能力显示为正常。

### 桌面壳（Electron）

`desktop/` 是独立的 npm 包，不进入前端构建产物，也不改变后端 API。它支持两种布局：

- **源码布局**：后端为 `backend/.venv` + uvicorn，前端为仓库 `frontend/dist`，`.env` 与
  `data/` 在仓库根。
- **安装版布局**（electron-builder `extraResources`）：`resources/backend/aiqf-backend.exe`
  + `_internal`、`resources/backend/tools/aiqf-napcat-installer.exe`、`resources/frontend/dist`；
  用户数据、密钥与受管连接器位于 Electron `userData`，安装目录保持只读。

核心行为：

- **进程边界**：主进程负责窗口、托盘、设置、子进程与安全策略；渲染进程只能通过 preload 暴露的固定方法调用，不接触 `ipcRenderer`、`fs` 或 `child_process`。
- **加载来源**：启动向导使用本地 `shell/index.html`；就绪后加载 `http://127.0.0.1:<实际端口>/`，让 REST、SSE 与静态资源保持同源。禁止导航到其他来源与新窗口，外链仅放行固定 Releases 地址。
- **后端生命周期**：优先探测 `8000` 上的本项目健康后端，识别到后进入外部模式，不 spawn、不停止；否则在空闲端口启动后端。源码版启动 `uvicorn`，CWD 固定为 `backend/`；安装版以固定参数 `[]` 直接启动冻结 exe，不经过 Python。两者都显式传入绝对数据目录、数据库 URL、前端产物目录与用户选择的 `CONNECTORS_DIR`；安装版还传入 `AI_GROUP_FRIEND_ENV_FILE` 与 `AI_GROUP_FRIEND_INSTALLER_EXE`，并清除继承的重定向变量。启动失败时结束进程并回到控制页；退出时先停止受管后端，Windows 超时用进程树结束兜底。
- **运行期健康**：进入 `running`/`external` 后每 12 秒探测 `/api/health`，超时 1.5 秒且单飞；前两次失败保持原状态，第三次标记 `degraded`，成功立即恢复。健康探测只更新 `backend.health`，绝不改变进程状态或重启/杀死进程。
- **首次向导**：源码版按“环境 → venv → 后端依赖 → `.env` → 前端依赖 → 前端构建 → 启动”执行，每步幂等并流式显示日志；只补齐缺失项，不覆盖已有 `.env`、数据库或构建产物。安装版只做运行时自检与 `userData/.env` 生成（随机密钥、`0600`、不覆盖），然后启动内置后端。启动成功后首次进入 `/onboarding`，后续进入 `/`。
- **导航守卫**：主进程记录上一次后端状态，只在状态从非运行转入 `running`/`external` 时导航；健康事件不会把用户从向导或设置页切走。
- **托盘可用性**：`createTray()` 记录 `{available, reason}` 并放入快照；关闭窗口与 `window-all-closed` 按实际能力决定最小化或退出，不把不可用的托盘说成可用。
- **设置与数据**：桌面设置保存在 Electron `userData/settings.json`（原子写入、字段校验）。安装版数据目录默认 `userData/data`、连接器默认 `userData/connectors/napcat`；源码版默认仓库 `data/` 与 `connectors/napcat`。两者修改后均需重启后端生效。打开目录只允许 `data/logs/backups/connectors` 四类白名单；目录选择对话框只返回路径，不读写文件、不执行命令。
- **维护**：托盘与“系统设置 → 桌面版”提供状态、版本、数据/日志/备份入口、重启后端与发布页；不提供自动更新，也不把维护入口暴露给群消息、模型或远程管理面。
- **桌面集成**：`frontend/src/api/desktop.ts` 声明 preload 契约；浏览器模式显式返回“不可用”，不会伪装桌面能力。设置页按 `desktop.packaged` 显示「安装版（自带运行时）」或「源码版（需本机 Python/Node）」。

### 发行包构建

- `scripts/build_release.py` 只用固定命令：版本一致性检查 → `npm run build` → 生成 ICO →
  PyInstaller 冻结后端（onedir）与 NapCat 安装器（onefile）→ electron-builder NSIS。
- 构建使用本机 `desktop/node_modules/electron/dist`，避免构建时联网下载 Electron；NSIS
  工具下载使用系统 CA。安装包 `asar: false`，便于审计内置文件。
- `release/BUILD_INFO.json` 记录版本、Git commit、工具链版本、产物大小与 SHA-256，并显式
  写入 `real_qq_verified: false`、`real_model_verified: false`、`signed: false` 与
  `installer_executed_on_clean_machine: false`。
- 安装包未签名、无自动更新；依赖分发与升级由用户手动完成。安装/卸载默认保留
  `userData`，完整策略见 [RELEASE.md](RELEASE.md)。

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
| 桌面壳 | `node:test` 覆盖设置原子写入/校验、端口探测、绝对环境变量、启动健康检查、运行期健康降级/恢复/单飞/定时器清理、向导幂等与 `.env` 不覆盖、外部后端不接管、安装版布局与固定参数；`electron . --smoke` 真实启动后端，断言首次启动进入 `/onboarding`、健康为 `healthy`、快照含托盘字段，并截图 |
| 发行包 | `scripts/build_release.py` 生成安装包与哈希清单；`scripts/release_smoke.py` 在隔离临时目录启动冻结后端（迁移/健康/前端/版本/运行模式）并运行安装版 Electron `--smoke`，清除 Python/Node 依赖。**不执行 NSIS 安装器，不接触真实 QQ/模型** |

测试使用临时文件 SQLite，不依赖本机数据与前端构建产物；不接触真实 QQ 或真实模型。
分层与当前证据见 [implementation/TEST_MATRIX.md](implementation/TEST_MATRIX.md)。

## 16. 扩展点

- 新连接器：实现 `BaseQQAdapter`，通过 `QQAdapterFactory.register(QQAdapterSpec(...))` 注册；账号/能力接口从工厂派生连接方式，消息流水线与 outbox 不修改。未实现能力必须在 `AdapterCapabilities` 中为 `false`。官方 QQ 机器人以 `available=False` 的规划项登记。
- 新模型：实现 `LLMProvider`，通过 ProviderRegistry 暴露与测试。
- 新工具：实现 `Tool` + Schema + 风险等级；默认禁用，需显式授权。当前工具集在启动时固定，不提供运行时注册入口。
- 新媒体能力：实现 Provider 契约与任务处理器，同时在能力中心诚实标注状态；只有任务处理器真正接通后，该能力才能在 `JOB_EXECUTABLE_CAPABILITIES` 中标记为 `job`，否则保持 `contract_only`。
- 新扩展：`GET /api/extensions/capabilities` 汇总契约与执行状态；新增类型时必须同时给出接口、实现、执行方式、流水线依赖与安全保证，不得只提供空接口就标记为可用。
- 新成长策略：在治理层增加策略，但不得绕过证据、锁定字段、版本与审计。
- 新前端页面：沿用 `api/client.ts`、`PageHeader`、`StateTag` 与统一状态处理。

## 17. 已知技术债

- 手动清理前可调用 `GET /api/system/retention/preview` 获取只读计数，但预览不是 dry-run，不能代替实际运行；自动清理按计划直接执行。清理不覆盖 outbox、审计、备份与当前 `app.log`。消息清理不改写记忆正文，只有记忆保留期清理会删除未固定记忆。
- 每人限频依赖 outbox 来源成员字段；历史记录缺少来源时不归属成员额度，群级限制仍生效。重复刷屏保护是单进程启发式，重启清零。
- 真实媒体下载/转存与真实多模态 Provider 未实现；长期记忆支持手动录入、手动或群级后台增量候选提取与关键词/二元词检索，但没有摘要压缩或向量语义检索。后台提取只生成待审核候选，不自动批准。
- 模型路由目前仅支持群级主/备用绑定与单次调用回退，不支持按功能拆分模型或基于成本/延迟/健康度的自动路由。不支持流式响应、Embedding、分布式限流、跨进程取消或服务商账单对账；模型列表不持久化缓存。
- Element Plus 全量打包导致构建产物偏大。
- OneBot 真实 NapCat 版本差异仍需用户联调。
- 安装版已能自带运行时并完成隔离冒烟，但**未签名、无自动更新、未在独立干净机器执行 NSIS 安装/卸载**；没有自动降级，升级前需完整复制 `userData`。源码版仍需本机 Python/Node。`--smoke` 使用真实 Electron 进程，在无图形会话的 CI 中可能不可用。
- 当前仅单进程内存适配器状态与事件缓存；多进程部署需要外部化。
- SQLite 适合单机规模；并发与大数据量需重新评估。

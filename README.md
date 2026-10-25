# AI 群友 · QQ 群聊 AI 管理平台

本地优先的「AI 群友」管理平台。用户使用**自己拥有并授权管理的专用 QQ 账号**，通过自行安装并登录的 OneBot 11 连接器（如 NapCat）接入，AI 只在用户明确加入白名单的群中，按保守策略参与聊天。平台提供可治理的人格成长、消息流水线、模型 Provider、预算、审计、备份和完整的中文管理控制台。

> **P0 完整 MVP**：Mock 闭环、OneBot 11 接入、基础人格治理、本群范围内的长期记忆检索、手动触发或群内可选开启的后台增量 AI 记忆候选提取与人工审核、群级主/备用模型绑定与受控故障回退，以及全部管理 API/页面已实现。后台提取默认关闭，只生成待审核候选；真实多模态、语义检索、定时话题、官方 QQ 机器人等属于规划能力，界面会明确标注「未配置 / 规划中 / Mock」，不会假装可用。

> **桌面版（本机一键启动）**：双击根目录 `start-desktop.cmd`，由本机桌面窗口自动完成缺失的依赖安装、前端构建、密钥生成并启动后端。仍需本机安装 Python 3.12+ 与 Node.js 20+；当前不提供独立安装包、代码签名或自动更新。详见 [docs/DESKTOP.md](docs/DESKTOP.md)。

---

## 重要声明

- 本项目**不登录 QQ、不收集 QQ 密码、不实现验证码绕过或风控规避**。QQ 登录完全由用户在自己安装的连接器中完成。
- 非官方连接器可能存在兼容性、平台规则与账号风险。请仅使用**自己拥有、获授权管理**的账号，并从「仅观察」开始，小范围验证后再开启回复。
- 未配置真实模型时，系统只提供 Mock 模型；Mock 回复是固定模板，**不代表真实模型能力**。
- 当前版本没有真实视觉 / OCR / 语音识别 Provider。图片、语音只会以「当前未配置识别能力」的降级提示进入上下文，AI 不会真的看到或听到内容。
- 群聊内容、OCR 文本、语音转写、工具结果一律视为**不可信数据**，不会被提升为系统或管理员指令。
- 默认只允许本机管理 API。远程管理需要显式配置，详见 [SECURITY.md](docs/SECURITY.md)。

## 当前能力状态

| 能力 | 状态 | 说明 |
| --- | --- | --- |
| Mock QQ 连接器 + Mock 模型 | ✅ 可用 | 无真实 QQ / 无 API Key 即可完整验收闭环 |
| OneBot 11（NapCat 等） | ✅ 已实现，需用户联调 | 正向 WebSocket 收事件 + HTTP/WS action 发送；Token 加密保存 |
| 官方 QQ 机器人 | ⏳ 规划中 | 接口占位，不可用 |
| 消息去重 / 白名单 / 自身过滤 / 暂停 / 限速 / 安静时段 | ✅ 可用 | 硬规则先于模型调用 |
| 触发模式 | ✅ 仅观察 / 仅 @ / 关键词 / 上下文（骨架） | 「上下文」为保守实现；「定时话题」规划中 |
| 人格：用户编写 / 模板 / 空白自成长 | ✅ 可用 | 证据门槛、锁定字段、版本、回滚、审核/自动/暂停 |
| 跨群学习 | ⚙️ 默认关闭 | 可配置但不推荐；默认 `admin_only` |
| OpenAI 兼容模型接口 | ✅ 可用 | 在控制台填写 Base URL / 模型 / Key，密钥加密保存 |
| Anthropic 原生接口 | ✅ 已实现，需真实 Key | 直接调用 Messages API；Base URL 留空使用官方地址，也可填写可信代理；未用真实 Key 联调 |
| 群级模型路由与受控回退 | ✅ 可用 | 每个群可绑定主模型与备用模型；仅 Provider 调用错误回退一次，预算/暂停/本地凭证与配置错误不回退，不会静默改用 Mock 或默认模型 |
| 真实视觉 / OCR / ASR / TTS / Embedding | ⏳ 未配置 | 仅接口与 Mock 任务队列，不伪称已识别 |
| 内置工具（计算器、日期时间） | ✅ 可用 | 无任意 Shell / 文件读写工具 |
| 第三方插件执行 | ⛔ 不执行 | 仅登记清单、权限与健康状态 |
| 预算与 Token 用量 | ✅ 可用 | 全局/群/Provider 维度聚合真实本地记录；超限在调用前阻断。费用仅按你填写的单价估算，未配置单价的调用标记为不可计价，费用预算会阻断而不是伪造 0 成本 |
| 用量趋势、预算告警与 CSV | ✅ 可用 | 按配置时区聚合小时/自然日真实用量；接近上限/超限去重生成告警并写审计、推送 SSE；CSV 仅含调用元数据，不含消息正文、提示词或凭证，导出动作写审计 |
| 备份 / 校验 / 恢复预览 / 恢复 | ✅ 可用 | 仅数据库，不含媒体、日志与加密密钥 |
| 长期记忆（本群范围） | ✅ 可用 | 手动管理 + 手动或群级后台增量 AI 候选提取；后台默认关闭、只生成待审核候选，批准前不保存、不注入；语义检索仍规划中 |
| Electron 桌面版（本机一键启动） | ✅ 已交付，需本机 Python/Node | 启动向导、托盘、后端进程管理、维护入口；复用本仓库 `.venv`，不是独立安装包，不含自动更新 |
| 评测回放、插件市场、MCP、多账号 | ⏳ 规划中 | 仅数据骨架或接口占位 |

## 技术栈

- **后端**：Python 3.12+（本仓库已在 Python 3.14.5 上验证）、FastAPI、Pydantic v2、SQLAlchemy 2 async、SQLite + aiosqlite、Alembic
- **前端**：Vue 3 + TypeScript + Vite + Element Plus + Pinia + Vue Router
- **桌面壳**：Electron 45（独立 `desktop/` 包；窗口加载本机 `http://127.0.0.1:<port>`，保持 API/SSE 同源）
- **实时**：SSE（`/api/events/stream`）
- **安全**：Fernet 应用层加密、API 密钥掩码、日志脱敏、本机优先的管理边界、sandbox + contextIsolation + 最小 IPC
- **质量**：pytest、ruff、mypy、vue-tsc、Vitest、`node:test`、Electron 截图冒烟

## 架构概览

```text
QQ / NapCat ──OneBot 11 WS──┐
                            ├─→ CanonicalMessage
Mock 事件 ──────────────────┘
                                   │
       ┌───────────────────────────▼───────────────────────────┐
       │ 消息流水线                                             │
       │ 去重 → 自身过滤 → 白名单 → 全局暂停 → 安静时段 → 静音 │
       │ → 限速 → 命令 → 触发决策 → 上下文/人格 → 模型/工具    │
       │ → 回复审查 → outbox → 发送 → 日志/用量/审计/SSE        │
       └───────────────────────────┬───────────────────────────┘
                                   │
                    Mock 连接器 / OneBot 11 HTTP action
```

更完整的设计说明见 [docs/SOFTWARE_DESIGN.md](docs/SOFTWARE_DESIGN.md)。

## 目录结构

```text
QQ-AI/
├─ start-desktop.cmd        # 双击启动桌面版（Windows）
├─ README.md / CLAUDE.md / .env.example / .gitignore
├─ docs/
│  ├─ DESKTOP.md            # 桌面版架构、向导、托盘、数据目录与排错
│  ├─ SOFTWARE_DESIGN.md    # 架构、数据模型、流水线与失败模式
│  ├─ API.md                # REST/SSE 接口与示例
│  ├─ SECURITY.md           # 安全边界、威胁模型与运维检查
│  └─ ROADMAP.md            # 范围、验收清单与后续规划
├─ desktop/                 # Electron 桌面壳（独立 npm 包）
│  ├─ main.js / preload.js  # 主进程、最小 IPC 桥
│  ├─ lib/                  # 设置、端口、后端进程、向导、日志
│  ├─ shell/                # 启动向导/控制页
│  └─ tests/                # node:test 单元测试
├─ scripts/
│  ├─ launch_desktop.ps1    # 桌面版引导（首次安装 Electron）
│  ├─ dev.ps1 / dev.sh      # 开发启动
│  ├─ check.ps1             # 全量质量检查
│  ├─ backup.ps1            # 命令行备份（API 优先，离线回退）
│  ├─ offline_backup.py     # 离线 SQLite 一致性备份（由 backup.ps1 调用）
│  ├─ gen_keys.py           # 生成本地密钥并写入 .env
│  └─ smoke_test.py         # 真实 uvicorn 端到端 Mock 冒烟测试
├─ backend/
│  ├─ app/                  # FastAPI 应用与服务
│  ├─ alembic/              # 数据库迁移
│  └─ tests/                # 单元 / 集成 / API / 适配器测试
├─ frontend/                # Vue 管理控制台
├─ data/                    # 本地数据库、日志、媒体、备份（不提交）
└─ Claude代码与AI群友笔记/   # 原始需求资料（保留不动）
```

## 快速开始（Windows 11）

### 前置条件

- Python **3.12+**（已验证 3.14.5）
- Node.js **20+** 与 npm（已验证 Node 24.19 / npm 12.0.2）
- Windows PowerShell；Git Bash 可选

桌面版不会代替你安装 Python/Node，也不会绕过系统权限；缺少时会在向导中给出明确提示。

### 方式 A：桌面版（推荐，一键启动）

1. 双击仓库根目录的 **`start-desktop.cmd`**（或在 PowerShell 中执行 `.\start-desktop.cmd`）。
2. 首次启动会安装 `desktop/` 的 Electron 依赖（约数百 MB，需要网络），随后打开蓝白橙启动向导。
3. 向导按顺序检查 Python/Node，补齐 `.venv`、后端依赖、`.env` 密钥与前端构建，然后启动本地后端并进入管理台；已在运行的本项目后端会被直接接管（外部模式），不会启动第二个进程。
4. 关闭窗口默认最小化到托盘；从托盘可恢复窗口、启停/重启后端或彻底退出。所有行为都可在「系统设置 → 桌面版」中调整。

> 桌面版复用本仓库的 `backend/.venv` 与 `frontend/dist`，**不是**免 Python/Node 的独立安装包，也**不包含自动更新**。升级代码后重新启动即可；如改动前端，需重新构建。详见 [docs/DESKTOP.md](docs/DESKTOP.md)。

### 方式 B：开发者手工启动

以下命令均以仓库根目录为起点。

#### 1. 安装后端

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -e ".[dev]"
```

若 PowerShell 阻止激活脚本，可仅对当前会话放行：

```powershell
Set-ExecutionPolicy -Scope Process Bypass
```

#### 2. 安装前端

```powershell
cd frontend
npm install
npm run build
```

开发模式可不构建；生产预览需要 `npm run build`，构建产物由 FastAPI 托管。

#### 3. 生成本地密钥

在项目根目录执行：

```powershell
backend\.venv\Scripts\python.exe scripts\gen_keys.py --write
```

它会以 `.env.example` 为模板创建 `.env`，写入随机的 `APP_SECRET_KEY` 与 `CREDENTIAL_ENCRYPTION_KEY`。

> **必须妥善保管 `CREDENTIAL_ENCRYPTION_KEY`。** 它不在数据库中，也不在备份中；更换或丢失后，已保存的 OneBot Token 与 API Key 将无法解密。`.env` 已被 `.gitignore` 忽略，不要提交或分享。

#### 4. 启动

开发模式（后端热重载 + Vite 前端）：

```powershell
.\scripts\dev.ps1
```

- 控制台：<http://127.0.0.1:5173>
- API 文档：<http://127.0.0.1:8000/api/docs>

或手动分别启动：

```powershell
# 终端 1：后端（工作目录必须是 backend）
cd backend
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000

# 终端 2：前端
cd frontend
npm run dev
```

生产 / 单进程预览（先构建前端）：

```powershell
cd frontend
npm run build
cd ..\backend
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

打开 <http://127.0.0.1:8000>，由 FastAPI 托管 `frontend/dist`。

### 首次验收（不需要真实 QQ 或模型）

1. 打开控制台，在「仪表盘」点击 **一键初始化 Mock 演示环境**。
2. 进入「模拟测试」，选择演示账号与 Mock 演示群，勾选 **@ 机器人**，点击 **注入 Mock 事件并发送**。
3. 在「消息与用量」查看入站/出站消息、发送队列、Mock 模型 Token 用量与费用完整性；仪表盘会按 Provider 和群展示今日真实调用记录。Mock 调用标记为「无外部费用」，不会伪造真实账单。
4. 在「扩展与预算」查看小时/自然日趋势；把某个请求预算的上限设为已用量以下，随后应出现「已超限」告警，并在系统设置的审计日志中看到 `budget.alert.exceeded`。导出 CSV 时只包含调用元数据，不包含群消息正文或密钥。
5. 在「QQ 接入 → Mock 已发送」查看 Mock 连接器收到的回复。
6. 在「系统设置」尝试全局暂停；暂停期间任何回复都会被拦截，发送队列也不会派发。
7. 在「系统设置 → 备份」创建并校验备份；恢复需要先全局暂停并输入 `RESTORE`。

所有演示只使用 Mock 连接器与 Mock 模型，不会连接或发送到真实 QQ。

## 接入真实 QQ（OneBot 11 / NapCat）

### 风险提示

请只使用自己拥有并获授权管理的专用账号。非官方连接器存在协议兼容、平台规则与封号风险；本软件不提供验证码绕过、设备指纹伪装、批量养号、自动加群/加好友、广告群发或限流规避。遇到验证码、风控或账号异常提示时，立即**暂停平台**并停止连接器，由账号所有者自行处理。

### 步骤

1. 自行安装 NapCat（或其他 OneBot 11 实现）并登录专用 QQ 账号。
2. 在连接器中启用：
   - WebSocket 服务器（本机示例：`ws://127.0.0.1:3001`）——用于接收事件；
   - HTTP API（本机示例：`http://127.0.0.1:3000`）——用于发送消息；
   - 一个独立访问 Token。不同连接器版本字段不同，请以其文档为准。
3. 打开控制台「QQ 接入」→ 新建账号 → 添加连接器实例：
   - 连接方式：`OneBot 11`；
   - WS 地址与 HTTP API 地址填写连接器实际地址；
   - Token 填写与连接器一致的独立 Token；
   - 默认只允许回环/私网地址。公网地址必须显式勾选「允许远程连接」并自行承担风险。
4. 点击 **测试连接**，确认 `get_login_info` 成功并读取到账号自身 QQ 号。
5. **导入群列表**。导入的群默认关闭 AI 回复。
6. 在「群聊管理」逐个确认群，先保持「仅观察」，观察一段时间后再切换为「仅 @ 回复」（默认推荐）。
7. 在「模型 API」填写真实的 OpenAI 兼容接口或 Anthropic 原生接口并点击 **测试连接**；测试错误会区分认证、网络、模型不存在、额度不足和超时。Anthropic 类型留空 Base URL 时使用官方地址，需要真实 API Key。

### 字段与行为

- 连接器状态、心跳、最后收发时间与错误码来自当前进程；后端重启后需重新连接。
- 收到的事件会先经过去重、自身消息过滤和白名单检查；未通过硬规则的消息不会触发模型调用。
- 发送状态未知（如网络超时）的队列消息标记为 `unknown`，**不会自动重发**，避免重复发送。
- 连续发送失败达到阈值会自动暂停该群并记录事件。
- 当前版本不下载或转存真实图片/语音，也不下载文件；媒体段只保留安全元数据与降级提示。

## 配置说明

### `.env`（仅本地，不提交）

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `APP_ENV` | `development` | 运行环境标识 |
| `APP_HOST` / `APP_PORT` | `127.0.0.1` / `8000` | 管理服务监听地址，默认仅本机 |
| `LOG_LEVEL` | `INFO` | 日志级别 |
| `DEFAULT_TIMEZONE` | `Asia/Shanghai` | 群安静时段默认时区 |
| `DATA_DIR` | `<项目根>/data` | 数据库、日志、媒体、备份根目录 |
| `DATABASE_URL` | 自动生成 | 默认 `sqlite+aiosqlite:///<项目根>/data/ai_group_friend.db`；相对路径按启动工作目录解析 |
| `AUTO_MIGRATE` | `true` | 启动时自动执行 Alembic 迁移 |
| `APP_SECRET_KEY` | 空 | 本机管理密钥；由 `gen_keys.py` 生成 |
| `CREDENTIAL_ENCRYPTION_KEY` | 空 | Fernet 凭证加密密钥；缺失时拒绝保存 Token/API Key |
| `ALLOW_REMOTE_ADMIN` | `false` | 是否允许非本机管理请求 |
| `ADMIN_API_TOKEN` | 空 | 远程管理 Token；仅在 `ALLOW_REMOTE_ADMIN=true` 时生效 |
| `CORS_ORIGINS` | `http://127.0.0.1:5173,http://localhost:5173` | 允许的前端来源，逗号分隔 |
| `LLM_TIMEOUT_SECONDS` | `45` | 模型请求超时 |
| `LLM_MAX_RETRIES` | `2` | 可重试错误的有限重试次数 |
| `MAX_TOOL_ROUNDS` / `MAX_TOOL_CALLS_PER_TURN` | `2` / `3` | 工具轮次与单轮调用上限 |
| `CONTEXT_MESSAGE_LIMIT` | `20` | 上下文消息条数上限 |
| `MEMORY_AUTO_EXTRACTION_INTERVAL_SECONDS` | `300` | 后台记忆候选提取调度检查间隔；群内开关默认关闭 |
| `MAX_REPLY_CHARS` | `500` | 回复长度审查上限 |
| `OUTBOX_MAX_ATTEMPTS` | `3` | 发送队列最大尝试次数 |
| `OUTBOX_FAILURE_PAUSE_THRESHOLD` | `3` | 连续失败自动暂停阈值 |
| `FRONTEND_DIST` | `<项目根>/frontend/dist` | 生产静态文件目录 |

可选的 `DEFAULT_LLM_*` 环境变量只适合临时调试。**正式 API Key 请在控制台「模型 API」中填写**，数据库中仅保存密文，接口只返回掩码。

### 数据库中的配置

群策略、人格、Provider、预算、保留策略、全局暂停、审计与备份记录保存在本地 SQLite。备份只包含数据库；媒体、日志与加密密钥不包含在内。

## 群白名单与回复策略

- **白名单默认空**：不导入或启用任何群，AI 不会回复。
- 默认回复模式为 **仅 @ 回复**；「仅观察」只记录不回复。
- 「关键词」命中群配置的关键词才回复；「上下文」为保守实现，仍受冷却、小时/每日上限和连续回复限制。
- 安静时段按群时区计算，可跨午夜。
- 全局紧急暂停优先于一切：不生成发送，也不派发发送队列。
- 工具默认在群内禁用；不存在任意 Shell、PowerShell、文件读写或任意 HTTP 请求工具。

## 人格治理

- **用户编写（authored）**：由用户定义自我描述与设定字段。
- **模板（template）**：选择内置模板作为起点。
- **空白自成长（emergent）**：初始无性格、无背景；AI 只能提出结构化人格提案，经治理服务校验证据、置信度、范围和锁定字段后，按「自动 / 人工审核 / 暂停」处理。
- 默认证据门槛：至少 2 个不同会话、3 次一致证据；单条消息不能改变人格。
- 每次变更生成版本与变更事件，可回滚；锁定字段、系统安全规则、群规和工具权限不可被成长覆盖。
- 跨群学习默认关闭；群消息不得提升为系统指令。
- 人格工作台中的「测试对话」只做 dry-run，不发送、不写消息日志。

## 备份与恢复

- 通过「系统设置 → 备份」或 `POST /api/backups` 创建一致性 SQLite 备份。
- 每个备份有清单、SHA-256、表计数和 SQLite 完整性校验。
- 恢复前必须：全局暂停 → 校验备份 → 阅读预览 → 输入 `RESTORE`。系统会自动创建安全备份并断开所有连接器。
- 备份**不包含**媒体文件、日志和 `CREDENTIAL_ENCRYPTION_KEY`。恢复后需使用同一加密密钥，否则旧 Token/API Key 无法解密。
- 命令行备份（后端未运行时自动使用 SQLite 在线备份）：

```powershell
.\scripts\backup.ps1 -Note "升级前"
# 或显式离线
.\scripts\backup.ps1 -Offline
```

离线备份不会出现在控制台备份列表与审计中，正式恢复仍建议使用控制台流程。

## 质量检查与冒烟测试

全量检查（ruff format/check、mypy、pytest、vue-tsc、Vitest、生产构建、桌面壳 `node:test`）：

```powershell
.\scripts\check.ps1
# 只检查后端或前端（-FrontendOnly 不包含桌面壳测试）
.\scripts\check.ps1 -BackendOnly
.\scripts\check.ps1 -FrontendOnly
```

真实进程端到端冒烟测试（临时数据目录 + 随机本机端口 + 真实 uvicorn，不接触真实 QQ/模型）：

```powershell
backend\.venv\Scripts\python.exe scripts\smoke_test.py
```

桌面壳测试与截图冒烟（会真实启动临时后端并截图到 `desktop/.smoke/`）：

```powershell
cd desktop
npm test
npm run smoke
```

它会验证演示环境、@ 回复闭环、非 @ 忽略、dry-run 不落库、全局暂停、群级模型绑定与删除保护、密钥脱敏与落盘加密、备份校验、错误确认短语、暂停前置条件、真实恢复、审计与恢复后重连。失败时返回非零并保留诊断日志（加 `--keep` 可保留临时目录）。

## 排错

| 现象 | 处理 |
| --- | --- |
| 打开 `:8000` 显示「前端尚未构建」 | `cd frontend; npm run build`，或开发时使用 Vite `:5173` |
| 保存 Provider 报 `CREDENTIAL_KEY_MISSING` | 运行 `python scripts/gen_keys.py --write` 并重启后端；不要用错误格式的 Fernet 密钥 |
| 远程访问返回 403 / 401 | 默认只允许本机。确需远程时设置 `ALLOW_REMOTE_ADMIN=true`、强 `ADMIN_API_TOKEN`，并通过受保护的反向代理（HTTPS）访问 |
| NapCat 连接失败 | 检查 WS/HTTP 端口、Token、连接器是否启动；公网地址需显式允许；查看「QQ 接入」中的状态 JSON 与错误码 |
| 测试模型报认证/模型/额度错误 | 在「模型 API」点击测试，按返回的 `error_code` 分类排查；Mock 模型无需 Key |
| 401/403 之外的端口冲突 | 修改 `APP_PORT` 或 Vite 端口，并同步代理配置 |
| 回复始终被拦截 | 查看「消息与用量」的拦截原因：白名单、仅 @、安静时段、冷却/小时上限、全局暂停、预算、模型未配置 |
| 备份恢复后连接器离线 | 这是预期行为；确认配置后重新连接。旧凭证还需要原加密密钥 |
| Windows 中文乱码 | 使用 Windows Terminal；脚本已设置 `PYTHONUTF8=1`，Python 输出显式使用 UTF-8 |
| 前端构建提示 chunk 过大 | Element Plus 整体打包导致，仅警告，不影响功能 |
| 桌面版提示 Electron 下载失败 | 设置 `ELECTRON_MIRROR` 镜像后重试，或检查网络/代理；详见 [DESKTOP.md](docs/DESKTOP.md) |
| 桌面版启动向导失败 | 查看控制页日志；常见原因是 Python/Node 版本、网络、`.env` 密钥无效或端口占用。已完成步骤可安全重试 |

## 安全与隐私

- 群消息默认保存在本机 SQLite。启用真实模型后，经过筛选的上下文会发送给你配置的模型服务；请自行评估服务条款与数据合规。
- Token / API Key 以 Fernet 密文存储，接口只返回掩码，日志做防御性脱敏。
- 管理 API 默认仅本机；所有管理写操作尽量写审计。
- 数据保留期限可在「系统设置」配置（日志 30 天 / 消息 90 天 / 媒体 30 天为默认值）；当前仅保存配置，自动清理调度仍属后续工作，请定期人工清理。
- 不要在 Issue、截图或日志中公开 `.env`、Token、API Key 或真实群成员信息。

完整安全说明与事件响应清单见 [docs/SECURITY.md](docs/SECURITY.md)。

## 已知限制

- 没有真实 NapCat 登录环境和真实模型 Key；OneBot 11 仅通过进程内假服务器与协议测试验证，真实 QQ 联调需用户完成。OpenAI 兼容与 Anthropic 原生适配器均只用 MockTransport 验证请求映射，未调用真实服务。
- 真实图片/语音不会下载或识别；媒体任务队列为 Mock，界面已如实标注。
- 长期记忆支持手动录入、手动触发或群级后台增量 AI 候选提取（必须人工审核）与本群范围内的关键词/二元词检索；后台提取默认关闭、按水位线增量扫描、全局暂停时停止。没有摘要压缩或向量语义检索。Mock 模型生成的候选仅用于演示，不应作为真实记忆长期保留。
- 模型路由目前只支持按群绑定主/备用 Provider，不支持按功能拆分模型，也没有基于成本、延迟或健康度的自动路由；回退仅在显式配置备用模型时发生。
- 费用是本地估算：只有你填写 Provider 单价、且服务返回完整 Token 用量后才会计算，且不是服务商账单；未配置单价或用量缺失的调用标记为不可计价，不会显示为 0。费用预算启用时，未配置单价的非 Mock Provider 会被阻断。若 Provider 不返回 Token 用量，该次调用无法计入费用上限，请改用会返回 `usage` 的接口。
- 用量趋势按配置时区（默认 `Asia/Shanghai`）在应用层分桶，不是服务商账单；未知费用保持为空。预算告警基于已记录的本地用量，同一策略、同一统计周期、同一级别最多记录一次；告警不会自动解除或执行额外动作，达到上限时仍由预算检查阻断调用。CSV 只导出模型调用元数据（时间、Provider、模型、Token、估算费用、状态等），不含消息正文、提示词、API Key 或任何凭证。
- Electron 桌面版提供本机一键启动、向导、托盘与维护入口，但**仍需本机 Python 3.12+ / Node.js 20+**；没有独立安装包、代码签名或自动更新，升级前端代码后需重新构建。桌面壳不会绕过既有安全边界，外部启动的本项目后端只会被连接、不会被桌面版停止。
- 定时话题、评测回放、插件执行、多账号、MCP 等仍为规划能力。
- 数据保留策略目前需人工触发清理；自动清理任务未实现。
- SQLite 适合单机小规模使用；高并发或多实例部署不在当前范围。
- 非官方连接器的兼容性与账号风险由用户自行评估。

## 文档

- [桌面版说明](docs/DESKTOP.md)
- [架构与实现设计](docs/SOFTWARE_DESIGN.md)
- [HTTP / SSE API](docs/API.md)
- [安全边界与事件响应](docs/SECURITY.md)
- [范围、验收与路线图](docs/ROADMAP.md)
- 原始需求资料：`Claude代码与AI群友笔记/`

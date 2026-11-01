# 阶段 0 + 1 + 2 + 3 + 4 + 5 + 6 + 7 + 8 进度记录

日期：2026-11-01
分支：`v1.3-phase1`

## 0.2.2 连接器可恢复安装与普通用户自动接入

### 已完成的本地实现

- 受管 NapCat 安装支持同版本完整目录复用、受管损坏目录隔离修复、未知目录拒绝且不
  触碰、陈旧 staging 清理；下载有界重试；ZIP 完整性/路径/重复项/符号链接/大小/压缩比
  校验；占用与权限错误映射为稳定错误码；安装事件区分 `installed/reused/repaired`。
- 新增 `POST /api/onboarding/actions/auto-configure-connector` 与向导一键入口：唯一可用
  受管 Shell 下输入 `AUTO CONFIG` 自动分配端口、生成加密 Token、写配置并创建
  `auto_connect=false` 的受管账号；不启动连接器、不登录 QQ。
- 向导每步返回 `status/started_at/completed_at/attempt_count/last_error_code/
  last_error_message/can_retry/next_action`；顶层返回 `counts` 与唯一 `next_action`；
  只有真实 OneBot 实例才把“连接器准备”标为完成。
- 账号页把手动地址/端口降级为高级模式，连接器页增加自动配置入口。

### 验证状态

- 后端 **459 passed**（1 条第三方弃用 warning）、ruff format/check 与 mypy 通过；
  前端 type-check、**76 tests passed**、生产构建通过；桌面 **39 passed**。
- 安装包构建与发布冒烟结果见 [FINAL_REPORT](FINAL_REPORT.md) 与
  [TEST_MATRIX](TEST_MATRIX.md)；真实 NapCat/QQ/模型/干净机仍未验收。
- 本机自动化测试不能替代 [真实环境验收手册](../testing/V0.2.2_REAL_ENV_ACCEPTANCE.md)。

### 外部未完成

- 七个连接器/QQ 节点、真实模型 Key、干净机 NSIS 安装/升级/回滚/卸载、代码签名与
  SmartScreen、NapCat 许可证与隐私合规。

## 0.2.1 最终审计（本机收口）

### 审计发现与本机修复

- `scripts/smoke_test.py` 曾继承仓库真实 `.env`；现在移除所有重定向/密钥/管理变量，
  显式指向不存在的临时 `.env`，并断言版本、数据目录、连接器目录与远程管理关闭。
- `scripts/build_release.py` 曾不清理 `release/`、可能收录旧安装包；现在构建前清理固定
  `release/`、拒绝 dirty 工作树（`--allow-dirty` 可显式放行并记录指纹）、只收集当前版本
  产物、失败清理半成品，并记录分支、dirty 状态、工作树指纹、Electron 实际版本与四处
  版本来源。
- 版本曾分散在 `Settings` 与包元数据；现在 `app_version` 直接引用 `app.__version__`，
  构建脚本校验 desktop/frontend/backend/pyproject 四处一致。
- 损坏/截断备份曾可能在读取表计数时抛出未处理异常；现在返回结构化校验失败，恢复在
  触碰当前数据库前拒绝，且不写审计、不生成安全备份或暂存文件。
- OneBot 空串/空白文本现在在发起 HTTP 前返回 `SEND_FAILED`。
- 新增 NSIS 配置静态回归测试（`oneClick=false`、`perMachine=false`、
  `deleteAppDataOnUninstall=false`、可改目录、产物名含版本）；该测试**不证明真实卸载
  行为**。
- 删除未使用函数与永远返回 501 的 `/api/demo/reset-hint`，避免文档/UI 出现虚假接口。

### 验证状态

- 定向与全量检查均通过：ruff format/check、mypy、pytest **442 passed**、前端
  **76 tests passed** 与生产构建、桌面 **39 passed**、`check.ps1`、源码进程冒烟、
  桌面 6 张截图。
- 0.2.1 安装包构建成功（`git_dirty=false`，安装包 155,824,181 bytes），发布冒烟通过
  （冻结后端 `packaged`、Alembic `f4a7b2c9d801`、桌面 0.2.1 / 6 张截图）。
- 实际输出与哈希记录于 [ROADMAP](../ROADMAP.md)、[TEST_MATRIX](TEST_MATRIX.md) 与
  [FINAL_REPORT](FINAL_REPORT.md)；未执行项保持未验证。

### 外部未完成

- 真实 QQ 收发、真实模型 Key、独立干净机 NSIS 安装/升级/回滚/卸载、代码签名与
  SmartScreen、NapCat 许可证法律审查与隐私合规均未完成。

## 阶段 8：发布、安装包与回归

### 目标

- 生成可安装的 Windows x64 发行包，至少包含后端、前端与桌面运行时；普通用户无需安装
  Python/Node。
- 提供版本号、变更日志、升级/回滚、卸载与数据保留说明。
- 建立从干净环境开始的安装版冒烟，并区分单元、集成、Mock、打包运行时、真实 QQ 与真实
  模型测试。
- 所有构建/测试结果来自实际执行；真实 QQ 验收前明确标注未验证，不宣称生产就绪。

**明确未完成**：没有使用真实 QQ 或真实模型；没有代码签名或自动更新；NSIS 安装器/卸载器
未在独立干净机器执行；未提交 Git。

### 改动

#### 后端

- `app/core/config.py`：识别 `sys.frozen`、`AI_GROUP_FRIEND_ENV_FILE`、
  `AI_GROUP_FRIEND_RESOURCE_ROOT`；冻结默认数据目录为用户目录，默认前端为
  `resources/frontend/dist`；新增 `resolve_backend_root()` 与 `runtime_mode`；版本 0.2.0。
- `app/main.py`、`app/core/schema_version.py`：Alembic 与前端路径兼容源码/冻结布局。
- `app/desktop_entry.py`（新）：冻结后端入口；固定回环、端口范围、日志级别白名单，无 reload。
- `app/connectors/installer.py`：安装版直接执行冻结的 `aiqf-napcat-installer.exe`
  （支持 `AI_GROUP_FRIEND_INSTALLER_EXE`），参数仍由后端固定生成。
- `packaging/aiqf-backend.spec`、`packaging/aiqf-napcat-installer.spec`（新）：
  onedir 后端（Alembic/tzdata）与 onefile 安装器；排除测试与开发工具。
- `pyproject.toml` / `uv.lock`：版本 0.2.0；新增 `packaging` extra（PyInstaller）。
- `tests/test_packaging.py`（新，8 项）：环境文件、资源根、冻结默认目录、运行模式、
  安装器路径、入口端口/日志校验。

#### 桌面壳

- `lib/paths.js`：`resolveRuntime()` 解析源码/安装版布局；安装版资源、`userData/.env`、
  数据与连接器、shell、图标、冒烟输出均按模式派生。
- `lib/backend-env.js`：传入 `AI_GROUP_FRIEND_ENV_FILE` / `INSTALLER_EXE`，清除继承重定向变量。
- `lib/backend.js`：安装版以 `args=[]` 直接启动冻结 exe；源码版保持 Python/uvicorn。
- `lib/setup.js`：新增 `ensureLocalEnvFile()`（随机密钥、`0600`、不覆盖、缺字段报错）与
  `inspectPackagedRuntime()`。
- `main.js`：启动步骤、数据目录、连接器目录、窗口/shell/图标/冒烟路径按模式分流；安装版
  不做 Python/Node/命令向导；快照增加 `packaged`。
- `package.json`：版本 0.2.0；electron-builder 配置（NSIS x64、extraResources、未启用 asar、
  `deleteAppDataOnUninstall=false`）；`pack:dir` / `dist` 脚本。
- `tests/packaged.test.js`（新，5 项）：布局、环境清理、固定参数启动、密钥文件、自检。
- `scripts/make_icon.py`（新）：PNG → ICO。

#### 发布流水线与文档

- `scripts/build_release.py`（新）：版本四向一致性、前端构建、ICO、PyInstaller ×2、
  electron-builder NSIS、`BUILD_INFO.json` 哈希与未验证标记；固定命令、无外部参数。
- `scripts/release_smoke.py`（新）：安装版布局/哈希、冻结后端隔离启动与迁移、前端托管、
  安装版 Electron `--smoke`、系统级 `PATH`、临时 `userData`/数据/密钥；输出
  `release/RELEASE_SMOKE.json`。
- 新增 `CHANGELOG.md`、`docs/RELEASE.md`、`docs/implementation/TEST_MATRIX.md`；同步
  README、DESKTOP、SECURITY、SOFTWARE_DESIGN、ROADMAP、FEATURE_STATUS、`.gitignore`。
- 安装版设置页显示「安装版（自带运行时）」；源码版显示「源码版（需本机 Python/Node）」。

### 实际检查（2026-11-01）

- 后端：`ruff format --check` 168 files already formatted；`ruff check` All checks
  passed；`mypy app` no issues in 134 source files；`pytest -q` 435 passed，1 warning，
  101.26s。
- 前端：`npm run type-check` 通过；`npm run test` 9 files / 76 tests passed（3.35s）；
  `npm run build` 通过（8.53s，主 chunk 1,226.56 kB / gzip 395.29 kB 体积警告）。
- 桌面：`npm test` 38 passed / 0 failed（9.47s）；`npm run smoke` 输出
  `DESKTOP_SMOKE_OK`，版本 0.2.0，6 张截图。
- `scripts/check.ps1`：「全部检查通过」。
- `scripts/smoke_test.py`：「冒烟测试全部通过。未接触真实 QQ 或真实模型。」
- `scripts/build_release.py`：成功；版本 0.2.0；NSIS 安装包
  `AI-Group-Friend-Setup-0.2.0-x64.exe` 155,826,158 bytes，SHA-256
  `119f48c5…f9ecce`；`win-unpacked/AI 群友.exe` 249,797,632 bytes。
- `scripts/release_smoke.py`：通过；冻结后端 `runtime_mode=packaged`、隔离数据目录、
  Alembic `f4a7b2c9d801`、内置前端、安装版 Electron 6 张截图（12.4s）；`PATH` 仅系统目录。
- 失败记录：`tests/test_packaging.py` 首次 `ruff check` 报 `I001` 导入排序，已用
  `ruff check --fix` 修复并复检通过；前端仅有 chunk 体积警告。未隐藏失败。

### 限制

- 安装包未签名；没有自动更新、自动回滚或安装包签名校验；`BUILD_INFO.json` SHA-256 只能
  校验构建产物一致。
- NSIS 安装/升级/回滚/卸载未在独立干净 Windows 机器执行；发布冒烟使用 `win-unpacked`，
  不创建快捷方式或安装注册表项。
- 安装版未在无 Python/Node 的真实机器上人工启动；发布冒烟通过系统级 `PATH` 与自检证明
  不调用外部运行时，但不能替代干净机器验收。
- 升级前必须完整复制 `userData`；旧版程序打开已迁移数据库不受支持；没有自动降级。
- 卸载默认保留数据，卸载不等于删除敏感数据。
- **真实 QQ 端到端与真实模型 Key 未验证，不得宣称生产就绪。**

## 阶段 7：扩展能力与未来接口

### 目标

让工具、视觉、语音、Embedding 与聊天平台保持显式接口，同时把「有契约」与「真的执行」分开：

- 未配置或未实现的视觉/语音/插件能力不得调用伪实现，UI 如实显示 `planned` / `unconfigured` / `contract_only`。
- 停用扩展后立即停止其任务。
- 新增适配器只实现标准接口，不修改消息流水线。
- 插件未来执行必须满足完整安全前置条件，当前仍不加载第三方代码。

**明确未完成**：没有使用真实 QQ 或真实模型；未做打包；**无数据库迁移**；未提交 Git。

### 改动

#### 后端

- `app/media/jobs.py`：新增 `cancel_jobs_for_unavailable_capabilities()`；取消支持 `running`；
  取消后的任务不会被迟到的成功/失败结果覆盖；重试前检查是否仍有可用 Provider。
- `app/services/provider_service.py`：记录 Provider 能力；停用时取消不再有可用 Provider 的能力下
  排队/运行任务；审计记录取消数量；能力概览新增 `execution`、`source`、`checked_at`、
  `enabled_provider_ids`、`last_error`、`next_step`；修正 `planned` 判定，未启用的可执行实现
  标为 `unconfigured`。
- `app/media/capability_router.py`：仅当全部注册实现都是规划占位时才报告 `planned`。
- `app/plugins/runtime.py`（新）：`PluginRuntime` 契约、八项前置要求与显式拒绝的
  `UnavailablePluginRuntime`。
- `app/plugins/registry.py`、`app/adapters/tools/registry.py`：公开记录增加 `execution`、
  `runtime_requirements`、`registration`、`authorization`。
- `app/adapters/qq/factory.py`（新）：`QQAdapterFactory` 注册表；`Mock`/`OneBot11`/规划中的
  `official` 由工厂构建，未知或不可用模式返回明确错误。
- `app/services/adapter_manager.py`、`app/api/accounts.py`、`app/api/system.py`：连接方式与适配器
  构建改为工厂派生，移除硬编码判断与 `isinstance` 耦合。
- `app/api/extensions.py`：新增只读 `GET /api/extensions/capabilities` 契约矩阵；媒体任务取消/
  重试写审计；Provider 启停记录 actor。
- 测试：`tests/test_phase7_extensions.py`（停用取消排队/在途任务、契约-only 不调用 Provider、
  适配器工厂、插件运行时前置要求、能力矩阵真实性、运行中任务取消）。

#### 前端

- `src/api/types.ts`：补齐真实媒体 Provider、能力执行方式、插件运行时要求与扩展契约类型。
- `src/utils/extensions.ts`（新）与 `tests/extensions.test.ts`：执行方式标签与停用取消提示。
- `CapabilitiesView.vue`：展示执行方式、来源、检查时间、下一步与最近错误；停用后如实提示取消的
  任务数量并刷新任务列表。
- `ExtensionsView.vue`：新增「扩展契约」页签；插件展开显示执行方式与八项运行时要求；工具页说明
  启动时固定注册、不存在插件式工具扩展。
- 冒烟：`scripts/smoke_test.py` 增加契约矩阵、工具白名单、`job`/`contract_only`、停用响应字段检查。

## 阶段 6：安全、数据、备份与恢复

### 目标

收口安全与数据治理缺口，全部以自动化测试与真实冒烟验证：

- HTTP 安全头、TrustedHost、严格 CORS、Provider Base URL 的元数据地址拒绝。
- 保留清理提供只读预览与服务端 `CLEANUP` 确认；手动记忆清理真实执行同样确认。
- 账号/群/人格/备份删除要求 `DELETE` 确认，并修正媒体、outbox 与历史消息的实际语义。
- 消息 CSV 导出、备份 Schema 兼容门禁、Electron 权限与 CSP 边界。

**明确未完成**：没有使用真实 QQ 或真实模型；未做打包；**无数据库迁移**；未提交 Git。

### 改动

#### 后端

- `app/core/security_headers.py`（新）：纯 ASGI 安全头；HTML CSP，Swagger 豁免，JSON 不加 CSP。
- `app/core/schema_version.py`（新）：当前/head Alembic 版本与 `schema_compatibility` 判定。
- `app/core/config.py`：`ALLOWED_HOSTS` 与严格 `CORS_ORIGINS` 校验；`app/main.py` 装配
  TrustedHost 与安全头，顺序为 SecurityHeaders → TrustedHost → CORS → RequestContext →
  ConnectorLocalGuard → RemoteAdminGuard。
- `app/services/provider_service.py`：拒绝元数据、链路本地、组播、未指定与共享地址，
  保留回环/私网；不解析 DNS。
- `app/services/retention.py`、`app/api/system.py`：只读 `preview()`、`CLEANUP` 确认、
  `GET /system/retention/preview`；`app/api/messages.py` 记忆清理确认真实执行。
- `app/services/account_service.py`、`group_service.py`、路由与 `runtime.py`：账号删除清理
  媒体引用、群删除取消待发并保留历史消息、人格级联、`DELETE` 确认词与审计。
- `app/services/query_service.py`、`app/api/messages.py`：消息 CSV（BOM、公式转义、50k 上限、
  `no-store`/`nosniff`、审计不含正文/搜索词）。
- `app/services/backup_service.py`、`app/api/backups.py`：恢复预览含 `schema`/`app_version`；
  不兼容在安全备份前返回 409；删除备份 `DELETE` 确认与审计。
- 测试：`test_phase6_security.py`、`test_phase6_data_cleanup.py`、`test_phase6_backup_schema.py`、
  `test_phase6_messages_export.py`；扩展 `test_retention.py`、`test_memory_phase4.py`、
  `test_migrations.py` 等。

#### 前端

- `src/utils/confirmation.ts`（新）与 `tests/confirmation.test.ts`：`DELETE`/`CLEANUP`
  确认词精确匹配；账号、群、人格、备份删除与真实清理使用输入确认词。
- `SettingsView.vue`：清理先预览计数，再输入 `CLEANUP` 执行；备份恢复显示 Schema 状态，
  不兼容时禁用恢复并说明原因。
- `MessagesView.vue`：导出 CSV 按钮，沿用当前筛选并注明含正文/发送者标识；
  outbox 筛选补充 `cancelled`；`api/types.ts`、`tests/client.test.ts` 同步。
- 清理与删除文案改为真实影响，不再声称与实现不符的“不会删除”。

#### 桌面

- `desktop/main.js`：显式 `webSecurity: true`、`allowRunningInsecureContent: false`；
  权限请求/检查仅允许 `clipboard-sanitized-write`，设备权限拒绝，阻止 `will-attach-webview`。
- `desktop/shell/index.html`：CSP（`connect-src 'none'` 等）。
- `desktop/tests/security.test.js`（新）：静态断言上述配置与 CSP。

#### 文档与冒烟

- 更新 `.env.example`（`ALLOWED_HOSTS`、CORS 校验说明）、`README.md`、`docs/API.md`、
  `docs/SECURITY.md`、`docs/DESKTOP.md`、`docs/ROADMAP.md`、
  `docs/implementation/FEATURE_STATUS.md`、本文件。
- `scripts/smoke_test.py`：HTML/JSON 安全头与 CSP、消息 CSV、元数据地址拒绝、备份 Schema
  预览、保留预览只读 / 无确认 400 / `CLEANUP` 成功；末行仍为
  「冒烟测试全部通过。未接触真实 QQ 或真实模型。」

### 实际检查（2026-10-31）

| 命令 | 实际结果 |
| --- | --- |
| `ruff format --check app tests` | 通过：163 files already formatted |
| `ruff check app tests` | 通过：All checks passed |
| `mypy app` | 通过：131 source files，无问题 |
| `pytest -o addopts="" -q` | 通过：418 passed, 1 warning（98.62s；仅 TestClient/httpx 弃用警告） |
| 阶段 6 定向测试（security / data_cleanup / backup_schema / messages_export） | 通过：44 passed |
| `frontend npm run type-check` | 通过：vue-tsc 退出码 0 |
| `frontend npm run test` | 通过：8 个文件、72 项 Vitest |
| `frontend npm run build` | 成功；仅 Vite 大 chunk 警告 |
| `desktop npm test` | 通过：33 项 node:test |
| `desktop npm run smoke` | 通过：全量 Alembic 迁移、`/onboarding`、健康 `healthy`；`DESKTOP_STARTUP_OK` / `DESKTOP_SMOKE_OK`，6 张截图 |
| `./scripts/check.ps1` | 通过：退出码 0，末尾「全部检查通过。」 |
| `scripts/smoke_test.py` | 通过：332 项 `[ok]`，末行「冒烟测试全部通过。未接触真实 QQ 或真实模型。」 |
| Alembic | **无新增迁移**；临时库执行现有 `upgrade head` |

### 限制

- Schema 门禁仅允许恢复到当前代码 head；缺少版本信息时允许但警告。
- SSRF 防护为语法/字面量级，存在 DNS rebinding 残余风险。
- 删除群只取消 `pending`/`pending_approval`；在途 `sending` 交由既有未知/失败路径。
- 账号删除保留仍被其他账号引用的共享媒体；媒体删除失败记录计数，不伪装成功。
- 清理预览是快照，实际运行数量可能因新写入而不同。
- Electron 权限行为只经静态测试与冒烟页面验证，真实系统权限交互需人工验收。

## 阶段 5：接入向导、诊断中心与桌面体验

### 目标

把首次接入、证据真实性、诊断复制与桌面生命周期做成可操作、可验证的闭环：

- 首次启动按后端真实证据走「环境 → 连接器 → QQ 登录 → 连接测试 → 模型 → 选群 →
  观察 → 开启回复」，Mock 与未验证状态不能被显示为真实就绪。
- 新增只读聚合接口与显式 allowlist 诊断；复制的诊断默认排除凭证、QQ 身份、群信息、
  消息正文与路径。
- 桌面首次启动进入接入向导；运行期健康探测与进程状态解耦；托盘不可用时诚实说明关闭
  行为，而不是静默失效。

**明确未完成**：没有使用真实 QQ 或真实模型；安装包、代码签名、自动更新属于阶段 8；
未提交 Git。

### 改动

#### 后端

- `app/services/system_evidence.py`（新）：新鲜度、最近可归属连接测试证据、实时实例事实。
- `app/services/onboarding_service.py`、`app/api/onboarding.py`（新）：八步状态、整体结论、
  下一步、警告与阻塞；GET 只读。
- `app/services/diagnostics_service.py`、`app/api/diagnostics.py`（新）：显式 allowlist
  计数、枚举、布尔值与后端生成的中文摘要；不含日志正文或路径。
- `app/services/privacy_service.py`（新）：设置与诊断共用隐私计数。
- `app/connectors/manager.py`、`app/api/connectors.py`：在线适配器诊断补写
  `connector.diagnose` 审计（只含模式/结果/四个证据布尔值）；GET 不写审计。
- `app/runtime.py`、`app/main.py`：装配并注册两个只读服务；无模型变更、无迁移。

#### 前端

- `views/OnboardingView.vue`、`views/DiagnosticsView.vue`、`components/ReadinessBanner.vue`（新）。
- `utils/onboarding.ts`、`utils/diagnostics.ts`：状态/进度/新鲜度纯函数、硬编码内部路由、
  账号与连接诊断脱敏复制；新增 `tests/onboarding.test.ts` 并扩展 `tests/diagnostics.test.ts`。
- `DashboardView`、`SettingsView`、`AccountsView`、`ConnectionDiagnostics`、`router`、
  `AppLayout`：待办横幅、桌面健康与托盘提示、逐项 loading/成功/回滚、备份下载/恢复预览
  超时、结构化账号状态、复制脱敏摘要、两个新导航入口。
- 空状态统一写明未配置/未实现或下一步；Mock/未验证继续使用警告或信息色。

#### 桌面

- `desktop/lib/backend.js`：12 秒健康探测、1.5 秒超时、单飞；前两次失败保持状态，第三次
  `degraded`，成功恢复；`stop()/restart()` 清理定时器；`getInfo()` 返回嵌套健康副本。
- `desktop/main.js`：首次启动导航到 `/onboarding`；只在状态从非运行转入运行态时导航，
  健康事件不抢页面；托盘可用性 `{available, reason}` 进入快照；托盘新增「打开接入向导」，
  外部后端停止项改为「断开外部后端」；关闭/退出按实际托盘能力执行。
- `desktop/tests/backend.test.js`：健康成功、两次失败、第三次降级、恢复、外部后端保持
  `external`、单飞、定时器清理、嵌套副本，共新增 3 项测试。

#### 文档与冒烟

- 更新 `README.md`、`docs/API.md`、`docs/DESKTOP.md`、`docs/SECURITY.md`、
  `docs/SOFTWARE_DESIGN.md`、`docs/ROADMAP.md`、`docs/implementation/FEATURE_STATUS.md`、
  本文件、`CLAUDE.md`。
- `scripts/smoke_test.py`：新增 onboarding/diagnostics 断言（`ready_mock_only`、只读、
  固定字段、无凭证/标识/消息正文/路径），末行仍为
  「冒烟测试全部通过。未接触真实 QQ 或真实模型。」
- 桌面 `--smoke`：断言首次启动路径 `/onboarding`、健康 `healthy`、快照含托盘字段，
  新增 `onboarding.png` 与 `diagnostics.png`。

### 实际检查（2026-10-31）

| 命令 | 实际结果 |
| --- | --- |
| `ruff format --check app tests` | 通过：157 files already formatted |
| `ruff check app tests` | 通过：All checks passed |
| `mypy app` | 通过：129 source files，无问题 |
| `pytest -q` | 通过：退出码 0；收集 373 项（`addopts=-q` 叠加 `-q` 不打印汇总行） |
| 阶段 5 定向测试（onboarding / diagnostics / api_smoke） | 通过：33 passed |
| `frontend npm run type-check` | 通过：vue-tsc 退出码 0 |
| `frontend npm run test` | 通过：7 个文件、67 项 Vitest |
| `frontend npm run build` | 成功；仅 Vite 大 chunk 警告 |
| `desktop npm test` | 通过：29 项 node:test |
| `desktop npm run smoke` | 通过：首次启动路径 `/onboarding`，健康 `healthy`，托盘字段存在（冒烟未创建托盘，`not_initialized`）；生成 6 张截图 |
| `scripts/smoke_test.py` | 通过：临时数据目录，269 项 `[ok]`（含新的只读向导/诊断断言）；末行「未接触真实 QQ 或真实模型」 |
| `./scripts/check.ps1` | 通过：退出码 0，末行「全部检查通过。」；前端 7 个文件 67 项 Vitest、生产构建成功（7.08s，仅大 chunk 警告）、桌面 29 项 node:test |

### 已知限制与风险

- 接入状态是后端派生视角：实时在线取内存适配器，配置与历史证据取数据库；测试证据可能
  过期，过期不满足步骤并提示重测。它不能替代真实群收发验收。
- 诊断是 allowlist 摘要，不是完整支持包；不提供日志 HTTP 下载。完整日志只保存在本机，
  桌面版可打开日志目录，用户需自行判断后分享。
- 健康监控只探测 `/api/health` 可达性，不自动重启、不杀进程、不改变进程状态；外部后端
  始终不停止。
- 托盘图标不可用时 `closeToTray` 无法生效，界面明确说明；这是资源/系统限制，不伪装成功。
- 向导不会自动运行真实模型测试、自动登录 QQ、自动导入群或自动开启回复。

## 阶段 4：人格、群聊行为与记忆

### 目标

把群聊行为从「能回复」收紧为「可审核、可限频、可拦截」，把人格与记忆从「能保存」
补齐为「可预览、可追溯、可导出、可清理」：

- 五档回复模式，新建与导入群默认 `observe`；手动确认模式的回复只能进入待审队列。
- 每成员时/日限频、群级回复字数与上下文条数、空消息/重复刷屏/敏感输出拦截，
  发送前最终门禁重新检查安静时段与暂停。
- 人格编辑纯投影预览、版本差异、候选影响范围与证据、规则改写拒绝。
- 记忆上下文账号/群隔离、CSV 导出、来源预览、清理与保留期、候选批准敏感度。

**明确未完成**：没有使用真实模型 Key 或真实 QQ 发起任何调用；语义/向量检索仍为
`planned`；测试全部使用临时 SQLite、Mock/脚本化适配器与假 I/O。

### 改动

#### 后端

- `app/core/sensitive.py`（新）：记忆与回复输出共用的凭证/验证码/证件号模式。
- `app/pipeline/output_guard.py`（新）：统一 `sanitize_reply`、空文本与敏感输出检查，
  编排器、命令回复、人工批准与 outbox 发送前共用。
- `app/core/csv.py`（新）：UTF-8 BOM、公式注入防护、行数上限与 CSV 响应 helper。
- `app/pipeline/policy.py`：`manual_confirm` 模式、默认 `observe`、每成员时/日限频、
  空消息与 60 秒重复刷屏启发式、限频纯函数、安静时段辅助函数。
- `app/pipeline/orchestrator.py`：待审入队 `pending_approval`、来源成员与 `reply_kind`、
  群级长度、命令回复审查、敏感输出 `sensitive_output`、空回复 `empty_output`、
  最终发送门禁复用审查。
- `app/pipeline/outbox.py`：条件 UPDATE 批准/拒绝、批准前完整检查、发送前长度/敏感复查、
  每人统计（`sent`/`unknown`，命令回复不计入）。
- `app/services/group_service.py`、`app/models/group.py`、`app/api/groups.py`：
  新群/导入默认观察、四档元数据、每成员限频与群级 `max_reply_chars` /
  `context_message_limit` 校验和有效值来源。
- `app/services/persona_store.py`、`app/pipeline/persona_growth.py`、`app/api/personas.py`：
  纯投影预览、版本详情与差异、候选不提前物化、旧/新快照与影响范围、证据端点、
  规则改写拒绝、`growth_policy` ORM 默认 `review`。
- `app/services/memory_service.py`、`app/services/memory_extraction.py`、
  `app/api/messages.py`：上下文账号/群隔离、导出、来源、清理、候选敏感度。
- `app/services/retention.py`、`app/api/system.py`：`memory_retention_days`
  （`0` = 不自动清理，单独归一化）与摘要 `memories_deleted`。
- 迁移 `f4a7b2c9d801`：群级长度两列、outbox 来源成员/`reply_kind` 与统计索引。

#### 前端

- `GroupsView.vue`：新建默认观察、五档选项、每人限频、群级长度/上下文条数。
- `MessagesView.vue`：`pending_approval` 过滤、「通过并发送 / 编辑后通过 / 拒绝」、
  二次确认与重复批准冲突提示。
- `PersonasView.vue`：保存前预览差异、版本查看与回滚预览、候选影响表与证据对话框。
- `MemoriesView.vue`：导出（默认排除敏感）、来源、清理（dry-run/二次确认）、
  候选批准敏感度。
- `SettingsView.vue`：记忆保留天数与删除计数。
- `utils/format.ts`、`utils/personas.ts`、`api/types.ts`、`api/client.ts`：新状态标签、
  模式文案与 diff/impact 纯函数；新增 `tests/personas.test.ts` 并扩展 `format.test.ts`。

#### 文档与冒烟

- 更新 `README.md`、`docs/API.md`、`docs/SECURITY.md`、`docs/SOFTWARE_DESIGN.md`、
  `docs/ROADMAP.md`、`docs/implementation/FEATURE_STATUS.md`、本文件、`CLAUDE.md`
  （约束 5：新群默认观察、既有群不迁移）。
- `scripts/smoke_test.py`：新群默认观察、四档元数据、人格预览不落库、手动确认批准/
  拒绝/审计/重复批准 409、记忆来源/导出（含敏感开关）/清理 dry-run；末行仍为
  「冒烟测试全部通过。未接触真实 QQ 或真实模型。」

### 实际检查（2026-10-31）

| 命令 | 实际结果 |
| --- | --- |
| `ruff format --check app tests` | 通过：149 files already formatted |
| `ruff check app tests` | 通过：All checks passed |
| `mypy app` | 通过：123 source files，无问题 |
| `pytest -o addopts="" -q` | 通过：362 passed, 1 warning（142.89s）；`-q` 下未打印汇总行，另行以 `-o addopts=""` 核对 |
| 阶段 4 定向测试（pipeline / memory_phase4 / persona_phase4 / migrations / api_smoke） | 通过：73 passed |
| `frontend npm run type-check` | 通过：vue-tsc 退出码 0 |
| `frontend npm run test` | 通过：6 个文件、56 项 Vitest |
| `frontend npm run build` | 成功（16.90s）；仅 Vite 大 chunk 警告 |
| `desktop npm test` | 通过：26 项 node:test |
| `./scripts/check.ps1` | 退出码 0，末行「全部检查通过。」 |
| `scripts/smoke_test.py` | 通过：临时数据目录，243 项 `[ok]`，末行「冒烟测试全部通过。未接触真实 QQ 或真实模型。」 |
| Alembic 临时 SQLite | `upgrade head`（`f4a7b2c9d801`）→ `downgrade d2e6b8a4c910` → `upgrade head`，三轮退出码 0，最终 `f4a7b2c9d801 (head)`；未触碰 `data/` |

### 已知限制与风险

- 手动确认只对 AI 回复生效；管理员命令仍即时执行（但经过输出清洗）。批准后首次发送
  若适配器不可用会留在 `pending`，由 outbox worker 按正常规则处理。
- 每人限频按 outbox 中 `sent` / `unknown` 的 AI 回复统计；待审草稿不占额度；历史记录
  缺少来源成员时不归属到具体成员，成员额度可能暂时偏宽，群级限制仍生效。
- 条件 UPDATE 在单进程内可靠；本项目是单进程本地应用，不支持多实例并发批准。
- 重复刷屏/回环保护是进程内 60 秒启发式，重启清零，不能识别所有第三方机器人。
- 默认观察只影响新建/导入群，既有群不迁移；演示群保留显式 `mention_only` 预设。
- 记忆导出默认排除敏感记忆，显式包含时写审计并提示；CSV 有行数与公式注入防护。
- 人格预览为纯投影不写库；版本/候选差异只展示脱敏摘要与证据预览，不展示思维链。
- 清理与自动保留只删除未固定记忆；语义检索仍为 `planned`。
- **真实 QQ 与真实模型验收仍未执行**。

### 用户验收清单（未执行）

- [ ] 新建群默认「观察」；发送消息只记录、不生成回复。
- [ ] 切换「手动确认」，@ 机器人后在发送队列看到待确认内容；编辑后批准只发送一次，
      重复批准显示冲突；`处理到期消息` 不会自动发送待审内容。
- [ ] 拒绝一条待审回复并确认审计记录；验证群暂停、安静时段、成员静音与限频都会
      阻止批准并保持待审。
- [ ] 配置每人时/日上限，确认超过后不再生成；确认命令回复不占每人额度。
- [ ] 设置群级回复字数/上下文条数，确认超长内容被拦截。
- [ ] 人格编辑先看到 before → after 预览；保存后版本与差异可查看；候选批准前可查看
      影响范围与证据；拒绝后不残留特征。
- [ ] 导出记忆（默认不含敏感），勾选包含敏感后确认提示与审计；查看来源；清理先 dry-run
      再执行；删除的记忆不再出现在后续回复上下文中。
- [ ] 将真实结果回填本文件；完成前保持「真实模型/真实 QQ 未验证」。

## 阶段 3：模型 API 真实调用

### 目标

把模型调用做成可验证、可诊断、可取消、费用透明的真实链路，同时保持 Mock 与真实调用
严格分离：模型列表能力发现、连通性与真实生成分开测试、测试证据持久化、限流与安全重试、
操作取消，以及禁止真实失败回退成 Mock 成功。

**明确未完成**：没有使用真实 API Key 发起任何请求。OpenAI 兼容与 Anthropic 原生适配器
只用 `httpx.MockTransport` 验证请求映射、错误分类、模型列表、重试与超时；真实 Key 验收
需用户在本机完成。

### 改动

#### 后端

- `app/adapters/llm/http_utils.py`：`Retry-After` 解析、上游 request id、统一脱敏错误
  details、连接失败/超时与读写超时的 `retry_safety` 分类。
- `app/adapters/llm/openai_compatible.py` / `anthropic_native.py`：不跟随重定向、每请求
  显式超时、429/5xx 重试元数据、模型列表（OpenAI 两种结构；Anthropic 分页最多 500 条）。
- `app/pipeline/provider_limiter.py`：单进程每 Provider 并发与最小间隔；Mock 跳过。
- `app/pipeline/operations.py`：内存操作注册表与取消；重启即清空。
- `app/pipeline/llm_gateway.py`：测试调用（单次、不回退、写用量与预算）、测试证据持久化、
  安全重试与参数化超时、取消用量、`LLMUsage.request_id`；真实主 Provider 失败禁止回退
  到 Mock（409 `PROVIDER_FALLBACK_MOCK_FORBIDDEN`）。
- `app/services/provider_service.py`：Base URL 归一化与校验、配置完整性、测试证据白名单
  读取与失效、模型列表、清除 Key、操作取消。
- 新增 API：`GET /providers/{id}/models`、`POST /providers/{id}/test-generation`、
  `POST /providers/{id}/operations/{operation_id}/cancel`；`POST /test` 支持可选 body。
- 模型 `LLMProvider.last_test_json/last_generation_json`；迁移 `d2e6b8a4c910`。
- 预算功能键新增 `provider_test`；用量查询返回 `request_id`。

#### 前端

- `src/api/providers.ts` 与 `src/utils/providers.ts`：模型列表、连通性/生成测试、取消、
  清除 Key；多标签证据、错误下一步、费用与模型列表状态文案。
- `ProviderReadinessTags.vue`、`ProviderTestResult.vue`；重写 `ProvidersView.vue`：
  真实调用费用确认、取消本地等待、真实生成对话框、可搜索模型列表、清除 Key 二次确认。
- `tests/providers.test.ts` 覆盖标签组合、Mock/真实分离、费用未知文案、模型列表状态、
  操作 ID 格式与唯一性。

### 实际检查（2026-10-31）

| 命令 | 结果 |
| --- | --- |
| `ruff format --check app tests` / `ruff check app tests` | 通过 |
| `mypy app` | 通过，120 个源文件无问题 |
| `pytest -q` | 338 项全部通过，退出码 0（`-q` 未打印汇总行，按收集数核对） |
| `pytest tests/test_provider_api.py -q` | 7 项通过 |
| `frontend npm run type-check` | 通过 |
| `frontend npm run test` | 5 个文件、50 项通过 |
| `frontend npm run build` | 成功；仅 Vite 大 chunk 警告 |
| `desktop npm test` | 26 项通过 |
| `scripts/check.ps1` | 退出码 0，末行「全部检查通过。」；后端 338 项、前端 50 项、桌面 26 项 |
| `scripts/smoke_test.py` | 全部通过，新增 Mock 模型列表/连通性/生成/证据/清空 Key 检查；末行仍为「冒烟测试全部通过。未接触真实 QQ 或真实模型。」 |
| 临时 SQLite Alembic `upgrade head → downgrade b8d4e2f6a130 → upgrade head` | 三轮均成功，最终 `d2e6b8a4c910 (head)`；未触碰 `data/` |

### 已知限制与风险

- 取消与超时可能已让服务商计费；UI 明确不保证上游停止。浏览器断线不会自动取消服务端任务。
- 读/写超时默认不重试，避免重复计费；可由 `LLM_RETRY_AMBIGUOUS_TIMEOUTS=true` 显式开启。
- 限流仅单进程有效；不实现分布式限流、流式响应、Embedding 或账单对账。
- 模型列表不持久化；服务商兼容性差异大，404/405/501 视为不支持，手动模型 ID 始终保留。
- 测试调用会计入本地用量与预算；费用为本地估算，不是服务商账单。
- 真实→Mock 回退被禁止是行为变更；旧的 Mock 备用配置会收到明确错误。
- 测试证据只保存白名单元数据和截断脱敏预览；不保存 Key、提示词或完整响应。
- **真实 Key 验收未执行**：连通性、真实生成、错误 Key/额度/429/超时/5xx、取消、预算、
  清除 Key 后重启等需用户完成并回填。

### 真实 Key 验收清单（用户执行）

- [ ] 新建真实 OpenAI 兼容或 Anthropic Provider；界面只显示掩码与「配置完整」，尚无测试通过。
- [ ] 获取模型列表（支持时）；不支持时手动填写并看到明确说明。
- [ ] 连通性测试前确认费用提示；得到延迟、Token、费用状态或「无法估算」；显示「连通性通过」。
- [ ] 真实生成测试得到真实文本；显示「真实生成通过」，用量记录出现 `purpose=test`。
- [ ] 错误 Key、额度不足、429、网络/超时、5xx 分别显示明确错误码与下一步，绝不出现 Mock 成功。
- [ ] 取消较慢请求；本地标记取消，用量 `cancelled`，文案不声称上游停止。
- [ ] 费用预算 + 未填单价 → 测试被阻断并解释；填单价后显示本地估算（不是账单）。
- [ ] 清除 Key 并重启：配置变为不完整、证据清空；API/日志/审计/CSV/备份/前端存储无明文 Key。
- [ ] 将脱敏结果回填本文件；完成前保持「真实模型未验证」。

## 阶段 2：连接器管理与自动安装

### 目标

把连接器从「手工下载 + 手工配置」升级为受管流程：抽象 Connector Manager、检测并复用
已有安装、显式确认后下载/校验/解压、启动官方安装器、控制进程、写配置前加密快照与
回滚、版本并存切换、诊断复用在线适配器、身份确认与配置导入。所有第三方动作只能由
本机页面触发，**不静默安装、不静默启动、不自动登录、不自动卸载**。

**明确未完成**：真实 `NapCatInstaller.exe` 未运行、真实 QQ 未登录、真实连接器进程/配置
未在真实 NapCat 上执行、真实入站/出站未验证。

### 改动

#### 后端

- `app/connectors/`：`base.py`（ConnectorProfile）、`napcat.py`（布局/版本/配置合并）、
  `paths.py`（路径边控）、`installer.py`（固定脚本子进程与 NDJSON 事件）、`jobs.py`
  （安装任务、取消、重启中断）、`process.py`（受管进程所有权与启停）、
  `state_engine.py`（纯状态推导）、`manager.py`（组合、快照/回滚、版本切换、诊断复用）。
- `app/api/connectors.py`、`app/api/local_guard.py`：本机限定路由与确认词；独立于
  `ALLOW_REMOTE_ADMIN`。
- `app/models/connector.py` 与 Alembic `b8d4e2f6a130`：安装、任务、加密配置快照；
  `adapter_instances` 新增受管安装关联与身份确认字段。
- `app/core/config.py`、`errors.py`、`runtime.py`、`schemas`：`CONNECTORS_DIR`、错误码、
  运行时装配与请求模型。
- 诊断复用、身份确认与 `/api/groups/import-connector` 的 `confirm_self_user_id` 门控。
- `scripts/install_napcat.py`：`--json-events`、`--dry-run --json`、`--list-releases
  --json`、磁盘空间检查、受管 manifest 字段；默认 CLI 行为保持兼容。

#### 前端

- 新增 `/connectors` 页面、路由与导航；`src/api/connectors.ts`、`src/utils/connectors.ts`。
- 诚实状态标签、证据与下一步；安装进度/取消、安装器确认、进程控制、配置预览/写入/
  快照回滚、版本切换、诊断复用、身份确认、配置导入。
- `AccountsView` 增加身份确认与拉群必填 QQ 号；保留高级手动模式。
- `desktop.ts` 与桌面桥增加连接器目录选择（仅桌面版）。
- `tests/connectors.test.ts`：11 项状态/确认/诚实性测试。

#### 桌面壳

- `settings.js` 新增 `connectorsDir`（空或绝对路径）；`backend-env.js` / `backend.js`
  仅在显式选择时传 `CONNECTORS_DIR`。
- `main.js` / `preload.js` 增加只打开目录对话框的 `desktop:choose-connectors-dir`；
  `openFolder` 增加 `connectors`。
- `settings.test.js`、`backend-env.test.js`、`preload.test.js` 覆盖默认值、校验与白名单。

#### 冒烟与文档

- `scripts/smoke_test.py` 使用临时 `CONNECTORS_DIR`，并断言本机限定、能力诚实、
  空安装列表与安装确认词；不扫描真实连接器。
- 更新 `CONNECTOR.md`、`CONNECTOR_DISTRIBUTION.md`、`FEATURE_STATUS.md`、本文件、
  `README.md`、`API.md`、`SOFTWARE_DESIGN.md`、`SECURITY.md`、`DESKTOP.md`、
  `ROADMAP.md`、`CLAUDE.md`。

### 真实执行的检查与结果（2026-10-31）

| 命令 | 实际结果 |
| --- | --- |
| `ruff format --check app tests scripts/install_napcat.py` | 137 files already formatted |
| `ruff check app tests scripts/install_napcat.py` | All checks passed |
| `mypy app` | Success: no issues found in 117 source files |
| `pytest -q` | 288 项测试全部通过；仅 1 条 Starlette/httpx 弃用警告 |
| 连接器与迁移定向测试 | 86 项通过（`test_connectors_*`、`test_napcat_installer`、`test_migrations`） |
| `npm run type-check` | 通过 |
| `npm run test` | 4 个文件、37 项 Vitest 通过 |
| `npm run build` | 成功；仅有 Element Plus 主 chunk 1,225.80 kB 体积警告 |
| `desktop: npm test` | 26 项通过，0 失败 |
| `./scripts/check.ps1` | 退出码 0，末尾「全部检查通过。」；后端/前端/桌面单测均通过 |
| `scripts/smoke_test.py` | 全部通过，末行「冒烟测试全部通过。未接触真实 QQ 或真实模型。」 |
| Alembic 临时库 | `upgrade head`（`b8d4e2f6a130`）→ `downgrade -1` → `upgrade head` 全部成功 |
| `scripts/install_napcat.py --dry-run --json` | 读取到 `v4.18.42`、994134 字节、digest `46c3…f39c`；未下载 |

### 已知限制

- 真实安装器、真实 NapCat 进程、真实配置写入与 QQ 登录未执行；自动化测试使用临时目录、
  假进程和假 I/O。
- 自动写配置只覆盖文档验证的 `v4.18.42`；其他版本为 `not_verified`/`incompatible`。
- 后端重启后不接管旧进程，不持久化 PID；停止按钮拒绝未跟踪进程，避免误杀。
- 平台不自动更新、不自动卸载，不接管受管根之外的外部安装。
- NapCat 配置中的 Token 由第三方明文保存，平台只能保证自身存储、接口与日志的脱敏。
- 端口探测存在竞态；写配置前二次检查，运行后仍可能被其他程序占用。

### 用户验收清单（未执行）

- [ ] 连接器页查询版本 → `INSTALL` → 下载/校验/解压成功；取消或失败重试不影响旧安装。
- [ ] `RUN INSTALLER` → 人工完成官方安装器 → 重新扫描为「已安装未启动」。
- [ ] `START NAPCAT` → 用户自行登录专用 QQ；页面最多显示「登录未确认（推断）」。
- [ ] 停止进程 → `WRITE CONFIG` → 核对快照、掩码 Token 与生成的实例。
- [ ] 启动 → 连接 → 诊断（确认复用在线适配器，无第二连接冲突）。
- [ ] `CONFIRM IDENTITY` → 导入群 → 仅观察 → 仅 @ 回复；记录时间/群号/消息 ID。
- [ ] 只有真实入站 + 成功出站都出现时，`traffic_verified` 才为真。
- [ ] 测试错误端口/Token、断开进程、只读目录；确认错误可恢复且下一步明确。
- [ ] 升级并存安装与 `SWITCH VERSION`/回滚流程；确认旧版本目录与配置保留。
- [ ] 将真实结果回填本文件；未完成前保持「真实 QQ 未验证」。

---

# 阶段 0 + 阶段 1 历史记录

## 1. 本轮目标

1. 建立阶段 0 审计与能力真实性基线。
2. 把 OneBot 11 从「WS 连上就算在线」升级为「握手 + 身份验证后才在线」。
3. 提供 9 项分项连接诊断，明确区分「连接/身份已验证」与「真实收发未验证」。
4. 修复审计发现的真实缺陷：重连身份查询死锁、身份错误码被覆盖、启动残留在线状态、
   `HTTPS://` 转换错误、`context` 回复模式的虚假描述。
5. 前端诚实展示分项证据、下一步建议与 `connected_unverified`。
6. 提供从 NapCat 官方 Release 下载、校验、安全解压的安装脚本，默认不执行安装器。

**明确未完成**：真实 QQ 登录、真实入站消息、真实出站发送、真实模型 Key 联调。

## 2. 改动文件

### 后端

- `app/core/errors.py`：新增 `ADAPTER_IDENTITY_UNVERIFIED`。
- `app/adapters/qq/base.py`：新增无副作用 `probe_action()` 默认实现。
- `app/adapters/qq/onebot11.py`：身份门控、epoch 丢弃过期结果、重连不阻塞接收循环、
  心跳不再提升状态、发送严格门控、TLS 大小写安全转换、`last_event_at`、`health_check`
  增加身份/来源/观测时间、`probe_action()`。
- `app/schemas/connection.py`：诊断数据结构。
- `app/services/connection_diagnostics.py`：9 项检查编排、失败报告、脱敏与下一步建议。
- `app/services/adapter_manager.py`：结构化测试连接、错误码保留、活动传输缓存、启动时
  重置残留运行时状态。
- `app/services/account_service.py`：保存/未保存连接测试返回诊断；审计记录状态；
  拉群错误区分身份未验证与离线。
- `app/api/groups.py`：`context` 回复模式标记 `planned`。
- `app/api/system.py`：能力中心注明真实 QQ 未验证、身份门控已实现、自动化测试只用
  本机假服务器。
- `tests/onebot_fakes.py`、`tests/test_connection_diagnostics.py`：新增假服务器与 10 项
  诊断/身份测试。
- `tests/test_onebot11.py`：TLS 大小写回归测试与身份门控后的 HTTP 测试状态构造。
- `tests/test_api_smoke.py`：诊断响应、Mock 诚实性、`context` 拒绝测试。
- `tests/test_napcat_installer.py`：23 项安装器安全测试，全部注入假 I/O。

### 前端

- `src/api/types.ts`：`LiveHealth`、`DiagnosticCheck`、`ConnectionDiagnostics`。
- `src/components/ConnectionDiagnostics.vue`：总状态、证据范围、9 项检查表、下一步。
- `src/utils/diagnostics.ts`：摘要、检查状态标签、实例下一步与按钮可用性。
- `src/utils/format.ts`：`connected_unverified`、`identity_verified`、`not_verified`
  标签与醒目（绝不为成功色）。
- `src/views/AccountsView.vue`：诊断对话框、60 秒超时、实例状态来源/错误/下一步、
  严格的连接/断开/拉群按钮、顶部「安装 ≠ 登录 ≠ 身份验证 ≠ 真实收发」。
- `src/views/GroupsView.vue`：删除「上下文参与」暗示可用的文案。
- `tests/diagnostics.test.ts`、`tests/format.test.ts`：新增诚实性断言。

### 脚本、配置与文档

- `scripts/install_napcat.py`：官方 Release、digest、白名单/重定向、流式校验、安全解压、
  许可证与 manifest、拒绝覆盖、TTY + `LAUNCH` 才执行安装器。
- `.gitignore`：排除 `connectors/`。
- `docs/CONNECTOR.md`、`docs/implementation/{AUDIT,FEATURE_STATUS,PROGRESS,CONNECTOR_DISTRIBUTION}.md`。
- 更新 `README.md`、`docs/API.md`、`docs/SOFTWARE_DESIGN.md`、`docs/SECURITY.md`、
  `docs/ROADMAP.md`、`docs/DESKTOP.md`。

## 3. 真实执行的检查与结果

| 命令 | 实际结果 |
| --- | --- |
| `ruff format --check app tests` | `126 files already formatted`，退出码 0 |
| `ruff check app tests` | `All checks passed!` |
| `ruff check ../scripts/install_napcat.py` | `All checks passed!` |
| `mypy app` | `Success: no issues found in 105 source files` |
| `pytest -q` | 227 项测试全部通过，退出码 0；仅有一条 Starlette/httpx 弃用警告 |
| `pytest tests/test_onebot11.py -q` | 12 项通过 |
| `pytest tests/test_connection_diagnostics.py -q` | 10 项通过 |
| `pytest tests/test_napcat_installer.py -q` | 23 项通过 |
| `pytest tests/test_api_smoke.py -q` | 通过（含新增诊断/`context` 测试） |
| `npm run type-check` | 通过 |
| `npm run test` | 3 个文件、26 项测试通过 |
| `npm run build` | 成功；仅有 Element Plus 主 chunk > 500 kB 警告 |
| `desktop: npm test` | 23 项通过，0 失败 |
| `scripts/smoke_test.py` | 全部通过；输出末行「冒烟测试全部通过。未接触真实 QQ 或真实模型。」 |
| `scripts/check.ps1` | 见下节最终记录 |
| `scripts/install_napcat.py --dry-run` | 读取到 `v4.18.42`、资产 994134 字节、digest `46c3…f39c` |
| `scripts/install_napcat.py` | 成功下载 994134 字节、校验 SHA-256 一致、安全解压到 `connectors/napcat/v4.18.42`；许可证与 manifest 已写入；未运行安装器 |

### 全量门禁

`scripts/check.ps1` 实际退出码为 0，末尾输出「全部检查通过。」，包含后端
ruff/mypy/pytest、前端类型检查/Vitest/生产构建、桌面壳 23 项 `node:test`。脚本明确提示
GUI 截图冒烟不在 `check.ps1` 中运行，本轮也未运行 `desktop: npm run smoke`。

## 4. 本轮修复的缺陷

1. WS 握手即 `online` → 改为 `connected_unverified`，身份成功才 `online`。
2. 重连时在接收循环内 `await` 身份动作可能死锁 → 改为独立任务，接收循环继续。
3. `connect_instance()` 用 `None` 覆盖身份错误码 → 保留错误码/消息。
4. 后端重启后数据库残留 `online` → 启动时重置运行时状态。
5. `HTTPS://` 被切成 `wsS://` → 基于 `urlsplit`/`_replace` 转换并补测试。
6. 测试连接只有 `ok + latency` → 9 项结构化证据与未验证范围。
7. 群列表失败导致整次测试失败 → 降为 warning，不推翻身份验证。
8. 前端把测试成功显示为绿色「成功」→ 改为「连接与身份验证通过（真实群收发尚未验证）」。
9. `context` 可选但保存被拒 → 标记 `planned`，前端禁用，文档删除虚假描述。
10. 没有官方安装入口 → 新增受校验、默认不执行的下载脚本。

## 5. 已知限制与风险

- 诊断会临时建立第二条连接；若连接器只允许单连接，需要先断开当前实例。UI 已提示。
- `connected_unverified` 不发送是保守且正确的行为；若连接器不支持 `get_login_info`，
  该连接将无法发送，需修复连接器配置。
- `real_inbound` 只在诊断窗口内实际收到消息时为 `ok`；它仍不等于完整验收。
- 官方 OneKey 包已实际下载、校验并解压到 `connectors/napcat/v4.18.42`；
  `NapCatInstaller.exe` 未运行，因此“安装/登录/服务配置”仍未验证。
- NapCat 许可证为自定义 Limited Redistribution License，本轮未做法律审查。
- 真实 QQ 与真实模型服务的兼容性、风控与账单行为不在本仓库验证范围。

## 6. 当时的下一阶段任务（已由阶段 2–8 完成或转为外部验收）

1. ~~Connector Manager：连接器发现、复用在线适配器执行诊断、进程生命周期与配置写入~~
   —— 已由阶段 2 完成，仍需真实环境验收。
2. ~~升级/回滚与版本兼容检查~~ —— 已由阶段 2 实现并存版本切换与配置回滚；安装包级
   升级/回滚仍需独立干净机演练。
3. 真实 QQ 验收结果回填 —— **仍未完成**，需账号所有者在本机执行。
4. 真实模型 Provider 联调与费用对账 —— **仍未完成**，需真实 Key。
5. ~~诊断复用在线适配器~~ —— 已由阶段 2 实现。

## 7. 真实 QQ 验收清单（用户执行，本仓库未执行）

> 阶段 2 起推荐使用「连接器」受管页；以下保留等价的手工路径。两种方式都必须由你
> 本人完成登录、安装器交互与受控群测试。

- [x] 运行 `scripts/install_napcat.py` 下载、校验并安全解压官方 OneKey 包
      （2026-10-31，`v4.18.42`，digest 一致，目标 `connectors/napcat/v4.18.42`）。
- [ ] 在连接器页输入 `INSTALL` 完成受管下载/校验/解压（或运行上述脚本）。
- [ ] 输入 `RUN INSTALLER`（或人工运行
      `connectors/napcat/v4.18.42/NapCatInstaller.exe`）完成安装，重新扫描。
- [ ] 输入 `START NAPCAT` 启动，并登录专用 QQ 账号（本项目不接触密码/验证码）。
- [ ] 停止进程后输入 `WRITE CONFIG`；核对掩码 Token、快照与关联实例。
- [ ] 启动后连接实例，执行「测试并诊断」，确认复用在线适配器、9 项结果与未验证范围。
- [ ] 输入 `CONFIRM IDENTITY`，确认状态为「在线」；未验证身份时不要开启回复。
- [ ] 导入群列表，保持「仅观察」，在测试群发送 @ 消息，确认被记录但不回复。
- [ ] 切换「仅 @ 回复」，@ 机器人并确认真实消息出现在群内；记录时间、群号、消息 ID。
- [ ] 只有真实入站 + 成功出站同时存在时 `traffic_verified` 才为真。
- [ ] 断开 NapCat 网络/进程，确认重连中且未重复发送；恢复后确认重新身份验证。
- [ ] 将真实结果补充到本文件；未完成前保持「真实 QQ 未验证」。

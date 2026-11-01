# 最终总结报告：阶段 0–8、0.2.1 收口与 0.2.2 连接器可恢复接入

日期：2026-11-01
分支：`v1.3-phase1`
版本：`0.2.2`

> **结论先行：本仓库的本地功能、自动化测试、Mock 端到端、源码进程冒烟、冻结后端与
> 安装版桌面冒烟均已完成并实际通过；0.2.2 额外完成受管 NapCat 安装复用/修复/重试与
> 普通用户一键自动配置。但真实 NapCat 安装器、真实 QQ 收发、真实模型 Key、独立干净机
> NSIS 安装/升级/回滚/卸载、代码签名与 SmartScreen 均未验证。不得宣称生产就绪。**

## 0. 0.2.2 本轮交付摘要

### 修复的问题

1. 同版本受管目录已存在时，安装直接失败，无法重复安装或从失败中恢复。
2. 受管目录残缺或未知目录与用户目录无法区分；错误清理可能触碰用户文件。
3. 截断/损坏 ZIP 的异常分类不稳定，用户看不到可操作错误。
4. 下载没有重试，网络抖动即导致失败并可能留下临时文件。
5. 普通用户仍被要求手填 WebSocket/HTTP 地址、端口与 Token。
6. 接入向导只读，步骤缺少状态、尝试次数、错误码、可重试与下一步动作；“已安装 Shell”
   曾被误判为连接器准备完成。
7. 连接测试失败时，页面缺少稳定错误码与安全错误文案。

### 新增的真实功能（本地实现，均有测试）

- 受管 NapCat 安装：同版本完整目录校验后复用；受管损坏目录隔离到 `.quarantine-*` 后
  原子修复；未知目录拒绝且不触碰；陈旧 staging 清理；有界下载重试；ZIP 完整性、路径、
  重复项、符号链接、大小与压缩比校验；Windows 占用/权限错误映射。
- 安装任务成功事件区分 `installed/reused/repaired`，并明确“安装器尚未运行”。
- `POST /api/onboarding/actions/auto-configure-connector`：对唯一可用受管 Shell 自动
  分配本机端口、生成加密 Token、写配置、创建受管 `onebot11` 账号；必须输入
  `AUTO CONFIG`；与 `/api/connectors/*` 共用本机回环守卫，远程管理不可调用；不启动
  连接器、不登录 QQ、`auto_connect=false`。
- 接入向导每步返回 `status/started_at/completed_at/attempt_count/last_error_code/
  last_error_message/can_retry/next_action`，顶层返回 `counts` 与唯一 `next_action`。
- 前端向导支持“一键自动配置”并如实展示错误与重试；账号页把手动填写地址降级为高级模式；
  连接器页增加自动配置入口。

### 仍然属于 Mock / 未验证

- 真实 NapCat 安装器执行、NapCat 登录、真实 QQ 入站/出站：**未执行**。
- 真实 OpenAI-compatible / Anthropic Key 调用：**未执行**。
- 干净机 NSIS 安装/升级/回滚/卸载、代码签名、自动更新：**未执行/未实现**。
- 所有连接器自动化测试使用临时目录、假进程与假 I/O；Mock 状态不会因自动化测试变成
  “真实 QQ 已验证”。

### 0.2.2 实际检查结果

| 检查 | 实际结果 |
| --- | --- |
| 后端 `ruff format --check app tests` / `ruff check app tests` | 通过 |
| 后端 `mypy app` | Success: no issues found in 134 source files |
| 后端 `pytest -q` | **459 passed**，1 warning（Starlette TestClient/httpx 弃用提示） |
| 前端 `npm run type-check` | 通过 |
| 前端 `npm run test` | 9 files / **76 tests passed** |
| 前端 `npm run build` | 通过；既有主 chunk 体积警告 |
| 桌面 `npm test` | **39 passed / 0 failed** |
| `scripts/smoke_test.py` | 全部通过；末行「冒烟测试全部通过。未接触真实 QQ 或真实模型。」 |
| 安装包与发布冒烟 | 见第 6 节 0.2.2 记录 |

### 需要用户在本机或干净机完成

- 真实 NapCat 安装器交互、NapCat 登录、身份确认。
- 七个验收节点（安装器启动、已安装、进程启动、WS、身份、真实入站、真实出站）分别记录，
  见 [../testing/V0.2.2_REAL_ENV_ACCEPTANCE.md](../testing/V0.2.2_REAL_ENV_ACCEPTANCE.md)。
- 真实模型 Key 的连通性、生成、计费、预算与清空 Key 验收。
- 干净 Windows 安装/升级/回滚/卸载与 SmartScreen 行为。

### 0.2.2 主要变更文件

- `scripts/install_napcat.py`、`backend/app/core/errors.py`
- `backend/app/api/onboarding.py`、`backend/app/api/local_guard.py`、
  `backend/app/services/onboarding_service.py`
- `backend/app/services/system_evidence.py`、`backend/app/services/account_service.py`
- `frontend/src/api/types.ts`、`frontend/src/api/connectors.ts`
- `frontend/src/views/OnboardingView.vue`、`AccountsView.vue`、`ConnectorsView.vue`
- 对应后端/前端测试、版本文件、发布文档与
  `docs/testing/V0.2.2_REAL_ENV_ACCEPTANCE.md`

> 本地已验证：上述代码变更完成后的第二次构建包含本机回环守卫修复，安装包与隔离发布
> 冒烟均基于该构建。

### 剩余风险

- 真实 Windows 文件占用、杀软拦截、NapCat 安装器行为与官方包差异只做了静态/假 I/O 验证。
- 自动配置固定写入 `v4.18.42` 的已知 OneBot 配置结构；其他版本仍不自动写配置。
- 自动配置后仍需用户启动 NapCat 并登录 QQ；任何“已配置”都不等于“可收发”。
- 真实 QQ 风控、NapCat 许可证与合规评估仍需用户/法务完成。

## 1. 已完成且有测试证据的功能

以下功能在本仓库有实现、自动化测试和真实执行的命令输出：

| 领域 | 已完成内容 | 主要证据 |
| --- | --- | --- |
| 工程基座 | FastAPI 模块化单体、统一 `{data,error,request_id}`、统一错误码、请求 ID、结构化日志、健康/就绪检查、Alembic 迁移 | 后端测试；`scripts/smoke_test.py`；干净临时库迁移 |
| 配置与凭证 | `.env` 配置、Fernet 加密、接口掩码、日志脱敏、管理 Token 只存 `sessionStorage` | `tests/test_phase6_security.py`、前端 `tests/client.test.ts` |
| 管理边界 | 默认仅回环；远程管理需显式开启 + Token；管理写操作审计；连接器 API 独立本机守卫 | 后端 API/安全测试 |
| Mock QQ + Mock 模型 | 文本、@、引用、图片/语音演示段、注入事件、完整消息流水线 | `tests/test_pipeline.py`、`tests/test_api_smoke.py`、源码进程冒烟 |
| OneBot 11 | 正向 WS 收事件、HTTP/WS action 发送、Bearer Token、心跳、退避重连、身份门控、9 项诊断 | `tests/test_onebot11.py`、`tests/test_connection_diagnostics.py`、本机假服务器 |
| 受管连接器 | 受管目录扫描、官方下载/校验/解压、安装任务、显式运行安装器、进程所有权、配置快照/回滚、并存版本切换、在线诊断复用 | `tests/test_connectors_*.py`、`tests/test_napcat_installer.py` |
| 群聊治理 | 去重、自身过滤、白名单、全局暂停、安静时段、限速、观察/仅 @/手动确认/自动回复/关键词 | `tests/test_pipeline.py`、`tests/test_group_behavior_phase4.py` |
| 人格治理 | 空白自成长、证据门槛、锁定字段、版本、回滚、审核/自动/暂停、候选提案 | `tests/test_persona_growth.py`、`tests/test_persona_phase4.py` |
| 记忆 | 本群范围长期记忆、手动管理、默认关闭的后台候选提取与人工审核 | `tests/test_memory_phase4.py`、源码进程冒烟 |
| 模型接入 | Mock、OpenAI-compatible、Anthropic 原生 Messages API、模型列表、连通性/真实生成测试、群级主备路由与一次受控回退、进程内限流、取消 | `tests/test_openai_provider.py`、`tests/test_anthropic_provider.py`、`tests/test_llm_gateway_resilience.py`、`tests/test_llm_routing.py` |
| 预算与用量 | 全局/账号/群/Provider/功能五维、调用前阻断、费用不伪造、趋势、告警、CSV 与审计 | `tests/test_budgets.py`、`tests/test_phase6_messages_export.py` |
| 数据治理 | 备份/校验/恢复、Schema 门禁、损坏备份拒绝、保留与清理预览/确认、删除完整性、媒体引用保护、待发取消 | `tests/test_backup_restore.py`、`tests/test_phase6_backup_schema.py`、`tests/test_phase6_data_cleanup.py` |
| 扩展契约 | 五类能力矩阵、任务队列执行与仅契约区分、停用即时止损、QQ 适配器工厂、插件不执行 | `tests/test_phase7_extensions.py` |
| 安全加固 | 安全响应头、TrustedHost、严格 CORS、云元数据地址拒绝、CSP、日志与诊断脱敏 | `tests/test_phase6_security.py`、`tests/test_phase5_diagnostics.py` |
| 前端控制台 | 十四个管理页面、蓝白橙主题、统一 API 客户端、接入向导、诊断中心、能力页 | `frontend/tests/` 9 文件 76 测试；`npm run build` |
| 桌面壳 | 单实例、托盘、窗口/导航/权限限制、最小 IPC、后端进程、健康探测、首次向导、外部后端只断开、安装版运行 | `desktop/tests/` 39 测试；`npm run smoke` 6 张截图 |
| Windows 发行 | PyInstaller 冻结后端与 NapCat 安装器、Vite 前端、Electron NSIS x64、`BUILD_INFO.json`、隔离发布冒烟 | `scripts/build_release.py`、`scripts/release_smoke.py`、`desktop/tests/packaging.test.js` |

### 0.2.1 最终审计实际执行结果

| 检查 | 实际结果 |
| --- | --- |
| 后端 `ruff format --check app tests` | 168 files already formatted |
| 后端 `ruff check app tests` | All checks passed |
| 后端 `mypy app` | Success: no issues found in 134 source files |
| 后端 `pytest` | 442 passed，1 warning（Starlette TestClient/httpx 弃用提示），103.08s |
| 前端 `npm run type-check` | 通过 |
| 前端 `npm run test` | 9 files / 76 tests passed，2.05s |
| 前端 `npm run build` | 通过，8.70s；主 chunk 1,226.56 kB（gzip 395.29 kB），仅体积警告 |
| 桌面 `npm test` | 39 passed，0 failed，9.43s |
| 桌面 `npm run smoke` | `DESKTOP_SMOKE_OK`，版本 0.2.1，6 张截图 |
| `scripts/check.ps1` | 全部检查通过；末尾明确提示未运行 GUI 截图冒烟 |
| `scripts/smoke_test.py` | 冒烟测试全部通过；未接触真实 QQ 或真实模型 |
| `scripts/build_release.py` | 见第 6 节 0.2.1 发布记录（提交 B 回填） |
| `scripts/release_smoke.py` | 见第 6 节 0.2.1 发布记录（提交 B 回填） |

0.2.1 新增/强化的测试：

- 损坏与截断备份：返回 `BACKUP_INVALID`，不触碰当前库、不写恢复审计、不产生安全备份或
  `*.restore-*` 暂存文件。
- OneBot 空串/空白文本：在任何 HTTP 请求前返回 `SEND_FAILED`，不更新 `last_sent_at`。
- NSIS 静态配置：x64、`oneClick=false`、`perMachine=false`、可改安装目录、卸载默认保留
  用户数据；**该测试不证明真实卸载行为**。
- 版本单一来源：`Settings.app_version` 与 `app.__version__` 一致。
- 已移除的 `/api/demo/reset-hint` 不再返回 501/成功。

## 2. 仅 Mock、单元或本地假服务验证的功能

这些功能有真实代码路径，但没有接触真实外部服务：

- **OneBot 11**：只连接本机假 WebSocket/HTTP 服务器；没有真实 NapCat 登录、真实群事件、
  真实消息发送。
- **受管 NapCat 流程**：只使用临时目录、假进程、假安装器与假 I/O；没有执行真实
  `NapCatInstaller.exe`，没有自动登录，没有真实配置写入。
- **OpenAI-compatible / Anthropic**：只使用 `httpx.MockTransport` 验证请求映射、错误
  分类与重试；没有真实 API Key 调用、账单或供应商差异验证。
- **媒体能力**：视觉/OCR/ASR/TTS/Embedding/视频只有确定性 Mock Provider 与接口契约；
  没有真实识别或转写。
- **桌面与安装版**：`--smoke` 与 `release_smoke.py` 使用临时 `userData`、临时数据目录、
  临时密钥和系统级 `PATH`；证明安装版不依赖仓库 `.venv`/Node，但不等于干净机安装验收。
- **源进程冒烟**：真实 uvicorn + 临时 SQLite，但连接器与模型均为 Mock。

## 3. 需要真实 QQ 账号或 API Key 才能验证的功能

| 项目 | 需要的条件 | 当前证据 | 状态 |
| --- | --- | --- | --- |
| 真实 NapCat 安装器交互 | 用户本机运行官方安装器 | 下载/校验/解压脚本与假 I/O 测试 | 未执行 |
| 真实 NapCat 登录 | 专用 QQ 账号，用户本人登录 | 不在代码中接触密码/验证码 | 未执行 |
| 真实 QQ 入站 | 受控群 + 真实事件 | 诊断项 `real_inbound` | 未验证 |
| 真实 QQ 出站 | 受控群 + 真实发送 | outbox 门控、诊断 `real_outbound` | 未验证 |
| `traffic_verified` | 身份确认后的非 Mock 持久化入站 + 成功出站 | 仅代码门控与假服务器测试 | 未触发 |
| OpenAI 兼容真实调用 | Base URL、模型、真实 Key | MockTransport 测试 | 未联调 |
| Anthropic 真实调用 | 真实 Key | MockTransport 测试 | 未联调 |
| 真实计费与预算对账 | 真实用量与单价 | 本地账本、费用完整性测试 | 未对账 |
| 真实暂停/断线/重连/发送失败恢复 | 真实连接器 | 假服务器与进程测试 | 未演练 |

验收步骤见
[V0.2.2_REAL_ENV_ACCEPTANCE.md](../testing/V0.2.2_REAL_ENV_ACCEPTANCE.md)、
[ROADMAP.md](../ROADMAP.md) 的“人工验收（需用户环境）”与
[CONNECTOR.md](../CONNECTOR.md)。真实安装器、QQ 与模型操作必须由账号所有者本人完成。

## 4. 未完成或受平台、许可证、环境限制的功能

- **真实 QQ 平台兼容与风控**：非官方 NapCat 的行为、协议差异、限流与封号风险不由本仓库
  保证；不实现验证码绕过、设备指纹伪装、反检测、批量养号、自动加群/加好友或广告群发。
- **代码签名与 SmartScreen**：安装包未签名；没有证书、时间戳或签名验证流程。
- **自动更新/自动回滚**：明确不支持；更新需手动运行新安装包。
- **独立干净机 NSIS 验收**：安装、覆盖升级、回滚、卸载均未在干净 Windows 机器执行；
  卸载默认保留数据，彻底删除需手工清理。
- **官方 QQ 机器人**：规划中，接口占位不可用。
- **第三方插件运行时**：只登记清单与权限，不执行第三方代码；未来运行时需沙箱、权限、
  用户确认、签名、超时、资源限制、审计与即时停用全部实现。
- **真实多模态与语义检索**：未配置；界面明确标记，不声称 AI 看到图片或听到语音。
- **上下文参与、定时话题、自动成本/延迟路由**：规划中，创建/保存会被拒绝。
- **NapCat 许可证法律审查与隐私/合规评估**：需用户/法务完成；本仓库未做法律结论。
- **OS 级 Electron 权限弹窗、下载行为**：只有静态配置测试，未做真实系统行为验收。
- **前端代码分割**：主 chunk 约 1.2 MB，仅有构建体积警告，未优化。

## 5. 运行、安装、数据目录、日志与故障排查

### 源码运行

```powershell
# 首次安装
cd backend
python -m venv .venv
.venv\Scripts\python.exe -m pip install -e ".[dev]"
cd ..\frontend
npm install
cd ..\desktop
npm install
cd ..
backend\.venv\Scripts\python.exe scripts\gen_keys.py --write
start-desktop.cmd
```

开发模式：`scripts\dev.ps1`；控制台 `http://127.0.0.1:5173`，API 文档
`http://127.0.0.1:8000/api/docs`。生产预览由 FastAPI 托管 `frontend/dist`：
`http://127.0.0.1:8000`。

### 安装版

1. 校验 `release/AI-Group-Friend-Setup-0.2.2-x64.exe` 的 SHA-256 与
   `release/BUILD_INFO.json` 一致后再运行。
2. NSIS 为 per-user 安装，可选择安装目录；安装包未签名，SmartScreen 可能提示未知发布者。
3. 首次启动进入 `/onboarding`；安装版在 `userData/.env` 生成独立随机密钥，不读取仓库
   `.env`，不覆盖已有文件。
4. 默认数据目录为 `userData/data`，受管连接器为 `userData/connectors/napcat`；可在桌面
   设置中修改，修改后需重启后端。
5. 升级前完整复制 `userData`；没有自动降级，旧程序可能无法读取新 Schema。
6. 卸载默认保留数据；彻底删除需手动清理 `userData`（含数据库、日志、备份、连接器与
   本地密钥）。

### 日志与排查

- 桌面日志：`userData/logs/desktop.log`（安装版）或桌面设置所示目录。
- 后端日志：应用自身脱敏过滤器处理；不要粘贴含 Token、Key、QQ 标识或群消息的原始日志。
- 诊断中心只展示后端派生的 allowlist 信息，不提供日志 HTTP 接口；复制诊断默认排除凭证、
  QQ 标识、群信息、消息正文与路径。
- 常见问题：
  - 端口被占用：桌面版会使用其他本机端口；外部已有本项目健康后端时直接连接，不重复启动。
  - 后端未就绪：查看桌面日志与 `/api/health`；健康探测连续失败只会标记降级，不会杀进程。
  - 无法连接真实 QQ：先完成安装器、登录、身份确认与诊断；`connected_unverified` 不等于
    可回复。
  - 模型测试失败：区分认证、网络、模型、额度、超时；真实失败不会回退成 Mock 成功。
  - 备份恢复被拒：检查 Schema 版本、校验和与数据库完整性；损坏备份不会触碰当前库。

## 6. 0.2.2 与 0.2.1 发布记录

### 0.2.2 本机构建（2026-11-01）

| 项目 | 结果 |
| --- | --- |
| `scripts/build_release.py --allow-dirty` | 退出码 0；版本 0.2.2；基础提交 `da5f5dd`；**`git_dirty=true`**（记录 status/diff 指纹）；四处版本一致；Electron 45.0.0 |
| 安装包 | `release/AI-Group-Friend-Setup-0.2.2-x64.exe`，155,842,669 bytes，SHA-256 `35f7fb67ae00b116b105cd1ab04850446f60cb2b67d291fc21bd80237b6f3546`；未签名 |
| `win-unpacked/AI 群友.exe` | 249,797,632 bytes，SHA-256 `e17c2e4185c16341cb63336c180e6dd5c08194be8eb375efb6386eabe8842e20` |
| `BUILD_INFO.json` | `version=0.2.2`、`git_dirty=true`、`signed=false`、`auto_update=false`、`real_qq_verified=false`、`real_model_verified=false`、`installer_executed_on_clean_machine=false` |
| `scripts/release_smoke.py` | 退出码 0；布局/哈希通过；冻结后端 `packaged`、版本 0.2.2、Alembic `f4a7b2c9d801`、内置前端、隔离数据目录；安装版 Electron 0.2.2、6 张截图、13.7s；`status=ok`、`real_qq_verified=false`、`real_model_verified=false` |
| 干净机 NSIS 安装/升级/回滚/卸载 | **未执行** |
| 真实 QQ / 真实模型 | **未执行** |

> 该安装包构建于未提交工作树，只用于本机验证 0.2.2 代码；**不是已提交的正式发行
> 构建**。正式分发前必须在干净提交上重新构建并复核 SHA-256。

### 0.2.1 发布记录（历史）

以下结果来自提交 A `1aa8e9f` 后的实际构建与发布冒烟；`release/` 不进入 Git。

| 项目 | 结果 |
| --- | --- |
| `scripts/build_release.py` | 退出码 0；版本 0.2.1；`git_dirty=false`；四处版本一致；Electron 45.0.0 |
| 安装包 | `AI-Group-Friend-Setup-0.2.1-x64.exe`，155,824,181 bytes，SHA-256 `bf3e95ba5520a0b97d14e766be27869a7c8033ad6e23c3495450b9d664af70be`；未签名 |
| `win-unpacked/AI 群友.exe` | 249,797,632 bytes，SHA-256 `e92bee0e0ee98e6ed490636a02ba949b8fc5a1311cfa1392bee1be3f66eb3ae0` |
| `BUILD_INFO.json` | `version=0.2.1`、`git_commit=1aa8e9f…`、`git_branch=v1.3-phase1`、`git_dirty=false`、`real_qq_verified=false`、`real_model_verified=false`、`installer_executed_on_clean_machine=false` |
| `scripts/release_smoke.py` | 退出码 0；布局/哈希通过；冻结后端 `runtime_mode=packaged`、Alembic `f4a7b2c9d801`、内置前端、隔离数据目录；安装版 Electron 版本 0.2.1、6 张截图、12.2s |
| `RELEASE_SMOKE.json` | `status=ok`、`real_qq_verified=false`、`real_model_verified=false`、`real_env_file_used=false`、`real_connectors_dir_used=false` |
| 干净机 NSIS 安装/升级/回滚/卸载 | **未执行** |
| 真实 QQ / 真实模型 | **未执行** |

构建机：Windows 11 x64，Python 3.14.5，Node v24.19.0，Electron 45.0.0。安装包构建于
`2026-11-01T10:38:53+0800`。构建与冒烟只验证本机隔离环境，不等于干净机安装或真实平台
验收。

## 7. 明确不宣称生产就绪

本版本是**本地优先的可运行 MVP/预发布版本**，不是生产就绪产品：

- 没有真实 QQ 端到端证据，没有真实模型 Key 证据，没有干净机安装证据。
- 安装包未签名，无自动更新，无远程管理默认开启，无任意 Shell/文件/URL 能力。
- 所有“真实环境未验证”的能力在 UI、API 能力矩阵与本文中保持未验证状态。
- 在完成第 3 节全部真实环境验收、第 4 节受限项评估与代码签名之前，不应面向不受控用户
  或生产群部署。

### 外部验收清单

- [ ] 干净 Windows 10/11 x64 校验哈希并执行 NSIS 安装
- [ ] 覆盖升级、旧 `userData` 回滚、卸载与数据保留/彻底删除演练
- [ ] 配置代码签名并验证 SmartScreen
- [ ] 节点 1：官方安装器实际启动
- [ ] 节点 2：NapCat 实际安装
- [ ] 节点 3：受管进程实际启动
- [ ] 节点 4：WebSocket 实际连接
- [ ] 节点 5：QQ 身份实际确认
- [ ] 节点 6：真实群消息实际入站
- [ ] 节点 7：真实群消息实际出站，并核对 `traffic_verified`
- [ ] 真实暂停、断线、重连、发送失败与恢复演练
- [ ] 真实 OpenAI-compatible Key 与 Anthropic Key 的连通性、生成、预算与错误场景
- [ ] NapCat 许可证法律审查与隐私/合规评估

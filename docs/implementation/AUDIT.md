# 阶段 0 审计：实现现状、安全边界与已验证范围

> **历史快照**：本文记录 2026-10-31 阶段 0 审计时的状态，其中“未完成/待办”多数已被
> 阶段 1–8 与 0.2.1 最终审计取代。当前状态以 [PROGRESS.md](PROGRESS.md)、
> [FEATURE_STATUS.md](FEATURE_STATUS.md)、[TEST_MATRIX.md](TEST_MATRIX.md) 与
> [FINAL_REPORT.md](FINAL_REPORT.md) 为准。

审计日期：2026-10-31
基线提交：`993012e`（V1.3 Phase 1 多模态基础、预算维度、数据保留与人格成长）
审计时工作区：包含本轮阶段 1 改动，尚未提交

## 1. 审计范围

对照 `Claude代码与AI群友笔记/AI群友项目指导文件_ClaudeCode分阶段实施版(4).md`
的阶段 0 与阶段 1 要求，检查：

- 连接器接入、连接状态语义、连接失败可诊断性；
- 发送队列在身份未确认时的行为；
- 前端对连接状态与测试结果的真实呈现；
- 第三方连接器的来源、下载、校验与许可证边界；
- 现有文档中是否存在把 Mock、骨架或规划能力写成真实能力的描述；
- 测试、格式、类型检查与构建是否真实通过。

本轮**不**审计真实 QQ 平台行为、真实模型服务账单、NapCat 安装器内部行为或操作系统
级安全。

## 2. 实际运行环境

- Windows 11 Home China 10.0.26200
- Git Bash（脚本兼容 PowerShell）
- Python 3.14.5（仓库 `.venv`）
- Node.js 24.19 / npm 12.0.2
- 数据库：临时 SQLite（测试）与本地 `data/`（运行时）
- 网络：2026-10-31 能访问 GitHub Release API 与资产下载地址，用于脚本查询、下载与校验

## 3. 实际运行的命令与结果

以下均为本轮实际执行结果，不是从 README 复制的结论。

| 命令 | 结果 |
| --- | --- |
| `ruff format --check app tests` | 通过；首次发现 `app/schemas/connection.py` 未格式化，格式化后 126 个文件全部通过 |
| `ruff check app tests` | 通过（All checks passed） |
| `ruff check ../scripts/install_napcat.py` | 通过 |
| `mypy app` | 通过：Success: no issues found in 105 source files |
| `pytest -q` | 通过；共收集 227 项测试，退出码 0 |
| `npm run type-check` | 通过，无输出错误 |
| `npm run test` | 通过：3 个测试文件、26 项测试 |
| `npm run build` | 通过；Vite 构建成功，仅有 Element Plus 主 chunk 超过 500 kB 的警告 |
| `desktop && npm test` | 通过：23 项测试，0 失败 |
| `scripts/install_napcat.py --dry-run` | 成功读取官方 Release；观察到的版本与 digest 见下 |
| `scripts/install_napcat.py` | 通过：下载 994134 字节、SHA-256 与 GitHub digest 一致、安全解压到 `connectors/napcat/v4.18.42`；未运行安装器 |
| `scripts/check.ps1` | 通过，退出码 0，末尾输出「全部检查通过。」 |
| `scripts/smoke_test.py` | 通过，末尾输出「冒烟测试全部通过。未接触真实 QQ 或真实模型。」 |
| `desktop: npm run smoke` | 未运行（GUI 截图冒烟不在本轮范围） |

`--dry-run` 实际输出摘要：

- 版本：`v4.18.42`
- 资产：`NapCat.Shell.Windows.OneKey.zip`，994134 字节
- GitHub digest：`sha256:46c3ec155aa61f12e89bbf97013a21243d00b0019b5565992a88852d7627f39c`

随后执行了脚本默认流程：下载、校验 SHA-256 并安全解压到
`connectors/napcat/v4.18.42/`，许可证与 manifest 已保存。**没有运行
`NapCatInstaller.exe`，没有登录 QQ，没有启动 WebSocket/HTTP API，也没有发送消息。**

## 4. 架构现状

- 后端为 FastAPI 模块化单体，`AppRuntime` 在 lifespan 中按序装配数据库、加密、
  事件总线、策略/流水线、服务、适配器与 outbox worker。
- 管理 API 默认仅回环；远程管理需显式开关与管理 Token；所有管理写操作写审计。
- 消息流水线先执行硬规则与预算，再调用模型；回复通过 outbox 异步派发。
- OneBot 11 使用正向 WebSocket 接收事件，HTTP action 优先，WS action 回退。
- 前端 Vue 3 管理台统一通过 `api/client.ts` 解包响应；管理 Token 只进
  `sessionStorage`。
- Electron 桌面壳只管理本机后端进程，不执行连接器，不绕过安全边界。

## 5. 本轮发现的问题

1. **连接状态过于粗糙**：WS 握手成功即标记 `online`；`get_login_info` 失败只写日志。
   这会把「传输层已连接」误当成「QQ 身份已验证」，且自身消息过滤依赖该身份。
2. **重连路径可能死锁**：重连在 `_receive_loop()` 内直接 `await` 身份查询，身份查询
   若走同一 WS 动作通道，会与同一协程的响应读取互相等待。
3. **身份错误被覆盖**：`connect_instance()` 末尾以 `None, None` 持久化错误码，导致
   身份失败原因丢失。
4. **测试连接证据不足**：只返回 `ok + latency`；群列表读取失败会使整次测试抛错；
   前端丢弃登录信息与群数量，无法区分「握手成功」与「真实可用」。
5. **旧运行时状态残留**：后端重启后数据库中的 `online` 等状态残留，但进程内没有
   适配器，界面会误报在线。
6. **TLS 地址大小写缺陷**：`HTTPS://` 被切片转换为 `wsS://`；小写路径正常。
7. **回复模式虚假描述**：`context` 在 API/UI 中可选，保存时却被拒绝；README 将其写成
   「上下文（骨架）✅」。
8. **缺少可审计的安装入口**：没有从官方来源下载、校验、解压连接器的脚本，也没有明确
   的许可证与不捆绑决策。
9. **缺少阶段 0 文档**：没有审计、能力真实性、进度与连接器分发记录。

以上问题均在本轮阶段 1 修复或补齐，详见 `PROGRESS.md`。

## 6. 安全边界复核

已确认仍成立：

- 不接触 QQ 密码；登录由用户自行安装的连接器完成。
- 不实现验证码绕过、设备指纹伪装、反检测、批量养号、自动加群/加好友、广告群发或
  限流规避。
- Token 与 API Key 加密保存，接口只返回掩码；日志脱敏。
- 管理 API 默认只监听回环；远程管理必须显式开启并携带管理 Token。
- 群白名单默认空；默认仅 @ 回复；全局紧急暂停优先。
- 群消息、OCR、转写、网页内容与工具结果均为不可信数据，不提升为系统/管理员指令。
- 不存在任意 Shell、文件读写、任意 URL 请求或 SSRF 工具；第三方插件代码不执行。
- 人格成长受证据、锁定字段、版本与回滚治理；不保存思维链。
- 前端管理 Token 只使用 `sessionStorage`；密钥只显示掩码。
- 本轮新增安装脚本不静默执行第三方程序，`--launch` 需要 TTY 与 `LAUNCH` 确认。

## 7. 未验证与未运行范围

- **真实 QQ 登录、真实入站消息、真实出站发送：未验证。** 全部 OneBot 测试使用本机
  进程内假服务器。
- **真实模型服务：未验证。** OpenAI 兼容与 Anthropic 适配器仅用 MockTransport 验证
  请求映射；没有真实 API Key 联调。
- **NapCat OneKey 包已下载、校验并解压到 `connectors/napcat/v4.18.42/`，但
  `NapCatInstaller.exe` 未运行，安装器内部行为未审计。** 未登录 QQ、未启动任何
  NapCat 服务。
- **真实图片/语音/OCR/ASR/TTS/Embedding：未配置、未验证。**
- **Electron GUI 截图冒烟：本轮未运行**（仅运行 `desktop` 的 `node:test`）。
- 真实 QQ 平台风控、账号状态、NapCat 内部行为均超出本仓库可验证范围。

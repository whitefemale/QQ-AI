# 范围、验收与路线图

更新日期：2026-11-01

## 1. 产品定位

本地优先的「AI 群友」管理平台：用户用自己拥有并授权管理的专用 QQ 账号，通过自建 OneBot 11 连接器接入，在明确白名单群内按保守策略聊天。人格成长必须可治理，所有能力状态必须诚实。

## 2. P0 已交付范围

### 工程基座

- [x] FastAPI 模块化单体、Pydantic v2 配置、统一响应包与稳定错误码
- [x] SQLite + SQLAlchemy 2 async + Alembic 初始迁移与增量迁移
- [x] Fernet 凭证加密、掩码返回、日志脱敏
- [x] 请求 ID、结构化日志、健康检查与就绪检查
- [x] pytest / ruff / mypy / vue-tsc / Vitest / 构建脚本
- [x] `.env.example`、`.gitignore`、开发/检查/备份/密钥/冒烟脚本
- [x] Electron 源码桌面版本机一键启动：双击 `start-desktop.cmd`、幂等首次向导、后端进程管理、托盘、桌面设置与维护入口
- [x] Windows x64 独立安装包：PyInstaller 冻结后端与 NapCat 安装器、内置前端、Electron NSIS；安装版无需 Python/Node。未签名、无自动更新（阶段 8）
- [x] 蓝白橙全站主题：设计令牌、Element Plus 主题覆盖、深蓝侧栏与橙色强调，保留成功/危险语义色

### 连接器与 Provider

- [x] `QQAdapter` 抽象与能力声明
- [x] Mock QQ 连接器：文本、@、引用、图片/语音演示段、注入事件、已发送列表
- [x] OneBot 11：正向 WebSocket 收事件、HTTP/WS action 发送、Bearer Token、心跳、指数退避重连、分段映射
- [x] OneBot 地址本机/私网限制与显式公网风险开关
- [x] 受管连接器（NapCat profile）：只扫描 `CONNECTORS_DIR`、布局/版本兼容检测、外部安装只读
- [x] 连接器安装任务：官方下载/SHA-256/安全解压、进度、取消、中断恢复、单任务互斥
- [x] 显式运行官方安装器、受管进程启停与所有权保护；后端重启后不接管、不杀旧 PID
- [x] 配置预览、端口/Token 生成、加密快照、原子写入、失败恢复与 `RESTORE CONFIG` 回滚
- [x] 并存版本安装与 `SWITCH VERSION` 活动切换；不自动更新、不自动卸载
- [x] 诊断优先复用在线适配器；身份确认与拉群门控；真实收发证据状态 `traffic_verified`
- [x] `/api/connectors/*` 本机守卫独立于远程管理；所有第三方动作需确认词与审计
- [x] 前端「连接器」页、配置导入兜底、桌面版目录选择与 `CONNECTORS_DIR` 传递
- [x] `LLMProvider` 抽象、Mock 模型、OpenAI-compatible 模型
- [x] Anthropic 原生 Messages API 适配器：system/消息合并、工具 `input_schema`、温度限制、错误分类、官方默认 Base URL
- [x] Provider 测试连接与认证/网络/模型/额度/超时分类
- [x] 群级主/备用模型绑定；仅在 Provider 调用错误时受控回退一次，不绕过预算、暂停、配置与凭证限制
- [x] 删除被群绑定的 Provider 返回 409，避免悬空绑定
- [x] ProviderRegistry 与能力状态（available / configured / mock_only / unconfigured / planned）
- [x] 媒体任务表与状态机（排队/运行/成功/失败/取消、幂等、超时、有限重试）
- [x] 插件 Manifest 校验、登记、健康状态、权限批准；**不执行第三方代码**；健康检查只保存声明，不发起第三方检查或网络请求
- [x] 官方 QQ 机器人仅保留 planned 占位

### 消息流水线

- [x] 去重（数据库唯一约束）、自身消息过滤、账号/群白名单
- [x] 全局紧急暂停、群静默时段、成员静音、群级冷却/小时/每日/连续回复限制、每成员时/日回复上限
- [x] 命令解析、触发决策（observe / mention_only / manual_confirm / always / keyword；context 与 scheduled 仍为规划中；新群默认 observe）
- [x] 空消息、重复刷屏启发式、发送前敏感内容/长度检查与最终安静时段门禁
- [x] 上下文按会话隔离；媒体能力缺失时的诚实降级提示
- [x] 分层提示词与不可信内容包裹；群规和人格绑定
- [x] LLM 超时/分类错误/有限重试；工具轮次上限
- [x] 回复长度审查（群级可覆盖）、发送队列幂等、未知状态不重发、连续失败自动暂停
- [x] 手动确认发送队列：`pending_approval`、批准前完整检查、原子批准/拒绝、重复批准 409、`dispatch-due` 不发送待审消息
- [x] 预算硬上限阻断；用量与成本记录
- [x] Provider / 群维度真实用量聚合；群级费用上限；费用完整性状态；未配置单价的费用预算阻断（`cost_unavailable`）
- [x] 按配置时区的小时/自然日真实用量趋势；未知成本保持 `null`
- [x] 预算告警事件：warning / exceeded、按策略与周期去重、写审计、发布 SSE；告警历史查询
- [x] 真实用量 CSV 导出：仅调用元数据、公式注入防护、不包含正文/提示词/凭证、导出写审计
- [x] SSE 事件总线、最近事件回放与断线心跳
- [x] 消息日志、outbox 日志、审计、用量查询
- [x] 群级可选后台增量记忆候选提取：默认关闭、水位线去重、仅生成待审核候选、全局暂停时停止
- [x] 记忆短期上下文的账号/群隔离、CSV 导出（默认排除敏感）、来源预览、手动清理（含 dry-run）、记忆保留天数与批准敏感度

### 工具

- [x] 工具接口、权限引擎、风险等级、参数 Schema 校验、超时与调用次数限制
- [x] 内置计算器与日期时间工具
- [x] 管理端安全测试；群默认禁用工具
- [x] 不存在任意 Shell / 文件读写 / 任意 URL 请求工具

### 人格

- [x] `authored` / `template` / `emergent` 三种模式
- [x] 空白模式初始无自我描述、无预置特征
- [x] 特征候选、证据门槛（≥2 会话、≥3 证据，可配置）、置信度
- [x] `auto` / `review` / `paused` 成长策略；锁定字段
- [x] 版本快照、变更事件、回滚
- [x] 跨群学习默认关闭；删除证据与派生特征清理
- [x] 空白人格治理校验：单条消息不突变、锁定字段不可覆盖、不保存思维链
- [x] 编辑前纯投影预览、版本详情差异、候选 old/new/impact 与绑定群证据预览、规则改写拒绝
- [x] 人格测试对话（dry-run）

### 管理控制台

- [x] 仪表盘：连接/模型/运行状态、用量、SSE 事件、全局暂停、Mock 演示初始化
- [x] QQ 接入、模型 API、能力中心、人格工作台、群聊管理
- [x] 消息与用量、模拟测试、扩展与预算、系统设置
- [x] 加载/空/错误/保存状态；破坏性操作二次确认；密钥掩码
- [x] 管理 Token 仅存 `sessionStorage`
- [x] 能力状态诚实展示；Mock / 规划中不被当作真实能力
- [x] 系统设置中的桌面版卡片：后端状态、数据目录、日志、自动启动/托盘开关、重启与白名单目录入口；浏览器模式诚实显示不可用

### 备份与治理

- [x] SQLite 一致性备份、清单、SHA-256、完整性校验
- [x] 恢复预览、必须暂停、`RESTORE` 确认、自动安全备份
- [x] 恢复时断开所有连接器并保持全局暂停
- [x] 数据库备份排除媒体、日志与加密密钥
- [x] 管理动作审计、设置、数据保留配置、隐私总览
- [x] 本机优先管理边界与远程管理 Token

### V1.3 Phase 1 增量（已交付）

- [x] 多模态契约：`MediaProcessor.inspect`、`RerankerProvider.rerank`、`VideoProcessor.describe_video` 与确定性 Mock；**真实 Provider 未配置，未接入业务回复管线**
- [x] 媒体 Provider 启停/健康状态持久化；媒体任务后台 worker；流水线只入队，不阻塞 QQ 事件
- [x] 媒体用量聚合（`/api/media/usage`）：请求/成功/失败/Mock 数、平均延迟、费用完整性；不含媒体内容或转写
- [x] 预算作用域扩展为 global / account / group / provider / feature；LLM 与媒体任务调用前检查；`reply → chat` 归一化
- [x] 数据保留与清理服务：自动清理默认关闭、可手动执行、可显式开启；消息/媒体/转写/媒体任务/轮转日志/人格证据/记忆来源级联清理；审计、幂等、批次上限、引用保护
- [x] 聊天内第一人称 emergent 成长：自然语言 `diff_summary`、用户自我认知询问触发、同人格+群并发合并、成长异步不阻塞回复
- [x] 前端 20 秒请求超时与 `TIMEOUT`；插件健康检查声明展示与权限批准/撤销 UI
- [x] README / API / SECURITY / ROADMAP / 设计文档与设置页如实描述上述边界

### 阶段 0 + 阶段 1 增量（2026-10-31）

- [x] 阶段 0 审计文档：`docs/implementation/AUDIT.md`、`FEATURE_STATUS.md`、
  `PROGRESS.md`、`CONNECTOR_DISTRIBUTION.md`
- [x] 连接身份门控：WS 握手后为 `connected_unverified`，`get_login_info` 成功才
  `online`；未验证身份不发送、不拉群、不派发 outbox
- [x] 修复重连身份查询死锁、身份错误码被覆盖、启动残留在线状态、`HTTPS://` 转换缺陷
- [x] 9 项分项连接诊断；配置/连接失败返回结构化报告；群列表失败降为警告；
  真实入站/出站明确未验证；诊断不发送消息
- [x] 前端诊断对话框、证据范围、实例下一步建议、`connected_unverified` 诚实状态；
  测试请求 60 秒超时
- [x] `context` 回复模式标记为规划并从保存路径拒绝；前端禁用与文案修正
- [x] `scripts/install_napcat.py`：官方 Release、digest、主机/重定向白名单、安全解压、
  许可证与 manifest、拒绝覆盖、TTY + `LAUNCH` 才执行安装器
- [x] `.gitignore` 排除 `connectors/`
- [ ] **真实 QQ 验收未执行**：真实登录、入站、出站、重连仍需账号所有者按
  [CONNECTOR.md](CONNECTOR.md) 清单完成
- [ ] **真实模型 Key 联调未执行**

### 阶段 2：连接器管理与自动安装（2026-10-31）

- [x] Connector Manager 抽象与 NapCat profile；只扫描受管根，外部安装只读
- [x] 受管目录设置与桌面系统目录选择；API 不接受任意路径
- [x] 安装/升级任务：JSON 事件、进度、取消、失败保留、重启后中断；不自动续跑
- [x] 官方安装器显式启动、受管进程启停、端口冲突拒绝与进程所有权保护
- [x] 配置预览/写入/快照/回滚与实例 Token 同步；写入失败自动恢复
- [x] 并存版本与活动版本切换；无自动更新/自动卸载
- [x] 诊断复用在线适配器；身份确认与拉群门控；`traffic_verified` 双向证据
- [x] 本机限定 API、确认词、审计与秘密环境隔离
- [x] 前端「连接器」页、配置导入兜底与诚实状态；桌面 `CONNECTORS_DIR`
- [ ] **真实 NapCat 安装器/进程/配置与 QQ 登录未执行**：需用户在场并按
  [CONNECTOR.md](CONNECTOR.md) 清单验收后，才能把真实连接标记为已验证

### 阶段 3：模型 API 真实调用（2026-10-31）

- [x] 模型列表（OpenAI 兼容两种结构；Anthropic 分页/去重/500 条上限；Mock 不伪造）
- [x] 连通性与真实生成测试分开；单次尝试、不自动重试、不回退；写用量并经过预算
- [x] 测试证据持久化白名单元数据；配置敏感字段变更/清空 Key 后失效
- [x] `Retry-After`、安全重试、读写超时默认不重试、不跟随重定向、每请求超时
- [x] 单进程 Provider 并发/间隔保护；`operation_id` 取消本地等待并记录取消用量
- [x] 真实主 Provider 失败禁止回退到 Mock；新增明确配置错误
- [x] 前端多标签证据、真实调用费用确认、取消、真实生成对话框、模型选择、清除 Key
- [x] Mock/真实后端测试、前端纯函数测试、冒烟覆盖；`LLMUsage.request_id`
- [ ] **真实模型 Key 验收未执行**：需用户用自有 Key 完成连通性、真实生成、错误场景、
  取消、预算与清除 Key 重启验收后，才能把真实模型标记为已验证

### 阶段 4：人格、群聊行为与记忆（2026-10-31）

- [x] 五档回复模式与新建/导入默认观察；既有群配置不迁移；演示群保留显式仅 @
- [x] 手动确认队列、批准/编辑后批准/拒绝、批准前检查、原子条件更新与重复批准冲突
- [x] 每成员时/日限频（outbox 口径）、群级回复字数与上下文条数上限
- [x] 统一敏感规则与输出审查：模型输出、命令回复、人工批准、outbox 发送前
- [x] 空消息与进程内重复刷屏启发式；发送前最终门禁重查安静时段
- [x] 人格纯投影预览、版本差异、候选不提前物化、证据预览、规则改写拒绝
- [x] 记忆上下文隔离、导出、来源、清理、保留天数（0 = 不自动删除）、候选敏感度
- [x] 后端/前端测试、冒烟与文档更新；不接触真实 QQ 或真实模型
- [ ] **真实 QQ / 真实模型验收仍未执行**

### 阶段 5：接入向导、诊断中心与桌面体验（2026-10-31）

- [x] `GET /api/onboarding`：八步证据聚合，区分 `done / action_required / optional / blocked / mock_only / not_verified`；`ready_for_replies` 仅在真实链路完成时为真
- [x] 实时在线只信内存适配器 `public_health()`；持久化状态只用于配置与历史证据；Mock 在线不计为真实在线
- [x] 连接测试证据归属当前实例、忽略 `test_unsaved`、配置更新后旧证据失效、超过 24 小时不完成、最新失败覆盖更早成功
- [x] 在线适配器诊断补写 `connector.diagnose` 审计；onboarding/diagnostics GET 永远只读
- [x] `GET /api/diagnostics` 显式 allowlist：计数、枚举、布尔值与后端生成的脱敏文本；不返回 Token、Key、QQ 标识、群名、消息正文、路径或日志行
- [x] 前端 `/onboarding`、`/diagnostics`、仪表盘待办横幅、结构化账号状态与连接诊断脱敏复制
- [x] 桌面首次启动进入 `/onboarding`；健康探测 12 秒/1.5 秒超时/单飞，3 次失败降级且不改变进程状态；托盘可用性与关闭矩阵
- [x] 冒烟与文档更新；不接触真实 QQ 或真实模型
- [ ] **真实 QQ / 真实模型验收仍未执行**

### 阶段 6：安全、数据、备份与恢复（2026-10-31）

- [x] 安全响应头：`nosniff`、`DENY`、`no-referrer`、`Permissions-Policy`；HTML CSP，Swagger 豁免，JSON 不加 CSP
- [x] TrustedHost 允许列表（`ALLOWED_HOSTS`）与严格 CORS（拒绝 `*`/空项/无 scheme，启动即失败）
- [x] Provider Base URL 拒绝元数据/链路本地/组播/未指定/共享地址，保留回环与私网；不跟随重定向
- [x] 保留清理只读预览 + `CLEANUP` 服务端确认；手动记忆清理真实执行同样需要确认词
- [x] 删除完整性：账号级联与媒体引用保护、群历史保留 + 解绑 + 待发取消、人格级联；账号/群/人格/备份 `DELETE` 确认词与审计
- [x] 消息 CSV 导出：BOM、公式注入防护、50,000 行上限、`no-store`/`nosniff`、审计不含正文/搜索词
- [x] 备份恢复 Schema 门禁（`BACKUP_SCHEMA_INCOMPATIBLE`）、应用版本展示、安全备份前中止
- [x] Electron `webSecurity`/权限处理器/设备权限拒绝/webview 阻止/shell CSP；前端输入 `DELETE`/`CLEANUP` 二次确认
- [x] 新增阶段 6 后端/前端/桌面测试与真实冒烟；**无数据库迁移**，未接触真实 QQ/模型
- [ ] **真实 QQ / 真实模型验收仍未执行**；Electron 权限与 OS 权限交互仍需人工验收

### 阶段 7：扩展能力与未来接口（2026-10-31）

- [x] 统一扩展契约矩阵 `GET /api/extensions/capabilities`：聊天适配器、模型 Provider、媒体 Provider、工具、插件分别列出接口、实现、执行方式、流水线依赖与安全保证
- [x] 媒体能力区分 `execution=job` 与 `contract_only`；未接通处理器的能力即使启用 Mock 也不会执行，并在能力中心给出 `next_step`
- [x] 停用媒体 Provider 立即取消对应能力下 `queued`/`running` 任务；在途 Provider 调用迟到的成功结果被丢弃、迟到失败不覆盖取消状态；取消/重试写审计
- [x] 任务重试仅在已失败且仍有可用 Provider 时允许，否则明确拒绝，避免排入不会执行的能力队列
- [x] `QQAdapterFactory` 注册表替代硬编码分支；账号与能力接口的连接方式由工厂派生，新增适配器只实现 `BaseQQAdapter`，不修改消息流水线
- [x] 工具固定为 `calculator`/`current_datetime` 且标注进程内固定注册；不存在插件式工具扩展
- [x] `PluginRuntime` 契约与八项未来前置要求（沙箱、权限清单、用户确认、签名校验、超时、资源限制、审计、即时停用）；当前执行入口显式返回 `OPERATION_PLANNED`
- [x] 前端能力中心展示执行方式/来源/检查时间/下一步/最近错误，停用后提示实际取消任务数；扩展页新增契约矩阵与插件运行时要求
- [x] 新增阶段 7 后端/前端测试与冒烟断言；**无数据库迁移**，未接触真实 QQ/模型
- [ ] **真实 QQ / 真实模型验收仍未执行**；第三方插件运行时、真实多模态 Provider 仍未实现

### 阶段 8：发布、安装包与回归（2026-11-01）

- [x] Windows x64 NSIS 安装包：PyInstaller 冻结后端（onedir）、冻结 NapCat 受管安装器、Vite 前端与 Electron 45；安装版无需 Python/Node
- [x] 安装版运行时：资源布局、`userData/.env` 随机密钥（不覆盖）、数据/连接器默认落在用户目录、安装目录只读
- [x] 后端冻结入口固定回环、端口/日志白名单、无命令行参数；受管 NapCat 安装器直接执行冻结 exe，参数仍由后端固定生成
- [x] Electron 安装版以固定参数启动内置后端；源码版保持 Python/uvicorn；设置页如实显示「安装版 / 源码版」
- [x] 发布流水线 `scripts/build_release.py`：版本一致性、前端构建、ICO、PyInstaller ×2、electron-builder NSIS、哈希清单 `release/BUILD_INFO.json`
- [x] 干净环境发布冒烟 `scripts/release_smoke.py`：布局/哈希、冻结后端迁移/健康/前端/运行模式、安装版 Electron `--smoke`、系统级 `PATH` 与临时密钥
- [x] 发布文档：`CHANGELOG.md`、`docs/RELEASE.md`、`docs/implementation/TEST_MATRIX.md`；README/DESKTOP/SECURITY/SOFTWARE_DESIGN 同步安装、升级、回滚、卸载与数据保留
- [x] 安装包未签名、无自动更新；卸载默认保留用户数据；升级前要求备份并复制完整 `userData`
- [ ] **NSIS 安装/升级/回滚/卸载尚未在独立干净 Windows 机器执行**
- [ ] **真实 QQ 端到端、真实模型 Key 仍未验证；不得宣称生产就绪**

## 3. 明确不在 P0 的能力

以下能力在界面/接口中标记为 `planned` 或 `unconfigured`，不得对外宣称可用：

- 记忆摘要压缩、向量语义检索与冲突检测（手动记忆、手动/群级后台候选提取、人工审核与本群范围内的基础检索已可用）
- 真实 Vision / OCR / ASR / TTS / Embedding Provider
- 视频理解、实时语音、图片生成
- 自定义 HTTP 工具、OpenAPI 导入、MCP
- 按功能拆分模型、基于成本/延迟/健康度的自动路由（群级主/备用绑定与单次受控回退已可用）
- 第三方插件代码执行、插件市场
- 评测实验室、批量回放
- 定时话题、主动私聊、主动发言调度
- 官方 QQ 机器人
- 多账号运营
- Tauri/Rust 桌面壳、**安装包代码签名**、自动更新与自动回滚（安装包已交付但未签名；升级需手动运行新安装包）
- 清理的「模拟执行」（当前只提供只读预览与手动记忆清理 dry-run，预览结果可能与实际运行不同）、outbox/审计/备份保留、VACUUM

## 4. 后续路线

### P1：真实媒体与工具扩展

1. 真实媒体 Provider 契约与至少一个可配置的视觉/ASR 实现（仍需本地开关与费用提示）。
2. 真实媒体下载/转存与真实多模态处理链路（本地存储、引用保护与基础保留清理已交付）。
3. Embedding + 语义记忆检索与冲突检测（当前已有手动记忆、手动/群级后台增量候选提取、人工审核、本群作用域隔离与关键词检索）。
4. 自定义 HTTP 工具的声明式配置、SSRF 防护、域名白名单与人工授权。
5. 更细的预算/SLA 统计，以及按功能/成本/延迟的自动模型路由（群级显式回退已实现）。
6. 定时话题与主动发言（默认关闭，需更强频率与内容护栏）。

### P2：平台化

1. 官方机器人连接器（受官方能力与政策约束）。
2. 插件沙箱/签名与插件市场（不在无沙箱情况下执行任意代码）。
3. 评测实验室与回放数据集。
4. 多账号与团队权限（仍需本机优先与最小权限）。
5. 桌面版增强：安装包代码签名、自动更新与回滚、系统级开机启动、安装器干净机器验收与更完善的运维面板（当前已提供未签名安装包与手动升级）。
6. 清理模拟执行（当前只提供只读预览）、outbox/审计/备份保留与更细的清理可观测性（基础调度与状态已交付）。

### 路线图原则

- 任何新增能力必须先在 UI 诚实标注状态，再谈可用性。
- 能接触消息、凭证或发送通道的功能，必须先有权限、审计、暂停与失败关闭设计。
- 不引入验证码绕过、反检测、批量养号、自动加群/加好友、广告群发或平台限流规避。
- P1/P2 不得破坏 P0 的默认保守策略与全局暂停。

## 5. 验收标准

### 自动化质量门

```powershell
# 后端
cd backend
.venv\Scripts\python.exe -m ruff format --check app tests
.venv\Scripts\python.exe -m ruff check app tests
.venv\Scripts\python.exe -m mypy app
.venv\Scripts\python.exe -m pytest -q

# 前端
cd ..\frontend
npm run type-check
npm run test
npm run build

# 桌面壳单元测试
cd ..\desktop
npm test

# 桌面壳真实截图冒烟（临时数据目录；不接触真实 QQ/模型）
.\node_modules\.bin\electron.cmd . --smoke

# 真实进程冒烟（项目根目录）
cd ..
backend\.venv\Scripts\python.exe scripts\smoke_test.py

# 发行包构建与干净环境冒烟（需 packaging extra；先构建）
backend\.venv\Scripts\python.exe scripts\build_release.py
backend\.venv\Scripts\python.exe scripts\release_smoke.py
```

全部命令必须真实通过；任何失败都不得在交付说明中隐藏。

### 本次交付实测记录（2026-10-25）

| 检查 | 实测结果 |
| --- | --- |
| `.\scripts\check.ps1` | 通过：ruff format（110 files）/ ruff check / mypy（99 files）/ pytest（117 passed） / vue-tsc / Vitest（16 passed） / vite build |
| `scripts/smoke_test.py` | 通过：真实 uvicorn + 临时数据目录，110 项断言全部 `[ok]`，含后台提取开关依赖、本群记忆注入、AI 候选提取/拒绝/重新提取/批准、Anthropic Provider 默认地址与密钥掩码、备份恢复后强制保持暂停、备份不含明文密钥 |
| Alembic 干净库 | 通过：`upgrade head` → `d9f3b6a2c715 (head)` → `downgrade base` → 再次 `upgrade head` |
| 备份脚本 | 通过：`backup.ps1` 调用运行中后端创建并校验备份；`-Offline` 生成一致性 SQLite 副本并输出 SHA-256 |
| 生产启动路径 | 通过：临时数据目录启动后端，`/` 由 FastAPI 返回已构建前端，`/api/health` 正常 |
| 静态检查备注 | 构建有 Element Plus chunk 体积警告（不影响功能）；pytest 有 TestClient/httpx 弃用警告 |
| 恢复可靠性修订 | 恢复改为“同目录暂存副本 + 原子替换”，WAL/SHM 清理与替换对 Windows 短暂文件占用做有限重试；实测冒烟恢复通过 |

`scripts/dev.ps1` 仅做 PowerShell 语法解析验证，未自动打开开发窗口；`scripts/dev.sh` 通过 `bash -n` 语法检查。

### 桌面版与主题交付实测记录（2026-10-25）

| 检查 | 实测结果 |
| --- | --- |
| `powershell -File scripts/check.ps1` | 通过：ruff format（110 files）/ ruff check / mypy（99 files）/ pytest（117 passed, 1 条 TestClient 弃用警告） / vue-tsc / Vitest（16 passed） / vite build / 桌面壳 node:test（23 passed）；构建仍只有 Element Plus chunk 体积警告 |
| 桌面壳单元测试 | 23 项通过：设置原子写入与校验、损坏 JSON 回退、端口占用与回退、绝对路径环境、健康检查/超时/取消、外部后端不 spawn 且不可重启、向导幂等与 `.env` 不覆盖、Windows 启动脚本编码、主进程/preload/shell/lib 语法解析、npm 经 `cmd.exe` 执行且拒绝 shell 元字符 |
| 安装命令边界 | Windows 向导通过 `cmd.exe /d /s /c` 执行固定的 npm `.cmd` 包装，参数逐项白名单校验并断开 `shell` 选项；消除了 Node 的 DEP0190 警告，渲染进程仍无法传入命令或参数 |
| `desktop: npm run smoke` | 通过：真实 Electron + 独立临时 userData + 临时数据目录 + 随机密钥 + 非 8000 端口 + 真实 uvicorn + Alembic 全量迁移；截图后重新执行真实启动路径（向导检查 → 后端启动 → 导航），输出 `DESKTOP_STARTUP_OK` 与 `DESKTOP_SMOKE_OK`，生成 `shell.png` / `dashboard.png` / `settings.png` / `startup.png` |
| 启动器 | `start-desktop.cmd --smoke` 与 `launch_desktop.ps1 --smoke` 均真实通过，输出相同 `DESKTOP_SMOKE_OK`；修复了启动脚本缺少 UTF-8 BOM（PowerShell 5.1 把中文按 ANSI 解析并报语法错误）与 `.cmd` 使用 LF 行尾（CMD 解析错乱）的问题；4 个 `.ps1` 均通过 PowerShell 语法解析，编码要求已加入桌面单元测试 |
| 视觉检查 | 截图确认深蓝侧栏、白底/浅蓝内容、橙色强调、桌面版徽章与设置卡片；启动页空提示条已消失，1440×920 下无异常滚动 |
| 未自动验证 | 托盘单击/双击、关闭到托盘、从托盘彻底退出、设置开关的鼠标交互仍需人工双击 `start-desktop.cmd` 验证；`--smoke` 已覆盖启动路径本身，但不能替代托盘与窗口交互验收 |

### V1.3 Phase 1 交付实测记录（2026-10-28）

| 检查 | 实测结果 |
| --- | --- |
| `backend: ruff format --check` | 通过：121 files already formatted |
| `backend: ruff check` | 通过：All checks passed |
| `backend: mypy` | 通过：103 source files，无问题 |
| `backend: pytest -q` | 通过：收集 191 项，退出码 0（仅 1 条 Starlette/httpx 弃用警告） |
| `frontend: npm run type-check` | 通过：vue-tsc 退出码 0 |
| `frontend: npm run test` | 通过：2 个测试文件、20 项 Vitest 全部通过 |
| `frontend: npm run build` | 通过；仍有 Element Plus 主 chunk 1,225 kB 体积警告，不影响功能 |
| `desktop: npm test` | 通过：23 项 node:test |
| `desktop: npm run smoke` | 通过：真实 Electron + 临时 userData/数据目录 + 非 8000 端口 + 全量 Alembic 迁移，输出 `DESKTOP_STARTUP_OK` / `DESKTOP_SMOKE_OK` |
| `./scripts/check.ps1` | 通过：后端、前端构建与桌面单测全部完成，脚本输出“全部检查通过” |
| `scripts/smoke_test.py` | 通过：真实 uvicorn 端到端 Mock 冒烟，164 项 `[ok]`，未接触真实 QQ/模型 |
| Alembic 干净库 | 通过：8 个迁移 `upgrade head` → `downgrade -1`（`f5c8a1d4e230`）→ `upgrade head`（`a7b3c9d1e240`），退出码 0 |

### 阶段 2 交付实测记录（2026-10-31）

| 检查 | 实测结果 |
| --- | --- |
| `backend: ruff format --check`（含安装脚本） | 通过：137 files already formatted |
| `backend: ruff check`（含安装脚本） | 通过：All checks passed |
| `backend: mypy` | 通过：117 source files，无问题 |
| `backend: pytest -q` | 通过：288 项，仅 1 条 Starlette/httpx 弃用警告 |
| 连接器与迁移定向测试 | 通过：86 项（含 API 本机守卫、确认词、快照回滚、状态矩阵、迁移往返） |
| `frontend: npm run type-check` | 通过：vue-tsc 退出码 0 |
| `frontend: npm run test` | 通过：4 个文件、37 项 Vitest |
| `frontend: npm run build` | 通过；Element Plus 主 chunk 1,225.80 kB 体积警告仍在 |
| `desktop: npm test` | 通过：26 项 node:test |
| `./scripts/check.ps1` | 通过：后端、前端构建与桌面单测全部完成，末尾「全部检查通过。」 |
| `scripts/smoke_test.py` | 通过：临时数据目录 + 临时 `CONNECTORS_DIR`；未接触真实 QQ/模型 |
| Alembic 临时库 | 通过：`upgrade head`（`b8d4e2f6a130`）→ `downgrade -1` → `upgrade head` |
| `install_napcat.py --dry-run --json` | 通过：只读取 Release 元数据，返回 `v4.18.42` 与 digest；未下载 |
| 真实安装器/进程/QQ 登录 | **未执行**：需用户在场并确认，详见 [CONNECTOR.md](CONNECTOR.md) |

### 阶段 4 交付实测记录（2026-10-31）

| 检查 | 实测结果 |
| --- | --- |
| `backend: ruff format --check` | 通过：149 files already formatted |
| `backend: ruff check` | 通过：All checks passed |
| `backend: mypy` | 通过：123 source files，无问题 |
| `backend: pytest` | 通过：362 passed, 1 warning（142.89s） |
| 阶段 4 定向测试 | 通过：73 项（pipeline、memory/persona phase4、migrations、api_smoke） |
| `frontend: npm run type-check` | 通过：vue-tsc 退出码 0 |
| `frontend: npm run test` | 通过：6 个文件、56 项 Vitest |
| `frontend: npm run build` | 通过（16.90s）；Vite 大 chunk 警告仍在 |
| `desktop: npm test` | 通过：26 项 node:test |
| `./scripts/check.ps1` | 退出码 0，末尾「全部检查通过。」 |
| `scripts/smoke_test.py` | 通过：临时数据目录 + 临时 `CONNECTORS_DIR`，243 项 `[ok]`；含默认观察、手动确认批准/拒绝、人格预览、记忆导出/清理；未接触真实 QQ/模型 |
| Alembic 临时库 | 通过：`upgrade head`（`f4a7b2c9d801`）→ `downgrade d2e6b8a4c910` → `upgrade head`；未触碰 `data/` |
| 真实 QQ / 真实模型 | **未执行**：需用户在本机用自有账号与 Key 验收 |

### 阶段 5 交付实测记录（2026-10-31）

| 检查 | 实测结果 |
| --- | --- |
| `backend: ruff format --check` | 通过：157 files already formatted |
| `backend: ruff check` | 通过：All checks passed |
| `backend: mypy` | 通过：129 source files，无问题 |
| `backend: pytest` | 通过：退出码 0；收集 373 项（`addopts=-q` 叠加 `-q` 不打印汇总行） |
| 阶段 5 定向测试 | 通过：33 项（onboarding、diagnostics、api_smoke） |
| `frontend: npm run type-check` | 通过：vue-tsc 退出码 0 |
| `frontend: npm run test` | 通过：7 个文件、67 项 Vitest |
| `frontend: npm run build` | 通过；Vite 大 chunk 警告仍在 |
| `desktop: npm test` | 通过：29 项 node:test（新增运行期健康/单飞/定时器测试） |
| `desktop: npm run smoke` | 通过：首次启动路径 `/onboarding`、健康 `healthy`、快照含托盘字段；生成 6 张截图（新增 onboarding/diagnostics） |
| `./scripts/check.ps1` | 通过：退出码 0，末尾「全部检查通过。」 |
| `scripts/smoke_test.py` | 通过：临时数据目录 + 临时 `CONNECTORS_DIR`，269 项 `[ok]`；含只读向导/诊断与脱敏断言；未接触真实 QQ/模型 |
| 真实 QQ / 真实模型 | **未执行**：接入向导不能替代真实收发验收 |

### 阶段 6 交付实测记录（2026-10-31）

| 检查 | 实测结果 |
| --- | --- |
| `backend: ruff format --check` | 通过：163 files already formatted |
| `backend: ruff check` | 通过：All checks passed |
| `backend: mypy` | 通过：131 source files，无问题 |
| `backend: pytest` | 通过：418 passed, 1 warning（98.62s；仅 TestClient/httpx 弃用警告） |
| 阶段 6 定向测试 | 通过：44 passed（security / data_cleanup / backup_schema / messages_export） |
| `frontend: npm run type-check` | 通过：vue-tsc 退出码 0 |
| `frontend: npm run test` | 通过：8 个文件、72 项 Vitest（新增 confirmation 4 项） |
| `frontend: npm run build` | 通过；Element Plus 主 chunk 1,226.53 kB 体积警告仍在 |
| `desktop: npm test` | 通过：33 项 node:test（新增 security 静态断言 4 项） |
| `desktop: npm run smoke` | 通过：全量 Alembic 迁移、首次启动 `/onboarding`、健康 `healthy`，输出 `DESKTOP_STARTUP_OK` / `DESKTOP_SMOKE_OK`，生成 6 张截图 |
| `./scripts/check.ps1` | 通过：退出码 0，末尾「全部检查通过。」 |
| `scripts/smoke_test.py` | 通过：临时数据目录 + 临时连接器目录，332 项 `[ok]`；含安全头/CSP、消息 CSV、元数据地址拒绝、备份 Schema 预览、清理预览只读与 `CLEANUP` |
| Alembic 迁移 | **无新增迁移**；冒烟与桌面 smoke 均在临时库执行现有 `upgrade head` |
| 真实 QQ / 真实模型 | **未执行**；本次只使用 Mock 与假服务器 |

### 阶段 7 交付实测记录（2026-10-31）

| 检查 | 实测结果 |
| --- | --- |
| `backend: ruff format --check` | 通过：166 files already formatted |
| `backend: ruff check` | 通过：All checks passed |
| `backend: mypy` | 通过：133 source files，无问题 |
| `backend: pytest` | 通过：427 passed, 1 warning（仅 TestClient/httpx 弃用警告） |
| 阶段 7 定向测试 | 通过：9 passed（`tests/test_phase7_extensions.py`） |
| `frontend: npm run type-check` | 通过：vue-tsc 退出码 0 |
| `frontend: npm run test` | 通过：9 个文件、76 项 Vitest（新增 extensions 4 项） |
| `frontend: npm run build` | 通过；Element Plus 主 chunk 1,226.56 kB 体积警告仍在 |
| `desktop: npm test` | 通过：33 项 node:test |
| `desktop: npm run smoke` | 通过：全量 Alembic 迁移、首次启动 `/onboarding`、健康 `healthy`，输出 `DESKTOP_STARTUP_OK` / `DESKTOP_SMOKE_OK`，生成 6 张截图 |
| `./scripts/check.ps1` | 通过：退出码 0，末尾「全部检查通过。」 |
| `scripts/smoke_test.py` | 通过：临时数据目录 + 临时连接器目录，347 项 `[ok]`；新增扩展契约、工具白名单、`job`/`contract_only`、停用响应断言 |
| Alembic 迁移 | **无新增迁移**；冒烟与桌面 smoke 均在临时库执行现有 `upgrade head` |
| 真实 QQ / 真实模型 | **未执行**；本次只使用 Mock 与假服务器 |

### 阶段 8 交付实测记录（2026-11-01）

所有数字来自 2026-11-01 本机实际命令输出（Windows 11 x64）。

| 检查 | 实测结果 |
| --- | --- |
| 后端 ruff / mypy / pytest | 格式与静态规则通过；mypy 134 源文件通过；pytest 435 passed，1 warning，101.26s |
| 前端 type-check / Vitest / build | 类型通过；9 files / 76 tests passed；构建通过（主 chunk 1,226.56 kB 体积警告） |
| 桌面 `npm test` / `npm run smoke` | 38 passed / 0 failed；`DESKTOP_SMOKE_OK`，6 张截图 |
| `scripts/check.ps1` | 全部检查通过 |
| `scripts/smoke_test.py` | 全部通过，未接触真实 QQ 或真实模型 |
| `scripts/build_release.py` | 成功；版本 0.2.0；安装包 155,826,158 bytes |
| `scripts/release_smoke.py` | 通过；冻结后端 `packaged`、Alembic `f4a7b2c9d801`、内置前端、桌面 6 张截图（12.4s） |
| 安装包 | `AI-Group-Friend-Setup-0.2.0-x64.exe`，SHA-256 `119f48c5…f9ecce`；未签名 |
| NSIS 安装/卸载 | **未在独立干净机器执行** |
| 真实 QQ / 真实模型 | **未执行** |

过程中的一次 `I001` 导入排序失败已修复并复检通过；前端仅有 chunk 体积警告。完整记录见
[implementation/TEST_MATRIX.md](implementation/TEST_MATRIX.md#3-本轮实测记录)。

### 0.2.1 最终审计实测记录（2026-11-01）

| 检查 | 实测结果 |
| --- | --- |
| 后端 ruff / mypy / pytest | 格式与静态规则通过；mypy 134 源文件通过；pytest **442 passed**，1 warning，103.08s |
| 前端 type-check / Vitest / build | 类型通过；9 files / **76 tests passed**；构建通过（主 chunk 1,226.56 kB 体积警告） |
| 桌面 `npm test` / `npm run smoke` | **39 passed / 0 failed**；`DESKTOP_SMOKE_OK`，版本 0.2.1，6 张截图 |
| `scripts/check.ps1` | 全部检查通过；明确提示不含 GUI 截图冒烟 |
| `scripts/smoke_test.py` | 全部通过，未接触真实 QQ 或真实模型 |
| `scripts/build_release.py` | 成功；版本 0.2.1；`git_dirty=false`；四处版本一致；Electron 45.0.0；安装包 155,824,181 bytes |
| `scripts/release_smoke.py` | 通过；冻结后端 `packaged`、Alembic `f4a7b2c9d801`、内置前端、隔离目录；桌面 0.2.1 / 6 张截图 / 12.2s |
| 安装包 | `AI-Group-Friend-Setup-0.2.1-x64.exe`，SHA-256 `bf3e95ba5520a0b97d14e766be27869a7c8033ad6e23c3495450b9d664af70be`；未签名 |
| `win-unpacked/AI 群友.exe` | 249,797,632 bytes，SHA-256 `e92bee0e0ee98e6ed490636a02ba949b8fc5a1311cfa1392bee1be3f66eb3ae0` |
| NSIS 安装/卸载 | **未在独立干净机器执行** |
| 真实 QQ / 真实模型 | **未执行** |

详细修复与测试见 [implementation/FINAL_REPORT.md](implementation/FINAL_REPORT.md) 与
[implementation/TEST_MATRIX.md](implementation/TEST_MATRIX.md)。

### 功能验收清单

- [x] 不使用真实 QQ/模型即可完成 Mock 全链路
- [x] @ 触发回复；非 @ 在默认模式被忽略且原因可查
- [x] 白名单外群、自身消息、重复事件不会触发回复
- [x] 全局暂停立即阻断回复与发送队列
- [x] dry-run 不发送、不落库
- [x] Mock 事件注入可持久化并进入 outbox
- [x] outbox 未知状态不重发（代码与测试覆盖，真实网络场景仍需联调）
- [x] Mock 用量记录与预算硬上限阻断
- [x] Provider 密钥掩码、响应与数据文件不含明文
- [x] 备份校验、恢复错误短语/未暂停拒绝、真实恢复回退临时数据
- [x] 恢复后审计留痕、重连后可再次完成 Mock 闭环
- [x] 空白人格初始为空；证据不足不产生稳定特征
- [x] 锁定字段/跨群隔离/版本回滚/重置行为
- [x] OneBot 适配器进程内假服务器测试（真实 NapCat 联调需用户环境）
- [x] 长期记忆手动增删改查、固定、敏感度/过期状态与自动注入预览
- [x] 记忆严格限定本群与当前发送者；跨群、过期、敏感与排除成员记忆不注入
- [x] 记忆写入拒绝疑似密码/验证码/证件号/银行卡号/API Key
- [x] AI 记忆候选提取可手动触发，或由群显式开启后台增量提取；候选在批准前不写入正式记忆、不注入提示词
- [x] 候选证据校验、敏感/重复/未知成员/低置信度过滤、Mock 来源标记与审计
- [x] 候选批准/拒绝、非 pending 冲突拒绝、批准后可检索与重新提取去重
- [x] 后台增量提取默认关闭、依赖长期记忆、时间 + 消息 ID 双字段游标推进、积压批次不跳过、无新消息不调用模型、全局暂停停止、错误脱敏记录
- [x] 新群/导入新行默认观察；既有群模式不被静默改写
- [x] `manual_confirm` 只生成待审队列，批准/拒绝写审计，重复批准 409，`dispatch-due` 不发送待审消息
- [x] 群级与每成员限频生效；待审草稿与命令回复不计入成员额度
- [x] 群级回复字数/上下文条数覆盖与 outbox 发送前复查
- [x] 敏感输出、空输出、重复刷屏与发送前安静时段门禁拦截
- [x] 人格预览不写库/不增版本/不增审计；版本差异、候选证据与规则改写拒绝
- [x] 记忆导出默认排除敏感、CSV 注入防护、来源脱敏、清理 dry-run/真实清理、删除后不再检索
- [x] `memory_retention_days=0` 不自动删除记忆；语义检索仍标记 planned
- [x] Anthropic 请求映射（system/消息合并、tool_use、usage、温度）、错误分类、默认 Base URL 与密钥掩码
- [x] 接入向导八步状态来自后端证据；Mock 阶段为 `ready_mock_only` 且 `ready_for_replies=false`
- [x] 连接测试证据归属、`test_unsaved` 忽略、配置更新后失效、stale 不完成、最新失败覆盖旧成功
- [x] onboarding/diagnostics GET 前后审计条数不变；响应不含凭证、QQ 标识、群名/群号、消息正文或路径
- [x] 桌面首次启动进入 `/onboarding`；健康失败不改后端状态；托盘不可用时关闭窗口退出并停止受管后端
- [x] HTML/JSON 安全头与 CSP；Swagger 文档不被 CSP 破坏
- [x] TrustedHost 拒绝未知 Host；CORS 拒绝通配符与非法来源；远程管理 Token 行为不变
- [x] Provider Base URL 拒绝云元数据与链路本地地址，允许回环/私网
- [x] 清理预览前后数据/审计/上次运行不变；无确认执行返回 400 且无副作用；`CLEANUP` 成功并审计
- [x] 账号删除清理未共享媒体并保留共享媒体；群删除取消待发、保留历史消息且解除关联
- [x] 账号/群/人格/备份删除缺少或错误确认词返回 400，数据不变
- [x] 消息 CSV 带 BOM、公式转义、正确响应头；审计不含正文/搜索词
- [x] 备份预览含 Schema/应用版本；不兼容恢复在安全备份前返回 409；删除备份需确认并审计
- [x] Electron `webSecurity`/权限白名单/设备权限拒绝/webview 阻止/shell CSP 静态断言通过
- [x] 前端类型检查、单元测试与生产构建
- [x] 能力中心与页面不把 Mock/规划中展示为真实可用
- [x] Windows x64 NSIS 安装包构建成功；内含冻结后端、NapCat 安装器、前端与 Electron
- [x] 安装版布局、`userData/.env` 不覆盖、固定参数启动内置后端通过桌面单元测试
- [x] 冻结后端在隔离临时目录启动、迁移、健康、托管前端、`runtime_mode=packaged` 通过发布冒烟
- [x] 安装版 Electron `--smoke` 首次启动进入 `/onboarding`、健康、6 张截图通过；系统级 `PATH`
- [x] `BUILD_INFO.json` 与实际产物 SHA-256 一致；明确标记未签名、真实 QQ/模型未验证
- [x] 文档明确真实 QQ 未验证、不宣称生产就绪，并给出升级/回滚/卸载/数据保留说明
- [ ] **NSIS 安装、升级、回滚、卸载在独立干净 Windows 机器验收**
- [ ] **安装包代码签名**

### 人工验收（需用户环境）

- [ ] 在独立干净 Windows 10/11 x64 机器校验安装包 SHA-256，执行 NSIS 安装并完成首次启动
- [ ] 演练升级（覆盖安装）、回滚（旧 `userData` + 旧安装包）与卸载；确认卸载默认保留数据、手工彻底删除路径正确
- [ ] 如需要正式分发，为安装包配置代码签名并验证 SmartScreen 行为
- [ ] 在连接器页完成下载/校验/解压，并显式运行官方安装器
- [ ] 真实 NapCat 登录专用 QQ 账号并完成连接器测试
- [ ] 写配置、确认身份、导入真实群列表，先仅观察、后仅 @ 回复
- [ ] 验证真实入站 + 出站后 `traffic_verified` 才转为有证据状态；记录群号/时间/消息 ID
- [ ] 真实 OpenAI-compatible 模型 Key 测试连接与回复
- [ ] 真实 Anthropic API Key 测试连接与回复
- [ ] 真实暂停、重连、发送失败与恢复流程演练
- [ ] 按组织要求完成隐私/合规评估

## 6. 风险登记

| 风险 | 影响 | 当前应对 |
| --- | --- | --- |
| 非官方连接器兼容性/风控 | 掉线、封号、协议差异 | 默认仅本机、保守策略、暂停、无规避实现、用户自行承担与联调 |
| 第三方安装器/批处理行为不可控 | 权限、联网、半安装 | 仅显式确认后启动固定文件；不代替操作、不提权、不强制结束安装器；文档明确风险 |
| 进程所有权丢失/配置竞态 | 误杀或覆盖配置 | 只停本会话进程；端口冲突拒绝启动；写配置前二次检查与加密快照回滚 |
| 未验证真实 QQ/模型 | 真实环境差异 | 明确列为已知限制；保留 Mock 与假服务器测试 |
| 提示注入 | 模型被诱导 | 不可信内容包裹、权限引擎、无高风险工具、白名单与人工审核 |
| 凭证/密钥丢失 | 旧凭证无法解密 | 密钥独立离线备份说明；禁止进备份；轮换流程 |
| SQLite 并发/规模 | 高并发下性能 | 单机小规模定位；短事务；后续可评估迁移 |
| 远程管理配置错误 | 管理面暴露 | 默认仅本机；显式开关 + Token；文档要求 HTTPS 代理 |
| 备份含凭证密文 | 备份泄露导致离线破解风险 | 按敏感文件保护；加密密钥分离；全盘加密建议 |
| 自动清理误删 | 数据不可恢复 | 默认关闭；手动执行先只读预览并要求 `CLEANUP` 确认；分批、审计、引用保护、只删轮转日志；预览与实跑可能有差异，已列为限制 |
| 安装包未签名/被篡改 | 恶意分发、SmartScreen 警告 | 提供 `BUILD_INFO.json` SHA-256；文档要求先校验；明确未签名；正式分发前需代码签名 |
| 升级/回滚导致数据不可读 | 旧程序打开新 Schema、数据丢失 | 升级前要求备份并复制完整 `userData`；无自动降级；Schema 门禁拒绝不兼容备份；干净机器演练仍待执行 |
| 控制台打包体积大 | 首屏加载慢 | 已知构建警告；后续按需引入 Element Plus |

## 7. 版本记录

### 0.2.1 — 最终审计与发布可复现性（2026-11-01）

- 完成阶段 0–8 只读审计后的本机修复：冒烟脚本完全隔离真实 `.env`；发布构建拒绝 dirty
  工作树、清理旧产物、记录工作树指纹与 Electron 实际版本；版本以 `app.__version__` 为
  单一来源；损坏备份结构化拒绝；空文本发送在任何 HTTP 请求前拒绝；新增 NSIS 静态配置
  回归测试；删除死代码与永远 501 的演示端点。
- 重新构建 0.2.1 安装包并执行隔离发布冒烟，结果见下一节“0.2.1 最终审计实测记录”与
  [implementation/TEST_MATRIX.md](implementation/TEST_MATRIX.md)。
- **仍未验证：真实 QQ 收发、真实模型 Key、独立干净机 NSIS 安装/升级/回滚/卸载、代码
  签名与 SmartScreen。不得宣称生产就绪。**
- 详细条目见 [../CHANGELOG.md](../CHANGELOG.md)。

### 0.2.0 — 阶段 1–8 增量与 Windows 安装包（2026-11-01）

- 汇总 V1.3 Phase 1、连接加固、阶段 2–7 全部增量；新增阶段 8 Windows x64 NSIS 安装包、
  冻结后端、安装版运行时、发布流水线与干净环境冒烟。
- 安装版自带 Python/前端/Electron 运行时，普通用户无需安装 Python/Node。
- **未签名、无自动更新；NSIS 安装/卸载未在独立干净机器执行；真实 QQ 端到端与真实模型
  Key 未验证，不宣称生产就绪。**
- 详细条目见 [../CHANGELOG.md](../CHANGELOG.md) 与
  [RELEASE.md](RELEASE.md)。

### 0.1.0 — P0 MVP（2026-10-25）

- 完成 Phase 0–3 P0 范围：工程基座、Mock/OneBot 连接器、Mock/OpenAI-compatible 模型、消息流水线、人格治理、工具/预算、备份恢复、中文 Vue 控制台。
- 完成真实 uvicorn + 临时数据库的端到端 Mock 冒烟测试与真实恢复验证。
- 明确标注规划中/未配置能力，不提供真实多模态或插件执行。
- 后续增量：新增本群范围内的长期记忆手动管理、受控注入，以及手动触发的 AI 候选提取与人工审核；后台自动提取已改为群级可选、默认关闭的增量候选提取，使用时间 + 消息 ID 双字段游标按批处理积压消息，摘要与语义检索仍标记为规划中。
- 后续增量：备份恢复改为同目录暂存副本 + 原子替换，并对 Windows 文件短暂占用做有限重试，避免复制中途失败截断当前数据库；恢复完成后显式恢复全局暂停，不依赖备份快照中的暂停状态。
- 后续增量：新增 Anthropic 原生 Messages API Provider（需真实 Key，未使用真实服务联调）；OpenAI-compatible 仍作为通用接入方式。
- 后续增量：新增群级主/备用模型绑定与受控故障回退。备用模型仅在主 Provider 发生可回退的调用错误时尝试一次；预算、全局暂停、Provider 禁用/缺失、配置与凭证错误不回退，也不会静默改用 Mock 或默认模型。被群绑定的 Provider 禁止直接删除。按功能拆分模型与自动成本/延迟路由仍为规划中。
- 后续增量：新增基于 `llm_usage` 的 Provider / 群维度用量汇总与仪表盘真实用量展示；费用按用户填写的单价本地估算，Mock 记为无外部费用，未配置单价的调用标记为不可计价（`cost` 为 `null`），绝不伪造 0 成本。费用预算在 Provider 无单价时以 `cost_unavailable` 阻断调用，防止绕过上限。
- 后续增量：新增用量趋势、预算告警与 CSV 导出。趋势按配置时区聚合真实 `llm_usage`，空桶补 0、未知成本保持为空；告警在达到阈值/上限时按策略、周期、级别去重写入 `budget_alerts`，写审计并推送 SSE，但不会替代预算阻断；CSV 仅导出调用元数据，不含消息正文、提示词或凭证，导出动作写审计。
- 后续增量：新增 Electron 桌面版（独立 `desktop/` 包）：双击启动、幂等首次向导（补齐 venv/依赖/.env/前端构建）、后端进程与健康检查、外部后端接管、托盘、桌面设置、日志与白名单目录入口。窗口只加载本地控制页或当前本机后端源，启用 sandbox/contextIsolation 与最小 IPC。当前不提供独立安装包或自动更新，仍需本机 Python/Node。
- 后续增量：全站改用蓝白橙主题（深蓝侧栏、白底、浅蓝内容、橙色强调），状态语义色保持成功绿/危险红；新增桌面版设置卡片与启动控制页。

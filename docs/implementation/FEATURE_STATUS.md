# 能力真实性清单

更新日期：2026-11-01

状态定义：

- **真实实现**：有业务实现与自动化测试，未配置外部服务时仍按自身边界工作。
- **部分实现**：核心路径已实现，但有明确缺口。
- **Mock**：只有本地模拟，不接触真实外部服务。
- **仅 UI / 契约**：界面或接口占位，无可用的真实执行路径。
- **规划**：明确不可用，调用会被拒绝或返回 `OPERATION_PLANNED`。

「真实环境验证」独立于代码实现：`否` 表示本仓库没有真实 QQ 或真实模型服务的证据。

| 能力 | 状态 | 证据 | 真实环境验证 | 备注 |
| --- | --- | --- | --- | --- |
| Mock QQ 连接器与 Mock 模型闭环 | 真实实现（本地） | `tests/test_pipeline.py`、`tests/test_api_smoke.py`、`scripts/smoke_test.py` | 不需要 | 固定模板，不连接网络 |
| OneBot 11 协议解析、WS 收事件、HTTP/WS action | 真实实现（本地假服务器验证；真实环境未验收） | `tests/test_onebot11.py`、`tests/onebot_fakes.py`、`tests/test_connection_diagnostics.py` | 否 | 只用本机假服务器；未接触真实 NapCat；空文本在 HTTP 前拒绝 |
| 连接身份门控（WS 连接 ≠ 在线） | 真实实现 | `tests/test_connection_diagnostics.py` | 否 | 必须 `get_login_info` 返回 `user_id` 才 `online` |
| 9 项连接诊断与证据范围 | 真实实现 | `tests/test_connection_diagnostics.py`、`tests/test_api_smoke.py` | 否 | 真实入站/出站永远不会被诊断伪造为已验证 |
| 接入向导证据聚合 | 真实实现（本地） | `tests/test_phase5_onboarding.py`、`tests/test_connectors_api.py`、`scripts/smoke_test.py` | 否 | 八步状态来自配置、内存适配器与既有审计；每步含状态/时间/尝试次数/错误码/重试与 `next_action`；Mock 永远不满足 `ready_for_replies`；GET 不写审计、不触发动作 |
| 受管连接器一键自动配置 | 真实实现（本地）；真实环境未验收 | `tests/test_connectors_api.py`、`frontend/tests/onboarding.test.ts` | 否 | 只对唯一可用的受管 Shell 自动分配本机端口、加密 Token、写配置并创建账号；需 `AUTO CONFIG` 确认；不启动连接器、不登录 QQ、`auto_connect=false`；仅 `v4.18.42` 自动写配置 |
| 脱敏诊断摘要 | 真实实现（本地） | `tests/test_phase5_diagnostics.py`、`scripts/smoke_test.py` | 否 | 显式 allowlist；不含 Token/Key/QQ 标识/群名/消息正文/路径/日志行；不提供日志 HTTP 接口 |
| 桌面运行期健康与托盘可用性 | 真实实现（本机） | `desktop/tests/backend.test.js`、`electron . --smoke` | 部分（本机测试） | 12 秒/1.5 秒/单飞；3 次失败降级但不改进程状态；托盘不可用时关闭窗口退出 |
| 真实 QQ 登录 | 外部能力 | — | 否 | 由 NapCat/用户完成；本项目不接触密码 |
| 真实 QQ 入站群消息 | 未验证 | 诊断项 `real_inbound` | 否 | 需要用户在受控群实测 |
| 真实 QQ 出站发送 | 未验证 | 诊断项 `real_outbound`、outbox 门控 | 否 | 诊断从不发送；需用户人工验收 |
| 官方 QQ 机器人 | 规划 | `/api/capabilities`、接口占位 | 否 | `planned`，不可用 |
| 去重、自身过滤、白名单、暂停、限速、安静时段 | 真实实现 | `tests/test_pipeline.py` | 不适用 | 硬规则先于模型；群级与每成员时/日限频 |
| 回复模式观察 / 仅 @ / 手动确认 / 自动回复 / 关键词 | 真实实现 | `tests/test_pipeline.py`、`tests/test_api_smoke.py` | 不适用 | **新建与导入新群默认观察**；既有群不迁移 |
| 手动确认待审队列 | 真实实现 | `tests/test_pipeline.py`、`tests/test_api_smoke.py` | 不适用 | 只发 `pending`；批准原子更新且重复 409 |
| 空消息 / 重复刷屏启发式 | 真实实现（本机启发式） | `tests/test_pipeline.py` | 不适用 | 进程内 60 秒窗口，重启清零 |
| 输出敏感检查与长度/安静时段门禁 | 真实实现 | `tests/test_pipeline.py`、`tests/test_persona_phase4.py` | 不适用 | 模型、命令、批准与 outbox 共用 |
| 上下文参与 / 定时话题 | 规划 | `/api/groups` 返回 `state: planned`；创建会 400 | 否 | 当前拒绝保存 |
| OpenAI 兼容 Provider | 真实实现（MockTransport 验证；真实环境未验收） | `tests/test_openai_provider.py`、`test_llm_routing.py` | 否 | 适配器实现完整；未使用真实 Key 联调 |
| Anthropic 原生 Provider | 真实实现（MockTransport 验证；真实环境未验收） | `tests/test_anthropic_provider.py` | 否 | 适配器实现完整；未使用真实 Key 联调 |
| 模型列表、连通性与真实生成测试 | 真实实现（本地/Mock） | `tests/test_provider_models.py`、`test_provider_api.py` | 否 | 真实远端测试未执行；证据不含 Key/提示词 |
| Provider 限流、安全重试、取消与真实→Mock 回退保护 | 真实实现 | `tests/test_llm_gateway_resilience.py`、`test_llm_routing.py` | 否 | 单进程限流；取消不保证上游停止计费 |
| 群级主/备用模型与受控回退 | 真实实现 | `tests/test_llm_routing.py` | 否 | 只回退一次；禁止真实失败回退到 Mock |
| 预算、用量、费用完整性 | 真实实现 | `tests/test_budgets.py` | 不适用（本地账本） | 未配单价的调用标记不可计价，不伪造 0 |
| 真实视觉 / OCR / ASR / TTS / Embedding / 视频理解 | 未配置 | `tests/test_media_contracts.py`、`tests/test_phase7_extensions.py`、能力页状态 | 否 | 只有确定性 Mock 与契约；能力概览区分 `job` 与 `contract_only` |
| 媒体任务队列与用量 | 真实实现（本地） | `tests/test_media_jobs.py`、`test_media_worker.py`、`test_media_usage.py` | 不适用 | Provider 是 Mock；停用 Provider 会取消排队与运行中任务 |
| 扩展契约矩阵与执行状态 | 真实实现（本地） | `tests/test_phase7_extensions.py`、`scripts/smoke_test.py` | 不适用 | `GET /api/extensions/capabilities` 汇总五类接口、执行方式与保证；只读 |
| 停用扩展即时止损 | 真实实现 | `tests/test_phase7_extensions.py` | 不适用 | 取消排队/运行中任务；迟到结果丢弃；取消/重试写审计 |
| QQ 适配器工厂与新增适配器契约 | 真实实现（本地） | `tests/test_phase7_extensions.py` | 否 | 注册 `BaseQQAdapter` 即可派生连接方式；未实现能力必须声明 false |
| 内置计算器 / 日期时间工具 | 真实实现 | `tests/test_tools_and_plugins.py`、`test_phase7_extensions.py` | 不适用 | 启动时固定注册、进程内执行；无任意 Shell/文件/URL 或插件式工具扩展 |
| 第三方插件代码执行 | 不执行 | `tests/test_tools_and_plugins.py`、`test_phase7_extensions.py` | 不适用 | 只登记清单、权限与声明；`PluginRuntime` 暴露但显式返回 `OPERATION_PLANNED` |
| 第三方插件运行时前置要求 | 规划 | `app/plugins/runtime.py`、`tests/test_phase7_extensions.py` | 不适用 | 沙箱、权限清单、用户确认、签名、超时、资源限制、审计、即时停用均未实现 |
| 人格编写 / 模板 / 空白自成长 | 真实实现 | `tests/test_persona_growth.py`、`test_self_inquiry.py`、`test_persona_phase4.py` | 否（使用 Mock 模型） | 证据、锁定字段、版本、回滚、预览、差异、证据、规则改写拒绝 |
| 长期记忆与本群范围检索 | 真实实现 | `tests/test_pipeline.py`、`tests/test_memory_phase4.py` | 否（使用 Mock 模型） | 无语义向量检索；上下文账号/群隔离；导出/来源/清理 |
| 后台记忆候选提取 | 真实实现（默认关闭） | 相关服务测试 | 否 | 只生成待审核候选；批准可选敏感度 |
| 数据保留与清理 | 真实实现（自动清理默认关闭） | `tests/test_retention.py` | 不适用 | 只读预览 + 手动 `CLEANUP` 确认；预览是快照，实跑数量可能不同；记忆保留 `0` = 不自动删除 |
| 备份 / 校验 / 恢复 | 真实实现 | `tests/test_backup_restore.py`、`tests/test_phase6_backup_schema.py` | 不适用 | 不含媒体、日志、加密密钥；Schema 门禁拒绝不兼容备份；损坏/截断文件在触碰当前库前拒绝且不留下暂存文件 |
| HTTP 安全头、TrustedHost、CORS 与 SSRF 收紧 | 真实实现 | `tests/test_phase6_security.py` | 不适用 | CSP 仅 HTML；Swagger 豁免；`ALLOWED_HOSTS` 默认本机；CORS 拒绝通配符；Provider 拒绝元数据地址但不解析 DNS |
| 删除完整性、媒体引用保护与待发取消 | 真实实现 | `tests/test_phase6_data_cleanup.py` | 不适用 | 账号/群/人格/备份需 `DELETE` 确认词；群历史保留但解绑；共享媒体保留 |
| 消息 CSV 导出 | 真实实现 | `tests/test_phase6_messages_export.py`、`scripts/smoke_test.py` | 不适用 | 含正文与发送者标识，不含媒体/提示词/凭证；50,000 行上限；审计不含正文/搜索词 |
| Electron 安全边界（webSecurity/权限/CSP） | 真实实现（静态与冒烟测试） | `desktop/tests/security.test.js`、`npm run smoke` | 部分（本机测试） | 权限处理器仅允许 clipboard-sanitized-write；真实系统权限交互需人工验收 |
| Electron 源码桌面一键启动 | 真实实现 | `desktop/tests/`、`npm test` | 部分（本机单元测试） | 需本机 Python/Node；复用仓库 `.venv` 与 `frontend/dist` |
| Windows 独立安装包（自带运行时） | 真实实现（构建 + 隔离冒烟） | `scripts/build_release.py`、`desktop/tests/packaged.test.js`、`desktop/tests/packaging.test.js`、`scripts/release_smoke.py` | 部分（本机隔离环境） | 0.2.2 本机构建 `git_dirty=true`、155,842,669 bytes、未签名；冻结后端与安装版 Electron 隔离冒烟通过；NSIS x64；无需 Python/Node；静态测试断言可改目录且默认保留数据，但**不证明真实卸载行为**；NSIS 安装/卸载未在独立干净机器执行 |
| 安装版冻结后端 | 真实实现（打包冒烟） | `tests/test_packaging.py`、`release_smoke.py` | 部分（本机隔离环境） | 固定回环/端口/日志白名单；临时数据目录迁移与健康检查通过 |
| 自动更新 / 代码签名 / 自动回滚 | 未实现（明确不支持） | `BUILD_INFO.json`、文档 | 否 | 只提供 SHA-256；升级需手动运行新安装包；不得宣称已签名或可自动更新 |
| NapCat 官方下载/校验/安全解压脚本 | 真实实现（默认下载+解压，不执行安装器） | `tests/test_napcat_installer.py` | 已实际下载、校验并解压 `v4.18.42`；修复/复用/隔离仅假 I/O 测试 | 安装器未运行；未登录 QQ；同版本完整目录复用、受管损坏目录隔离修复、未知目录拒绝不触碰；下载有界重试；ZIP 完整性/压缩比/符号链接校验 |
| Connector Manager 抽象与受管安装检测 | 真实实现 | `tests/test_connectors_napcat.py`、`tests/test_connectors_manager.py` | 否（临时目录/假布局） | 只实现 NapCat profile；只扫描 `CONNECTORS_DIR` |
| 连接器安装任务（下载/校验/解压、取消、重启中断） | 真实实现（子进程为假 I/O 测试） | `tests/test_connectors_jobs.py` | 否 | 单任务互斥；下载有界重试；后端重启不自动续跑；成功事件区分 `installed/reused/repaired`，并明确“安装器尚未运行” |
| 官方安装器显式启动 | 部分实现 | `tests/test_connectors_process.py` | 否 | 交互式第三方 GUI，平台不代替用户操作 |
| 受管进程启动/停止/归属 | 部分实现 | `tests/test_connectors_process.py`、`test_connectors_manager.py` | 否 | 只停本会话进程；后端重启后拒绝接管或杀旧 PID |
| 连接器配置预览、加密快照与回滚 | 真实实现 | `tests/test_connectors_manager.py` | 否 | 仅 `v4.18.42` 自动写配置；失败自动恢复 |
| 诊断复用在线适配器 | 真实实现 | `tests/test_connectors_manager.py` | 否 | 无在线实例时临时建连并标注来源 |
| 身份确认与拉群门控 | 真实实现 | `tests/test_connectors_identity.py`、`test_connectors_api.py` | 否 | 必须匹配当前在线非 Mock 适配器 |
| 连接器真实收发状态（`traffic_verified`） | 真实实现（证据门控） | `tests/test_connectors_state.py` | 否 | 需身份确认后的非 Mock 持久化入站 + 成功出站 |
| 连接器配置导入 / 外部安装只读 | 真实实现 | `tests/test_connectors_manager.py`、`test_connectors_api.py` | 否 | 导入不写外部文件；Token 只返回掩码 |
| 桌面版选择连接器目录 | 真实实现 | `desktop/tests/settings.test.js`、`backend-env.test.js`、`preload.test.js` | 部分（本机单元测试） | 只打开系统目录对话框；重启后端生效 |
| 连接器自动更新 / 自动卸载 | 未实现（明确不支持） | `/api/connectors/capabilities` | 否 | 页面诚实标记 `false` |
| 真实 QQ 端到端验收 | 未执行 | [docs/testing/V0.2.2_REAL_ENV_ACCEPTANCE.md](../testing/V0.2.2_REAL_ENV_ACCEPTANCE.md) | 否 | 七个验收节点必须分开记录；连接成功不等于真实收发 |
| 多账号、评测回放、MCP、插件市场 | 规划 | 模块级占位 | 否 | 不在当前范围 |

## 最需要显式标注的五项

1. **真实 QQ 未验证**：连接诊断通过不等于真实群收发成功；`traffic_verified` 需要真实
   入站与出站证据，本仓库未产生。
2. **真实模型 Key 未联调**：真实 Provider 适配器只有 `httpx.MockTransport` 请求映射、错误分类、重试与模型列表测试；阶段 3 的连通性、真实生成、取消、预算与清空 Key 流程需用户用自有 Key 在本机验收。
3. **NapCat 安装器未执行**：官方包已下载、校验并解压，但未运行安装器、未登录 QQ；
   仓库未捆绑连接器，也不自动登录。安装目录复用、损坏隔离与下载重试只有假 I/O 测试，
   真实安装器行为仍需用户验收。
4. **连接器进程/配置只经假进程验证**：启动、停止、安装器与写配置路径有自动化测试，
   但没有在真实 NapCat 上执行；受管版本的自动配置仅覆盖文档验证的 `v4.18.42`。
   向导的“一键自动配置”会创建受管账号并写入加密 Token，但仍需用户自行启动 NapCat
   并完成 QQ 登录。
5. **安装包未签名、未在干净机器验收**：Windows NSIS 安装包已构建并通过隔离冒烟，但
   没有代码签名或自动更新；NSIS 安装/升级/回滚/卸载尚未在独立干净 Windows 机器执行，
   不得宣称生产就绪。

# 更新记录

所有构建与测试结论以仓库内实际执行记录为准；`release/BUILD_INFO.json` 与
`release/RELEASE_SMOKE.json` 是构建机生成的产物，不进入 Git。

## 0.2.1 — 最终审计与发布可复现性（2026-11-01）

### 修复与加固

- **备份恢复**：损坏或截断的备份文件现在会稳定返回 `BACKUP_INVALID`，不会在读取表计数
  时抛出未处理异常，也不会触碰当前数据库或留下 `*.restore-*` 暂存文件。
- **OneBot 发送**：空串/纯空白文本在发起任何 HTTP 请求前返回 `SEND_FAILED`，不更新
  `last_sent_at`。
- **冒烟隔离**：`scripts/smoke_test.py` 不再继承仓库 `.env`、密钥、数据目录、数据库或
  远程管理配置；显式使用临时目录并断言版本、数据目录、连接器目录与关闭远程管理。
- **发布构建**：`scripts/build_release.py` 构建前校验 Git 工作树（默认拒绝 dirty）、
  清理旧 `release/`、只收集当前版本产物、失败时清理半成品；`BUILD_INFO.json` 记录
  分支、dirty 状态与工作树指纹、Electron 实际版本与四处版本来源。
- **版本单一来源**：`Settings.app_version` 直接引用 `app.__version__`，构建脚本校验
  desktop/frontend/backend/pyproject 四处一致。
- **发布冒烟**：只接受当前版本对应的安装包，拒绝 `release/` 中残留的旧版本安装包。
- **清理**：删除未使用的 `response_preview()`、`_state_summary()` 与永远返回 501 的
  `/api/demo/reset-hint` 端点。

### 测试

- 新增损坏/截断备份恢复测试、空文本发送拒绝测试、NSIS 数据保留与安装参数的静态配置
  测试、版本单一来源测试、已移除端点回归测试。
- 静态 NSIS 测试只证明配置值，**不证明真实卸载行为**；干净机安装/卸载仍未执行。

### 已知限制

- 与 0.2.0 相同：真实 QQ 收发、真实模型 Key、干净机 NSIS 安装/升级/回滚/卸载、代码签名
  与自动更新均未验证；不宣称生产就绪。

## 0.2.0 — Windows 安装包与发布回归（2026-11-01）

### 新增

- **Windows x64 独立安装包**：PyInstaller 冻结后端（onedir）+ 冻结 NapCat 安装器 +
  Vite 生产前端 + Electron 壳，打包为 NSIS 安装程序。安装版自带运行时，用户无需安装
  Python/Node。
- **安装版运行时布局**：后端从 `resources/backend` 启动，前端从
  `resources/frontend/dist` 托管；首次启动在 Electron `userData` 下自动生成独立 `.env`
  密钥，不读取仓库 `.env`，不覆盖已有文件。
- **发布构建流水线**：`scripts/build_release.py` 使用固定命令完成版本一致性检查、前端
  构建、图标生成、后端/安装器冻结、Electron 打包、哈希清单与 `BUILD_INFO.json`。
- **干净环境发布冒烟**：`scripts/release_smoke.py` 在临时目录与临时密钥下验证安装版
  后端启动、Alembic 迁移、前端托管、版本/运行模式，以及安装版 Electron 的首次启动与
  截图；不读取真实 `.env`、数据或连接器目录。
- **发布文档**：新增本文、[docs/RELEASE.md](docs/RELEASE.md) 与
  [docs/implementation/TEST_MATRIX.md](docs/implementation/TEST_MATRIX.md)，记录安装、
  升级/回滚、卸载、数据保留、构建与测试分层。

### 修复与加固

- 冻结运行时正确解析资源根、Alembic 配置与默认前端目录；数据与受管连接器默认落在
  用户目录，安装目录保持只读。
- 安装版后端只监听 `127.0.0.1`，端口与日志级别经白名单校验，不接受命令行参数。
- 受管 NapCat 安装器在安装版中直接执行冻结的可执行文件，参数仍由后端固定生成，不使用
  `shell=True`。
- Electron 在安装版中以固定参数启动内置后端；源码版仍使用本机 `.venv` 的 Python。
- 桌面设置页显示「安装版（自带运行时）」或「源码版（需本机 Python/Node）」，不混淆。

### 已知限制

- **真实 QQ 端到端尚未验证**。安装包构建、冻结后端启动与 Mock 冒烟通过，不代表真实
  NapCat 登录、真实群入站或出站发送已验证。验收清单见 [docs/CONNECTOR.md](docs/CONNECTOR.md)。
- **真实模型 Key 尚未联调**。OpenAI 兼容与 Anthropic 原生适配器只使用本地
  `httpx.MockTransport` 验证。
- **安装包未签名**，Windows SmartScreen 可能提示未知发布者；本版本不提供自动更新。
- **NSIS 安装器/卸载器尚未在独立的干净 Windows 机器上执行**；发布冒烟使用同一安装包
  内容的 `win-unpacked` 目录，并隔离 `userData`、数据目录与密钥。
- 卸载默认**保留**用户数据（数据库、日志、备份、受管连接器与本地密钥）；需要彻底删除时
  须手工清理，详见 [docs/RELEASE.md](docs/RELEASE.md)。

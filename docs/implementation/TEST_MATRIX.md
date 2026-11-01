# 测试矩阵与证据分层

更新日期：2026-11-01
分支：`v1.3-phase1`

本文件区分「单元测试、集成/API 测试、Mock 端到端、打包运行时冒烟、安装器验收、
真实 QQ 端到端、真实模型验收」。同一结论只使用对应层级的证据，不用低层级测试冒充真实
环境验证。

## 1. 层级定义

| 层级 | 定义 | 是否接触外部服务 |
| --- | --- | --- |
| 单元 | 纯函数、策略、解析、格式、治理逻辑；临时对象或内存数据 | 否 |
| 集成 / API | 临时 SQLite、ASGI 生命周期、Alembic、路由、审计、适配器假服务器 | 否 |
| Mock 端到端 | Mock 连接器 + Mock 模型跑完整消息流水线、outbox、用量、备份 | 否 |
| 源码进程冒烟 | 真实 uvicorn + 临时数据目录 + 随机端口，执行 Mock 全链路 | 否 |
| 打包后端冒烟 | 冻结 `aiqf-backend.exe` 在隔离临时目录启动、迁移、托管前端 | 否 |
| 安装版桌面冒烟 | `win-unpacked` 的 Electron `--smoke`，临时 `userData`/数据/密钥 | 否 |
| 安装器验收 | 在独立干净 Windows 上运行 NSIS 安装、升级、回滚、卸载 | 否（但改系统安装状态） |
| 真实 QQ 端到端 | 真实 NapCat 登录、真实群入站与出站、诊断与证据门控 | **是** |
| 真实模型验收 | 真实 OpenAI-compatible / Anthropic Key 调用、计费与错误场景 | **是** |

## 2. 自动化层

### 2.1 后端

| 命令 | 覆盖 | 当前结果 |
| --- | --- | --- |
| `cd backend && .venv/Scripts/python.exe -m ruff format --check app tests` | 格式 | 通过：168 files already formatted |
| `... -m ruff check app tests` | 静态规则 | 通过：All checks passed |
| `... -m mypy app` | 类型 | 通过：no issues found in 134 source files |
| `... -m pytest -q` | 单元、集成、API、Mock 端到端 | 435 passed，1 warning（Starlette TestClient 的 httpx 弃用提示），101.26s |
| `... -m pytest -q tests/test_packaging.py` | 源码/冻结路径、环境文件、安装器可执行文件、入口参数 | 8 passed（阶段 8 定向） |

重点测试文件：

- `tests/test_pipeline.py`：去重、自身过滤、白名单、暂停、安静时段、限速、触发模式、
  outbox 未知状态不重发。
- `tests/test_api_smoke.py`：ASGI 生命周期、统一响应、Mock 闭环、安全头、备份与清理。
- `tests/test_phase6_security.py`：TrustedHost、CORS、SSRF 语法判定、日志脱敏、CSP。
- `tests/test_phase6_data_cleanup.py`：账号/群删除、媒体引用保护、待发取消、审计。
- `tests/test_phase6_backup_schema.py`：Schema 门禁、恢复中止、备份删除确认。
- `tests/test_phase6_messages_export.py`：CSV 编码、公式注入防护、行数上限、审计脱敏。
- `tests/test_phase7_extensions.py`：扩展契约、任务止损、适配器工厂、插件不执行。
- `tests/test_napcat_installer.py`：受管安装器的固定边界、哈希/解压/进程假 I/O。
- `tests/test_packaging.py`：`AI_GROUP_FRIEND_ENV_FILE`、资源根、冻结默认目录、
  `runtime_mode`、冻结安装器路径、打包入口端口/日志白名单、`app_version` 单一来源。
- `tests/test_backup_restore.py`：原子替换与全局暂停保持；截断/同大小随机损坏的备份返回
  `BACKUP_INVALID`，不触碰当前库、不写恢复审计、不产生安全备份或 `*.restore-*` 文件。
- `tests/test_onebot11.py`：空串/空白文本在发起任何 HTTP 请求前返回 `SEND_FAILED`，
  不更新 `last_sent_at`。

### 2.2 前端

| 命令 | 覆盖 | 当前结果 |
| --- | --- | --- |
| `cd frontend && npm run type-check` | vue-tsc | 通过（退出码 0） |
| `npm run test` | 状态映射、脱敏、格式化、确认词、API 客户端 | 9 files / 76 tests passed，3.35s |
| `npm run build` | Vite 生产构建 | 通过，8.53s；主 chunk 1,226.56 kB（gzip 395.29 kB），仅体积警告 |

重点文件：`tests/client.test.ts`（管理 Token 只进 `sessionStorage`）、
`tests/confirmation.test.ts`（`DELETE`/`CLEANUP` 精确匹配）、`tests/connectors.test.ts`、
`tests/diagnostics.test.ts`、`tests/onboarding.test.ts`、`tests/providers.test.ts`。

### 2.3 桌面壳

| 命令 | 覆盖 | 当前结果 |
| --- | --- | --- |
| `cd desktop && npm test` | 设置、路径、端口、后端环境、首次向导、安全边界、安装版布局 | 38 passed，0 failed，9.47s |
| `npm run smoke` | 源码版 Electron 首次启动、健康、`/onboarding`、截图 | 通过：`DESKTOP_SMOKE_OK`，版本 0.2.0，6 张截图 |

阶段 8 新增：

- `tests/packaged.test.js`（5 项）：安装版资源布局；显式环境变量清理；固定参数启动内置
  后端且不经过 Python；`userData/.env` 创建且不覆盖；安装包完整性自检。
- `tests/syntax.test.js`：Windows 脚本 BOM/CRLF 约束。

0.2.1 新增：

- `tests/packaging.test.js`：静态断言 NSIS 目标为 x64、`oneClick=false`、
  `perMachine=false`、`allowToChangeInstallationDirectory=true`、
  `deleteAppDataOnUninstall=false`，产物名含 `${version}`/`${arch}`。**只证明配置值，
  不证明真实卸载行为**。

### 2.4 源码进程 Mock 冒烟

```powershell
backend\.venv\Scripts\python.exe scripts\smoke_test.py
```

真实启动 uvicorn，使用临时数据目录、临时 `CONNECTORS_DIR`、随机密钥与随机端口；覆盖
Mock 闭环、安全头、CSV、备份 Schema、清理预览/确认、扩展契约等。0.2.1 起显式清除继承
的重定向/密钥/管理变量、指向不存在的临时 `.env`，并断言健康版本、数据目录、连接器目录
与远程管理关闭。**不接触真实 QQ、NapCat 或真实模型。**

### 2.5 打包运行时冒烟

```powershell
backend\.venv\Scripts\python.exe scripts\release_smoke.py
```

先从 `scripts/build_release.py` 生成发行包，再执行：

1. 安装版布局与 `BUILD_INFO.json` 哈希/大小，且 `release/` 中只存在当前版本的一个安装包；
2. 冻结后端：健康、版本、`runtime_mode=packaged`、隔离 `DATA_DIR`、内置前端、SQLite、
   Alembic 版本；
3. 安装版 Electron `--smoke`：临时 `userData`、首次启动 `/onboarding`、健康、6 张截图；
4. Electron `PATH` 仅系统目录，清除 Python/Node 环境变量。

当前结果：见 `release/RELEASE_SMOKE.json`（构建机生成，不进入 Git）。本文件记录通过与否，
不复制可能变化的临时路径。

## 3. 阶段 8 / 0.2.0 实测记录

执行日期：2026-11-01。以下结果均来自本机实际命令输出；构建机为 Windows 11 x64，
Python 3.14.5、Node v24.19.0、Electron 45.0.0。

| 命令 | 结果 |
| --- | --- |
| 后端 `ruff format --check app tests` / `ruff check app tests` / `mypy app` | 全部通过（168 文件格式、134 源文件类型） |
| 后端 `pytest -q` | 435 passed，1 warning，101.26s |
| 前端 `npm run type-check` / `npm run test` / `npm run build` | 类型通过；9 files / 76 tests passed；构建通过（体积警告） |
| 桌面 `npm test` | 38 passed，0 failed |
| 桌面 `npm run smoke` | `DESKTOP_SMOKE_OK`，版本 0.2.0，6 张截图 |
| `scripts/check.ps1` | 「全部检查通过」 |
| `scripts/smoke_test.py` | 「冒烟测试全部通过。未接触真实 QQ 或真实模型。」 |
| `scripts/build_release.py` | 成功生成 0.2.0 NSIS 安装包与 `win-unpacked`，写出 `BUILD_INFO.json` |
| `scripts/release_smoke.py` | 通过：布局/哈希、冻结后端 `runtime_mode=packaged`、Alembic `f4a7b2c9d801`、内置前端、6 张截图；桌面阶段 12.4s |
| 安装包 | `AI-Group-Friend-Setup-0.2.0-x64.exe`，155,826,158 bytes，SHA-256 `119f48c5…f9ecce` |
| `win-unpacked/AI 群友.exe` | 249,797,632 bytes，SHA-256 `c9732e4c…b9597363` |

**过程中的失败与修正（未隐藏）**：

- 后端 `tests/test_packaging.py` 首次 `ruff check` 报 `I001` 导入排序错误；执行
  `ruff check --fix` 后复检通过。该问题已计入上述最终通过结果，首次失败记录保留在此。
- 前端构建存在 `Some chunks are larger than 500 kB` 警告（主 chunk 1,226.56 kB）；
  这是性能提示，不是构建失败，尚未做代码分割。
- 后端测试的 1 条 warning 来自第三方 Starlette TestClient 对 `httpx` 的弃用提示，
  不影响测试通过。

构建产物与 `release/RELEASE_SMOKE.json` 位于本机 `release/`（不进入 Git）；本文件只记录
结果，不复制可能变化的临时路径。

### 3.1 0.2.1 最终审计实测记录（2026-11-01）

| 命令 | 实际结果 |
| --- | --- |
| 后端 `ruff format --check app tests` / `ruff check app tests` / `mypy app` | 通过（168 文件格式、134 源文件类型） |
| 后端 `pytest`（不带额外 `-q` 以显示汇总） | **442 passed**，1 warning，103.08s |
| 前端 `npm run type-check` / `npm run test` / `npm run build` | 类型通过；9 files / **76 tests passed**（2.05s）；构建通过（8.70s，体积警告） |
| 桌面 `npm test` | **39 passed，0 failed**（9.43s） |
| 桌面 `npm run smoke` | `DESKTOP_SMOKE_OK`，版本 **0.2.1**，6 张截图 |
| `scripts/check.ps1` | 全部检查通过；脚本末尾提示 GUI 截图冒烟未在 check 中运行 |
| `scripts/smoke_test.py` | 全部通过；未接触真实 QQ 或真实模型 |
| `scripts/build_release.py` / `scripts/release_smoke.py` | 提交 A 后执行，结果回填于 [FINAL_REPORT.md](FINAL_REPORT.md) 第 6 节 |

0.2.1 定向新增测试均包含在 442 项后端测试与 39 项桌面测试中：损坏/截断备份恢复、
空文本发送前拒绝、版本单一来源、已移除端点回归、NSIS 静态配置。静态 NSIS 测试只证明
配置值，不证明真实卸载行为。

## 4. 手工验收（尚未执行）

| 项目 | 需要什么 | 当前状态 |
| --- | --- | --- |
| NSIS 安装 / 升级 / 回滚 / 卸载 | 独立干净 Windows 10/11 x64 虚拟机或机器 | **未执行** |
| 安装包代码签名与 SmartScreen 行为 | 代码签名证书 | **未实现** |
| 真实 NapCat 下载/校验/解压与安装器 | 用户本机、官方包、交互式安装器 | 仅下载/校验/解压过 `v4.18.42`；安装器未运行 |
| 真实 QQ 登录 | 用户自有账号 | **未执行** |
| 真实群入站/出站与 `traffic_verified` | 受控群、真实登录 | **未执行** |
| 真实 OpenAI-compatible 模型 | 用户自有 Key 与端点 | **未执行** |
| 真实 Anthropic 模型 | 用户自有 Key | **未执行** |
| 真实入站/出站、暂停、重连、失败恢复演练 | 真实环境 | **未执行** |

## 5. 结论边界

- 可以声明：Windows x64 安装包已成功构建；冻结后端与安装版桌面壳在隔离临时环境中通过
  启动、迁移、健康、前端托管与截图冒烟。
- 不可以声明：真实 QQ 端到端已验证、真实模型已验证、安装器已在干净机器验收、安装包已
  签名、可以自动更新或生产就绪。
- 发布说明必须持续保留：**真实 QQ 端到端尚未验证；真实模型 Key 未联调；安装包未签名；
  NSIS 安装器未在独立干净机器执行。**

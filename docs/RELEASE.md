# 发行、安装、升级与卸载

本文件说明 AI 群友 0.2.2 的 Windows 发行包、构建流水线、干净环境冒烟、升级/回滚、
卸载与数据保留策略。**所有结论以实际构建与测试记录为准。**

## 0.2.2 发布说明

> **真实 QQ 端到端尚未验证。** 本版本没有在真实 NapCat 登录环境完成群消息入站与出站
> 发送验收。安装包、内置后端启动与 Mock 冒烟通过，不等于真实 QQ 可用。
>
> **真实模型 Key 尚未联调。** OpenAI 兼容与 Anthropic 原生 Provider 只通过本地
> `httpx.MockTransport` 测试请求映射、错误分类与重试。
>
> **不宣称生产就绪。** 安装包未签名、无自动更新；NSIS 安装器/卸载器尚未在独立的干净
> Windows 机器上执行。

0.2.2 在 0.2.1 的基础上强化受管 NapCat 安装：同版本完整目录复用、受管损坏目录隔离修复、
未知目录拒绝且不触碰、陈旧 staging 清理、有界下载重试与稳定 ZIP/占用/权限错误码。
接入向导新增可执行动作：只有一个可用受管 Shell 时，普通用户输入 `AUTO CONFIG` 即可
自动分配端口、生成加密 Token、写配置并创建账号，无需手填 WS/HTTP 地址；仍不会启动
连接器或登录 QQ。安装后仍自带 Python 后端、NapCat 受管安装器、前端构建产物与 Electron
运行时。完整变更见 [../CHANGELOG.md](../CHANGELOG.md)。

## 1. 发行产物

| 产物 | 说明 |
| --- | --- |
| `release/AI-Group-Friend-Setup-0.2.2-x64.exe` | NSIS 安装程序；per-user，可选安装目录，创建开始菜单与桌面快捷方式 |
| `release/win-unpacked/` | 与安装包同源的未打包目录；发布冒烟使用此目录，避免自动安装 |
| `release/BUILD_INFO.json` | 版本、构建时间、Git commit、Python/Node/Electron 版本、产物大小与 SHA-256 |
| `release/RELEASE_SMOKE.json` | 干净环境冒烟结果；只在构建机生成，不进入 Git |

`release/` 已被 `.gitignore` 排除。发布时只需分发安装程序与构建信息；不要把
`release/win-unpacked`、本机 `.env`、`data/` 或连接器目录一起打包。

### 0.2.2 本机构建记录（2026-11-01）

| 项目 | 实测值 |
| --- | --- |
| 版本 / Git | 0.2.2；基础提交 `da5f5dd`；分支 `v1.3-phase1`；**`git_dirty=true`** |
| 工作树指纹 | status `7f2a9e68…`、diff `e9c56ae8…`（完整值见 `BUILD_INFO.json`） |
| 安装包 | `AI-Group-Friend-Setup-0.2.2-x64.exe`；155,842,669 bytes；SHA-256 `35f7fb67ae00b116b105cd1ab04850446f60cb2b67d291fc21bd80237b6f3546` |
| `win-unpacked/AI 群友.exe` | 249,797,632 bytes；SHA-256 `e17c2e4185c16341cb63336c180e6dd5c08194be8eb375efb6386eabe8842e20` |
| 版本来源 | desktop/frontend/backend `__init__`/pyproject 均为 0.2.2；Electron 45.0.0 |
| 签名 / 干净机安装 | **未签名；未在独立干净机器执行安装/升级/回滚/卸载** |
| 发布冒烟 | 退出码 0；冻结后端 `runtime_mode=packaged`、版本 0.2.2、Alembic `f4a7b2c9d801`、内置前端、隔离数据目录；安装版 Electron 0.2.2、6 张截图、13.7s；`RELEASE_SMOKE.json` `status=ok` |

> **重要：本次 0.2.2 安装包在未提交工作树上构建，`BUILD_INFO.json` 明确记录
> `git_dirty=true` 与工作树指纹。** 它用于本机验证 0.2.2 代码，不代表可复现的已提交
> 构建；正式分发前应在干净提交上重新构建。
>
> 构建完成后仅修改了不进入安装包的 `scripts/smoke_test.py`（补齐向导 `counts` 断言）并
> 重跑源码进程冒烟；安装包内的后端、前端、桌面壳与连接器代码均未因此变化，故未重新
> 打包。当前工作树 diff 指纹会与 `BUILD_INFO.json` 中的构建时指纹不同。

### 0.2.1 本机构建记录（2026-11-01，历史）

| 项目 | 实测值 |
| --- | --- |
| 版本 / Git | 0.2.1；提交 `1aa8e9f`；分支 `v1.3-phase1`；`git_dirty=false` |
| 安装包 | 155,824,181 bytes；SHA-256 `bf3e95ba5520a0b97d14e766be27869a7c8033ad6e23c3495450b9d664af70be` |
| `win-unpacked/AI 群友.exe` | 249,797,632 bytes；SHA-256 `e92bee0e0ee98e6ed490636a02ba949b8fc5a1311cfa1392bee1be3f66eb3ae0` |
| 发布冒烟 | 通过；冻结后端 `runtime_mode=packaged`、Alembic `f4a7b2c9d801`、内置前端、6 张截图、12.2s |
| 签名 / 干净机安装 | **未签名；未在独立干净机器执行安装/升级/回滚/卸载** |

构建机为 Windows 11 x64、Python 3.14.5、Node v24.19.0、Electron 45.0.0。以上哈希只对应
本次本机构建，不能证明安装包来自可复现的公共构建，也不能替代代码签名。

### 校验哈希

PowerShell：

```powershell
Get-FileHash .\release\AI-Group-Friend-Setup-0.2.2-x64.exe -Algorithm SHA256
Get-Content .\release\BUILD_INFO.json
```

Git Bash：

```bash
sha256sum release/AI-Group-Friend-Setup-0.2.2-x64.exe
```

哈希以 `BUILD_INFO.json` 中对应条目为准。若哈希不一致，不要运行安装包。

## 2. 系统要求

- Windows 10/11 x64。
- 安装版**不需要** Python、Node.js、npm、git 或 Visual C++ 构建工具；运行时全部随包。
- 源码版仍需要 Python 3.12+、Node.js 20+；见 [README](../README.md)。
- 首次启动会创建本地数据库并执行迁移；需要可写的用户目录。
- 安装版的受管连接器不会随安装包分发。NapCat 仍由用户在「连接器」页显式下载、校验、
  运行安装器并自行登录，平台不代替用户完成这些步骤。

## 3. 安装与首次启动

1. 校验哈希后运行 `AI-Group-Friend-Setup-0.2.2-x64.exe`。
2. 安装器为 per-user，可修改安装目录；不要求管理员权限。安装包未签名，Windows
   SmartScreen 可能显示「未知发布者」，请先核对哈希再决定是否运行。
3. 启动「AI 群友」。首次启动会：
   - 在 Electron `userData` 下生成独立 `.env`（`APP_SECRET_KEY` 与
     `CREDENTIAL_ENCRYPTION_KEY`），**不会读取仓库 `.env`，也不会覆盖已有文件**；
   - 用内置后端在回环地址启动 FastAPI，自动执行 Alembic 迁移；
   - 打开 `/onboarding` 接入向导。
4. 按向导完成连接器、QQ 登录、连接测试、模型、选群、观察与开启回复。真实 QQ 登录由
   用户在 NapCat 中完成。

安装版不会把数据写入安装目录；程序目录可保持只读。

## 4. 数据、密钥与日志位置

| 内容 | 安装版默认位置 |
| --- | --- |
| 数据库 | `%APPDATA%\ai-group-friend-desktop\data\ai_group_friend.db` |
| 应用日志 | `%APPDATA%\ai-group-friend-desktop\data\logs\app.log` |
| 备份 | `%APPDATA%\ai-group-friend-desktop\data\backups\` |
| 媒体 | `%APPDATA%\ai-group-friend-desktop\data\media\` |
| 本地密钥 | `%APPDATA%\ai-group-friend-desktop\.env` |
| 受管连接器 | `%APPDATA%\ai-group-friend-desktop\connectors\napcat\`（可在连接器页改到其他绝对目录） |
| 桌面设置 | `%APPDATA%\ai-group-friend-desktop\settings.json` |
| 桌面日志 | `%APPDATA%\ai-group-friend-desktop\logs\desktop.log` |

注意：

- 在设置页修改数据目录后，新数据写入新目录，**不会自动迁移旧数据**。请先备份或复制。
- `CREDENTIAL_ENCRYPTION_KEY` 不在数据库、备份或安装包中。丢失后已保存的 OneBot Token
  与模型 API Key 无法解密。请离线保存一份恢复副本，但不要与数据库备份放在同一位置。
- 卸载程序不会删除上述 `userData` 内容。

## 5. 升级策略

当前版本**不提供自动更新**，也不会后台下载或执行代码。

推荐升级流程：

1. 在控制台「系统设置 → 备份」创建并校验一份数据库备份。
2. 完全退出应用（包括托盘），确认受管后端已停止。
3. 关闭应用后，将 `%APPDATA%\ai-group-friend-desktop` **整体复制**到安全位置。这包含
   数据库、密钥、设置与受管连接器；它是唯一能完整回滚到旧版本的数据快照。
4. 运行新版本安装程序，选择原安装目录覆盖安装。用户数据目录不在安装目录内，不会被覆盖。
5. 启动新版本；后端会在启动时执行 `AUTO_MIGRATE=true` 的 Alembic 迁移。
6. 在向导/诊断页确认后端健康、数据与凭证可用；先保持全局暂停，验证后再恢复回复。

升级不会自动迁移或复制外部数据目录；如你自定义过数据目录，请自行备份该目录。

## 6. 回滚策略

本版本没有自动降级，也不保证旧程序能读取新 Schema。数据库迁移通常是向前的；
**不要只把旧版安装程序覆盖到已迁移的新数据库上就期望正常启动**。

推荐回滚流程：

1. 完全退出应用。
2. 先复制当前 `%APPDATA%\ai-group-friend-desktop` 留档，避免丢失升级后产生的数据。
3. 用升级前复制的**旧版完整 `userData` 快照**替换当前目录；这会同时恢复旧数据库、旧设置
   与旧 `.env` 密钥。
4. 安装并启动旧版本安装包。
5. 使用升级前的备份或数据快照恢复业务数据；不要使用由新版本创建、Schema 更新的备份去
   恢复旧程序——恢复预览会标记为不兼容并拒绝。

如果无法提供升级前的数据快照，回滚只能恢复程序文件，旧版本可能无法读取已迁移的数据库。
因此升级前的完整 `userData` 复制是强制步骤。

## 7. 卸载与数据保留

### 默认行为

通过 Windows「设置 → 应用 → 已安装的应用 → AI 群友 → 卸载」，或运行安装目录中的卸载器。
卸载程序默认 **保留用户数据**（NSIS `deleteAppDataOnUninstall=false`）：

- 保留：`%APPDATA%\ai-group-friend-desktop\` 下的数据库、日志、备份、媒体、密钥、桌面
  设置与受管连接器目录。
- 删除：安装目录中的程序文件、快捷方式与卸载信息。
- 不会停止或卸载用户自行安装的 NapCat，也不会删除其进程或登录状态。

保留数据便于重装后继续使用，也意味着**卸载不等于删除敏感数据**。

### 彻底删除

确认不再需要数据后，手工删除：

1. `%APPDATA%\ai-group-friend-desktop\`（数据库、日志、备份、媒体、`.env` 密钥、设置）。
2. 如果你在设置中改过数据目录或连接器目录，删除对应目录。
3. 安装目录残留（通常卸载器已删除）。
4. 用户自行安装的 NapCat 及其配置目录（先退出 NapCat；平台不会代为卸载）。

> 删除 `.env` 后，即使保留了数据库，旧 Token/API Key 也无法解密。若以后可能需要恢复，
> 请先离线保存 `CREDENTIAL_ENCRYPTION_KEY`。

### 保留期

应用内的自动清理默认关闭；消息、日志、媒体保留天数可在「系统设置 → 数据保留」配置。
卸载不会触发清理。备份只包含数据库，不包含媒体、日志与加密密钥。

## 8. 从源码构建发行包

### 依赖

- Windows 10/11 x64。
- Python 3.12+（构建机已验证 3.14.5）。
- Node.js 20+ 与 npm（构建机已验证 Node 24.19.0）。
- 后端虚拟环境：

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev,packaging]"
cd ..\frontend
npm install
cd ..\desktop
npm install
cd ..
```

普通开发/测试只需 `.[dev]`；`packaging` extra 才会安装 PyInstaller。

### 构建

```powershell
backend\.venv\Scripts\python.exe scripts\build_release.py
```

流程与固定命令：

1. 检查 Git 工作树；存在未提交改动时默认拒绝构建。确需测试打包流程时使用
   `--allow-dirty`，`BUILD_INFO.json` 会记录 `git_dirty=true` 与工作树指纹。
2. 校验 `desktop/package.json`、`frontend/package.json`、`backend/app/__init__.py`、
   `backend/pyproject.toml` 版本一致；`Settings.app_version` 直接引用
   `app.__version__`，不维护第二份常量。Electron 版本从 `desktop/package.json` 读取，
   并与已安装的 `node_modules/electron` 交叉校验。
3. 清理仓库根 `release/`（拒绝符号链接/路径逃逸），避免旧安装包混入。
4. `npm run build`（前端）；可用 `--skip-frontend` 复用已有 `frontend/dist`。
5. `scripts/make_icon.py` 从 PNG 生成 ICO。
6. PyInstaller 构建 `backend/dist/aiqf-backend`（onedir）与
   `backend/dist/aiqf-napcat-installer.exe`（onefile），复制安装器到后端 `tools/`。
7. electron-builder 构建 NSIS；强制使用本机 `node_modules/electron/dist`，避免联网下载
   Electron；自动为 Node 加上 `--use-system-ca` 以完成 NSIS 工具下载。
8. 只收集 `AI-Group-Friend-Setup-{version}-x64.exe` 与 `win-unpacked/AI 群友.exe`，
   写入 `release/BUILD_INFO.json`：版本、构建时间、分支、commit、dirty 状态与指纹、
   四处版本来源、Python/Node/Electron 版本、产物字节数与 SHA-256，以及真实 QQ/模型/
   干净机安装均未验证的标记。构建失败会清理 `release/` 半成品。

只生成未打包目录：

```powershell
backend\.venv\Scripts\python.exe scripts\build_release.py --dir-only
```

构建脚本不读取本机 `.env`，不把 `data/`、日志、备份、连接器或凭证打入安装包；PyInstaller
规格只包含应用代码、Alembic 与 `tzdata`。

## 9. 干净环境发布冒烟

先构建发行包，再运行：

```powershell
backend\.venv\Scripts\python.exe scripts\release_smoke.py
```

它只使用固定路径与临时目录，不读取真实 `.env`、数据库、桌面设置或连接器目录：

1. 校验 `release/win-unpacked` 布局与 `BUILD_INFO.json` 中每个产物的 SHA-256/大小；
   要求 `release/` 中只存在 `BUILD_INFO.version` 对应的一个安装包，拒绝残留旧版本安装包。
2. 在临时目录生成随机密钥与独立 `.env`，直接启动冻结后端；检查健康、版本、
   `runtime_mode=packaged`、隔离数据目录、内置前端、数据库与 Alembic 版本。
3. 以 `--smoke` 启动安装版 Electron；其自身使用临时 `userData` 与临时数据目录。冒烟会
   重新走首次启动路径，进入 `/onboarding`，检查健康并生成 6 张截图。
4. 把 Electron 的 `PATH` 限制为系统目录，并清除 Python/Node 相关环境变量，验证安装版
   不依赖仓库 `.venv`、`node_modules` 或本机 Python/Node。
5. 结果写入 `release/RELEASE_SMOKE.json`。`--keep` 保留临时目录，`--skip-desktop` 只测
   冻结后端与布局。

**该冒烟不等于执行了 NSIS 安装器。** 它使用安装包同源的 `win-unpacked` 内容，避免在
构建机上创建快捷方式、注册表项或安装状态；在独立干净 Windows 机器上的安装、升级、
回滚与卸载仍需人工验收。

## 10. 测试分层

详细矩阵与命令见
[docs/implementation/TEST_MATRIX.md](implementation/TEST_MATRIX.md)。

| 层级 | 证明什么 | 不证明什么 |
| --- | --- | --- |
| 单元 / API 测试 | 模块、策略、错误码、Schema、安全边界 | 真实外部服务 |
| 集成 / Mock 闭环 | 消息流水线、outbox、备份恢复、Mock 模型/连接器 | 真实 QQ 或真实模型 |
| `scripts/smoke_test.py` | 真实 uvicorn + 临时数据库的完整本地闭环 | 打包后的运行时 |
| `scripts/release_smoke.py` | 冻结后端与安装版 Electron 在隔离环境可启动 | NSIS 安装器、真实 QQ |
| `desktop npm run smoke` | 源码版 Electron 首次启动与截图 | 安装版干净机器安装 |
| 真实 QQ 端到端 | 真实登录、入站、出站 | **本仓库未执行** |
| 真实模型 | 真实 Provider 请求与计费 | **本仓库未执行** |

## 11. 发布验收清单

- [x] 版本号在桌面、前端、后端包与 `pyproject.toml` 中一致。
- [x] 冻结后端、NapCat 受管安装器、前端产物与 Electron 均进入安装包。
- [x] `BUILD_INFO.json` 写入哈希与「真实 QQ/模型未验证」标记。
- [x] `scripts/release_smoke.py` 在隔离环境通过（冻结后端 + 安装版 Electron）。
- [x] 后端/前端/桌面单元测试与源码冒烟通过（见 TEST_MATRIX 与 ROADMAP 实测记录）。
- [ ] **在独立干净 Windows 机器上执行 NSIS 安装、升级、回滚与卸载。**
- [ ] **安装包代码签名**（本版本未签名）。
- [ ] **真实 QQ 端到端验收**（登录、入站、出站、诊断、`traffic_verified`）。
- [ ] **真实模型 Key 验收**（连通性、真实生成、预算、错误场景）。

以上未勾选项完成前，发布说明必须保留「真实 QQ 端到端尚未验证 / 未签名 / 不宣称生产就绪」。

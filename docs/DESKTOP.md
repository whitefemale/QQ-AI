# 桌面版说明

桌面版是同一套「AI 群友」管理平台的本机启动外壳。它使用 Electron 打开窗口、管理本机后端并加载管理控制台。桌面版有两种运行方式：

| 方式 | 运行时 | 数据与密钥 | 适用场景 |
| --- | --- | --- | --- |
| **安装版** | 安装包自带冻结后端、前端与 Electron；**不需要 Python/Node** | `%APPDATA%\ai-group-friend-desktop\` 下的独立 `.env`、数据与连接器 | 普通用户 |
| **源码版** | 复用仓库 `backend/.venv`、`frontend/dist` 与本机 Python/Node | 仓库根 `.env` 与 `data/`（默认） | 开发、调试、自行构建 |

两种方式都不提供自动更新。安装包未签名；**真实 QQ 端到端尚未验证**。

## 1. 启动方式

### 1.1 安装版

1. 校验并运行 `release/AI-Group-Friend-Setup-<版本>-x64.exe`（per-user，可选择安装目录）。
2. 启动安装后的「AI 群友」。首次运行会：
   - 自检 `resources/backend/aiqf-backend.exe`、受管 NapCat 安装器与
     `resources/frontend/dist/index.html`；
   - 在 `%APPDATA%\ai-group-friend-desktop\.env` 生成随机 `APP_SECRET_KEY` 与
     `CREDENTIAL_ENCRYPTION_KEY`；已有文件不会被覆盖，缺字段会明确报错；
   - 以固定参数启动内置后端（仅 `127.0.0.1`），自动执行 Alembic 迁移；
   - **首次启动进入「接入向导」**（`/onboarding`），后续启动进入仪表盘。
3. 不需要安装 Python、Node.js 或 npm；也不会连接仓库 `.venv`。

详见 [RELEASE.md](RELEASE.md)。

### 1.2 源码版

1. 确认已安装 Python 3.12+、Node.js 20+ 与 npm。
2. 双击仓库根目录的 `start-desktop.cmd`（或执行 `.\start-desktop.cmd`）。
3. 首次运行会：
   - 检查 `desktop/node_modules`，必要时执行 `npm install` 安装 Electron；
   - 打开蓝白橙启动向导；
   - 检查 Python/Node 版本；
   - 缺少 `backend/.venv` 时创建并安装后端运行依赖；
   - 缺少 `.env` 时调用 `scripts/gen_keys.py --write` 生成本地密钥；
   - 缺少 `frontend/dist/index.html` 时安装前端依赖并执行生产构建；
   - 启动本地后端，**首次启动进入「接入向导」**，后续启动进入仪表盘。

向导每一步都是幂等的：已完成/已存在的项目会显示“已存在 / 已就绪 / 无需构建”，不会重复安装，也不会覆盖现有 `.env`、数据库或构建产物。

### 1.3 源码版前置条件与网络

- 首次安装 Electron 需要下载约数百 MB；网络受限时可在启动前设置镜像：

  ```powershell
  $env:ELECTRON_MIRROR = "https://npmmirror.com/mirrors/electron/"
  .\start-desktop.cmd
  ```

- 启动器只负责引导 Electron；Python 与前置工具不会自动下载。
- 首次安装后端/前端依赖同样需要访问对应的包源。

## 2. 窗口、托盘与关闭

- 窗口直接加载 `http://127.0.0.1:<端口>`，与 REST API、SSE 和静态资源同源；不会用 `file://` 加载管理台。
- 默认 **关闭窗口 = 最小化到系统托盘**，后端继续运行。单击托盘图标或选择「打开控制台」可恢复窗口。
- 托盘菜单支持：打开控制台、打开接入向导、查看后端状态、启动/停止（外部后端为「断开外部后端」）/重启后端、打开数据/日志/备份目录、彻底退出。
- 选择「退出」或在设置中关闭“关闭窗口时最小化到托盘”后再关闭窗口，桌面版会先停止由它启动的后端，再退出。
- 如果连接的是**外部后端**（你自己在终端里启动的本项目），托盘与设置中的停止/重启/退出不会结束那个进程，只会断开桌面版的连接。

### 生命周期矩阵

| 场景 | 受管后端 | 外部后端 |
| --- | --- | --- |
| 托盘可用 + `closeToTray=true`，关闭窗口 | 隐藏窗口，后端继续运行 | 隐藏窗口，仅保持连接 |
| 托盘不可用，关闭窗口 | 按正常关闭退出，并停止受管后端 | 按正常关闭退出，仅断开连接 |
| 托盘「退出」 | 先停止受管进程再退出 | 只断开连接，不停止外部进程 |
| 托盘「停止后端」 | 停止本会话启动的进程树 | 只断开连接 |
| 窗口内重启后端 | 停止后重新启动 | 不允许，提示先在原终端停止 |

托盘可用性来自创建托盘的实际结果：图标缺失为 `icon_missing`，图标无法读取为 `icon_invalid`，创建失败为 `tray_error`，尚未初始化为 `not_initialized`。快照只返回 `{available, reason}`，不返回图标路径。**托盘不可用时「关闭窗口最小化到托盘」不会生效**，设置页会明确警告“关闭窗口将退出应用并停止受管后端”，不会假装已最小化。

首次启动、重启或从托盘打开向导时才会导航；后端健康探测发出的状态事件不会把用户从接入向导或设置页切走。

所有设置项都会即时保存到本机；其中自动启动与托盘行为立即生效，数据目录变更需要重启后端。

## 3. 桌面设置

进入管理台「系统设置 → 桌面版」：

| 设置/操作 | 说明 |
| --- | --- |
| 启动时自动启动后端 | 关闭后，启动桌面版只显示控制页，由你手动点击启动 |
| 关闭窗口时最小化到托盘 | 关闭后，关闭窗口即退出应用并停止受管后端 |
| 启动时显示主窗口 | 关闭后应用在托盘运行，需要时再从托盘打开 |
| 数据目录 | 安装版默认 `%APPDATA%\ai-group-friend-desktop\data`；源码版默认仓库 `data/`。修改后需重启后端生效 |
| 连接器目录 | 在「连接器」页通过系统目录选择；安装版默认 `%APPDATA%\ai-group-friend-desktop\connectors\napcat`，源码版默认 `connectors/napcat/`。修改后需重启后端生效 |
| 重启后端 | 重启受管后端并刷新控制台；外部后端不可重启 |
| 打开数据/日志/备份 | 只能打开这三个白名单目录，不接受任意路径 |
| 打开连接器目录 | 在「连接器」页打开当前受管根或用户选择的目录 |
| 打开发布页 | 打开固定的 GitHub Releases 页面，仅作手动更新入口 |

浏览器直接访问 `http://127.0.0.1:8000` 时，该卡片会如实显示“未在桌面版中运行”，不会伪造桌面能力。

## 4. 数据、日志与配置放在哪里

| 内容 | 安装版默认位置 | 源码版默认位置 |
| --- | --- | --- |
| 数据库 | `%APPDATA%\ai-group-friend-desktop\data\ai_group_friend.db` | `<仓库>/data/ai_group_friend.db` |
| 应用日志 | `...\data\logs\app.log` | `<仓库>/data/logs/app.log` |
| 备份 | `...\data\backups\` | `<仓库>/data/backups/` |
| 受管连接器 | `...\connectors\napcat\`，或连接器页选择的绝对目录 | `<仓库>/connectors/napcat/`，或所选目录 |
| 桌面设置 | `%APPDATA%\ai-group-friend-desktop\settings.json` | 同左 |
| 桌面日志 | `%APPDATA%\ai-group-friend-desktop\logs\desktop.log` | 同左 |
| 本地密钥 | `%APPDATA%\ai-group-friend-desktop\.env`（不进入安装包、数据库或备份） | 仓库根 `.env`（不进入 Git、数据库或备份） |

在设置中改到其他目录后，桌面版会把 `DATA_DIR` 与 `DATABASE_URL` 以**绝对路径**传给后端；切换目录不会迁移旧数据，请自行复制数据库或使用备份/恢复功能。

桌面版启动后端时会显式设置：

- `APP_HOST=127.0.0.1`、`APP_PORT=<实际端口>`；
- `DATA_DIR`、`DATABASE_URL`、`FRONTEND_DIST` 的绝对路径；
- 安装版额外传入 `AI_GROUP_FRIEND_ENV_FILE=<userData>/.env` 与
  `AI_GROUP_FRIEND_INSTALLER_EXE=<resources>/backend/tools/aiqf-napcat-installer.exe`；
- 用户选择了连接器目录时，传入绝对 `CONNECTORS_DIR`；安装版默认
  `<userData>/connectors/napcat`，源码版留空时后端使用仓库默认
  `<仓库根>/connectors/napcat`；
- `AUTO_MIGRATE=true`；
- 源码版额外设置 `PYTHONUTF8=1`、`PYTHONIOENCODING=utf-8`，工作目录固定为 `backend/`。

安装版会主动删除从父进程继承的 `AI_GROUP_FRIEND_ENV_FILE`、
`AI_GROUP_FRIEND_INSTALLER_EXE`、`AI_GROUP_FRIEND_RESOURCE_ROOT` 与空 `CONNECTORS_DIR`，
避免读取仓库或外部环境配置。已有 `.env` 的密钥不会被覆盖。

## 5. 后端进程与端口

- 优先使用 `8000`。如果该端口上已经是**本项目的健康后端**，桌面版直接连接它（外部模式），不会再启动第二个进程，避免两个进程同时写同一个 SQLite 数据库。
- 如果 `8000` 被其他程序占用，会在后续端口中选择空闲端口。
- 安装版以固定参数 `[]` 直接启动 `resources/backend/aiqf-backend.exe`；源码版以固定参数启动 `backend/.venv` 的 Python 与 uvicorn。两种方式都不接受渲染进程传入命令、路径或环境变量。
- 启动阶段轮询 `GET /api/health`，要求 `data.status === "ok"`，默认最长等待 60 秒。
- 后端进入 `running`/`external` 后，每 **12 秒**探测一次 `/api/health`，单次超时 **1.5 秒**，同一时间只允许一个探测（重叠 tick 直接跳过）。结果只写入 `backend.health`，结构为 `{state, lastCheckAt, latencyMs, consecutiveFailures, message}`。
- 前两次失败只累计次数并保持原健康状态；连续第 3 次失败标记 `degraded`；任何一次成功立即恢复 `healthy` 并清零。健康失败**不会**把 `running`/`external` 改成 `stopped`/`error`，也不会停止或重启进程。外部后端失败仍保持 `external`。
- 这里的健康只表示**后端 HTTP 进程可达性**，不代表 QQ 连接、连接器登录或模型可用；这些状态请以接入向导与诊断页为准。
- 后端启动失败时，控制页会显示失败步骤与日志尾部；可点击重试。已完成的步骤不会重复执行。
- 停止后端时先发送终止信号；Windows 下若超时仍未退出，使用 `taskkill /PID <pid> /T /F` 结束进程树，避免残留 Python 进程。
- 后端异常退出时，窗口切回控制页，而不是继续显示不可用的控制台。

### 外部后端与端口排查

```powershell
# 查看 8000 端口占用
Get-NetTCPConnection -LocalPort 8000 -State Listen |
  Select-Object LocalAddress, LocalPort, OwningProcess

# 若确认是本项目残留的 Python 进程，可结束它（请先核对进程）
Stop-Process -Id <PID>
```

## 6. 首次向导的限制与安全边界

- 向导只执行**代码中固定的命令与参数**，渲染进程不能传入任意命令、路径或 URL。
- Windows 下 npm/npx 的 `.cmd` 包装通过 `cmd.exe /d /s /c` 执行，参数逐项校验为安全字符；不启用 Node 的 `shell` 选项，避免未转义参数被 shell 解释。
- 目录打开、发布页与设置更新均通过 preload 白名单 IPC；不向页面暴露 `ipcRenderer`、`fs`、`child_process`。
- 窗口启用 `contextIsolation: true`、`nodeIntegration: false`、`sandbox: true`，并显式固定 `webSecurity: true`、`allowRunningInsecureContent: false`；只允许导航到本地启动页或当前本机后端源，禁止任意新窗口与外部导航。
- 默认会话的权限请求/检查处理器只允许 `clipboard-sanitized-write`；摄像头、麦克风、定位、通知、MIDI、全屏等请求一律拒绝，设备权限处理器固定拒绝，`will-attach-webview` 一律阻止。
- `shell/index.html` 带 CSP：`default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'none'; font-src 'self'; object-src 'none'; base-uri 'none'; form-action 'none'`。管理台页面由后端按 HTML 响应发送安全头与 CSP。
- 日志不记录 `.env` 密钥、Token 或 API Key；`CREDENTIAL_ENCRYPTION_KEY` 不会写入桌面设置或备份。
- 桌面壳本身**不安装、不登录、不启动 NapCat**，也不向页面新增连接器命令 IPC。受管
  连接器动作由本机后台在用户打开「连接器」页并输入确认词后执行：下载/校验/解压、启动
  官方安装器、启动/停止 NapCat、写配置与回滚。平台不代替用户完成安装器界面或 QQ 登录。
  详见 [CONNECTOR.md](CONNECTOR.md)。
- 连接器目录选择只打开系统目录对话框并把绝对路径写入设置；不读写文件、不执行命令。
- 无自动更新、无远程命令执行、无静默上传。

## 7. 更新与卸载

当前版本**不提供自动更新**。

### 7.1 安装版

- **升级**：创建控制台备份 → 完全退出应用 → 复制整个
  `%APPDATA%\ai-group-friend-desktop` → 运行新版本安装程序覆盖原安装目录 → 启动并确认数据。
- **回滚**：没有自动降级。退出应用后，用升级前的 `userData` 完整副本替换当前目录，再安装
  旧版本。不要用旧程序直接打开已迁移的新数据库；新版创建的备份可能因 Schema 不兼容被
  旧版拒绝。
- **卸载**：Windows「设置 → 应用」或安装目录卸载器。默认**保留** `userData`
  （数据库、日志、备份、媒体、`.env` 密钥、设置、受管连接器）与外部自定义数据目录；
  只删除程序文件与快捷方式。
- **彻底删除**：确认不再需要后，手工删除 `%APPDATA%\ai-group-friend-desktop\`、自定义
  数据/连接器目录与残留安装目录；自行安装的 NapCat 需自行退出并卸载。
- 删除 `.env` 后旧 Token/API Key 无法解密。若以后可能需要恢复，先离线保存
  `CREDENTIAL_ENCRYPTION_KEY`。

完整步骤与数据保留说明见 [RELEASE.md](RELEASE.md)。

### 7.2 源码版

- 更新代码后重新启动 `start-desktop.cmd` 即可；如果前端源文件发生变化，需要手工执行
  `cd frontend; npm run build`（桌面向导只在 `frontend/dist` 缺失时构建）。
- 更新依赖后可删除/重建 `.venv`、`desktop/node_modules` 或前端 `node_modules`，向导会补齐缺失项。
- 卸载：退出桌面版（确认后端已停止），按需删除以下内容：
  - `desktop/node_modules/`（Electron 与测试依赖）；
  - `frontend/node_modules/` 与 `frontend/dist/`（如需彻底移除构建产物）；
  - `backend/.venv/`（如需彻底移除后端虚拟环境）；
  - 数据目录（默认 `data/`）——**删除前请先备份数据库**；
  - 自行安装的连接器目录（默认 `connectors/napcat/`，不纳入 Git）——先退出 NapCat；
  - `%APPDATA%\ai-group-friend-desktop\`（桌面设置与桌面日志）。
- **不要删除或泄露 `.env`**，除非你已确认不再需要解密旧 Token/API Key；丢失 `CREDENTIAL_ENCRYPTION_KEY` 后旧凭证无法恢复。

## 8. 故障排查

| 现象 | 处理 |
| --- | --- |
| 安装版提示安装包不完整 | 重新安装或重新解压 `win-unpacked`；检查 `resources/backend/aiqf-backend.exe`、`resources/backend/tools/aiqf-napcat-installer.exe` 与 `resources/frontend/dist/index.html` 是否存在 |
| 安装版提示 `.env` 缺少有效密钥 | 不要手工填写弱密钥；备份并移走 `%APPDATA%\ai-group-friend-desktop\.env` 后重启，让应用重新生成；注意旧凭证依赖原密钥 |
| Windows 提示未知发布者 | 安装包未签名。先按 `BUILD_INFO.json` 校验 SHA-256，再决定是否运行；不要在来源不明的安装包上绕过提示 |
| 提示未找到 Python / Node（源码版） | 安装 Python 3.12+、Node.js 20+，确认 `python --version`、`node --version`、`npm --version` 在终端可用后重试 |
| Electron 下载失败 | 设置 `ELECTRON_MIRROR` 镜像后删除 `desktop/node_modules` 重试，或检查代理/网络 |
| 提示 `.env` 缺少有效密钥 | 向导不会覆盖现有 `.env`；请备份后手工修复或用新目录重新生成，注意旧凭证依赖原密钥 |
| 页面显示“前端尚未构建” | 在 `frontend/` 执行 `npm run build`；向导只在 dist 缺失时自动构建 |
| 后端启动超时 | 查看控制页日志与 `<数据目录>/logs/app.log`；检查端口占用、依赖是否完整、数据库是否损坏 |
| 关闭窗口后找不到应用 | 应用在系统托盘；单击托盘图标恢复，或从托盘选择退出 |
| 退出后仍有 Python 进程 | 用上文端口/进程命令核对；若确认是残留后端，可手工结束 |
| 外部后端无法重启 | 这是设计行为；请先在启动它的终端中停止该后端，再由桌面版接管 |
| 管理台数据与预期目录不符 | 设置中的目录变更需重启后端；外部后端可能使用它自己的数据目录 |
| 连接器页提示无法选择目录 | 目录选择仅在桌面版可用；浏览器模式请使用当前受管根或手工设置 `CONNECTORS_DIR` 后重启后端 |
| 连接器页看不到新目录 | 目录设置在重启后端后生效；重启后点「重新扫描」 |
| 重启后无法停止 NapCat | 旧进程归属未知，属于预期保护；请手动关闭 NapCat，平台不会按端口杀进程 |

## 9. 自检命令

桌面壳单元测试（不需要打开窗口）：

```powershell
cd desktop
npm test
```

真实截图冒烟（使用独立临时 userData、临时数据目录、随机密钥与非 8000 端口，不连接用户的后端，不接触真实 QQ/模型）：

```powershell
cd desktop
npm run smoke
```

冒烟会先启动临时后端截取控制页/仪表盘/设置，再停止后端并**重新走一遍首次启动路径**（向导检查 + 后端启动 + 导航），断言首次启动进入 `/onboarding`、后端健康状态为 `healthy`、快照包含托盘可用性字段，再打开 `/diagnostics` 截图。成功后输出 `DESKTOP_STARTUP_OK` 与 `DESKTOP_SMOKE_OK`，并把 `shell.png`、`dashboard.png`、`settings.png`、`startup.png`、`onboarding.png`、`diagnostics.png` 写入 `desktop/.smoke/`。该目录、Electron 依赖与缓存均不进入 Git。

`npm test` 中的 `security.test.js` 静态断言 `webSecurity: true`、`allowRunningInsecureContent: false`、权限处理器仅允许 `clipboard-sanitized-write`、设备权限拒绝、阻止 `will-attach-webview`，以及 shell 页 CSP 含 `connect-src 'none'`。这些单元测试只能证明代码配置存在；真实系统权限弹窗、下载或页面行为仍需人工验收。

安装版冒烟（先构建发行包；隔离临时 `userData`、数据目录、密钥与系统级 `PATH`）：

```powershell
backend\.venv\Scripts\python.exe scripts\release_smoke.py
```

它会校验 `win-unpacked` 布局与哈希、启动冻结后端验证迁移/健康/前端托管，再启动安装版
Electron `--smoke`，断言版本、首次启动 `/onboarding`、健康与 6 张截图。**不会执行 NSIS
安装器**，也不会读取真实 `.env`、数据或连接器目录。

源码自动化检查（后端 + 前端 + 桌面单元测试；不含 GUI 冒烟、真实进程冒烟、发行构建与
发行冒烟）见根目录 `scripts/check.ps1`；发行构建与安装/升级/卸载说明见
[RELEASE.md](RELEASE.md)。

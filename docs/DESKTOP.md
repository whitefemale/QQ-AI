# 桌面版说明

桌面版是同一套「AI 群友」管理平台的本机启动外壳。它使用 Electron 打开一个窗口，自动检查本地依赖、启动本仓库的后端，并加载现有的管理控制台。它不是免安装包，**仍然使用你本机的 Python 与 Node.js**，也不提供自动更新。

## 1. 启动方式

1. 确认已安装 Python 3.12+、Node.js 20+ 与 npm。
2. 双击仓库根目录的 `start-desktop.cmd`。
3. 首次运行会：
   - 检查 `desktop/node_modules`，必要时执行 `npm install` 安装 Electron；
   - 打开蓝白橙启动向导；
   - 检查 Python/Node 版本；
   - 缺少 `backend/.venv` 时创建并安装后端运行依赖；
   - 缺少 `.env` 时调用 `scripts/gen_keys.py --write` 生成本地密钥；
   - 缺少 `frontend/dist/index.html` 时安装前端依赖并执行生产构建；
   - 启动本地后端并打开管理控制台。

向导每一步都是幂等的：已完成/已存在的项目会显示“已存在 / 已就绪 / 无需构建”，不会重复安装，也不会覆盖现有 `.env`、数据库或构建产物。

也可在 PowerShell 中执行：

```powershell
.\start-desktop.cmd
```

### 前置条件与网络

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
- 托盘菜单支持：打开控制台、查看后端状态、启动/停止/重启后端、打开数据/日志/备份目录、彻底退出。
- 选择「退出」或在设置中关闭“关闭窗口时最小化到托盘”后再关闭窗口，桌面版会先停止由它启动的后端，再退出。
- 如果连接的是**外部后端**（你自己在终端里启动的本项目），托盘与设置中的重启/退出不会结束那个进程，只会断开桌面版的连接。

所有设置项都会即时保存到本机；其中自动启动与托盘行为立即生效，数据目录变更需要重启后端。

## 3. 桌面设置

进入管理台「系统设置 → 桌面版」：

| 设置/操作 | 说明 |
| --- | --- |
| 启动时自动启动后端 | 关闭后，启动桌面版只显示控制页，由你手动点击启动 |
| 关闭窗口时最小化到托盘 | 关闭后，关闭窗口即退出应用并停止受管后端 |
| 启动时显示主窗口 | 关闭后应用在托盘运行，需要时再从托盘打开 |
| 数据目录 | 默认是仓库的 `data/`；修改后需重启后端生效 |
| 重启后端 | 重启受管后端并刷新控制台；外部后端不可重启 |
| 打开数据/日志/备份 | 只能打开这三个白名单目录，不接受任意路径 |
| 打开发布页 | 打开固定的 GitHub Releases 页面，仅作手动更新入口 |

浏览器直接访问 `http://127.0.0.1:8000` 时，该卡片会如实显示“未在桌面版中运行”，不会伪造桌面能力。

## 4. 数据、日志与配置放在哪里

| 内容 | 默认位置 |
| --- | --- |
| 数据库 | `<数据目录>/ai_group_friend.db` |
| 应用日志 | `<数据目录>/logs/app.log` |
| 备份 | `<数据目录>/backups/` |
| 桌面设置 | `%APPDATA%\ai-group-friend-desktop\settings.json` |
| 桌面日志 | `%APPDATA%\ai-group-friend-desktop\logs\desktop.log` |
| 本地密钥 | 仓库根目录 `.env`（不进入 Git、数据库或备份） |

默认数据目录是仓库根目录下的 `data/`。在设置中改到其他目录后，桌面版会把 `DATA_DIR` 与 `DATABASE_URL` 以**绝对路径**传给后端；切换目录不会迁移旧数据，请自行复制数据库或使用备份/恢复功能。

桌面版启动后端时会显式设置：

- `APP_HOST=127.0.0.1`、`APP_PORT=<实际端口>`；
- `PYTHONUTF8=1`、`PYTHONIOENCODING=utf-8`；
- `DATA_DIR`、`DATABASE_URL`、`FRONTEND_DIST` 的绝对路径；
- `AUTO_MIGRATE=true`。

`.env` 中的密钥与其他配置不会被覆盖；后端工作目录固定为 `backend/`。

## 5. 后端进程与端口

- 优先使用 `8000`。如果该端口上已经是**本项目的健康后端**，桌面版直接连接它（外部模式），不会再启动第二个进程，避免两个进程同时写同一个 SQLite 数据库。
- 如果 `8000` 被其他程序占用，会在后续端口中选择空闲端口。
- 健康检查轮询 `GET /api/health`，要求 `data.status === "ok"`，默认最长等待 60 秒。
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
- 窗口启用 `contextIsolation: true`、`nodeIntegration: false`、`sandbox: true`；只允许导航到本地启动页或当前本机后端源，禁止任意新窗口与外部导航。
- 日志不记录 `.env` 密钥、Token 或 API Key；`CREDENTIAL_ENCRYPTION_KEY` 不会写入桌面设置或备份。
- 无自动更新、无远程命令执行、无静默上传。

## 7. 更新与卸载

当前版本**不提供自动更新**，也没有安装器：

- 更新代码后重新启动 `start-desktop.cmd` 即可；如果前端源文件发生变化，需要手工执行 `cd frontend; npm run build`（桌面向导只在 `frontend/dist` 缺失时构建）。
- 更新依赖后可删除/重建 `.venv` 或前端 `node_modules`，向导会补齐缺失项。
- 卸载：退出桌面版（确认后端已停止），按需删除以下内容：
  - `desktop/node_modules/`（Electron 与测试依赖）；
  - `frontend/node_modules/` 与 `frontend/dist/`（如需彻底移除构建产物）；
  - `backend/.venv/`（如需彻底移除后端虚拟环境）；
  - 数据目录（默认 `data/`）——**删除前请先备份数据库**；
  - `%APPDATA%\ai-group-friend-desktop\`（桌面设置与桌面日志）。
- **不要删除或泄露 `.env`**，除非你已确认不再需要解密旧 Token/API Key；丢失 `CREDENTIAL_ENCRYPTION_KEY` 后旧凭证无法恢复。

## 8. 故障排查

| 现象 | 处理 |
| --- | --- |
| 提示未找到 Python / Node | 安装 Python 3.12+、Node.js 20+，确认 `python --version`、`node --version`、`npm --version` 在终端可用后重试 |
| Electron 下载失败 | 设置 `ELECTRON_MIRROR` 镜像后删除 `desktop/node_modules` 重试，或检查代理/网络 |
| 提示 `.env` 缺少有效密钥 | 向导不会覆盖现有 `.env`；请备份后手工修复或用新目录重新生成，注意旧凭证依赖原密钥 |
| 页面显示“前端尚未构建” | 在 `frontend/` 执行 `npm run build`；向导只在 dist 缺失时自动构建 |
| 后端启动超时 | 查看控制页日志与 `<数据目录>/logs/app.log`；检查端口占用、依赖是否完整、数据库是否损坏 |
| 关闭窗口后找不到应用 | 应用在系统托盘；单击托盘图标恢复，或从托盘选择退出 |
| 退出后仍有 Python 进程 | 用上文端口/进程命令核对；若确认是残留后端，可手工结束 |
| 外部后端无法重启 | 这是设计行为；请先在启动它的终端中停止该后端，再由桌面版接管 |
| 管理台数据与预期目录不符 | 设置中的目录变更需重启后端；外部后端可能使用它自己的数据目录 |

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

冒烟会先启动临时后端截取控制页/仪表盘/设置，再停止后端并**重新走一遍首次启动路径**（向导检查 + 后端启动 + 导航），成功后输出 `DESKTOP_STARTUP_OK` 与 `DESKTOP_SMOKE_OK`，并把 `shell.png`、`dashboard.png`、`settings.png`、`startup.png` 写入 `desktop/.smoke/`。该目录、Electron 依赖与缓存均不进入 Git。

完整质量检查（后端 + 前端 + 桌面单元测试）见根目录 `scripts/check.ps1`。

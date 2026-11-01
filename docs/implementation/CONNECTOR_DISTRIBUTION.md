# 连接器分发决策（NapCat）

更新日期：2026-10-31

## 结论

本仓库**不捆绑、不提交、不再分发** NapCat 二进制文件。用户明确确认后，平台或命令行
脚本才从 NapCat 官方 GitHub Release 下载 OneKey 包，校验后解压到受管目录。
`connectors/` 已被 `.gitignore` 忽略。

受管流程中的每一个第三方动作都需要用户在**本机回环页面**输入确认词：

| 动作 | 入口 | 确认词 |
| --- | --- | --- |
| 下载/校验/解压 | 连接器页安装任务 | `INSTALL` |
| 取消下载任务 | 连接器页任务面板 | `CANCEL` |
| 运行官方安装器 | 连接器页 | `RUN INSTALLER` |
| 启动 NapCat | 连接器页 | `START NAPCAT` |
| 停止本会话进程 | 连接器页 | `STOP NAPCAT` |
| 写配置并创建实例 | 连接器页 | `WRITE CONFIG` |
| 恢复配置快照 | 连接器页 | `RESTORE CONFIG` |
| 切换活动版本 | 连接器页 | `SWITCH VERSION` |
| 导入配置 | 连接器页 | `IMPORT CONFIG` |
| 确认 QQ 身份 | 连接器页 | `CONFIRM IDENTITY` |

确认词不匹配、请求来自非回环地址、Host/Origin 异常或全局紧急暂停生效时，动作被拒绝。
所有写操作写审计，审计不包含 Token、配置正文或完整本机路径清单。

平台不实现静默安装、后台自动更新、自动升级或自动卸载。下载任务失败或被取消后可以
重试，但不会断点续传或自动续跑；后端重启会把运行中的任务标为 `interrupted`。

## 来源与版本

- 项目：`NapNeko/NapCatQQ`（<https://github.com/NapNeko/NapCatQQ>）
- Release API：`https://api.github.com/repos/NapNeko/NapCatQQ/releases/latest`
- 资产名：`NapCat.Shell.Windows.OneKey.zip`（只接受这个精确名称）
- 2026-10-31 实际下载/校验的版本：`v4.18.42`
- 观察到的资产大小：`994134` 字节
- 观察到的 GitHub digest：`sha256:46c3ec155aa61f12e89bbf97013a21243d00b0019b5565992a88852d7627f39c`
- 下载 URL：`https://github.com/NapNeko/NapCatQQ/releases/download/v4.18.42/NapCat.Shell.Windows.OneKey.zip`

版本、大小和 digest 会随上游更新变化；脚本**不硬编码**上述值，而是在每次运行时从
Release API 读取并校验。本页的数值只是本轮审计时观察到的结果。

## 下载与解压防护

1. 只允许 `https`；主机白名单为 `api.github.com`、`github.com`、
   `release-assets.githubusercontent.com`、`objects.githubusercontent.com`。
2. 拒绝 userinfo、IP 字面量、非默认 HTTPS 端口和非法端口。
3. 自定义重定向处理器逐个校验跳转目标，最多 5 次跳转。
4. 资产必须带有合法的 `sha256:<64 hex>` digest；缺失或格式错误直接拒绝下载。
5. 流式写入临时 staging 文件，同时计算 SHA-256；核对 `Content-Length`、
   Release 声明的 `size`、实际字节数和 digest。任一不符即删除临时文件并报错。
6. 解压前拒绝绝对路径、盘符、`..`、空/`.` 组件、NUL、控制字符、反斜杠、冒号/ADS、
   Windows 保留名、尾随空格/点、符号链接、特殊文件与大小写不敏感重复路径。
7. 限制条目数不超过 200、单文件和总解压大小不超过 50 MB；校验必须存在
   `NapCatInstaller.exe`。
8. 全部校验通过后才把 staging 目录原子重命名为最终目录；目标已存在时拒绝覆盖。

受管安装只从 `CONNECTORS_DIR`（默认 `<仓库根>/connectors/napcat`）扫描，深度与条目
数受限，拒绝符号链接/junction 与越界路径。候选 shell 必须包含 `napcat.bat` 及至少一个
布局标记（`config/`、`NapCatWinBootMain.exe`、`package.json`）。不在该根目录内的外部
安装不会被接管，只能通过配置导入或高级手动设置以 `external_readonly` 接入。

## 第三方程序执行边界

安全模型的窄化例外只允许：

1. 本次后端进程创建的子进程：受校验的 `scripts/install_napcat.py`；
2. 受管安装内的 `NapCatInstaller.exe`（启动前重新核对 manifest SHA-256）；
3. 受管安装内的 `napcat.bat`，经绝对 `cmd.exe /d /s /c` 固定调用；
4. 绝对路径 `%SystemRoot%\System32\taskkill.exe`，仅用于停止本会话仍跟踪的进程树。

所有调用固定参数、`shell=False`、无提权、工作目录限定在受管目录；不提供任意命令、
任意参数、任意 URL 或任意文件读写接口。子进程环境使用允许列表，不继承
`CREDENTIAL_ENCRYPTION_KEY`、`APP_SECRET_KEY`、`ADMIN_API_TOKEN` 或数据库连接等敏感
变量。

**不实现任意 Shell/PowerShell/Python 执行、任意文件读写、任意 URL 请求或 SSRF。**
上述例外之外没有任何执行权限。

## 配置写入与快照

- 只写受管安装的 `config/onebot11.json` 或用户确认后的
  `config/onebot11_<QQ>.json`；最大 20 个文件、每个 256 KiB，结构未知即拒绝。
- 写入前要求进程停止、端口可用、版本兼容、Token 加密密钥可用。
- 先加密快照（Fernet，复用 `CredentialCipher`），再临时文件 + `fsync` + `os.replace`
  原子替换，并回读校验端口与 Token。
- 文件或数据库任一步失败：恢复配置快照与该实例旧的加密 Token/端点；恢复失败返回
  `CONNECTOR_ROLLBACK_FAILED`，不假装成功。
- 每个配置文件保留最近 10 组快照；快照正文永不通过 API 返回，也不写普通日志。
- 自动写配置只支持文档验证版本（当前 `v4.18.42`）；其他版本只能检测/手动配置/导入。

NapCat 的配置协议要求 Token 以明文存在于其文件中。平台只保证自身数据库加密、接口
掩码、日志与审计脱敏，**不能**保证第三方配置文件权限；请确认受管目录的本地访问控制。

## 许可证

NapCat 仓库声明的是 **NapCat Limited Redistribution License**，不是标准 OSI 开源
许可证。该许可证通常包含非商业使用、保留完整许可证与来源、修改版本分发限制等条款。
**本仓库没有对许可证全文做法律审查，也不据此授予任何再分发权利。**

脚本会通过 GitHub contents API 尝试把该 tag 的 `LICENSE*` 保存为
`connectors/napcat/<版本>/LICENSE-NapCat.txt`，并在 `manifest.json` 中记录来源与 blob
SHA。获取失败时标记 `license.status="unavailable"` 并打印警告，不声称许可证已审阅。

使用者应在安装、使用或再分发前自行阅读官方许可证全文，并自行承担合规责任。由于
许可条款可能限制再分发，本仓库选择不捆绑连接器，只提供用户显式触发的下载脚本和
本机受管页面。

## 安装目录、数据与卸载

- 默认安装根目录：`<仓库根>/connectors/napcat/`；每个版本一个子目录。桌面版可通过
  系统目录选择改写 `connectorsDir`，重启后端后传给 `CONNECTORS_DIR`。
- `manifest.json` 记录版本、资产 URL、大小、digest、许可证状态、安装器相对路径与
  SHA-256、安装时间及下一步。`manifest.json` 含 `real_qq_verified: false`，不表示
  已通过真实 QQ 验收。
- 升级采用并存安装：新版本写入新目录，不覆盖、不删除旧版本；`SWITCH VERSION` 只切换
  数据库活动指针。平台不自动更新、不后台检查更新、不自动卸载。
- 卸载：先退出 NapCat 与控制台，手动删除对应的 `connectors/napcat/<版本>/`。平台不
  提供删除 API，避免误删第三方与 QQ 数据。NapCat 自行创建的 QQ 数据目录不在此目录内，
  需在 NapCat 文档指引下单独处理。
- 本项目的数据目录（`data/`）不会因删除连接器而被清理；如需删除消息、媒体与日志，
  请使用控制台的数据保留功能或手动处理，并先完成备份评估。

## 未执行事项

- 已通过脚本默认流程下载并校验完整 OneKey 包，安全解压到
  `connectors/napcat/v4.18.42/`；没有运行 `NapCatInstaller.exe`。
- 受管安装器、启动/停止、配置写入与版本切换只由自动化测试中的假进程/临时目录验证；
  没有用真实 QQ 登录、没有启动真实 WebSocket/HTTP API、没有发送真实消息。
- 真实环境验收清单见 [CONNECTOR.md](../CONNECTOR.md) 与
  [PROGRESS.md](PROGRESS.md)，必须由账号所有者在本机完成。

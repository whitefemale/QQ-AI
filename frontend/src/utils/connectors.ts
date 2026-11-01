/**
 * 连接器状态的纯展示逻辑。
 *
 * 这里刻意不让「安装包存在 / 进程存活 / WebSocket 在线」被渲染成绿色成功；
 * 只有后端给出真实入站 + 出站证据的 traffic_verified 才是成功。
 */

import type { ConnectorInstallation, ConnectorJob, ConnectorStateName } from '@/api/types'
import type { TagType } from '@/utils/format'

export const CONNECTOR_STATE_LABELS: Record<ConnectorStateName, string> = {
  not_installed: '未安装',
  installing: '安装任务运行中',
  installer_ready: '安装包已解压 · 安装器未运行',
  installer_running: '安装器运行中',
  installed_not_started: '已安装 · 未启动',
  starting: '启动中',
  waiting_login: '等待登录（推断）',
  logged_in_not_connected: '已登录 · 未连接（推断）',
  connected_traffic_unverified: '已连接 · 真实收发未验证',
  traffic_verified: '观察到真实双向收发',
  interrupted: '中断',
  running_unmanaged: '外部进程运行中 · 归属未知',
  auth_failed: '鉴权失败',
  incompatible: '版本不兼容',
  external_readonly: '外部安装 · 只读',
  unknown_error: '未知错误',
}

export const CONNECTOR_STATE_NOTES: Record<ConnectorStateName, string> = {
  not_installed: '尚未检测到受管连接器。',
  installing: '正在下载、校验或解压安装包；这不代表已安装或已登录。',
  installer_ready: '安装包已解压，但官方交互式安装器尚未运行。',
  installer_running: '官方安装器是第三方交互式程序，请在它的窗口内完成安装。',
  installed_not_started: '检测到合格 shell，但连接器进程未启动。',
  starting: '本会话已启动连接器，尚未观察到登录身份。',
  waiting_login: '根据端口监听推断，尚未确认 QQ 登录；这是推断而非验证。',
  logged_in_not_connected: 'HTTP 身份探测成功，但 WebSocket 尚未连接；这是推断。',
  connected_traffic_unverified: 'WebSocket 与身份验证通过，但没有真实群收发记录。',
  traffic_verified: '观察到的真实入站与成功出站记录；不是诊断自动验证。',
  interrupted: '后端重启或任务中断；进程归属无法安全确认，请手动检查。',
  running_unmanaged: '端口被非本会话进程占用；平台不会接管或终止它。',
  auth_failed: '连接器拒绝了 Token 或鉴权失败。',
  incompatible: '版本或配置布局无法识别，禁止自动写配置。',
  external_readonly: '外部安装只读；请使用配置导入或高级手动设置。',
  unknown_error: '状态推导失败；请重新扫描并查看日志。',
}

export function connectorStateLabel(state?: string | null): string {
  if (!state) return '状态未知'
  return CONNECTOR_STATE_LABELS[state as ConnectorStateName] ?? state
}

export function connectorStateNote(state?: string | null): string {
  if (!state) return '状态未知；不要假定连接可用。'
  return CONNECTOR_STATE_NOTES[state as ConnectorStateName] ?? '未识别的状态；请重新扫描后确认。'
}

/** 只有 traffic_verified 可以显示成功；其余最多展示信息/警告/错误。 */
export function connectorStateTag(state?: string | null): TagType {
  if (state === 'traffic_verified') return 'success'
  if (state === 'auth_failed' || state === 'incompatible' || state === 'unknown_error') return 'danger'
  if (
    state === 'installer_ready' ||
    state === 'waiting_login' ||
    state === 'logged_in_not_connected' ||
    state === 'connected_traffic_unverified' ||
    state === 'running_unmanaged' ||
    state === 'interrupted' ||
    state === 'external_readonly'
  ) {
    return 'warning'
  }
  return 'info'
}

export function connectorStateNextSteps(installation: ConnectorInstallation): string[] {
  if (installation.next_steps?.length) return installation.next_steps
  if (installation.state?.next_steps?.length) return installation.state.next_steps
  return [connectorStateNote(installation.state?.state ?? installation.last_state)]
}

/** 进程字段绝不会被用来推导“在线”。 */
export function connectorProcessText(installation: ConnectorInstallation): string {
  if (installation.process.owned && installation.process.alive) {
    return `本会话受管进程运行中（启动于 ${installation.process.started_at ?? '未知时间'}）`
  }
  if (installation.port_listening) {
    return '端口在监听，但不是本会话启动的进程；归属未知，请手动确认后关闭重复实例'
  }
  return '未检测到本会话受管进程'
}

export function connectorInstallerText(installation: ConnectorInstallation): string {
  if (installation.installer.owned && installation.installer.alive) return '本会话启动的安装器仍在运行'
  if (installation.installer_launched_at) return '本会话曾启动安装器，当前已无受管安装器进程'
  return '本会话尚未启动安装器'
}

export function isRealTrafficVerified(installation: ConnectorInstallation): boolean {
  return installation.state?.state === 'traffic_verified' && installation.real_traffic_verified === true
}

export function connectorIsInferred(installation: ConnectorInstallation): boolean {
  return installation.state?.inferred === true
}

export function confirmationMatches(input: string | null | undefined, expected: string): boolean {
  return (input ?? '').trim() === expected
}

export function jobCanCancel(job: ConnectorJob | null | undefined): boolean {
  if (!job) return false
  return job.can_cancel && !job.cancel_requested && ['queued', 'running'].includes(job.state)
}

export function jobProgressText(job: ConnectorJob | null | undefined): string {
  if (!job) return '无安装任务'
  if (job.error_code) return `失败（${job.error_code}）：${job.error_message ?? job.message}`
  return `${job.progress}% · ${job.stage} · ${job.message || job.state}`
}

export function desktopConnectorDirHint(isDesktopMode: boolean): string {
  if (isDesktopMode) return '桌面版可在系统对话框中选择受管连接器根目录；修改后需重启后端。'
  return '浏览器模式无法选择服务器目录；请使用当前配置根目录，或改用桌面版。'
}

export function licenseText(license: Record<string, unknown>): string {
  const status = String(license.status ?? 'not_fetched')
  if (status === 'not_fetched') return '许可证未获取，需人工审查'
  const name = license.name ?? license.spdx_id ?? license.license
  return name ? String(name) : `许可证状态：${status}`
}

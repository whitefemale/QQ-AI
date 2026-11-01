/** 连接诊断的纯展示逻辑：只依据后端返回的证据措辞，绝不把 Mock 或握手成功说成真实收发。 */

import type {
  AccountStatusSnapshot,
  ConnectionDiagnostics,
  ConnectionCheckState,
  DiagnosticCheck,
} from '@/api/types'
import { stateLabel, type TagType } from '@/utils/format'

export const CHECK_STATE_LABELS: Record<ConnectionCheckState, string> = {
  ok: '通过',
  warning: '警告',
  failed: '失败',
  skipped: '已跳过',
  not_verified: '未验证',
}

export function checkStateLabel(state?: string | null): string {
  if (!state) return '—'
  return CHECK_STATE_LABELS[state as ConnectionCheckState] ?? state
}

/** 只有逐项检查的 ok 可以使用绿色；not_verified 永远不是通过。 */
export function checkStateTag(state?: string | null): TagType {
  if (state === 'ok') return 'success'
  if (state === 'failed') return 'danger'
  if (state === 'warning' || state === 'not_verified') return 'warning'
  return 'info'
}

export interface DiagnosticsSummary {
  type: 'success' | 'warning' | 'error' | 'info'
  title: string
  description: string
}

export function diagnosticsSummary(report: ConnectionDiagnostics): DiagnosticsSummary {
  const next = report.next_step ? `下一步：${report.next_step}` : report.note
  if (report.state === 'mock_only' || report.is_mock) {
    return {
      type: 'info',
      title: 'Mock 连接通过（不连接真实 QQ）',
      description: `${report.note}${report.next_step ? ` 下一步：${report.next_step}` : ''}`,
    }
  }
  if (report.state === 'failed') {
    return {
      type: 'error',
      title: '连接失败',
      description: report.error_message || next,
    }
  }
  return {
    type: 'warning',
    title: '连接与身份验证通过（真实群收发尚未验证）',
    description: `本测试不发送任何消息，也不等待真实群消息。${next}`,
  }
}

export function checkDetail(check: DiagnosticCheck): string {
  const code = check.error_code ? `（${check.error_code}）` : ''
  return `${check.detail}${code}`
}

/** 实例列表中的可操作建议；不把未知状态伪装成健康。 */
export function instanceStatusNextStep(
  status?: string | null,
  connectionMode?: string | null,
  errorMessage?: string | null,
): string {
  switch (status) {
    case 'online':
      return connectionMode === 'mock'
        ? 'Mock 在线不代表真实 QQ；请使用 OneBot 11 连接器完成真实环境验收。'
        : 'QQ 身份已验证；真实群消息收发仍需在受控测试群人工验收。'
    case 'connected_unverified':
      return 'WebSocket 已连接但尚未确认 QQ 登录身份。请在连接器内登录 QQ，然后重新连接或重新诊断。'
    case 'reconnecting':
      return '正在自动重连。若持续失败，请检查连接器进程、地址与 Token；已进入队列的消息不会盲目重发。'
    case 'connecting':
      return '正在建立连接，请稍候后刷新状态。'
    case 'error':
      return `连接失败${errorMessage ? `：${errorMessage}` : ''}。检查 NapCat 是否启动、正向 WebSocket 是否开启、地址与 Token 是否一致。`
    case 'unconfigured':
      return '尚未填写 WebSocket 地址与 Token。填写后点击「测试并诊断」，通过后再连接。'
    case 'disconnected':
    case 'offline':
      return '未连接。确认连接器已启动并登录 QQ，然后点击「连接」，或先执行「测试并诊断」。'
    default:
      return '状态未知；请刷新后重新诊断，不要假定连接可用。'
  }
}

export interface InstanceActionAvailability {
  canConnect: boolean
  canDisconnect: boolean
  canFetchGroups: boolean
}

export function instanceActions(status?: string | null): InstanceActionAvailability {
  return {
    canConnect: ['disconnected', 'offline', 'unconfigured', 'error', 'connected_unverified'].includes(status ?? ''),
    canDisconnect: ['online', 'connected_unverified', 'reconnecting'].includes(status ?? ''),
    canFetchGroups: status === 'online',
  }
}

const MODE_LABELS: Record<string, string> = {
  mock: 'Mock（非真实 QQ）',
  onebot11: 'OneBot 11',
  official: '官方机器人（规划）',
}

const CONNECTION_STATE_LABELS: Record<string, string> = {
  failed: '失败',
  identity_verified: '身份已验证（真实收发未验证）',
  mock_only: '仅 Mock（未连接真实 QQ）',
}

/** 复制前去掉端点、本机路径与可能的 QQ 标识；宁可多隐藏，不泄露。 */
export function sanitizeDiagnosticText(value: string): string {
  return value
    .replace(/\b(?:wss?|https?):\/\/[^\s"'`）)]+/giu, '端点已隐藏')
    .replace(/(?:[A-Za-z]:\\|\/)[^\s"'`）)]{3,}/gu, '路径已隐藏')
    .replace(/\b\d{5,12}\b/gu, '数字标识已隐藏')
}

/**
 * 连接诊断的脱敏复制文本。
 * 只包含整体状态、逐项检查与时间；不含登录 QQ 号、昵称、群列表或群数量。
 */
export function connectionDiagnosticsCopy(report: ConnectionDiagnostics): string {
  const mode = MODE_LABELS[report.connection_mode] ?? report.connection_mode
  const state = CONNECTION_STATE_LABELS[report.state] ?? report.state
  const lines = [
    'AI 群友连接诊断（已脱敏）',
    `测试时间：${report.tested_at}`,
    `连接方式：${mode}`,
    `总体状态：${state}`,
    `测试发送消息：${report.message_send_attempted ? '是' : '否（本测试不发送任何消息）'}`,
    '检查项：',
  ]
  if (!report.checks.length) {
    lines.push('- 无检查项')
  }
  for (const check of report.checks) {
    const code = check.error_code ? `（${sanitizeDiagnosticText(check.error_code)}）` : ''
    lines.push(`- ${sanitizeDiagnosticText(check.label)}：${checkStateLabel(check.state)}${code}`)
    if (check.detail) {
      lines.push(`  说明：${sanitizeDiagnosticText(check.detail)}`)
    }
    if (check.next_step) {
      lines.push(`  下一步：${sanitizeDiagnosticText(check.next_step)}`)
    }
  }
  lines.push('说明：诊断只验证配置、连接、身份与动作通道，不代表真实群消息收发已验证。')
  return lines.join('\n')
}

/** 账号实时状态的结构化脱敏摘要；不包含账号名、QQ 号、实例名、地址、Token 或错误正文。 */
export function accountStatusCopy(snapshot: AccountStatusSnapshot): string {
  const account = snapshot.account
  const lines = [
    'AI 群友账号状态（已脱敏）',
    `账号启用：${account.enabled ? '是' : '否'}`,
    `账号状态：${stateLabel(account.status)}`,
    `全局紧急暂停：${snapshot.global_pause.paused ? '是' : '否'}`,
    `实例数量：${account.instances.length}`,
  ]
  account.instances.forEach((instance, index) => {
    const mode = MODE_LABELS[instance.connection_mode] ?? instance.connection_mode
    const live = instance.live_health
    lines.push(`- 实例 ${index + 1}：${mode} / 数据库状态：${stateLabel(instance.status)}`)
    lines.push(`  实时适配器：${live?.status ? stateLabel(live.status) : '当前进程无适配器'}`)
    lines.push(`  身份验证：${live?.identity_verified ? '已验证' : '未验证'}`)
    lines.push(`  实时观测时间：${live?.observed_at || '—'}`)
    if (typeof live?.heartbeat_age_seconds === 'number') {
      lines.push(`  心跳年龄：${live.heartbeat_age_seconds} 秒`)
    }
  })
  lines.push('说明：实时状态来自当前后端进程；重启后需重新连接。原始状态可能含 QQ 标识，请勿公开粘贴。')
  return lines.join('\n')
}

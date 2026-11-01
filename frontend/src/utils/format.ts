import type { BusEvent } from '@/api/types'

export type TagType = 'success' | 'warning' | 'danger' | 'info' | 'primary'

export function formatTime(value?: string | null): string {
  if (!value) return '—'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return new Intl.DateTimeFormat('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  }).format(date)
}

export function formatBytes(bytes?: number | null): string {
  if (bytes === null || bytes === undefined) return '—'
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(2)} MB`
}

export function formatNumber(value?: number | null): string {
  if (value === null || value === undefined) return '—'
  return new Intl.NumberFormat('zh-CN').format(value)
}

/** 只展示本地按用户填写单价估算的费用；null 表示单价未配置，绝不伪造成本。 */
export function formatCost(value?: number | null, currency = 'USD'): string {
  if (value === null || value === undefined) return '—'
  const digits = Math.abs(value) >= 0.01 ? 4 : 6
  return `${value.toFixed(digits)} ${currency}`
}

export const COST_STATUS_LABELS: Record<string, string> = {
  complete: '估算完整',
  partial: '部分未计价',
  unconfigured: '单价未配置',
  not_applicable: '无外部费用',
  no_calls: '无成功调用',
}

export function costStatusLabel(value?: string | null): string {
  if (!value) return '—'
  return COST_STATUS_LABELS[value] ?? value
}

export function costStatusTag(value?: string | null): TagType {
  if (value === 'complete') return 'success'
  if (value === 'partial' || value === 'unconfigured') return 'warning'
  return 'info'
}

export function truncate(text: string | null | undefined, limit = 80): string {
  if (!text) return '—'
  return text.length > limit ? `${text.slice(0, limit)}…` : text
}

export const STATE_LABELS: Record<string, string> = {
  online: '在线',
  offline: '离线',
  disconnected: '未连接',
  unconfigured: '未配置',
  connecting: '连接中',
  connected_unverified: '已连接 · 身份未验证',
  reconnecting: '重连中',
  identity_verified: '身份已验证 · 真实收发未验证',
  not_verified: '未验证',
  error: '错误',
  disabled: '已停用',
  enabled: '已启用',
  configured: '已配置',
  available: '可用',
  mock_only: '仅 Mock',
  mock: 'Mock 模拟',
  planned: '规划中',
  unsupported_by_adapter: '连接器不支持',
  healthy: '健康',
  incompatible: '版本不兼容',
  builtin_active: '内置模块运行中',
  runtime_planned: '运行时规划中',
  pending: '待发送',
  sending: '发送中',
  sent: '已发送',
  failed: '失败',
  unknown: '状态未知',
  received: '已接收',
  observed: '仅观察',
  intercepted: '已拦截',
  replied: '已回复',
  command: '命令',
  duplicate: '重复事件',
  paused: '已暂停',
  running: '运行中',
  queued: '排队中',
  succeeded: '已完成',
  cancelled: '已取消',
  candidate: '候选',
  stable: '已稳定',
  rejected: '已拒绝',
  pending_review: '待审核',
  applied: '已应用',
  no_change: '无变化',
  skipped: '已跳过',
  insufficient_evidence: '证据不足',
  auto: '自动应用',
  review: '人工审核',
  admin_only: '仅控制台手动',
  group: '仅当前群',
  cross_group: '跨群学习',
  observe: '仅观察',
  mention_only: '仅 @ 回复',
  manual_confirm: '手动确认',
  keyword: '关键词触发（高级）',
  always: '自动回复',
  pending_approval: '待确认发送',
  awaiting_approval: '待人工确认',
  sensitive_output: '疑似敏感内容',
  empty_output: '空回复被拦截',
  repeat_loop: '重复刷屏拦截',
  invalid_message: '无效消息拦截',
  low: '低风险',
  medium: '中风险',
  high: '高风险',
}

export function stateLabel(value?: string | null): string {
  if (!value) return '—'
  return STATE_LABELS[value] ?? value
}

export function stateTag(value?: string | null): TagType {
  if (!value) return 'info'
  if (['online', 'available', 'healthy', 'sent', 'succeeded', 'stable', 'applied', 'builtin_active'].includes(value)) {
    return 'success'
  }
  if (['error', 'failed', 'incompatible', 'rejected', 'high', 'intercepted', 'sensitive_output'].includes(value)) {
    return 'danger'
  }
  if (['reconnecting', 'connecting', 'connected_unverified', 'identity_verified', 'not_verified', 'pending', 'sending', 'queued', 'running', 'candidate', 'pending_review', 'unknown', 'mock_only', 'warning', 'paused', 'pending_approval', 'awaiting_approval', 'repeat_loop'].includes(value)) {
    return 'warning'
  }
  if (['planned', 'unconfigured', 'disabled', 'runtime_planned', 'unsupported_by_adapter'].includes(value)) {
    return 'info'
  }
  return 'primary'
}

const EVENT_LABELS: Record<string, string> = {
  'system.started': '系统启动',
  'system.paused': '全局暂停',
  'system.resumed': '全局恢复',
  'adapter.status': '连接器状态',
  'message.received': '收到消息',
  'message.observed': '仅观察',
  'message.intercepted': '消息被拦截',
  'message.duplicate': '重复事件',
  'command.handled': '命令处理',
  'reply.generated': '生成回复',
  'reply.failed': '回复失败',
  'reply.awaiting_approval': '回复待人工确认',
  'outbox.sent': '消息已发送',
  'outbox.failed': '发送失败',
  'outbox.unknown': '发送状态未知',
  'outbox.auto_paused': '连续失败自动暂停',
  'persona.growth_applied': '人格已成长',
  'persona.review_required': '人格提案待审核',
  'budget.alert': '预算告警',
}

export function eventLabel(type: string): string {
  return EVENT_LABELS[type] ?? type
}

export function eventDetail(event: BusEvent): string {
  const payload = event.payload ?? {}
  const candidates = [
    'reason',
    'detail',
    'message',
    'sent_text',
    'status',
    'action',
    'error_message',
    'summary',
  ]
  for (const key of candidates) {
    const value = payload[key]
    if (typeof value === 'string' && value) return truncate(value, 120)
  }
  const entries = Object.entries(payload).filter(([, value]) => typeof value !== 'object')
  if (!entries.length) return '—'
  return truncate(entries.map(([key, value]) => `${key}: ${String(value)}`).join(' · '), 120)
}

export function riskTag(level: string): TagType {
  if (level === 'high') return 'danger'
  if (level === 'medium') return 'warning'
  return 'success'
}

/** 接入向导的纯展示逻辑：只依据后端给出的枚举与计数，绝不自行推断真实可用。 */

import type {
  OnboardingFreshness,
  OnboardingPayload,
  OnboardingStep,
  OnboardingStepState,
} from '@/api/types'
import type { TagType } from '@/utils/format'

export const STEP_STATE_LABELS: Record<OnboardingStepState, string> = {
  done: '已完成',
  action_required: '需要处理',
  optional: '可选',
  blocked: '已阻止',
  mock_only: '仅 Mock',
  not_verified: '未验证',
}

export function stepStateLabel(state?: string | null): string {
  if (!state) return '—'
  return STEP_STATE_LABELS[state as OnboardingStepState] ?? state
}

/** Mock 与未验证永远不能使用 success 样式。 */
export function stepStateTag(state?: string | null): TagType {
  if (state === 'done') return 'success'
  if (state === 'blocked') return 'danger'
  if (state === 'action_required' || state === 'not_verified' || state === 'mock_only') return 'warning'
  return 'info'
}

export const FRESHNESS_LABELS: Record<OnboardingFreshness, string> = {
  fresh: '新鲜（1 小时内）',
  aging: '较早（24 小时内）',
  stale: '已过期（超过 24 小时）',
  missing: '无证据',
  not_applicable: '不适用',
}

export function freshnessLabel(value?: string | null): string {
  if (!value) return '不适用'
  return FRESHNESS_LABELS[value as OnboardingFreshness] ?? value
}

export function freshnessTag(value?: string | null): TagType {
  if (value === 'fresh') return 'success'
  if (value === 'aging') return 'warning'
  if (value === 'stale') return 'danger'
  return 'info'
}

export interface OverallBanner {
  type: 'success' | 'warning' | 'info' | 'error'
  title: string
  description: string
}

export function overallBanner(payload: OnboardingPayload): OverallBanner {
  if (payload.overall === 'ready_real') {
    return {
      type: 'success',
      title: '真实接入已就绪',
      description: '步骤均来自当前后端状态；真实发送仍需人工验收，状态未知的消息不会自动重发。',
    }
  }
  if (payload.overall === 'ready_mock_only') {
    return {
      type: 'warning',
      title: 'Mock 演示已就绪，不代表真实 QQ 或模型',
      description: '当前链路只使用 Mock 连接器与 Mock 模型；不会连接真实 QQ，也不会产生真实模型回复。',
    }
  }
  if (payload.overall === 'blocked') {
    return {
      type: 'error',
      title: '接入被阻止',
      description: payload.blockers.join('；') || '存在必须解除的阻断项。',
    }
  }
  return {
    type: 'info',
    title: '还有待办步骤',
    description: payload.next_action
      ? `下一步：${payload.next_action.label}。请按顺序完成，状态会从后端重新读取。`
      : '请按顺序检查各步骤。',
  }
}

/** 只统计真正完成的步骤；mock_only、optional 与未验证都不计入进度。 */
export function completedCount(steps: OnboardingStep[]): number {
  return steps.filter((step) => step.state === 'done').length
}

export function progressText(steps: OnboardingStep[]): string {
  return `已完成 ${completedCount(steps)} / ${steps.length} 步`
}

/** 优先返回阻断或需要处理的步骤，其次才是可选项。 */
export function nextTodoStep(steps: OnboardingStep[]): OnboardingStep | null {
  const ordered = [...steps].sort((left, right) => left.order - right.order)
  return (
    ordered.find((step) => ['blocked', 'action_required', 'not_verified'].includes(step.state)) ??
    ordered.find((step) => step.state === 'optional') ??
    null
  )
}

const EVIDENCE_LABELS: Record<string, string> = {
  database: '本地数据库',
  credential_key_configured: '凭证密钥已配置',
  global_paused: '全局暂停',
  onebot_instances: 'OneBot 11 实例',
  mock_instances: 'Mock 实例',
  installations: '连接器安装',
  shell_installed: '已安装外壳',
  ready_installations: '可用安装',
  live_online_instances: '实时在线实例',
  identity_confirmed_instances: '已确认身份实例',
  tested_at: '测试时间',
  source: '证据来源',
  ok: '测试通过',
  state: '状态',
  age_seconds: '证据年龄（秒）',
  identity_verified: '身份验证',
  action_path_verified: '动作通道',
  group_list_verified: '群列表',
  real_inbound_verified: '真实入站',
  real_outbound_verified: '真实出站',
  real_providers: '真实 Provider',
  configured_real_providers: '配置完整',
  tested_real_providers: '测试通过且新鲜',
  outcome: '测试结果',
  latency_ms: '延迟（毫秒）',
  real_groups: '真实群',
  enabled_real_groups: '已启用真实群',
  mock_groups: 'Mock 群',
  real_observe_groups: '真实观察群',
  observed_currently: '已记录入站的观察群',
  ready_real_groups: '可自动回复的真实群',
  ready_manual_groups: '待审的真实群',
  ready_mock_groups: '可演示的 Mock 群',
}

export interface EvidenceRow {
  key: string
  label: string
  value: string
}

/** 只展示后端 allowlist 内的计数/布尔/时间，值本身不做任何推断。 */
export function evidenceRows(step: OnboardingStep): EvidenceRow[] {
  return Object.entries(step.evidence ?? {})
    .filter(([, value]) => value !== null && value !== undefined && value !== '')
    .map(([key, value]) => ({
      key,
      label: EVIDENCE_LABELS[key] ?? key,
      value: formatEvidenceValue(value),
    }))
}

function formatEvidenceValue(value: unknown): string {
  if (typeof value === 'boolean') return value ? '是' : '否'
  if (typeof value === 'number') return new Intl.NumberFormat('zh-CN').format(value)
  if (typeof value === 'string') return value
  return '—'
}

export const NEXT_STEP_ROUTES: Record<string, string> = {
  backend: '/diagnostics',
  connector: '/connectors',
  qq_login: '/accounts',
  connection_test: '/accounts',
  model: '/providers',
  groups: '/groups',
  observe: '/groups',
  enable: '/groups',
}

/** 只允许跳转到硬编码的内部路由，避免把后端字段当作任意跳转地址。 */
export function stepRoute(step: OnboardingStep): string {
  return NEXT_STEP_ROUTES[step.key] ?? '/onboarding'
}

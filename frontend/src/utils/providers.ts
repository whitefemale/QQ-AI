/**
 * 模型 Provider 的纯展示逻辑。
 *
 * 一个绿色标签不能同时代表“配置完整”“连通性通过”“真实生成通过”；
 * Mock 结果始终与真实调用分开显示，费用未知时显示“无法估算”。
 */

import type {
  LLMProvider,
  ProviderModelListState,
  ProviderTestOutcome,
  ProviderTestUsage,
} from '@/api/types'
import { formatCost } from '@/utils/format'
import type { TagType } from '@/utils/format'

export interface ProviderReadinessTag {
  key: string
  label: string
  type: TagType
  note: string
}

const OUTCOME_LABELS: Record<ProviderTestOutcome, string> = {
  success: '通过',
  failure: '失败',
  cancelled: '已取消',
}

function outcomeTag(outcome: ProviderTestOutcome, successType: TagType): TagType {
  if (outcome === 'success') return successType
  if (outcome === 'failure') return 'danger'
  return 'info'
}

/** 组合展示配置、测试证据与 Mock/停用状态；不合并成单一“可用”。 */
export function providerReadinessTags(provider: LLMProvider): ProviderReadinessTag[] {
  const tags: ProviderReadinessTag[] = []

  if (provider.is_mock) {
    tags.push({
      key: 'mock',
      label: 'Mock 模拟',
      type: 'warning',
      note: '固定模板回复；不能证明真实 API 可用。',
    })
  }

  if (!provider.enabled) {
    tags.push({
      key: 'disabled',
      label: '已停用',
      type: 'info',
      note: '停用后不参与自动回复路由；显式点击测试仍会调用该 Provider。',
    })
  }

  if (!provider.is_mock) {
    tags.push(
      provider.config_complete
        ? {
            key: 'config',
            label: '配置完整',
            type: 'success',
            note: 'Base URL、模型 ID 与 API Key 均已保存；不代表网络或额度可用。',
          }
        : {
            key: 'config',
            label: '配置不完整',
            type: 'warning',
            note: '请补全 Base URL、模型 ID 与 API Key。',
          },
    )
  }

  const connectivity = provider.last_test
  if (connectivity) {
    tags.push({
      key: 'connectivity',
      label: `${provider.is_mock ? 'Mock ' : ''}连通性${OUTCOME_LABELS[connectivity.outcome]}`,
      type: outcomeTag(connectivity.outcome, provider.is_mock ? 'info' : 'success'),
      note: connectivity.message ?? connectivity.error_code ?? '无详细信息。',
    })
  } else {
    tags.push({
      key: 'connectivity',
      label: '未测试连通性',
      type: 'info',
      note: '尚无显式连通性测试证据。',
    })
  }

  if (!provider.is_mock) {
    const generation = provider.last_generation
    if (generation) {
      tags.push({
        key: 'generation',
        label: `真实生成${OUTCOME_LABELS[generation.outcome]}`,
        type: outcomeTag(generation.outcome, 'success'),
        note: generation.message ?? generation.error_code ?? '无详细信息。',
      })
    } else {
      tags.push({
        key: 'generation',
        label: '未做真实生成',
        type: 'info',
        note: '连通性通过不等于真实生成通过。',
      })
    }
  }

  return tags
}

const NEXT_STEPS: Record<string, string> = {
  LLM_AUTH_FAILED: '检查 API Key 是否有效、是否已过期，以及是否被删除或替换。',
  LLM_QUOTA_EXCEEDED: '检查服务商账户余额、额度与账单状态，处理后再测试。',
  LLM_RATE_LIMITED: '稍后再试，或降低请求频率；不要通过并发重试绕过限流。',
  LLM_TIMEOUT: '检查网络和超时设置；超时可能已产生费用，默认不会自动重试。',
  LLM_NETWORK_ERROR: '检查 Base URL、网络与代理配置；确认服务状态后重试。',
  LLM_MODEL_NOT_FOUND: '核对模型 ID 与 Base URL；必要时先获取模型列表。',
  LLM_INVALID_RESPONSE: '检查 Base URL 是否指向兼容接口，或提示词/参数是否超出限制。',
  LLM_NOT_CONFIGURED: '补全 Base URL、模型 ID 与 API Key 后再测试。',
  LLM_CANCELLED: '已取消本地等待；服务商可能仍会生成并计费。',
  BUDGET_EXCEEDED: '调整预算策略，或为 Provider 填写单价后再测试。',
  PROVIDER_OPERATION_CONFLICT: '同一操作仍在进行；等待完成或先取消，再重新发起。',
  PROVIDER_DISABLED: '先在列表或编辑对话框中启用该 Provider。',
}

export function providerNextStep(errorCode?: string | null): string | null {
  if (!errorCode) return null
  return NEXT_STEPS[errorCode] ?? null
}

/** 优先使用服务端返回的下一步建议；服务端未覆盖时使用本地映射。 */
export function providerActionHint(errorCode?: string | null, serverNextStep?: string | null): string | null {
  return serverNextStep || providerNextStep(errorCode)
}

export function providerTestOutcomeLabel(outcome?: ProviderTestOutcome | null): string {
  if (!outcome) return '未测试'
  return OUTCOME_LABELS[outcome]
}

export function providerTestOutcomeTag(outcome?: ProviderTestOutcome | null): TagType {
  if (outcome === 'success') return 'success'
  if (outcome === 'failure') return 'danger'
  return 'info'
}

export function formatProviderUsage(usage?: ProviderTestUsage | null): string {
  if (!usage) return '无用量数据'
  const tokens =
    usage.total_tokens === null
      ? 'Token：未知'
      : `Token：${usage.input_tokens ?? '?'} 输入 / ${usage.output_tokens ?? '?'} 输出（共 ${usage.total_tokens}）`
  if (usage.cost_status === 'mock_zero') {
    return `${tokens} · Mock 无外部费用`
  }
  if (usage.cost_status === 'estimated' && usage.estimated_cost !== null) {
    return `${tokens} · 本地估算 ${formatCost(usage.estimated_cost, usage.currency)}（不是服务商账单）`
  }
  return `${tokens} · 费用无法估算（缺少单价或 Token，不会补成 0）`
}

export function providerUsageTags(usage?: ProviderTestUsage | null): ProviderReadinessTag[] {
  if (!usage) return []
  if (usage.cost_status === 'mock_zero') {
    return [{ key: 'cost', label: 'Mock 无外部费用', type: 'info', note: usage.note }]
  }
  if (usage.cost_status === 'estimated') {
    return [{ key: 'cost', label: '本地估算费用', type: 'warning', note: usage.note }]
  }
  return [{ key: 'cost', label: '费用无法估算', type: 'warning', note: usage.note }]
}

const MODEL_LIST_STATES: Record<string, { label: string; type: TagType }> = {
  available: { label: '模型列表已获取', type: 'success' },
  unsupported: { label: '服务商不支持模型列表', type: 'info' },
  mock: { label: 'Mock 无远端模型列表', type: 'info' },
  not_configured: { label: '配置不完整，无法获取', type: 'warning' },
  auth_failed: { label: '认证失败', type: 'danger' },
  rate_limited: { label: '被限流', type: 'warning' },
  network_error: { label: '网络错误', type: 'danger' },
  timeout: { label: '超时', type: 'danger' },
  invalid_response: { label: '响应格式无效', type: 'danger' },
  error: { label: '获取失败', type: 'danger' },
}

export function providerModelListState(state?: string | null): { label: string; type: TagType } {
  return MODEL_LIST_STATES[state ?? ''] ?? { label: '未知状态', type: 'info' }
}

export function providerModelListSummary(state: ProviderModelListState | string | null | undefined): string {
  const info = providerModelListState(typeof state === 'string' ? state : null)
  return info.label
}

/** 每次用户点击测试都生成新的操作 ID；取消端点必须使用同一个 ID。 */
export function makeOperationId(): string {
  const cryptoApi = globalThis.crypto
  if (cryptoApi?.randomUUID) {
    return cryptoApi.randomUUID()
  }
  const random = Math.random().toString(36).slice(2, 10)
  return `op-${Date.now().toString(36)}-${random}`
}

import { describe, expect, it } from 'vitest'

import type { LLMProvider, ProviderTestRecord } from '@/api/types'
import {
  formatProviderUsage,
  makeOperationId,
  providerActionHint,
  providerModelListState,
  providerNextStep,
  providerReadinessTags,
  providerTestOutcomeLabel,
  providerTestOutcomeTag,
} from '@/utils/providers'

function provider(overrides: Partial<LLMProvider> = {}): LLMProvider {
  return {
    id: 'p1',
    name: '测试 Provider',
    provider_type: 'openai_compatible',
    base_url: 'https://example.invalid/v1',
    model: 'test-model',
    api_key_configured: true,
    api_key_masked: 'sk-****abcd',
    timeout_seconds: 45,
    max_output_tokens: 800,
    temperature: 0.7,
    is_default: false,
    enabled: true,
    status: 'configured',
    is_mock: false,
    config_complete: true,
    ...overrides,
  }
}

function evidence(overrides: Partial<ProviderTestRecord> = {}): ProviderTestRecord {
  return {
    kind: 'connectivity',
    outcome: 'success',
    ok: true,
    tested_at: '2026-10-31T00:00:00Z',
    latency_ms: 120,
    attempts: 1,
    model: 'test-model',
    is_mock: false,
    error_code: null,
    message: null,
    reply_preview: 'OK',
    upstream_request_id: null,
    usage: null,
    ...overrides,
  }
}

function tagKeys(providerValue: LLMProvider): string[] {
  return providerReadinessTags(providerValue).map((tag) => tag.key)
}

describe('provider readiness tags', () => {
  it('never collapses configuration and real call evidence into one available tag', () => {
    const tags = providerReadinessTags(provider())
    expect(tagKeys(provider())).toEqual(['config', 'connectivity', 'generation'])
    expect(tags.find((tag) => tag.key === 'config')?.label).toBe('配置完整')
    expect(tags.find((tag) => tag.key === 'connectivity')?.label).toBe('未测试连通性')
    expect(tags.find((tag) => tag.key === 'generation')?.label).toBe('未做真实生成')
    expect(tags.some((tag) => tag.label === '可用')).toBe(false)
  })

  it('marks incomplete and disabled real providers honestly', () => {
    const tags = providerReadinessTags(
      provider({ config_complete: false, enabled: false, api_key_configured: false }),
    )
    expect(tags.map((tag) => tag.label)).toEqual(['已停用', '配置不完整', '未测试连通性', '未做真实生成'])
    expect(tags.find((tag) => tag.key === 'config')?.type).toBe('warning')
  })

  it('separates Mock success from real success', () => {
    const tags = providerReadinessTags(
      provider({
        is_mock: true,
        config_complete: true,
        last_test: evidence({ is_mock: true }),
      }),
    )
    expect(tags.map((tag) => tag.label)).toEqual(['Mock 模拟', 'Mock 连通性通过'])
    const connectivity = tags.find((tag) => tag.key === 'connectivity')
    expect(connectivity?.type).toBe('info')
    expect(tags.some((tag) => tag.key === 'generation')).toBe(false)
  })

  it('shows real connectivity and generation outcomes independently', () => {
    const tags = providerReadinessTags(
      provider({
        last_test: evidence(),
        last_generation: evidence({
          kind: 'generation',
          outcome: 'failure',
          ok: false,
          error_code: 'LLM_QUOTA_EXCEEDED',
          message: '额度不足',
        }),
      }),
    )
    expect(tags.find((tag) => tag.key === 'connectivity')?.label).toBe('连通性通过')
    expect(tags.find((tag) => tag.key === 'connectivity')?.type).toBe('success')
    const generation = tags.find((tag) => tag.key === 'generation')
    expect(generation?.label).toBe('真实生成失败')
    expect(generation?.type).toBe('danger')
    expect(generation?.note).toBe('额度不足')
  })

  it('labels cancellation without claiming success', () => {
    const tags = providerReadinessTags(
      provider({
        is_mock: true,
        last_test: evidence({ is_mock: true, outcome: 'cancelled', ok: false }),
      }),
    )
    expect(tags.find((tag) => tag.key === 'connectivity')?.label).toBe('Mock 连通性已取消')
    expect(tags.find((tag) => tag.key === 'connectivity')?.type).toBe('info')
  })
})

describe('provider next steps', () => {
  it('gives concrete actions for common failures', () => {
    expect(providerNextStep('LLM_AUTH_FAILED')).toContain('API Key')
    expect(providerNextStep('LLM_QUOTA_EXCEEDED')).toContain('余额')
    expect(providerNextStep('LLM_RATE_LIMITED')).toContain('稍后')
    expect(providerNextStep('LLM_TIMEOUT')).toContain('费用')
    expect(providerNextStep('BUDGET_EXCEEDED')).toContain('预算')
    expect(providerNextStep('LLM_CANCELLED')).toContain('计费')
    expect(providerNextStep('SOMETHING_ELSE')).toBeNull()
    expect(providerNextStep(null)).toBeNull()
  })

  it('prefers the server next step when present', () => {
    expect(providerActionHint('LLM_AUTH_FAILED', '服务端专用建议')).toBe('服务端专用建议')
    expect(providerActionHint('LLM_AUTH_FAILED', null)).toContain('API Key')
  })

  it('maps test outcomes to labels and tags', () => {
    expect(providerTestOutcomeLabel('success')).toBe('通过')
    expect(providerTestOutcomeLabel('failure')).toBe('失败')
    expect(providerTestOutcomeLabel('cancelled')).toBe('已取消')
    expect(providerTestOutcomeLabel(null)).toBe('未测试')
    expect(providerTestOutcomeTag('success')).toBe('success')
    expect(providerTestOutcomeTag('failure')).toBe('danger')
    expect(providerTestOutcomeTag('cancelled')).toBe('info')
  })
})

describe('provider usage wording', () => {
  it('shows Mock calls as zero external cost, not as a real estimate', () => {
    const text = formatProviderUsage({
      input_tokens: 5,
      output_tokens: 2,
      total_tokens: 7,
      estimated_cost: 0,
      currency: 'USD',
      cost_status: 'mock_zero',
      note: 'Mock 无外部费用',
    })
    expect(text).toContain('Mock 无外部费用')
    expect(text).not.toContain('本地估算')
  })

  it('labels estimates as local, not provider bills', () => {
    const text = formatProviderUsage({
      input_tokens: 10,
      output_tokens: 5,
      total_tokens: 15,
      estimated_cost: 0.0002,
      currency: 'USD',
      cost_status: 'estimated',
      note: '按本地单价估算',
    })
    expect(text).toContain('15')
    expect(text).toContain('本地估算')
    expect(text).toContain('不是服务商账单')
  })

  it('never turns unknown usage or pricing into zero', () => {
    const text = formatProviderUsage({
      input_tokens: null,
      output_tokens: null,
      total_tokens: null,
      estimated_cost: null,
      currency: 'USD',
      cost_status: 'unavailable',
      note: '缺少单价',
    })
    expect(text).toContain('Token：未知')
    expect(text).toContain('费用无法估算')
    expect(text).not.toMatch(/0(\.0+)? USD/)
    expect(formatProviderUsage(null)).toBe('无用量数据')
  })
})

describe('model list states', () => {
  it('maps supported, unsupported and error states honestly', () => {
    expect(providerModelListState('available')).toEqual({ label: '模型列表已获取', type: 'success' })
    expect(providerModelListState('unsupported')).toEqual({ label: '服务商不支持模型列表', type: 'info' })
    expect(providerModelListState('mock')).toEqual({ label: 'Mock 无远端模型列表', type: 'info' })
    expect(providerModelListState('not_configured').type).toBe('warning')
    expect(providerModelListState('auth_failed').type).toBe('danger')
    expect(providerModelListState('timeout').type).toBe('danger')
    expect(providerModelListState('unexpected')).toEqual({ label: '未知状态', type: 'info' })
  })
})

describe('operation ids', () => {
  it('generates cancel-compatible, unique ids on each click', () => {
    const ids = new Set(Array.from({ length: 20 }, () => makeOperationId()))
    expect(ids.size).toBe(20)
    for (const id of ids) {
      // 后端要求 8–64 位 [A-Za-z0-9_-]；UUID 与回退格式都满足。
      expect(id).toMatch(/^[A-Za-z0-9_-]{8,64}$/)
    }
  })
})

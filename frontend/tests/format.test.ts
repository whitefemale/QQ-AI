import { describe, expect, it } from 'vitest'

import type { BusEvent } from '@/api/types'
import {
  costStatusLabel,
  costStatusTag,
  eventDetail,
  eventLabel,
  formatBytes,
  formatCost,
  formatNumber,
  riskTag,
  stateLabel,
  stateTag,
  truncate,
} from '@/utils/format'

describe('format helpers', () => {
  it('formats bytes with a dash for missing values', () => {
    expect(formatBytes(null)).toBe('—')
    expect(formatBytes(512)).toBe('512 B')
    expect(formatBytes(2048)).toBe('2.0 KB')
    expect(formatBytes(2 * 1024 * 1024)).toBe('2.00 MB')
  })

  it('formats numbers and truncates long text', () => {
    expect(formatNumber(1234567)).toBe('1,234,567')
    expect(formatNumber(null)).toBe('—')
    expect(truncate('abcdefgh', 4)).toBe('abcd…')
    expect(truncate('abc', 4)).toBe('abc')
    expect(truncate('', 4)).toBe('—')
  })

  it('never renders an unknown cost as zero', () => {
    expect(formatCost(null)).toBe('—')
    expect(formatCost(undefined)).toBe('—')
    expect(formatCost(0)).toBe('0.000000 USD')
    expect(formatCost(0.0123)).toBe('0.0123 USD')
    expect(formatCost(0.000123, 'CNY')).toBe('0.000123 CNY')
  })
})

describe('cost completeness labels', () => {
  it('labels every cost status without claiming unknown costs are complete', () => {
    expect(costStatusLabel('complete')).toBe('估算完整')
    expect(costStatusLabel('partial')).toBe('部分未计价')
    expect(costStatusLabel('unconfigured')).toBe('单价未配置')
    expect(costStatusLabel('not_applicable')).toBe('无外部费用')
    expect(costStatusLabel('no_calls')).toBe('无成功调用')
    expect(costStatusLabel(null)).toBe('—')
    expect(costStatusTag('complete')).toBe('success')
    expect(costStatusTag('partial')).toBe('warning')
    expect(costStatusTag('unconfigured')).toBe('warning')
    expect(costStatusTag('not_applicable')).toBe('info')
  })
})

describe('state labels and tags', () => {
  it('maps known backend states to Chinese labels', () => {
    expect(stateLabel('mention_only')).toBe('仅 @ 回复')
    expect(stateLabel('mock_only')).toBe('仅 Mock')
    expect(stateLabel('planned')).toBe('规划中')
    expect(stateLabel('candidate')).toBe('候选')
    expect(stateLabel(null)).toBe('—')
    expect(stateLabel('custom_state')).toBe('custom_state')
  })

  it('never marks mock or planned capabilities as success', () => {
    expect(stateTag('available')).toBe('success')
    expect(stateTag('mock_only')).toBe('warning')
    expect(stateTag('planned')).toBe('info')
    expect(stateTag('unconfigured')).toBe('info')
    expect(stateTag('failed')).toBe('danger')
    expect(stateTag('unknown')).toBe('warning')
  })

  it('labels risk levels without downgrading high risk', () => {
    expect(riskTag('high')).toBe('danger')
    expect(riskTag('medium')).toBe('warning')
    expect(riskTag('low')).toBe('success')
  })
})

describe('event display', () => {
  it('translates known event types and preserves unknown ones', () => {
    expect(eventLabel('message.intercepted')).toBe('消息被拦截')
    expect(eventLabel('budget.alert')).toBe('预算告警')
    expect(eventLabel('custom.event')).toBe('custom.event')
  })

  it('prefers readable payload fields for the detail line', () => {
    const event: BusEvent = {
      seq: 1,
      type: 'message.intercepted',
      at: '2026-01-01T00:00:00Z',
      payload: { reason: 'global_paused', message: 'ignored', group_id: 'g1' },
    }
    expect(eventDetail(event)).toBe('global_paused')
  })

  it('falls back to scalar payload entries', () => {
    const event: BusEvent = {
      seq: 2,
      type: 'adapter.status',
      at: '2026-01-01T00:00:00Z',
      payload: { status: 'online', attempts: 1, nested: { a: 1 } },
    }
    expect(eventDetail(event)).toBe('online')
  })

  it('shows a dash for empty payloads', () => {
    const event: BusEvent = { seq: 3, type: 'system.started', at: '2026-01-01T00:00:00Z', payload: {} }
    expect(eventDetail(event)).toBe('—')
  })
})

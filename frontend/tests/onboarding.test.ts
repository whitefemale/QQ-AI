import { describe, expect, it } from 'vitest'

import type { OnboardingPayload, OnboardingStep } from '@/api/types'
import {
  completedCount,
  evidenceRows,
  freshnessLabel,
  freshnessTag,
  nextTodoStep,
  overallBanner,
  progressText,
  stepRoute,
  stepStateLabel,
  stepStateTag,
} from '@/utils/onboarding'

function step(overrides: Partial<OnboardingStep> = {}): OnboardingStep {
  return {
    key: 'connector',
    order: 2,
    title: '连接器准备',
    state: 'action_required',
    summary: '尚未配置连接器。',
    next_step: '添加 OneBot 11 实例。',
    route: '/connectors',
    freshness: 'not_applicable',
    evidence: {},
    ...overrides,
  }
}

function payload(overrides: Partial<OnboardingPayload> = {}): OnboardingPayload {
  return {
    schema_version: 'onboarding.v1',
    checked_at: '2026-10-31T00:00:00Z',
    overall: 'action_required',
    ready_for_replies: false,
    mock_only: false,
    global_paused: false,
    steps: [step()],
    warnings: [],
    blockers: [],
    next_action: { key: 'connector', label: '连接器准备', route: '/connectors' },
    notes: [],
    ...overrides,
  }
}

describe('onboarding step states', () => {
  it('never styles mock or unverified as success', () => {
    expect(stepStateTag('done')).toBe('success')
    expect(stepStateTag('mock_only')).toBe('warning')
    expect(stepStateTag('not_verified')).toBe('warning')
    expect(stepStateTag('action_required')).toBe('warning')
    expect(stepStateTag('blocked')).toBe('danger')
    expect(stepStateTag('optional')).toBe('info')
    expect(stepStateLabel('mock_only')).toBe('仅 Mock')
    expect(stepStateLabel('not_verified')).toBe('未验证')
  })

  it('counts only done steps in progress', () => {
    const steps = [
      step({ key: 'backend', order: 1, state: 'done' }),
      step({ key: 'connector', order: 2, state: 'mock_only' }),
      step({ key: 'qq_login', order: 3, state: 'optional' }),
      step({ key: 'model', order: 5, state: 'done' }),
    ]
    expect(completedCount(steps)).toBe(2)
    expect(progressText(steps)).toBe('已完成 2 / 4 步')
  })

  it('prefers blocked and action_required over optional', () => {
    const steps = [
      step({ key: 'observe', order: 7, state: 'optional' }),
      step({ key: 'model', order: 5, state: 'not_verified' }),
      step({ key: 'enable', order: 8, state: 'blocked' }),
    ]
    expect(nextTodoStep(steps)?.key).toBe('model')
    expect(nextTodoStep([step({ key: 'enable', state: 'blocked' })])?.key).toBe('enable')
    expect(nextTodoStep([step({ key: 'observe', state: 'optional' })])?.key).toBe('observe')
    expect(nextTodoStep([step({ state: 'done' })])).toBeNull()
  })

  it('maps freshness without calling stale evidence fresh', () => {
    expect(freshnessLabel('fresh')).toContain('1 小时')
    expect(freshnessLabel('stale')).toContain('过期')
    expect(freshnessLabel(undefined)).toBe('不适用')
    expect(freshnessTag('fresh')).toBe('success')
    expect(freshnessTag('aging')).toBe('warning')
    expect(freshnessTag('stale')).toBe('danger')
    expect(freshnessTag('missing')).toBe('info')
  })
})

describe('onboarding overall banner', () => {
  it('uses success only for a real ready chain', () => {
    const real = overallBanner(
      payload({ overall: 'ready_real', ready_for_replies: true, steps: [step({ state: 'done' })] }),
    )
    expect(real.type).toBe('success')
    expect(real.title).toContain('真实接入已就绪')

    const mock = overallBanner(payload({ overall: 'ready_mock_only', mock_only: true }))
    expect(mock.type).toBe('warning')
    expect(mock.title).toContain('Mock')
    expect(mock.title).toContain('不代表真实')
  })

  it('shows blockers and the next action', () => {
    const blocked = overallBanner(payload({ overall: 'blocked', blockers: ['全局紧急暂停已开启。'] }))
    expect(blocked.type).toBe('error')
    expect(blocked.description).toContain('全局紧急暂停')

    const pending = overallBanner(payload())
    expect(pending.type).toBe('info')
    expect(pending.description).toContain('连接器准备')
  })
})

describe('onboarding evidence helpers', () => {
  it('formats allowlisted values without inventing state', () => {
    const rows = evidenceRows(
      step({
        evidence: {
          onebot_instances: 2,
          identity_confirmed_instances: 0,
          global_paused: false,
          tested_at: null,
        },
      }),
    )
    expect(rows).toEqual([
      { key: 'onebot_instances', label: 'OneBot 11 实例', value: '2' },
      { key: 'identity_confirmed_instances', label: '已确认身份实例', value: '0' },
      { key: 'global_paused', label: '全局暂停', value: '否' },
    ])
  })

  it('only routes to hard-coded internal pages', () => {
    expect(stepRoute(step({ key: 'model', route: 'https://evil.invalid' }))).toBe('/providers')
    expect(stepRoute(step({ key: 'unknown', route: 'https://evil.invalid' }))).toBe('/onboarding')
  })
})

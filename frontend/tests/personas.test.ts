import { describe, expect, it } from 'vitest'

import type { PersonaDiff, PersonaTraitDiffItem } from '@/api/types'
import { diffValueText, impactSummary, traitDiffLabel } from '@/utils/personas'

function buildDiff(overrides: Partial<PersonaDiff['impact']> = {}): PersonaDiff {
  return {
    fields: [],
    traits: { added: [], changed: [], removed: [] },
    impact: {
      field_changes: 0,
      traits_added: 0,
      traits_changed: 0,
      traits_removed: 0,
      description_changed: false,
      scopes: [],
      locked_fields: [],
      skipped_locked: [],
      ...overrides,
    },
  }
}

const trait: PersonaTraitDiffItem = {
  trait_key: '说话风格',
  trait_value: '简短',
  source_scope: 'global',
}

describe('diff value rendering', () => {
  it('renders missing and blank values as a dash', () => {
    expect(diffValueText(null)).toBe('—')
    expect(diffValueText(undefined)).toBe('—')
    expect(diffValueText('   ')).toBe('—')
    expect(diffValueText([])).toBe('—')
    expect(diffValueText({})).toBe('—')
  })

  it('renders scalars, arrays, and nested objects without JSON dumps', () => {
    expect(diffValueText(' 安静  ')).toBe('安静')
    expect(diffValueText(42)).toBe('42')
    expect(diffValueText(false)).toBe('false')
    expect(diffValueText(['a', null, 'b'])).toBe('a、—、b')
    expect(diffValueText({ temperature: 0.7, tags: ['x'] })).toBe('temperature：0.7；tags：x')
  })
})

describe('trait diff labels', () => {
  it('hides the global scope and shows group scopes', () => {
    expect(traitDiffLabel(trait)).toBe('说话风格：简短')
    expect(traitDiffLabel({ ...trait, source_scope: 'group:g1' })).toBe('说话风格：简短 · group:g1')
  })

  it('marks blank trait values instead of showing an empty string', () => {
    expect(traitDiffLabel({ ...trait, trait_value: '   ' })).toBe('说话风格：（空）')
  })
})

describe('impact summary', () => {
  it('summarises field and trait changes', () => {
    const summary = impactSummary(
      buildDiff({
        field_changes: 2,
        traits_added: 1,
        traits_changed: 3,
        traits_removed: 1,
        description_changed: true,
        skipped_locked: ['mood'],
      }),
    )
    expect(summary).toBe('字段 2 · 新增特征 1 · 修改特征 3 · 移除特征 1 · 自我描述将变化 · 锁定跳过 1')
  })

  it('falls back to an explicit note when there is no diff', () => {
    expect(impactSummary(undefined)).toBe('无差异摘要')
    expect(impactSummary(buildDiff())).toBe('字段 0 · 新增特征 0 · 修改特征 0 · 移除特征 0')
  })
})

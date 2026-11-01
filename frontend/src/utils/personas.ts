import type { PersonaDiff, PersonaTraitDiffItem } from '@/api/types'

export function diffValueText(value: unknown): string {
  if (value === null || value === undefined) return '—'
  if (typeof value === 'string') return value.trim() || '—'
  if (typeof value === 'number' || typeof value === 'boolean') return String(value)
  if (Array.isArray(value)) return value.length ? value.map((item) => diffValueText(item)).join('、') : '—'
  if (typeof value === 'object') {
    const entries = Object.entries(value as Record<string, unknown>)
    return entries.length ? entries.map(([key, item]) => `${key}：${diffValueText(item)}`).join('；') : '—'
  }
  return String(value)
}

export function traitDiffLabel(trait: PersonaTraitDiffItem): string {
  const value = trait.trait_value?.trim() || '（空）'
  const scope = trait.source_scope && trait.source_scope !== 'global' ? ` · ${trait.source_scope}` : ''
  return `${trait.trait_key}：${value}${scope}`
}

export function impactSummary(diff?: PersonaDiff): string {
  if (!diff) return '无差异摘要'
  const impact = diff.impact
  const parts = [
    `字段 ${impact.field_changes}`,
    `新增特征 ${impact.traits_added}`,
    `修改特征 ${impact.traits_changed}`,
    `移除特征 ${impact.traits_removed}`,
  ]
  if (impact.description_changed) parts.push('自我描述将变化')
  if (impact.skipped_locked.length) parts.push(`锁定跳过 ${impact.skipped_locked.length}`)
  return parts.join(' · ')
}

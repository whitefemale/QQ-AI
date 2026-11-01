import { describe, expect, it } from 'vitest'

import {
  extensionKindLabel,
  mediaExecutionLabel,
  mediaExecutionTagType,
  mediaToggleMessage,
  pluginExecutionLabel,
} from '@/utils/extensions'

describe('extension helpers', () => {
  it('distinguishes executable capabilities from contract-only ones', () => {
    expect(mediaExecutionLabel('job')).toBe('任务队列执行')
    expect(mediaExecutionLabel('contract_only')).toBe('仅接口契约')
    expect(mediaExecutionLabel(undefined)).toBe('未知')
    expect(mediaExecutionTagType('job')).toBe('success')
    expect(mediaExecutionTagType('contract_only')).toBe('info')
  })

  it('labels plugin execution honestly', () => {
    expect(pluginExecutionLabel('builtin_in_process')).toBe('内置进程内')
    expect(pluginExecutionLabel('not_executed')).toBe('不执行代码')
    expect(pluginExecutionLabel(undefined)).toBe('未知')
  })

  it('maps contract kinds to Chinese labels without inventing new ones', () => {
    expect(extensionKindLabel('chat_adapter')).toBe('聊天平台适配器')
    expect(extensionKindLabel('custom_kind')).toBe('custom_kind')
  })

  it('reports cancelled jobs after disabling a provider', () => {
    expect(mediaToggleMessage(true)).toBe('已启用媒体 Provider。')
    expect(mediaToggleMessage(false, 2)).toContain('取消 2 个')
    expect(mediaToggleMessage(false, 0)).toContain('没有需要取消的任务')
    expect(mediaToggleMessage(false, 0, '数据库不可用')).toContain('取消任务时失败')
    expect(mediaToggleMessage(false, 0, '数据库不可用')).not.toContain('已取消')
  })
})

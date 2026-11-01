/** 扩展能力契约的纯展示辅助函数；不包含任何执行逻辑。 */

export function mediaExecutionLabel(execution: string | undefined): string {
  if (execution === 'job') return '任务队列执行'
  if (execution === 'contract_only') return '仅接口契约'
  return '未知'
}

export function mediaExecutionTagType(execution: string | undefined): 'success' | 'info' {
  return execution === 'job' ? 'success' : 'info'
}

export function pluginExecutionLabel(execution: string | undefined): string {
  if (execution === 'builtin_in_process') return '内置进程内'
  if (execution === 'not_executed') return '不执行代码'
  return '未知'
}

export function extensionKindLabel(kind: string): string {
  const labels: Record<string, string> = {
    chat_adapter: '聊天平台适配器',
    llm_provider: '模型 Provider',
    media_provider: '媒体 Provider',
    tool: '工具',
    plugin: '插件',
  }
  return labels[kind] ?? kind
}

/** 停用 Provider 后如实报告被取消的任务数；不把失败包装成成功。 */
export function mediaToggleMessage(
  enabled: boolean,
  cancelledJobs = 0,
  cancellationError?: string | null,
): string {
  if (enabled) return '已启用媒体 Provider。'
  if (cancellationError) return `已停用媒体 Provider，但取消任务时失败：${cancellationError}`
  if (cancelledJobs > 0) return `已停用媒体 Provider，并取消 ${cancelledJobs} 个排队或运行中的任务。`
  return '已停用媒体 Provider；该能力下没有需要取消的任务。'
}

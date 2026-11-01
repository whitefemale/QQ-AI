/** 破坏性操作的输入确认词：必须完全一致，避免误点或回车直接执行。 */
import { ElMessageBox } from 'element-plus'

export const DELETE_PHRASE = 'DELETE'
export const CLEANUP_PHRASE = 'CLEANUP'

export function confirmationMatches(input: string | null | undefined, phrase: string): boolean {
  return (input ?? '').trim() === phrase
}

/** 弹出输入框并要求用户输入确认词；取消或输入不匹配时返回 false。 */
export async function typedConfirm(
  message: string,
  phrase: string,
  title = '确认操作',
): Promise<boolean> {
  try {
    const result = await ElMessageBox.prompt(message, title, {
      confirmButtonText: '确认',
      cancelButtonText: '取消',
      type: 'warning',
      closeOnClickModal: false,
      inputPlaceholder: `请输入 ${phrase}`,
      inputValidator: (value: string) =>
        confirmationMatches(value, phrase) || `请输入 ${phrase} 以确认`,
    })
    return confirmationMatches(result.value, phrase)
  } catch {
    return false
  }
}

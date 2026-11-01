// 与后端 app/budgets/service.py 的 FEATURE_KEYS 保持一致。
// 功能预算只接受这些固定键，避免任意文本成为作用域 ID。
export const FEATURE_OPTIONS = [
  { value: 'chat', label: '聊天回复' },
  { value: 'provider_test', label: '模型测试' },
  { value: 'persona_growth', label: '人格成长' },
  { value: 'memory_extraction', label: '记忆提取' },
  { value: 'media.image.describe', label: '图片描述' },
  { value: 'media.ocr.extract', label: 'OCR 文字识别' },
  { value: 'media.audio.transcribe', label: '语音转写' },
  { value: 'media.text.embed', label: '文本向量' },
  { value: 'media.inspect', label: '媒体检查' },
  { value: 'media.text.rerank', label: '文本重排' },
  { value: 'media.video.describe', label: '视频理解' },
] as const

export function featureLabel(value: string): string {
  const key = value === 'reply' ? 'chat' : value
  return FEATURE_OPTIONS.find((item) => item.value === key)?.label ?? value
}

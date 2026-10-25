import { ref } from 'vue'

import type { BusEvent } from '@/api/types'
import { defineStore } from 'pinia'

/** 后端 SSE 使用 event: <type> 命名事件，因此需要逐类型订阅。 */
const EVENT_TYPES = [
  'system.started',
  'system.paused',
  'system.resumed',
  'adapter.status',
  'message.received',
  'message.observed',
  'message.intercepted',
  'message.duplicate',
  'command.handled',
  'reply.generated',
  'reply.failed',
  'outbox.sent',
  'outbox.failed',
  'outbox.unknown',
  'outbox.auto_paused',
  'persona.growth_applied',
  'persona.review_required',
]

export type StreamStatus = 'idle' | 'connecting' | 'open' | 'closed'

export const useEventsStore = defineStore('events', () => {
  const items = ref<BusEvent[]>([])
  const status = ref<StreamStatus>('idle')
  let source: EventSource | null = null

  function push(event: BusEvent): void {
    if (!event || typeof event.seq !== 'number') return
    if (items.value.some((item) => item.seq === event.seq)) return
    items.value = [event, ...items.value].slice(0, 200)
  }

  function handleMessage(message: MessageEvent<string>): void {
    try {
      push(JSON.parse(message.data) as BusEvent)
    } catch {
      // 忽略无法解析的事件，避免破坏控制台
    }
  }

  function connect(): void {
    if (source || typeof EventSource === 'undefined') return
    status.value = 'connecting'
    source = new EventSource('/api/events/stream?replay=20')
    source.onopen = () => {
      status.value = 'open'
    }
    source.onerror = () => {
      status.value = 'closed'
      // 浏览器会自动重连；此处只更新状态，不主动关闭。
    }
    source.onmessage = handleMessage
    for (const type of EVENT_TYPES) {
      source.addEventListener(type, handleMessage as EventListener)
    }
  }

  function disconnect(): void {
    if (source) {
      source.close()
      source = null
    }
    status.value = 'idle'
  }

  function clear(): void {
    items.value = []
  }

  return { items, status, connect, disconnect, clear }
})

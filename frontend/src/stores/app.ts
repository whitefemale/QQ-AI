import { computed, ref } from 'vue'

import { api } from '@/api/client'
import type { AppSettings, CapabilitiesPayload, GlobalPause } from '@/api/types'
import { defineStore } from 'pinia'

export const useAppStore = defineStore('app', () => {
  const settings = ref<AppSettings | null>(null)
  const capabilities = ref<CapabilitiesPayload | null>(null)
  const ready = ref(false)
  const loading = ref(false)
  const lastError = ref<string | null>(null)

  const paused = computed(() => settings.value?.global_pause?.paused ?? false)
  const appVersion = computed(() => settings.value?.app.version ?? '—')

  async function loadSettings(): Promise<void> {
    settings.value = await api<AppSettings>('/settings')
  }

  async function loadCapabilities(): Promise<void> {
    capabilities.value = await api<CapabilitiesPayload>('/capabilities')
  }

  async function loadReady(): Promise<void> {
    ready.value = (await api<{ ready: boolean }>('/ready')).ready
  }

  async function refresh(): Promise<void> {
    loading.value = true
    lastError.value = null
    try {
      await Promise.all([loadSettings(), loadCapabilities(), loadReady()])
    } catch (error) {
      lastError.value = error instanceof Error ? error.message : '加载系统信息失败。'
      throw error
    } finally {
      loading.value = false
    }
  }

  async function applyPause(pause: GlobalPause): Promise<void> {
    if (!settings.value) {
      await loadSettings()
      return
    }
    settings.value.global_pause = pause
  }

  async function pauseAll(reason: string): Promise<GlobalPause> {
    const result = await api<{ global_pause: GlobalPause }>('/system/pause-all', {
      method: 'POST',
      body: { reason },
    })
    await applyPause(result.global_pause)
    return result.global_pause
  }

  async function resumeAll(): Promise<GlobalPause> {
    const result = await api<{ global_pause: GlobalPause }>('/system/resume', { method: 'POST' })
    await applyPause(result.global_pause)
    return result.global_pause
  }

  return {
    settings,
    capabilities,
    ready,
    loading,
    lastError,
    paused,
    appVersion,
    loadSettings,
    loadCapabilities,
    loadReady,
    refresh,
    pauseAll,
    resumeAll,
  }
})

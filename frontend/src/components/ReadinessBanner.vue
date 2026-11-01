<template>
  <el-alert
    v-if="error && !payload"
    type="info"
    :closable="false"
    show-icon
    title="暂时无法读取接入状态"
    :description="error"
  >
    <el-button size="small" :loading="loading" @click="emit('retry')">重试</el-button>
  </el-alert>

  <el-alert
    v-else-if="payload && payload.overall !== 'ready_real'"
    :type="banner.type"
    :title="banner.title"
    :description="banner.description"
    :closable="false"
    show-icon
  >
    <div class="banner-actions">
      <el-button size="small" type="primary" @click="router.push('/onboarding')">打开接入向导</el-button>
      <el-button v-if="payload.next_action" size="small" @click="router.push(payload.next_action.route)">
        下一步：{{ payload.next_action.label }}
      </el-button>
      <el-button size="small" @click="router.push('/diagnostics')">诊断与日志</el-button>
    </div>
  </el-alert>
</template>

<script setup lang="ts">
import { computed } from 'vue'

import type { OnboardingPayload } from '@/api/types'
import { overallBanner } from '@/utils/onboarding'
import { useRouter } from 'vue-router'

const props = defineProps<{
  payload: OnboardingPayload | null
  error?: string | null
  loading?: boolean
}>()
const emit = defineEmits<{ retry: [] }>()

const router = useRouter()
const banner = computed(() =>
  props.payload
    ? overallBanner(props.payload)
    : { type: 'info' as const, title: '', description: '' },
)
</script>

<style scoped>
.banner-actions {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  margin-top: 8px;
}
</style>

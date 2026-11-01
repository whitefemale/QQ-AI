<template>
  <div class="page">
    <PageHeader
      title="接入向导"
      description="按步骤完成真实 QQ 与模型接入。所有状态都从后端实时读取；向导不会自动登录 QQ、自动测试模型、自动导入群或自动开启回复。"
    >
      <template #actions>
        <el-button :loading="loading" @click="load">刷新状态</el-button>
      </template>
    </PageHeader>

    <el-alert v-if="error" type="error" :title="error" show-icon :closable="false">
      <el-button size="small" :loading="loading" @click="load">重试</el-button>
    </el-alert>

    <template v-if="payload">
      <el-alert
        :type="banner.type"
        :title="banner.title"
        :description="banner.description"
        show-icon
        :closable="false"
      />

      <div class="card summary-card">
        <div class="summary-row">
          <div class="summary-main">
            <span class="muted">检查时间</span>
            <span>{{ formatTime(payload.checked_at) }}</span>
            <el-divider direction="vertical" />
            <span class="muted">真实回复</span>
            <StateTag
              :state="payload.ready_for_replies ? 'available' : 'not_verified'"
              :label="payload.ready_for_replies ? '已就绪（仍需人工验收）' : '未就绪'"
            />
            <el-divider direction="vertical" />
            <span class="muted">Mock 演示</span>
            <StateTag :state="payload.mock_only ? 'mock_only' : 'none'" :label="payload.mock_only ? '仅 Mock' : '否'" />
            <el-divider direction="vertical" />
            <span class="muted">全局暂停</span>
            <StateTag :state="payload.global_paused ? 'paused' : 'available'" :label="payload.global_paused ? '暂停中' : '未暂停'" />
          </div>
          <el-button
            v-if="payload.next_action"
            type="primary"
            @click="router.push(payload.next_action.route)"
          >
            下一步：{{ payload.next_action.label }}
          </el-button>
        </div>
        <div class="progress-line">
          <el-progress :percentage="progressPercent" :status="progressStatus" :stroke-width="10" />
          <span class="muted">{{ progressText(payload.steps) }}</span>
        </div>
      </div>

      <el-alert
        v-for="(warning, index) in payload.warnings"
        :key="`warning-${index}`"
        type="warning"
        :title="warning"
        show-icon
        :closable="false"
      />
      <el-alert
        v-for="(blocker, index) in payload.blockers"
        :key="`blocker-${index}`"
        type="error"
        :title="blocker"
        show-icon
        :closable="false"
      />

      <div v-if="desktopMode" class="card desktop-card">
        <div class="card-title">
          <span>桌面版启动检查</span>
          <StateTag
            :state="desktopSetup?.running ? 'running' : desktopSetup?.error ? 'error' : 'available'"
            :label="desktopSetup?.running ? '准备中' : desktopSetup?.error ? '有错误' : '已完成'"
          />
        </div>
        <p class="muted">
          这些步骤由桌面版在本机执行（环境、Python/Node、前端构建与后端启动），不是后端 API 能力。浏览器模式下不显示。
        </p>
        <el-alert v-if="desktopError" type="error" :title="desktopError" show-icon :closable="false" />
        <div v-if="desktopSetup?.steps.length" class="setup-steps">
          <div v-for="item in desktopSetup.steps" :key="item.id" class="setup-step">
            <el-tag size="small" :type="desktopStepTag(item.status)" effect="light">{{ desktopStepLabel(item.status) }}</el-tag>
            <span class="setup-label">{{ item.label }}</span>
            <span class="muted">{{ item.detail }}</span>
          </div>
        </div>
        <p v-else class="muted">尚未收到桌面启动步骤；后端运行后会自动刷新。</p>
      </div>

      <div class="steps-grid">
        <div v-for="step in orderedSteps" :key="step.key" class="card step-card" :class="`step-${step.state}`">
          <div class="step-head">
            <div class="step-title">
              <span class="step-index">{{ step.order }}</span>
              <span>{{ step.title }}</span>
            </div>
            <div class="step-tags">
              <el-tag size="small" :type="stepStateTag(step.state)" effect="light">{{ stepStateLabel(step.state) }}</el-tag>
              <el-tag
                v-if="step.freshness && step.freshness !== 'not_applicable'"
                size="small"
                :type="freshnessTag(step.freshness)"
                effect="plain"
              >
                {{ freshnessLabel(step.freshness) }}
              </el-tag>
            </div>
          </div>
          <p class="step-summary">{{ step.summary }}</p>
          <p v-if="step.next_step" class="step-next"><span class="muted">下一步：</span>{{ step.next_step }}</p>
          <div v-if="evidenceRows(step).length" class="evidence">
            <span v-for="row in evidenceRows(step)" :key="row.key" class="evidence-item">
              <span class="muted">{{ row.label }}</span>
              <span class="mono">{{ row.value }}</span>
            </span>
          </div>
          <el-button size="small" plain class="step-action" @click="router.push(stepRoute(step))">
            前往「{{ step.title }}」相关页面
          </el-button>
        </div>
      </div>

      <div class="card notes">
        <div class="card-title">说明</div>
        <ul>
          <li v-for="(note, index) in payload.notes" :key="index">{{ note }}</li>
        </ul>
      </div>
    </template>

    <div v-else-if="loading" class="card">
      <el-skeleton :rows="6" animated />
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'

import { api, errorMessage } from '@/api/client'
import { desktopErrorMessage, getDesktopInfo, isDesktop, subscribeDesktopState } from '@/api/desktop'
import type { DesktopInfo, DesktopSetupStep } from '@/api/desktop'
import type { OnboardingPayload } from '@/api/types'
import PageHeader from '@/components/PageHeader.vue'
import StateTag from '@/components/StateTag.vue'
import { formatTime } from '@/utils/format'
import {
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
import { ElMessage } from 'element-plus'
import { useRouter } from 'vue-router'

const router = useRouter()
const payload = ref<OnboardingPayload | null>(null)
const loading = ref(false)
const error = ref<string | null>(null)

const desktopMode = isDesktop()
const desktopInfo = ref<DesktopInfo | null>(null)
const desktopError = ref<string | null>(null)
let unsubscribeDesktop: (() => void) | null = null

const banner = computed(() =>
  payload.value
    ? overallBanner(payload.value)
    : { type: 'info' as const, title: '正在读取接入状态', description: '' },
)
const orderedSteps = computed(() =>
  payload.value ? [...payload.value.steps].sort((left, right) => left.order - right.order) : [],
)
const progressPercent = computed(() => {
  if (!payload.value || !payload.value.steps.length) return 0
  const done = payload.value.steps.filter((step) => step.state === 'done').length
  return Math.round((done / payload.value.steps.length) * 100)
})
const progressStatus = computed<'success' | 'warning' | 'exception' | undefined>(() => {
  if (!payload.value) return undefined
  if (payload.value.overall === 'ready_real') return 'success'
  if (payload.value.overall === 'blocked') return 'exception'
  return 'warning'
})
const desktopSetup = computed(() => desktopInfo.value?.setup ?? null)

function desktopStepLabel(status: DesktopSetupStep['status']): string {
  const labels: Record<DesktopSetupStep['status'], string> = {
    pending: '待执行',
    running: '执行中',
    ok: '完成',
    skipped: '已跳过',
    error: '失败',
  }
  return labels[status] ?? status
}

function desktopStepTag(status: DesktopSetupStep['status']): 'success' | 'warning' | 'danger' | 'info' {
  if (status === 'ok') return 'success'
  if (status === 'error') return 'danger'
  if (status === 'running' || status === 'skipped') return 'warning'
  return 'info'
}

async function load(): Promise<void> {
  loading.value = true
  error.value = null
  try {
    payload.value = await api<OnboardingPayload>('/onboarding')
  } catch (err) {
    error.value = errorMessage(err)
    const next = payload.value ? nextTodoStep(payload.value.steps) : null
    if (next) {
      ElMessage.warning(`状态刷新失败，当前显示的是上次结果：${next.title}`)
    }
  } finally {
    loading.value = false
  }
}

async function loadDesktop(): Promise<void> {
  if (!desktopMode) return
  try {
    desktopInfo.value = await getDesktopInfo()
    desktopError.value = null
  } catch (err) {
    desktopError.value = desktopErrorMessage(err)
  }
}

function onFocus(): void {
  void load()
  void loadDesktop()
}

onMounted(() => {
  void load()
  void loadDesktop()
  if (desktopMode) {
    unsubscribeDesktop = subscribeDesktopState((info) => {
      desktopInfo.value = info
    })
  }
  window.addEventListener('focus', onFocus)
})

onBeforeUnmount(() => {
  unsubscribeDesktop?.()
  unsubscribeDesktop = null
  window.removeEventListener('focus', onFocus)
})
</script>

<style scoped>
.summary-card {
  margin-top: 14px;
}

.summary-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  flex-wrap: wrap;
}

.summary-main {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  font-size: 13px;
}

.progress-line {
  display: flex;
  align-items: center;
  gap: 14px;
  margin-top: 14px;
}

.progress-line :deep(.el-progress) {
  flex: 1;
}

.desktop-card {
  margin-top: 14px;
}

.setup-steps {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-top: 10px;
}

.setup-step {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  font-size: 13px;
}

.setup-label {
  min-width: 150px;
  font-weight: 600;
}

.steps-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(330px, 1fr));
  gap: 14px;
  margin-top: 14px;
}

.step-card {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.step-blocked {
  border-color: var(--app-danger, #dc2626);
}

.step-head {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 10px;
}

.step-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-weight: 650;
  font-size: 14px;
}

.step-index {
  display: grid;
  place-items: center;
  width: 22px;
  height: 22px;
  border-radius: 7px;
  background: var(--app-surface-soft);
  color: var(--app-muted);
  font-size: 12px;
}

.step-tags {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
  justify-content: flex-end;
}

.step-summary {
  margin: 0;
  font-size: 13px;
  line-height: 1.6;
}

.step-next {
  margin: 0;
  font-size: 12.5px;
  line-height: 1.6;
}

.evidence {
  display: flex;
  flex-wrap: wrap;
  gap: 6px 14px;
  font-size: 12px;
}

.evidence-item {
  display: inline-flex;
  gap: 5px;
}

.step-action {
  align-self: flex-start;
  margin-top: 4px;
}

.notes {
  margin-top: 14px;
}

.notes ul {
  margin: 0;
  padding-left: 18px;
  display: flex;
  flex-direction: column;
  gap: 6px;
  font-size: 13px;
  line-height: 1.6;
}
</style>

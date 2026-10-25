<template>
  <div class="page">
    <PageHeader title="仪表盘" :description="headerDescription">
      <template #actions>
        <el-button :loading="loading" @click="load">刷新</el-button>
        <el-button type="primary" :loading="demoLoading" @click="bootstrapDemo">一键初始化 Mock 演示环境</el-button>
        <el-button @click="router.push('/playground')">打开模拟测试</el-button>
      </template>
    </PageHeader>

    <el-alert
      v-if="error"
      type="error"
      :title="error"
      show-icon
      :closable="false"
    />

    <el-alert
      v-if="dashboard?.global_pause.paused"
      type="error"
      title="全局紧急暂停生效中：所有自动回复和发送队列均已停止。"
      :description="dashboard.global_pause.reason || '未填写原因'"
      show-icon
      :closable="false"
    />

    <el-alert
      v-if="dashboard?.providers.default?.is_mock"
      type="warning"
      title="当前默认模型是 Mock 模型：回复内容为固定模板，仅用于验证流程，不代表真实模型能力。"
      show-icon
      :closable="false"
    />

    <el-alert
      v-if="dashboard && dashboard.providers.total === 0"
      type="info"
      title="尚未配置模型 Provider。可以先初始化 Mock 演示环境，或前往「模型 API」填写真实的 OpenAI 兼容接口。"
      show-icon
      :closable="false"
    />

    <div class="grid grid-4">
      <div class="card metric">
        <span class="metric-label">QQ 账号</span>
        <span class="metric-value">{{ dashboard?.accounts.total ?? '—' }}</span>
        <span class="muted">在线 {{ dashboard?.accounts.online ?? 0 }} 个</span>
      </div>
      <div class="card metric">
        <span class="metric-label">白名单群</span>
        <span class="metric-value">{{ dashboard?.groups.total ?? '—' }}</span>
        <span class="muted">启用中 {{ dashboard?.groups.active ?? 0 }} 个</span>
      </div>
      <div class="card metric">
        <span class="metric-label">今日消息</span>
        <span class="metric-value">{{ (dashboard?.messages.inbound_today ?? 0) + (dashboard?.messages.outbound_today ?? 0) }}</span>
        <span class="muted">收 {{ dashboard?.messages.inbound_today ?? 0 }} · 发 {{ dashboard?.messages.outbound_today ?? 0 }}</span>
      </div>
      <div class="card metric">
        <span class="metric-label">今日模型调用</span>
        <span class="metric-value">{{ formatNumber(dashboard?.usage_today.requests ?? 0) }}</span>
        <span class="muted">
          {{ formatNumber(dashboard?.usage_today.tokens ?? 0) }} tokens · 失败 {{ dashboard?.usage_today.failed_requests ?? 0 }}
          · 估算 {{ formatCost(dashboard?.usage_today.cost, dashboard?.usage_today.currency) }}
        </span>
      </div>
    </div>

    <el-alert
      v-if="dashboard && (dashboard.usage_today.cost_status === 'partial' || dashboard.usage_today.cost_status === 'unconfigured')"
      type="warning"
      show-icon
      :closable="false"
      title="今日存在无法估算成本的模型调用"
      :description="dashboard.usage_today.cost_note"
    />

    <div class="grid grid-2">
      <div class="card">
        <div class="card-title">
          <span>运行状态</span>
          <StateTag :state="appStore.ready ? 'available' : 'error'" :label="appStore.ready ? '后端就绪' : '后端异常'" />
        </div>
        <el-descriptions :column="2" border size="small">
          <el-descriptions-item label="应用">{{ dashboard?.app.name ?? '—' }} v{{ dashboard?.app.version ?? '—' }}</el-descriptions-item>
          <el-descriptions-item label="环境">{{ dashboard?.app.env ?? '—' }}</el-descriptions-item>
          <el-descriptions-item label="默认模型">
            <template v-if="dashboard?.providers.default">
              {{ dashboard.providers.default.name }}
              <el-tag v-if="dashboard.providers.default.is_mock" size="small" type="warning">Mock</el-tag>
              <span class="muted"> / {{ dashboard.providers.default.model }}</span>
            </template>
            <span v-else class="muted">未配置</span>
          </el-descriptions-item>
          <el-descriptions-item label="模型 Provider">{{ dashboard?.providers.total ?? 0 }} 个（启用 {{ dashboard?.providers.enabled ?? 0 }}）</el-descriptions-item>
          <el-descriptions-item label="全局暂停">
            <StateTag :state="appStore.paused ? 'paused' : 'available'" :label="appStore.paused ? '已暂停' : '正常运行'" />
          </el-descriptions-item>
          <el-descriptions-item label="发送队列">
            <span class="mono">{{ outboxSummary }}</span>
          </el-descriptions-item>
        </el-descriptions>
        <div class="quick-actions">
          <el-button size="small" @click="router.push('/accounts')">配置 QQ 接入</el-button>
          <el-button size="small" @click="router.push('/providers')">配置模型</el-button>
          <el-button size="small" @click="router.push('/groups')">管理群白名单</el-button>
          <el-button size="small" @click="router.push('/personas')">人格工作台</el-button>
        </div>
      </div>

      <div class="card">
        <div class="card-title">
          <span>媒体能力</span>
          <span class="muted">真实 Provider 未配置时不识别内容</span>
        </div>
        <el-table :data="dashboard?.capabilities ?? []" size="small">
          <el-table-column prop="capability" label="能力" width="100" />
          <el-table-column label="状态" width="110">
            <template #default="{ row }">
              <StateTag :state="row.state" />
            </template>
          </el-table-column>
          <el-table-column prop="note" label="说明" show-overflow-tooltip />
        </el-table>
      </div>
    </div>

    <div class="grid grid-2">
      <div class="card">
        <div class="card-title">
          <span>今日按 Provider 用量</span>
          <el-tag size="small" :type="costStatusTag(dashboard?.usage_today.cost_status)">
            {{ costStatusLabel(dashboard?.usage_today.cost_status) }}
          </el-tag>
        </div>
        <el-table :data="providerUsageRows" size="small" max-height="300">
          <el-table-column label="Provider" min-width="170">
            <template #default="{ row }">
              <div>
                {{ row.provider_name || '未记录 Provider' }}
                <el-tag v-if="row.is_mock" size="small" type="warning">Mock</el-tag>
              </div>
              <div class="muted mono">{{ row.model || row.provider_type }}</div>
            </template>
          </el-table-column>
          <el-table-column label="请求" width="100">
            <template #default="{ row }">
              {{ formatNumber(row.requests) }}
              <div class="muted small-text">成功 {{ row.successful_requests }} · 失败 {{ row.failed_requests }}</div>
            </template>
          </el-table-column>
          <el-table-column label="Token" width="85">
            <template #default="{ row }">{{ formatNumber(row.tokens) }}</template>
          </el-table-column>
          <el-table-column label="估算费用" min-width="150">
            <template #default="{ row }">
              <div>{{ formatCost(row.cost, row.currency) }}</div>
              <el-tag size="small" :type="costStatusTag(row.cost_status)">{{ costStatusLabel(row.cost_status) }}</el-tag>
            </template>
          </el-table-column>
        </el-table>
        <el-empty v-if="!providerUsageRows.length" description="今日还没有模型调用。" :image-size="60" />
        <p class="muted small-text">费用按你填写的 Provider 单价与本地 Token 记录估算，不是服务商账单。</p>
      </div>

      <div class="card">
        <div class="card-title">
          <span>今日按群用量</span>
          <span class="muted">仅展示有调用的群</span>
        </div>
        <el-table :data="groupUsageRows" size="small" max-height="300">
          <el-table-column label="群" min-width="150">
            <template #default="{ row }">{{ row.group_name || row.group_id || '未关联群' }}</template>
          </el-table-column>
          <el-table-column label="请求" width="100">
            <template #default="{ row }">
              {{ formatNumber(row.requests) }}
              <div class="muted small-text">成功 {{ row.successful_requests }} · 失败 {{ row.failed_requests }}</div>
            </template>
          </el-table-column>
          <el-table-column label="Token" width="85">
            <template #default="{ row }">{{ formatNumber(row.tokens) }}</template>
          </el-table-column>
          <el-table-column label="估算费用" min-width="150">
            <template #default="{ row }">
              <div>{{ formatCost(row.cost, row.currency) }}</div>
              <el-tag size="small" :type="costStatusTag(row.cost_status)">{{ costStatusLabel(row.cost_status) }}</el-tag>
            </template>
          </el-table-column>
        </el-table>
        <el-empty v-if="!groupUsageRows.length" description="今日还没有群内模型调用。" :image-size="60" />
      </div>
    </div>

    <div class="grid grid-2">
      <div class="card">
        <div class="card-title">
          <span>实时事件</span>
          <StateTag :state="eventsStore.status === 'open' ? 'online' : 'reconnecting'" :label="eventsStore.status === 'open' ? 'SSE 已连接' : 'SSE 未连接'" />
        </div>
        <el-empty v-if="liveEvents.length === 0" description="暂无实时事件；初始化演示环境或注入模拟事件后可看到。" :image-size="60" />
        <el-timeline v-else>
          <el-timeline-item v-for="event in liveEvents" :key="event.seq" :timestamp="formatTime(event.at)" placement="top">
            <div class="event-line">
              <el-tag size="small" effect="plain">{{ eventLabel(event.type) }}</el-tag>
              <span class="muted">{{ eventDetail(event) }}</span>
            </div>
          </el-timeline-item>
        </el-timeline>
      </div>

      <div class="card">
        <div class="card-title">
          <span>最近消息</span>
          <el-button size="small" text @click="router.push('/messages')">查看全部</el-button>
        </div>
        <el-empty v-if="!dashboard?.recent_messages.length" description="暂无消息记录" :image-size="60" />
        <el-table v-else :data="dashboard.recent_messages" size="small">
          <el-table-column label="时间" width="118">
            <template #default="{ row }">{{ formatTime(row.at) }}</template>
          </el-table-column>
          <el-table-column label="方向" width="70">
            <template #default="{ row }">
              <el-tag size="small" :type="row.direction === 'inbound' ? 'info' : 'success'">
                {{ row.direction === 'inbound' ? '收' : '发' }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="sender_name" label="发送者" width="110" show-overflow-tooltip />
          <el-table-column prop="preview" label="内容" show-overflow-tooltip />
          <el-table-column label="状态" width="90">
            <template #default="{ row }">
              <StateTag :state="row.status" />
            </template>
          </el-table-column>
        </el-table>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import { api, errorMessage } from '@/api/client'
import type { DashboardPayload } from '@/api/types'
import PageHeader from '@/components/PageHeader.vue'
import StateTag from '@/components/StateTag.vue'
import { useAppStore } from '@/stores/app'
import { useEventsStore } from '@/stores/events'
import {
  costStatusLabel,
  costStatusTag,
  eventDetail,
  eventLabel,
  formatCost,
  formatNumber,
  formatTime,
} from '@/utils/format'
import { ElMessage } from 'element-plus'
import { useRouter } from 'vue-router'

const router = useRouter()
const appStore = useAppStore()
const eventsStore = useEventsStore()

const dashboard = ref<DashboardPayload | null>(null)
const loading = ref(false)
const demoLoading = ref(false)
const error = ref<string | null>(null)

const headerDescription = computed(
  () =>
    '查看连接、群聊、消息与模型调用概况。所有统计来自本地数据库；Mock 数据会明确标注，不代表真实 QQ 或真实模型。',
)

const liveEvents = computed(() =>
  eventsStore.items.length ? eventsStore.items.slice(0, 12) : (dashboard.value?.recent_events.slice(0, 12) ?? []),
)

const providerUsageRows = computed(() =>
  (dashboard.value?.usage_today.by_provider ?? []).filter((row) => row.requests > 0),
)

const groupUsageRows = computed(() =>
  (dashboard.value?.usage_today.by_group ?? []).filter((row) => row.requests > 0),
)

const outboxSummary = computed(() => {
  const outbox = dashboard.value?.outbox ?? {}
  const entries = Object.entries(outbox)
  if (!entries.length) return '空'
  return entries.map(([status, count]) => `${status}:${count}`).join(' · ')
})

async function load(): Promise<void> {
  loading.value = true
  error.value = null
  try {
    dashboard.value = await api<DashboardPayload>('/dashboard')
    await appStore.refresh()
  } catch (err) {
    error.value = errorMessage(err)
  } finally {
    loading.value = false
  }
}

async function bootstrapDemo(): Promise<void> {
  demoLoading.value = true
  try {
    const result = await api<{ created: string[]; notes: string[] }>('/demo/bootstrap', {
      method: 'POST',
      body: {},
    })
    ElMessage.success(
      result.created.length ? `演示环境已创建：${result.created.join('、')}` : '演示环境已存在，无需重复创建。',
    )
    await load()
    eventsStore.connect()
  } catch (err) {
    ElMessage.error(errorMessage(err))
  } finally {
    demoLoading.value = false
  }
}

onMounted(load)
</script>

<style scoped>
.quick-actions {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  margin-top: 14px;
}

.event-line {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.small-text {
  font-size: 11px;
  margin-top: 2px;
}

</style>

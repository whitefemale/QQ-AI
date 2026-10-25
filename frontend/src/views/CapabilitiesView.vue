<template>
  <div class="page">
    <PageHeader
      title="能力中心"
      description="集中查看连接方式、模型接口与多模态能力的真实状态。未配置真实 Provider 时，AI 不会识别图片、语音或视频内容，界面不会把模拟结果伪装成真实识别。"
    >
      <template #actions>
        <el-button :loading="loading" @click="loadAll">刷新</el-button>
        <el-button :loading="processing" @click="processDue">处理到期媒体任务</el-button>
      </template>
    </PageHeader>

    <el-alert v-if="error" type="error" :title="error" show-icon :closable="false" />

    <el-alert
      v-if="hasMockOnly"
      type="warning"
      show-icon
      :closable="false"
      title="部分媒体能力仅启用了 Mock Provider：处理结果是模拟的，不代表真实识别。"
    />
    <el-alert
      v-if="capabilities && !hasRealMedia"
      type="info"
      show-icon
      :closable="false"
      title="当前没有启用真实媒体 Provider。收到图片/语音/视频时，模型只会看到「未配置识别能力」的文字提示。"
    />

    <div class="grid grid-2">
      <div class="card">
        <div class="card-title">连接方式</div>
        <el-table :data="capabilities?.connections ?? []" size="small">
          <el-table-column prop="name" label="方式" min-width="150" />
          <el-table-column label="状态" width="130">
            <template #default="{ row }">
              <StateTag :state="row.state" />
            </template>
          </el-table-column>
          <el-table-column prop="note" label="说明" show-overflow-tooltip />
          <el-table-column type="expand">
            <template #default="{ row }">
              <pre class="detail-pre">{{ JSON.stringify(row.capabilities ?? {}, null, 2) }}</pre>
            </template>
          </el-table-column>
        </el-table>
      </div>

      <div class="card">
        <div class="card-title">模型接口</div>
        <el-descriptions :column="1" border size="small">
          <el-descriptions-item label="可用">
            <el-tag v-for="item in capabilities?.llm.available ?? []" :key="item" size="small" type="success" class="gap-tag">
              {{ llmTypeLabel(item) }}
            </el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="规划中">
            <el-tag v-for="item in capabilities?.llm.planned ?? []" :key="item" size="small" type="info" class="gap-tag">
              {{ item }}
            </el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="说明">{{ capabilities?.llm.note ?? '—' }}</el-descriptions-item>
        </el-descriptions>
        <el-divider />
        <div class="card-title">功能状态</div>
        <div class="feature-list">
          <div v-for="feature in capabilities?.features ?? []" :key="feature.key" class="feature-line">
            <span class="mono">{{ feature.key }}</span>
            <StateTag :state="feature.state" />
            <span class="muted">{{ feature.note }}</span>
          </div>
        </div>
      </div>
    </div>

    <div class="card">
      <div class="card-title">
        <span>媒体能力</span>
        <span class="muted">available = 真实已启用 · mock_only = 仅模拟 · unconfigured = 未配置 · planned = 规划中</span>
      </div>
      <el-table v-loading="loading" :data="capabilities?.media ?? []" row-key="capability">
        <el-table-column prop="capability" label="能力" width="140" />
        <el-table-column prop="provider_type" label="Provider 类型" width="140" />
        <el-table-column label="状态" width="120">
          <template #default="{ row }">
            <StateTag :state="row.state" />
          </template>
        </el-table-column>
        <el-table-column prop="note" label="说明" min-width="260" show-overflow-tooltip />
        <el-table-column label="已注册 Provider" min-width="220">
          <template #default="{ row }">
            <span v-if="!row.providers.length" class="muted">无</span>
            <el-tag v-for="provider in row.providers" :key="provider.provider_id" size="small" class="gap-tag" :type="provider.enabled ? 'success' : 'info'">
              {{ provider.name }}{{ provider.is_mock ? '（Mock）' : '' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column type="expand">
          <template #default="{ row }">
            <div class="provider-list">
              <el-empty v-if="!row.providers.length" description="没有注册 Provider" :image-size="45" />
              <div v-for="provider in row.providers" :key="provider.provider_id" class="provider-line">
                <div class="provider-meta">
                  <strong>{{ provider.name }}</strong>
                  <span class="muted mono">{{ provider.provider_id }} · v{{ provider.version }}</span>
                  <StateTag :state="provider.status" />
                  <el-tag v-if="provider.is_mock" size="small" type="warning">Mock</el-tag>
                  <el-tag v-if="provider.planned" size="small" type="info">规划中</el-tag>
                  <span class="muted">健康：{{ provider.health_status }}</span>
                </div>
                <div class="row-actions">
                  <el-button size="small" @click="testMedia(provider.provider_id)">健康检查</el-button>
                  <el-button size="small" :disabled="provider.planned" @click="toggleMedia(provider, !provider.enabled)">
                    {{ provider.enabled ? '停用' : '启用' }}
                  </el-button>
                </div>
              </div>
            </div>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <div class="card">
      <div class="card-title">
        <span>媒体任务队列</span>
        <div class="filter-line">
          <el-select v-model="jobStatus" size="small" clearable placeholder="全部状态" style="width: 140px" @change="loadJobs">
            <el-option label="queued" value="queued" />
            <el-option label="running" value="running" />
            <el-option label="succeeded" value="succeeded" />
            <el-option label="failed" value="failed" />
            <el-option label="cancelled" value="cancelled" />
          </el-select>
          <el-button size="small" @click="loadJobs">刷新</el-button>
        </div>
      </div>
      <el-table v-loading="jobsLoading" :data="jobs" size="small">
        <el-table-column prop="job_type" label="类型" width="100" />
        <el-table-column prop="capability" label="能力" width="110" />
        <el-table-column prop="media_ref" label="媒体引用" min-width="180" show-overflow-tooltip />
        <el-table-column label="状态" width="110">
          <template #default="{ row }"><StateTag :state="row.status" /></template>
        </el-table-column>
        <el-table-column label="尝试" width="80">
          <template #default="{ row }">{{ row.attempts }}/{{ row.max_attempts }}</template>
        </el-table-column>
        <el-table-column label="错误" min-width="180">
          <template #default="{ row }">
            <span v-if="row.error_code" class="muted">{{ row.error_code }}：{{ row.error_message }}</span>
            <span v-else class="muted">—</span>
          </template>
        </el-table-column>
        <el-table-column label="创建时间" width="150">
          <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="130">
          <template #default="{ row }">
            <el-button v-if="['queued', 'running'].includes(row.status)" size="small" @click="cancelJob(row)">取消</el-button>
            <el-button v-else-if="row.status === 'failed'" size="small" @click="retryJob(row)">重试</el-button>
          </template>
        </el-table-column>
      </el-table>
      <el-empty v-if="!jobsLoading && !jobs.length" description="暂无媒体任务。P0 阶段不会自动下载真实 QQ 媒体文件。" :image-size="55" />
      <p class="muted job-note">Mock 媒体任务的输出是模拟结果，不代表真实识别；真实媒体 Provider 属于后续版本规划。</p>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import { api, errorMessage } from '@/api/client'
import type { CapabilitiesPayload, MediaJob } from '@/api/types'
import PageHeader from '@/components/PageHeader.vue'
import StateTag from '@/components/StateTag.vue'
import { formatTime } from '@/utils/format'
import { ElMessage } from 'element-plus'

interface RegistryProvider {
  provider_id: string
  name: string
  version: string
  enabled: boolean
  status: string
  health_status: string
  is_mock: boolean
  planned: boolean
  last_error?: string | null
}

const capabilities = ref<CapabilitiesPayload | null>(null)
const loading = ref(false)
const jobsLoading = ref(false)
const processing = ref(false)
const error = ref<string | null>(null)
const jobs = ref<MediaJob[]>([])
const jobStatus = ref<string | undefined>(undefined)

function llmTypeLabel(value: string): string {
  if (value === 'mock') return 'Mock 模型'
  if (value === 'anthropic_native') return 'Anthropic 原生'
  if (value === 'openai_compatible') return 'OpenAI 兼容'
  return value
}

const hasMockOnly = computed(() => capabilities.value?.media.some((item) => item.state === 'mock_only') ?? false)
const hasRealMedia = computed(() => capabilities.value?.media.some((item) => item.state === 'available') ?? false)

async function loadCapabilities(): Promise<void> {
  loading.value = true
  error.value = null
  try {
    capabilities.value = await api<CapabilitiesPayload>('/capabilities')
  } catch (err) {
    error.value = errorMessage(err)
  } finally {
    loading.value = false
  }
}

async function loadJobs(): Promise<void> {
  jobsLoading.value = true
  try {
    const query: Record<string, string | number> = { limit: 100 }
    if (jobStatus.value) query.status = jobStatus.value
    const data = await api<{ items: MediaJob[] }>('/media/jobs', { query })
    jobs.value = data.items
  } catch (err) {
    ElMessage.error(errorMessage(err))
  } finally {
    jobsLoading.value = false
  }
}

async function loadAll(): Promise<void> {
  await Promise.all([loadCapabilities(), loadJobs()])
}

async function toggleMedia(provider: RegistryProvider, enabled: boolean): Promise<void> {
  try {
    await api(`/media/providers/${provider.provider_id}/enable`, {
      method: 'POST',
      body: { enabled },
    })
    ElMessage.success(enabled ? '已启用媒体 Provider。' : '已停用媒体 Provider。')
    await loadCapabilities()
  } catch (err) {
    ElMessage.error(errorMessage(err))
  }
}

async function testMedia(providerId: string): Promise<void> {
  try {
    const data = await api<RegistryProvider>(`/media/providers/${providerId}/test`, { method: 'POST' })
    if (data.health_status === 'healthy') {
      ElMessage.success('健康检查通过。')
    } else {
      ElMessage.warning(`健康状态：${data.health_status}${data.last_error ? ` · ${data.last_error}` : ''}`)
    }
    await loadCapabilities()
  } catch (err) {
    ElMessage.error(errorMessage(err))
  }
}

async function cancelJob(job: MediaJob): Promise<void> {
  try {
    await api(`/media/jobs/${job.id}/cancel`, { method: 'POST' })
    ElMessage.success('任务已取消。')
    await loadJobs()
  } catch (err) {
    ElMessage.error(errorMessage(err))
  }
}

async function retryJob(job: MediaJob): Promise<void> {
  try {
    await api(`/media/jobs/${job.id}/retry`, { method: 'POST' })
    ElMessage.success('任务已重新排队。')
    await loadJobs()
  } catch (err) {
    ElMessage.error(errorMessage(err))
  }
}

async function processDue(): Promise<void> {
  processing.value = true
  try {
    const data = await api<{ processed: number }>('/media/jobs/process-due', { method: 'POST' })
    ElMessage.success(`已处理 ${data.processed} 个到期任务。`)
    await loadJobs()
  } catch (err) {
    ElMessage.error(errorMessage(err))
  } finally {
    processing.value = false
  }
}

onMounted(loadAll)
</script>

<style scoped>
.gap-tag {
  margin-right: 6px;
  margin-bottom: 4px;
}

.feature-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.feature-line {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  font-size: 13px;
}

.detail-pre {
  background: var(--app-surface-soft);
  border-radius: 6px;
  padding: 10px;
  font-size: 12px;
  margin: 0 12px 10px 48px;
}

.provider-list {
  padding: 8px 16px 12px 48px;
}

.provider-line {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
  padding: 8px 0;
  border-bottom: 1px dashed var(--app-border);
}

.provider-meta {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.filter-line {
  display: flex;
  gap: 8px;
  align-items: center;
}

.job-note {
  margin: 10px 0 0;
  font-size: 12px;
}
</style>

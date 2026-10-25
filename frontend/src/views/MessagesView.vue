<template>
  <div class="page">
    <PageHeader
      title="消息与用量"
      description="查看消息处理结果、触发/拦截原因、发送队列与模型调用用量。群消息仅来自你接入的账号与白名单群；提示词不会在这里展示，敏感字段已脱敏。"
    >
      <template #actions>
        <el-button :loading="loading" @click="reloadCurrent">刷新</el-button>
      </template>
    </PageHeader>

    <el-alert v-if="error" type="error" :title="error" show-icon :closable="false" />

    <el-tabs v-model="activeTab" @tab-change="onTabChange">
      <el-tab-pane label="消息日志" name="messages">
        <div class="card">
          <div class="filter-bar">
            <el-input v-model="filters.search" placeholder="搜索内容 / 发送者 / QQ 号" clearable style="width: 220px" @keyup.enter="loadMessages(1)" />
            <el-select v-model="filters.account_id" placeholder="账号" clearable style="width: 150px">
              <el-option v-for="account in accounts" :key="account.id" :label="account.display_name" :value="account.id" />
            </el-select>
            <el-select v-model="filters.group_id" placeholder="群" clearable style="width: 160px">
              <el-option v-for="group in groups" :key="group.id" :label="group.name || group.platform_group_id" :value="group.id" />
            </el-select>
            <el-select v-model="filters.direction" placeholder="方向" clearable style="width: 100px">
              <el-option label="接收" value="inbound" />
              <el-option label="发送" value="outbound" />
            </el-select>
            <el-select v-model="filters.status" placeholder="处理状态" clearable style="width: 140px">
              <el-option v-for="status in messageStatuses" :key="status.value" :label="status.label" :value="status.value" />
            </el-select>
            <el-date-picker
              v-model="dateRange"
              type="datetimerange"
              range-separator="至"
              start-placeholder="开始时间"
              end-placeholder="结束时间"
              style="width: 340px"
            />
            <el-button type="primary" @click="loadMessages(1)">查询</el-button>
            <el-button @click="resetFilters">重置</el-button>
          </div>

          <el-table v-loading="loading" :data="messages" row-key="id">
            <el-table-column label="时间" width="152">
              <template #default="{ row }">{{ formatTime(row.event_timestamp) }}</template>
            </el-table-column>
            <el-table-column label="方向" width="75">
              <template #default="{ row }">
                <el-tag size="small" :type="row.direction === 'inbound' ? 'info' : 'success'">
                  {{ row.direction === 'inbound' ? '接收' : '发送' }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column label="会话 / 发送者" width="180">
              <template #default="{ row }">
                <div>{{ row.group_name || (row.conversation_type === 'private' ? '私聊' : row.conversation_id) }}</div>
                <div class="muted">
                  {{ row.sender_name || row.sender_id }}
                  <el-tag v-if="row.is_self" size="small" type="warning">自身</el-tag>
                </div>
              </template>
            </el-table-column>
            <el-table-column label="内容" min-width="260">
              <template #default="{ row }">
                <div class="message-text">{{ truncate(row.content_text, 140) || '（无文本内容）' }}</div>
              </template>
            </el-table-column>
            <el-table-column label="状态" width="120">
              <template #default="{ row }">
                <StateTag :state="row.processing_status" />
              </template>
            </el-table-column>
            <el-table-column label="触发 / 拦截原因" width="140">
              <template #default="{ row }">
                <span class="muted">{{ row.trigger_reason || '—' }}</span>
              </template>
            </el-table-column>
            <el-table-column label="模型" width="150">
              <template #default="{ row }">
                <span v-if="row.model_latency_ms !== null || row.input_tokens !== null" class="muted">
                  {{ row.model_latency_ms ?? '—' }} ms · {{ row.input_tokens ?? 0 }}/{{ row.output_tokens ?? 0 }} tok
                </span>
                <span v-else class="muted">—</span>
              </template>
            </el-table-column>
            <el-table-column type="expand">
              <template #default="{ row }">
                <div class="detail-panel">
                  <div class="detail-grid">
                    <div><span class="muted">内部 ID：</span><span class="mono">{{ row.id }}</span></div>
                    <div><span class="muted">平台消息 ID：</span><span class="mono">{{ row.platform_message_id }}</span></div>
                    <div><span class="muted">账号：</span>{{ row.account_name || row.account_id }}</div>
                    <div><span class="muted">会话类型：</span>{{ row.conversation_type }}</div>
                    <div><span class="muted">会话 ID：</span><span class="mono">{{ row.conversation_id }}</span></div>
                    <div><span class="muted">回复目标：</span><span class="mono">{{ row.reply_to_message_id || '—' }}</span></div>
                  </div>
                  <el-alert
                    v-if="row.error_code"
                    type="error"
                    :title="`${row.error_code}：${row.error_message || ''}`"
                    :closable="false"
                    show-icon
                  />
                  <div class="muted">完整文本</div>
                  <pre class="detail-pre">{{ row.content_text || '（空）' }}</pre>
                  <div class="muted">消息段（仅内部 media_ref，不含原始媒体内容）</div>
                  <pre class="detail-pre">{{ JSON.stringify(row.segments, null, 2) }}</pre>
                </div>
              </template>
            </el-table-column>
          </el-table>
          <el-empty v-if="!loading && !messages.length" description="没有匹配的消息。可先初始化 Mock 演示环境并注入模拟事件。" />
          <div class="pager">
            <el-pagination
              v-model:current-page="page"
              v-model:page-size="pageSize"
              :total="total"
              :page-sizes="[20, 50, 100, 200]"
              layout="total, sizes, prev, pager, next"
              @current-change="loadMessages()"
              @size-change="loadMessages(1)"
            />
          </div>
        </div>
      </el-tab-pane>

      <el-tab-pane label="发送队列" name="outbox">
        <div class="card">
          <div class="filter-bar">
            <el-select v-model="outboxStatus" placeholder="状态" clearable style="width: 150px" @change="loadOutbox(1)">
              <el-option v-for="status in outboxStatuses" :key="status.value" :label="status.label" :value="status.value" />
            </el-select>
            <el-button @click="loadOutbox(1)">刷新</el-button>
            <el-button type="primary" :loading="dispatching" @click="dispatchDue">处理到期消息</el-button>
          </div>
          <el-alert
            type="info"
            :closable="false"
            show-icon
            title="未知发送状态不会重发"
            description="网络超时导致的 unknown 状态保持不动，避免重复发送；只有明确可重试的失败才会重新排队。"
          />
          <el-table v-loading="outboxLoading" :data="outbox" row-key="id">
            <el-table-column label="创建时间" width="152">
              <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
            </el-table-column>
            <el-table-column label="会话" width="160">
              <template #default="{ row }">
                <div class="mono">{{ row.conversation_id }}</div>
                <div class="muted">{{ row.conversation_type }}</div>
              </template>
            </el-table-column>
            <el-table-column label="内容" min-width="240">
              <template #default="{ row }">{{ truncate(row.content, 140) }}</template>
            </el-table-column>
            <el-table-column label="状态" width="120">
              <template #default="{ row }"><StateTag :state="row.status" /></template>
            </el-table-column>
            <el-table-column label="尝试" width="80">
              <template #default="{ row }">{{ row.attempts }}/{{ row.max_attempts }}</template>
            </el-table-column>
            <el-table-column label="计划重试" width="152">
              <template #default="{ row }">{{ formatTime(row.next_attempt_at) }}</template>
            </el-table-column>
            <el-table-column label="错误" min-width="180">
              <template #default="{ row }">
                <span v-if="row.last_error_code" class="muted">{{ row.last_error_code }}：{{ row.last_error_message }}</span>
                <span v-else class="muted">—</span>
              </template>
            </el-table-column>
            <el-table-column label="已发送 ID" width="160">
              <template #default="{ row }">
                <span class="mono">{{ row.sent_platform_message_id || '—' }}</span>
              </template>
            </el-table-column>
          </el-table>
          <el-empty v-if="!outboxLoading && !outbox.length" description="发送队列为空。" />
          <div class="pager">
            <el-pagination
              v-model:current-page="outboxPage"
              v-model:page-size="outboxPageSize"
              :total="outboxTotal"
              :page-sizes="[20, 50, 100]"
              layout="total, sizes, prev, pager, next"
              @current-change="loadOutbox()"
              @size-change="loadOutbox(1)"
            />
          </div>
        </div>
      </el-tab-pane>

      <el-tab-pane label="模型用量" name="usage">
        <div class="grid grid-4">
          <div class="card metric">
            <span class="metric-label">{{ usageSummary?.hours ?? 24 }} 小时请求</span>
            <span class="metric-value">{{ formatNumber(usageSummary?.requests ?? 0) }}</span>
            <span class="muted">成功 {{ formatNumber(usageSummary?.successful_requests ?? 0) }} · 失败 {{ formatNumber(usageSummary?.failed_requests ?? 0) }}</span>
          </div>
          <div class="card metric">
            <span class="metric-label">Token</span>
            <span class="metric-value">{{ formatNumber(usageSummary?.tokens ?? 0) }}</span>
          </div>
          <div class="card metric">
            <span class="metric-label">估算成本</span>
            <span class="metric-value">{{ formatCost(usageSummary?.cost, usageSummary?.currency) }}</span>
            <span class="muted">
              <el-tag size="small" :type="costStatusTag(usageSummary?.cost_status)">
                {{ costStatusLabel(usageSummary?.cost_status) }}
              </el-tag>
              按本地单价估算，不是服务商账单
            </span>
          </div>
          <div class="card metric">
            <span class="metric-label">调用记录</span>
            <span class="metric-value">{{ usageTotal }}</span>
            <span class="muted">含失败与成长分析</span>
          </div>
        </div>
        <el-alert
          v-if="usageSummary && (usageSummary.cost_status === 'partial' || usageSummary.cost_status === 'unconfigured')"
          type="warning"
          :closable="false"
          show-icon
          title="部分成功调用没有可估算的成本"
          :description="usageSummary.cost_note"
        />
        <div class="card">
          <div class="filter-bar">
            <el-select v-model="usageFilters.purpose" placeholder="用途" clearable style="width: 160px" @change="loadUsage(1)">
              <el-option label="聊天回复" value="reply" />
              <el-option label="人格成长分析" value="persona_growth" />
            </el-select>
            <el-select v-model="usageFilters.status" placeholder="状态" clearable style="width: 140px" @change="loadUsage(1)">
              <el-option label="成功" value="success" />
              <el-option label="失败" value="error" />
            </el-select>
            <el-button @click="loadUsage(1)">刷新</el-button>
          </div>
          <el-table v-loading="usageLoading" :data="usage" size="small">
            <el-table-column label="时间" width="152">
              <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
            </el-table-column>
            <el-table-column label="模型" min-width="180">
              <template #default="{ row }">
                <div class="mono">{{ row.model }}</div>
                <div class="muted">{{ row.provider_type }}</div>
              </template>
            </el-table-column>
            <el-table-column prop="purpose" label="用途" width="130" />
            <el-table-column label="Token" width="130">
              <template #default="{ row }">
                <template v-if="row.input_tokens !== null || row.output_tokens !== null">
                  {{ row.input_tokens ?? 0 }} / {{ row.output_tokens ?? 0 }}
                </template>
                <span v-else class="muted">—</span>
              </template>
            </el-table-column>
            <el-table-column label="耗时" width="90">
              <template #default="{ row }">{{ row.latency_ms !== null ? `${row.latency_ms} ms` : '—' }}</template>
            </el-table-column>
            <el-table-column label="估算成本" width="130">
              <template #default="{ row }">{{ formatCost(row.estimated_cost, row.currency) }}</template>
            </el-table-column>
            <el-table-column label="状态" width="110">
              <template #default="{ row }"><StateTag :state="row.status" /></template>
            </el-table-column>
            <el-table-column prop="error_code" label="错误" min-width="130" />
          </el-table>
          <el-empty v-if="!usageLoading && !usage.length" description="暂无模型调用记录。" />
          <div class="pager">
            <el-pagination
              v-model:current-page="usagePage"
              v-model:page-size="usagePageSize"
              :total="usageTotal"
              :page-sizes="[20, 50, 100]"
              layout="total, sizes, prev, pager, next"
              @current-change="loadUsage()"
              @size-change="loadUsage(1)"
            />
          </div>
        </div>
      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'

import { api, errorMessage } from '@/api/client'
import type { Account, Group, MessageRecord, OutboxRecord, UsageRecord, UsageSummary } from '@/api/types'
import PageHeader from '@/components/PageHeader.vue'
import StateTag from '@/components/StateTag.vue'
import { costStatusLabel, costStatusTag, formatCost, formatNumber, formatTime, truncate } from '@/utils/format'
import { ElMessage } from 'element-plus'

const activeTab = ref('messages')
const loading = ref(false)
const error = ref<string | null>(null)

const accounts = ref<Account[]>([])
const groups = ref<Group[]>([])

const messageStatuses = [
  { value: 'received', label: '已接收' },
  { value: 'observed', label: '仅观察' },
  { value: 'generating', label: '生成中' },
  { value: 'replied', label: '已回复' },
  { value: 'queued', label: '已入队' },
  { value: 'sent', label: '发送记录' },
  { value: 'send_unknown', label: '发送状态未知' },
  { value: 'send_failed', label: '发送失败' },
  { value: 'intercepted', label: '已拦截' },
  { value: 'failed', label: '处理失败' },
]

const outboxStatuses = [
  { value: 'pending', label: '待发送' },
  { value: 'sending', label: '发送中' },
  { value: 'sent', label: '已发送' },
  { value: 'failed', label: '失败（可重试）' },
  { value: 'unknown', label: '状态未知' },
]

const filters = reactive({
  search: '',
  account_id: '',
  group_id: '',
  direction: '',
  status: '',
})
const dateRange = ref<[Date, Date] | null>(null)

const messages = ref<MessageRecord[]>([])
const page = ref(1)
const pageSize = ref(50)
const total = ref(0)

const outbox = ref<OutboxRecord[]>([])
const outboxStatus = ref('')
const outboxPage = ref(1)
const outboxPageSize = ref(50)
const outboxTotal = ref(0)
const outboxLoading = ref(false)
const dispatching = ref(false)

const usage = ref<UsageRecord[]>([])
const usageSummary = ref<UsageSummary | null>(null)
const usageFilters = reactive({ purpose: '', status: '' })
const usagePage = ref(1)
const usagePageSize = ref(50)
const usageTotal = ref(0)
const usageLoading = ref(false)

async function loadReferences(): Promise<void> {
  try {
    const [accountData, groupData] = await Promise.all([
      api<{ items: Account[] }>('/accounts'),
      api<{ items: Group[] }>('/groups'),
    ])
    accounts.value = accountData.items
    groups.value = groupData.items
  } catch (err) {
    error.value = errorMessage(err)
  }
}

async function loadMessages(targetPage?: number): Promise<void> {
  if (targetPage) page.value = targetPage
  loading.value = true
  error.value = null
  try {
    const query: Record<string, string | number> = {
      page: page.value,
      page_size: pageSize.value,
    }
    if (filters.search.trim()) query.search = filters.search.trim()
    if (filters.account_id) query.account_id = filters.account_id
    if (filters.group_id) query.group_id = filters.group_id
    if (filters.direction) query.direction = filters.direction
    if (filters.status) query.status = filters.status
    if (dateRange.value) {
      query.since = dateRange.value[0].toISOString()
      query.until = dateRange.value[1].toISOString()
    }
    const data = await api<{ items: MessageRecord[]; total: number }>('/messages', { query })
    messages.value = data.items
    total.value = data.total
  } catch (err) {
    error.value = errorMessage(err)
  } finally {
    loading.value = false
  }
}

function resetFilters(): void {
  filters.search = ''
  filters.account_id = ''
  filters.group_id = ''
  filters.direction = ''
  filters.status = ''
  dateRange.value = null
  loadMessages(1)
}

async function loadOutbox(targetPage?: number): Promise<void> {
  if (targetPage) outboxPage.value = targetPage
  outboxLoading.value = true
  try {
    const query: Record<string, string | number> = {
      page: outboxPage.value,
      page_size: outboxPageSize.value,
    }
    if (outboxStatus.value) query.status = outboxStatus.value
    const data = await api<{ items: OutboxRecord[]; total: number }>('/outbox', { query })
    outbox.value = data.items
    outboxTotal.value = data.total
  } catch (err) {
    ElMessage.error(errorMessage(err))
  } finally {
    outboxLoading.value = false
  }
}

async function loadUsage(targetPage?: number): Promise<void> {
  if (targetPage) usagePage.value = targetPage
  usageLoading.value = true
  try {
    const query: Record<string, string | number> = {
      page: usagePage.value,
      page_size: usagePageSize.value,
    }
    if (usageFilters.purpose) query.purpose = usageFilters.purpose
    if (usageFilters.status) query.status = usageFilters.status
    const [usageData, summary] = await Promise.all([
      api<{ items: UsageRecord[]; total: number }>('/usage', { query }),
      api<UsageSummary>('/usage/summary', { query: { hours: 24 } }),
    ])
    usage.value = usageData.items
    usageTotal.value = usageData.total
    usageSummary.value = summary
  } catch (err) {
    ElMessage.error(errorMessage(err))
  } finally {
    usageLoading.value = false
  }
}

async function dispatchDue(): Promise<void> {
  dispatching.value = true
  try {
    const data = await api<{ processed: number }>('/outbox/dispatch-due', { method: 'POST' })
    ElMessage.success(`已处理 ${data.processed} 条到期消息。`)
    await loadOutbox()
  } catch (err) {
    ElMessage.error(errorMessage(err))
  } finally {
    dispatching.value = false
  }
}

function onTabChange(name: string | number): void {
  if (name === 'messages') void loadMessages()
  if (name === 'outbox') void loadOutbox()
  if (name === 'usage') void loadUsage()
}

function reloadCurrent(): void {
  if (activeTab.value === 'messages') void loadMessages()
  else if (activeTab.value === 'outbox') void loadOutbox()
  else void loadUsage()
  void loadReferences()
}

onMounted(async () => {
  await loadReferences()
  await loadMessages(1)
})
</script>

<style scoped>
.filter-bar {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  margin-bottom: 12px;
  align-items: center;
}

.message-text {
  white-space: pre-wrap;
  word-break: break-word;
}

.detail-panel {
  padding: 8px 16px 12px 48px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.detail-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
  gap: 6px 18px;
  font-size: 12px;
}

.detail-pre {
  background: var(--app-surface-soft);
  border-radius: 6px;
  padding: 10px;
  font-size: 12px;
  max-height: 260px;
  overflow: auto;
  margin: 0;
  white-space: pre-wrap;
  word-break: break-word;
}

.pager {
  display: flex;
  justify-content: flex-end;
  margin-top: 12px;
}
</style>

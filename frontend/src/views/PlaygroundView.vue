<template>
  <div class="page">
    <PageHeader
      title="模拟测试"
      description="用 Mock 事件验证触发策略、人格提示词与回复生成。dry-run 不会发送、不会写入消息日志；注入 Mock 事件会走完整流水线并发送到 Mock 连接器，但永远不会发往真实 QQ。"
    >
      <template #actions>
        <el-button :loading="optionsLoading" @click="loadOptions">刷新选项</el-button>
      </template>
    </PageHeader>

    <el-alert
      type="warning"
      show-icon
      :closable="false"
      title="图片/语音只作为能力降级演示"
      description="当前版本没有真实视觉或语音识别 Provider。附加图片/语音段时，模型只会收到「未配置识别能力」的提示，不会真的看到或听到内容。"
    />
    <el-alert v-if="error" type="error" :title="error" show-icon :closable="false" />

    <div class="grid grid-2 playground-grid">
      <div class="card">
        <div class="card-title">构造模拟消息</div>
        <el-form label-width="110px">
          <el-form-item label="账号" required>
            <el-select v-model="form.account_id" style="width: 100%" placeholder="选择 Mock 或已登记账号" @change="onAccountChange">
              <el-option v-for="account in options.accounts" :key="account.id" :label="account.name" :value="account.id">
                <span>{{ account.name }}</span>
                <el-tag v-if="account.has_mock" size="small" type="warning" style="float: right; margin-top: 6px">Mock</el-tag>
              </el-option>
            </el-select>
          </el-form-item>
          <el-form-item label="群" required>
            <el-select v-model="form.group_id" style="width: 100%" placeholder="选择已登记的群">
              <el-option v-for="group in accountGroups" :key="group.id" :label="group.name || group.platform_group_id" :value="group.id">
                <span>{{ group.name || group.platform_group_id }}</span>
                <el-tag v-if="!group.enabled" size="small" type="info" style="float: right; margin-top: 6px">未启用</el-tag>
              </el-option>
            </el-select>
            <div v-if="selectedGroup && !selectedGroup.enabled" class="form-tip">
              该群当前未启用 AI 回复，模拟结果可能因策略被拦截；这是预期行为。
            </div>
          </el-form-item>
          <el-form-item label="人格覆盖">
            <el-select v-model="form.persona_id" style="width: 100%" clearable placeholder="使用群绑定或默认人格">
              <el-option v-for="persona in options.personas" :key="persona.id" :label="`${persona.name}（${persona.mode}）`" :value="persona.id" />
            </el-select>
          </el-form-item>
          <el-form-item label="发送者">
            <div class="sender-row">
              <el-input v-model="form.sender_name" maxlength="64" placeholder="模拟群友" />
              <el-input v-model="form.sender_id" maxlength="128" placeholder="20001" />
            </div>
          </el-form-item>
          <el-form-item label="消息内容">
            <el-input v-model="form.text" type="textarea" :rows="4" maxlength="4000" show-word-limit placeholder="例如：今天天气不错，大家有什么安排？" />
          </el-form-item>
          <el-form-item label="触发方式">
            <div class="trigger-options">
              <el-checkbox v-model="form.mention">@ 机器人（需要账号已确定自身 QQ 号）</el-checkbox>
              <el-checkbox v-model="form.attach_image">附加图片段（仅降级提示）</el-checkbox>
              <el-checkbox v-model="form.attach_audio">附加语音段（仅降级提示）</el-checkbox>
            </div>
          </el-form-item>
          <el-form-item label="引用消息 ID">
            <el-input v-model="form.reply_to" maxlength="128" placeholder="可选，模拟回复引用" />
          </el-form-item>
        </el-form>

        <div class="action-row">
          <el-button type="primary" :loading="running" @click="runDry">dry-run 模拟（不发送）</el-button>
          <el-tooltip :disabled="canInject" content="需要账号启用中的 Mock 连接器在线">
            <span>
              <el-button type="warning" plain :disabled="!canInject" :loading="injecting" @click="injectMock">注入 Mock 事件并发送</el-button>
            </span>
          </el-tooltip>
          <el-button @click="resetForm">清空</el-button>
        </div>
        <p class="muted">
          「注入 Mock 事件」会持久化消息、生成回复并写入发送队列，随后由 Mock 连接器接收；可在「QQ 接入 → Mock 已发送」查看。
        </p>
      </div>

      <div class="card result-card">
        <div class="card-title">
          <span>运行结果</span>
          <StateTag v-if="lastRunKind" :state="lastRunKind === 'dry' ? 'mock_only' : 'available'" :label="lastRunKind === 'dry' ? 'dry-run' : 'Mock 注入'" />
        </div>
        <el-empty v-if="!result" description="运行一次模拟后在这里查看策略判定与回复。" :image-size="70" />
        <template v-else>
          <el-descriptions :column="1" border size="small">
            <el-descriptions-item label="动作">
              <StateTag :state="String(result.action)" />
              <span class="mono" style="margin-left: 8px">{{ result.action }}</span>
            </el-descriptions-item>
            <el-descriptions-item label="原因">
              {{ result.reason }}<span v-if="result.detail" class="muted"> · {{ result.detail }}</span>
            </el-descriptions-item>
            <el-descriptions-item label="是否发送">
              <el-tag size="small" :type="sent ? 'warning' : 'info'">{{ sent ? '已发送到 Mock' : '未发送' }}</el-tag>
            </el-descriptions-item>
            <el-descriptions-item v-if="result.provider_id" label="模型">
              {{ result.model }}
              <el-tag v-if="result.is_mock" size="small" type="warning">Mock 模型</el-tag>
              <span class="muted"> · {{ result.latency_ms ?? '—' }} ms</span>
            </el-descriptions-item>
            <el-descriptions-item v-if="result.input_tokens !== null" label="Token">
              {{ result.input_tokens ?? 0 }} 输入 / {{ result.output_tokens ?? 0 }} 输出
            </el-descriptions-item>
            <el-descriptions-item v-if="result.message_id" label="消息 ID">
              <span class="mono">{{ result.message_id }}</span>
            </el-descriptions-item>
            <el-descriptions-item v-if="result.outbox_id" label="队列 ID">
              <span class="mono">{{ result.outbox_id }}</span>
            </el-descriptions-item>
            <el-descriptions-item v-if="result.error_code" label="错误">
              <span class="mono">{{ result.error_code }}</span>
            </el-descriptions-item>
          </el-descriptions>

          <div v-if="result.reply" class="reply-preview">
            <div class="muted">回复内容</div>
            <div class="reply-text">{{ result.reply }}</div>
            <el-tag v-if="result.is_mock" size="small" type="warning">Mock 模型生成，不代表真实模型水平</el-tag>
          </div>
          <div v-else class="muted no-reply">本次未生成回复。</div>

          <el-collapse v-if="result.prompt_preview" class="prompt-collapse">
            <el-collapse-item title="脱敏后的提示词预览" name="prompt">
              <pre class="prompt-pre">{{ result.prompt_preview }}</pre>
            </el-collapse-item>
          </el-collapse>
        </template>
      </div>
    </div>

    <div class="card">
      <div class="card-title">选项说明</div>
      <p class="muted">{{ options.note || '模拟运行不会发送到 QQ，也不会写入消息日志。模拟事件注入仅对 Mock 连接器可用。' }}</p>
      <el-alert
        type="info"
        :closable="false"
        show-icon
        title="为什么有时没有回复？"
        description="常见原因：群未启用、白名单/自身消息过滤、非 @ 触发、安静时段、冷却/小时上限、全局暂停、预算耗尽、模型未配置。运行结果会给出具体 reason。"
      />
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'

import { api, errorMessage } from '@/api/client'
import type { Account } from '@/api/types'
import PageHeader from '@/components/PageHeader.vue'
import StateTag from '@/components/StateTag.vue'
import { ElMessage, ElMessageBox } from 'element-plus'

interface PlaygroundOptions {
  accounts: Array<{ id: string; name: string; has_mock: boolean }>
  groups: Array<{
    id: string
    name: string | null
    platform_group_id: string
    account_id: string
    enabled: boolean
    paused: boolean
    persona_id: string | null
  }>
  personas: Array<{ id: string; name: string; mode: string }>
  note: string
}

interface PipelineResultView {
  accepted?: boolean
  action: string
  reason: string
  detail?: string | null
  reply?: string | null
  outbox_id?: string | null
  message_id?: string | null
  provider_id?: string | null
  model?: string | null
  is_mock?: boolean
  latency_ms?: number | null
  input_tokens?: number | null
  output_tokens?: number | null
  error_code?: string | null
  prompt_preview?: string | null
}

interface DryRunResponse {
  dry_run: boolean
  sent: boolean
  persisted: boolean
  note: string
  result: PipelineResultView
}

interface InjectResponse {
  dry_run: boolean
  sent: boolean
  persisted: boolean
  mock: boolean
  sent_text: string | null
  result: unknown
}

const options = ref<PlaygroundOptions>({ accounts: [], groups: [], personas: [], note: '' })
const fullAccounts = ref<Account[]>([])
const optionsLoading = ref(false)
const running = ref(false)
const injecting = ref(false)
const error = ref<string | null>(null)

const form = reactive({
  account_id: '',
  group_id: '',
  persona_id: '',
  sender_name: '模拟群友',
  sender_id: '20001',
  text: '',
  mention: true,
  attach_image: false,
  attach_audio: false,
  reply_to: '',
})

const result = ref<PipelineResultView | null>(null)
const lastRunKind = ref<'dry' | 'inject' | null>(null)
const sent = ref(false)

const accountGroups = computed(() => options.value.groups.filter((group) => group.account_id === form.account_id))
const selectedGroup = computed(() => accountGroups.value.find((group) => group.id === form.group_id) ?? null)
const selfId = computed(() => fullAccounts.value.find((item) => item.id === form.account_id)?.self_platform_user_id ?? null)
const canInject = computed(() => {
  const account = options.value.accounts.find((item) => item.id === form.account_id)
  return Boolean(account?.has_mock && form.group_id)
})

function onAccountChange(): void {
  if (!accountGroups.value.some((group) => group.id === form.group_id)) {
    form.group_id = ''
    form.persona_id = selectedGroup.value?.persona_id ?? ''
  }
}

async function loadOptions(): Promise<void> {
  optionsLoading.value = true
  error.value = null
  try {
    const [optionData, accountData] = await Promise.all([
      api<PlaygroundOptions>('/playground/options'),
      api<{ items: Account[] }>('/accounts'),
    ])
    options.value = optionData
    fullAccounts.value = accountData.items
    if (!form.account_id && optionData.accounts.length) {
      form.account_id = optionData.accounts[0].id
    }
    if (!form.group_id) {
      const firstGroup = accountGroups.value[0]
      if (firstGroup) form.group_id = firstGroup.id
    }
  } catch (err) {
    error.value = errorMessage(err)
  } finally {
    optionsLoading.value = false
  }
}

function buildSegments(): Array<Record<string, unknown>> {
  const segments: Array<Record<string, unknown>> = []
  if (form.text.trim()) segments.push({ type: 'text', text: form.text })
  if (form.mention && selfId.value) {
    segments.push({ type: 'mention', text: selfId.value, metadata: { qq: selfId.value } })
  }
  if (form.reply_to.trim()) {
    segments.push({ type: 'reply', text: form.reply_to.trim(), metadata: { id: form.reply_to.trim() } })
  }
  if (form.attach_image) {
    segments.push({ type: 'image', media_ref: 'playground-demo-image', metadata: { note: '模拟图片，未下载' } })
  }
  if (form.attach_audio) {
    segments.push({ type: 'audio', media_ref: 'playground-demo-audio', metadata: { note: '模拟语音，未转写' } })
  }
  return segments
}

function validate(): boolean {
  if (!form.account_id) {
    ElMessage.warning('请选择账号。')
    return false
  }
  if (!form.group_id) {
    ElMessage.warning('请选择群。')
    return false
  }
  if (!form.text.trim() && !form.attach_image && !form.attach_audio) {
    ElMessage.warning('请输入消息内容，或附加一个媒体段用于能力降级演示。')
    return false
  }
  return true
}

function mentionsPayload(): string[] {
  return form.mention && selfId.value ? [selfId.value] : []
}

async function runDry(): Promise<void> {
  if (!validate()) return
  running.value = true
  result.value = null
  try {
    const data = await api<DryRunResponse>('/playground/run', {
      method: 'POST',
      body: {
        account_id: form.account_id,
        group_id: form.group_id,
        persona_id: form.persona_id || null,
        text: form.text,
        segments: buildSegments(),
        mentions: mentionsPayload(),
        sender_id: form.sender_id,
        sender_name: form.sender_name,
        reply_to_message_id: form.reply_to || null,
      },
    })
    result.value = data.result
    lastRunKind.value = 'dry'
    sent.value = false
  } catch (err) {
    ElMessage.error(errorMessage(err))
  } finally {
    running.value = false
  }
}

async function injectMock(): Promise<void> {
  if (!validate()) return
  if (canInject.value !== true) {
    ElMessage.warning('该账号没有在线 Mock 连接器，无法注入模拟事件。')
    return
  }
  try {
    await ElMessageBox.confirm(
      '将通过 Mock 连接器走完整流水线：消息会写入本地日志，若触发回复会进入发送队列并由 Mock 连接器接收。不会发往真实 QQ。继续？',
      '注入 Mock 事件',
      { type: 'warning', confirmButtonText: '注入', cancelButtonText: '取消' },
    )
  } catch {
    return
  }
  injecting.value = true
  try {
    const data = await api<InjectResponse>(`/accounts/${form.account_id}/mock/events`, {
      method: 'POST',
      body: {
        group_internal_id: form.group_id,
        text: form.text,
        segments: buildSegments(),
        mentions: mentionsPayload(),
        sender_id: form.sender_id,
        sender_name: form.sender_name,
        reply_to_message_id: form.reply_to || null,
      },
    })
    const raw = data.result as Record<string, unknown> | null
    result.value = raw ? (raw as unknown as PipelineResultView) : null
    lastRunKind.value = 'inject'
    sent.value = Boolean(data.sent)
    ElMessage.success(data.sent ? 'Mock 事件已处理并发送回复。' : 'Mock 事件已处理，流水线未生成发送。')
  } catch (err) {
    ElMessage.error(errorMessage(err))
  } finally {
    injecting.value = false
  }
}

function resetForm(): void {
  form.text = ''
  form.reply_to = ''
  form.attach_image = false
  form.attach_audio = false
  form.mention = true
  result.value = null
  lastRunKind.value = null
  sent.value = false
}

onMounted(loadOptions)
</script>

<style scoped>
.playground-grid {
  align-items: start;
}

.sender-row {
  display: grid;
  grid-template-columns: 1fr 160px;
  gap: 8px;
  width: 100%;
}

.trigger-options {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.action-row {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  margin-top: 6px;
}

.result-card {
  min-height: 420px;
}

.reply-preview {
  margin-top: 12px;
  background: #f6f9f7;
  border-radius: 8px;
  padding: 12px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.reply-text {
  white-space: pre-wrap;
  word-break: break-word;
}

.no-reply {
  margin-top: 12px;
}

.prompt-collapse {
  margin-top: 12px;
}

.prompt-pre {
  background: #f7f8fb;
  border-radius: 6px;
  padding: 10px;
  font-size: 12px;
  white-space: pre-wrap;
  word-break: break-word;
  max-height: 320px;
  overflow: auto;
}
</style>

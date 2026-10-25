<template>
  <div class="page">
    <PageHeader
      title="模型 API"
      description="配置 OpenAI 兼容的 Chat Completions 接口、Anthropic 原生 Messages API 或使用 Mock 模型。API Key 加密保存在本地，界面与接口只返回掩码，不会写入前端存储或日志。"
    >
      <template #actions>
        <el-button :loading="loading" @click="load">刷新</el-button>
        <el-button type="primary" @click="openCreate">新增 Provider</el-button>
      </template>
    </PageHeader>

    <el-alert
      type="info"
      show-icon
      :closable="false"
      title="凭据说明"
      description="软件仅保存你填写的 API Key（Fernet 加密）。请求由本地后端直接发往你配置的 Base URL；请确认该服务可信。"
    />

    <el-alert v-if="error" type="error" :title="error" show-icon :closable="false" />

    <div class="card">
      <el-table v-loading="loading" :data="providers">
        <el-table-column label="名称" min-width="160">
          <template #default="{ row }">
            <div class="provider-name">
              <span>{{ row.name }}</span>
              <el-tag v-if="row.is_default" size="small" type="success">默认</el-tag>
              <el-tag v-if="row.is_mock" size="small" type="warning">Mock</el-tag>
            </div>
            <div class="muted mono">{{ row.model }}</div>
          </template>
        </el-table-column>
        <el-table-column label="类型" width="160">
          <template #default="{ row }">{{ typeLabel(row.provider_type) }}</template>
        </el-table-column>
        <el-table-column label="Base URL" min-width="190">
          <template #default="{ row }">
            <span class="mono">
              {{ row.base_url || (row.provider_type === 'anthropic_native' ? 'Anthropic 官方默认' : '—（本地 Mock）') }}
            </span>
          </template>
        </el-table-column>
        <el-table-column label="API Key" width="130">
          <template #default="{ row }">
            <span class="mono">{{ row.api_key_configured ? row.api_key_masked : '未配置' }}</span>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="120">
          <template #default="{ row }">
            <StateTag :state="row.status" />
            <div v-if="row.last_error" class="muted error-text">{{ row.last_error }}</div>
          </template>
        </el-table-column>
        <el-table-column label="参数" width="150">
          <template #default="{ row }">
            <span class="muted">timeout {{ row.timeout_seconds }}s · max {{ row.max_output_tokens }}</span>
            <div class="muted">temperature {{ row.temperature }}</div>
          </template>
        </el-table-column>
        <el-table-column label="费用估算" width="120">
          <template #default="{ row }">
            <el-tag size="small" :type="costTrackingTag(row.cost_tracking)">{{ costTrackingLabel(row.cost_tracking) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="启用" width="75">
          <template #default="{ row }">
            <el-switch :model-value="row.enabled" @change="(value: string | number | boolean) => toggleEnabled(row, Boolean(value))" />
          </template>
        </el-table-column>
        <el-table-column label="操作" width="280" fixed="right">
          <template #default="{ row }">
            <div class="row-actions">
              <el-button size="small" :loading="testingId === row.id" @click="testProvider(row)">测试</el-button>
              <el-button size="small" :disabled="row.is_default" @click="makeDefault(row)">设为默认</el-button>
              <el-button size="small" @click="openEdit(row)">编辑</el-button>
              <el-button size="small" type="danger" text @click="deleteProvider(row)">删除</el-button>
            </div>
          </template>
        </el-table-column>
      </el-table>
      <el-empty v-if="!loading && !providers.length" description="还没有模型 Provider。可先初始化 Mock 演示环境，或新增 OpenAI 兼容接口。" />
    </div>

    <div class="card">
      <div class="card-title">
        <span>已支持的接入类型</span>
        <span class="muted">隐藏未知能力，不做虚假承诺</span>
      </div>
      <el-table :data="types" size="small">
        <el-table-column prop="label" label="类型" width="190" />
        <el-table-column label="状态" width="120">
          <template #default="{ row }">
            <StateTag :state="row.available ? 'available' : (row.state ?? 'planned')" :label="row.available ? '可用' : '规划中'" />
          </template>
        </el-table-column>
        <el-table-column prop="note" label="说明" />
      </el-table>
    </div>

    <el-dialog v-model="dialog" :title="editing ? '编辑 Provider' : '新增 Provider'" width="580px" :close-on-click-modal="false">
      <el-form label-width="140px">
        <el-form-item label="类型" required>
          <el-select v-model="form.provider_type" style="width: 100%" @change="onTypeChange">
            <el-option label="Mock 模型（演示）" value="mock" />
            <el-option label="OpenAI 兼容接口" value="openai_compatible" />
            <el-option label="Anthropic 原生接口" value="anthropic_native" />
          </el-select>
        </el-form-item>
        <el-form-item label="名称" required>
          <el-input v-model="form.name" maxlength="128" placeholder="例如：本地 Ollama / 官方 API" />
        </el-form-item>
        <template v-if="isRemoteType">
          <el-form-item label="Base URL" :required="form.provider_type === 'openai_compatible'">
            <el-input
              v-model="form.base_url"
              :placeholder="form.provider_type === 'anthropic_native' ? '留空使用 https://api.anthropic.com/v1' : 'https://api.example.com/v1'"
            />
            <div class="form-tip">
              <template v-if="form.provider_type === 'anthropic_native'">
                Anthropic Messages API 地址；留空使用官方默认，可填写自建代理。不能访问的地址会由连接测试报错。
              </template>
              <template v-else>填写兼容 OpenAI Chat Completions 的服务根地址，通常以 /v1 结尾。</template>
            </div>
          </el-form-item>
          <el-form-item label="模型 ID" required>
            <el-input
              v-model="form.model"
              :placeholder="form.provider_type === 'anthropic_native' ? '例如：claude-sonnet-5' : '例如：gpt-4o-mini、qwen2.5-7b-instruct'"
            />
          </el-form-item>
          <el-form-item label="API Key" :required="!editing">
            <el-input v-model="form.api_key" type="password" show-password :placeholder="editing ? '留空表示不修改现有 Key' : '粘贴 API Key'" />
            <div class="form-tip">
              <template v-if="form.provider_type === 'anthropic_native'">
                仅加密存储在本地数据库；不会显示明文。请使用你有权使用的 Anthropic API Key。
              </template>
              <template v-else>仅加密存储在本地数据库；不会显示明文。</template>
            </div>
          </el-form-item>
        </template>
        <el-form-item label="超时（秒）">
          <el-input-number v-model="form.timeout_seconds" :min="1" :max="300" />
        </el-form-item>
        <el-form-item label="最大输出 Token">
          <el-input-number v-model="form.max_output_tokens" :min="1" :max="32000" />
        </el-form-item>
        <el-form-item label="Temperature">
          <el-input-number
            v-model="form.temperature"
            :min="0"
            :max="form.provider_type === 'anthropic_native' ? 1 : 2"
            :step="0.1"
          />
          <div v-if="form.provider_type === 'anthropic_native'" class="form-tip">Anthropic Messages API 的范围为 0–1。</div>
        </el-form-item>
        <el-form-item label="设为默认">
          <el-switch v-model="form.is_default" />
        </el-form-item>
        <el-form-item label="启用">
          <el-switch v-model="form.enabled" />
        </el-form-item>
        <el-divider content-position="left">计费估算（可选）</el-divider>
        <el-form-item label="输入价 / 1K">
          <el-input-number v-model="form.input_price_per_1k" :min="0" :step="0.001" :precision="6" />
        </el-form-item>
        <el-form-item label="输出价 / 1K">
          <el-input-number v-model="form.output_price_per_1k" :min="0" :step="0.001" :precision="6" />
        </el-form-item>
        <div class="form-tip" style="margin-left: 140px">价格仅用于本地用量估算，单位由你自行保持一致。</div>
      </el-form>
      <template #footer>
        <el-button @click="dialog = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="save">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'

import { api, errorMessage } from '@/api/client'
import type { LLMProvider } from '@/api/types'
import PageHeader from '@/components/PageHeader.vue'
import StateTag from '@/components/StateTag.vue'
import { ElMessage, ElMessageBox } from 'element-plus'

interface ProviderTypeOption {
  value: string
  label: string
  available: boolean
  state?: string
  note: string
}

const providers = ref<LLMProvider[]>([])
const types = ref<ProviderTypeOption[]>([])
const loading = ref(false)
const saving = ref(false)
const testingId = ref<string | null>(null)
const error = ref<string | null>(null)

const dialog = ref(false)
const editing = ref<LLMProvider | null>(null)

function emptyForm() {
  return {
    provider_type: 'openai_compatible',
    name: '',
    base_url: '',
    model: '',
    api_key: '',
    timeout_seconds: 45,
    max_output_tokens: 800,
    temperature: 0.7,
    is_default: false,
    enabled: true,
    input_price_per_1k: 0,
    output_price_per_1k: 0,
  }
}

const form = reactive(emptyForm())
const isRemoteType = computed(
  () => form.provider_type === 'openai_compatible' || form.provider_type === 'anthropic_native',
)

function typeLabel(value: string): string {
  return types.value.find((item) => item.value === value)?.label ?? value
}

function costTrackingLabel(value?: string): string {
  return { configured: '单价已配置', mock_zero: 'Mock 零费用', unconfigured: '单价未配置' }[value ?? ''] ?? '未知'
}

function costTrackingTag(value?: string): 'success' | 'warning' | 'info' {
  if (value === 'configured') return 'success'
  if (value === 'mock_zero') return 'info'
  return 'warning'
}

async function load(): Promise<void> {
  loading.value = true
  error.value = null
  try {
    const data = await api<{ items: LLMProvider[]; types: ProviderTypeOption[] }>('/providers')
    providers.value = data.items
    types.value = data.types
  } catch (err) {
    error.value = errorMessage(err)
  } finally {
    loading.value = false
  }
}

function onTypeChange(): void {
  if (form.provider_type === 'mock' && !form.name.trim()) {
    form.name = 'Mock 模型'
  }
  if (form.provider_type === 'anthropic_native') {
    form.temperature = Math.min(form.temperature, 1)
    if (!form.base_url.trim()) form.base_url = 'https://api.anthropic.com/v1'
    if (!form.model.trim()) form.model = 'claude-sonnet-5'
    if (!form.name.trim()) form.name = 'Anthropic Claude'
  }
  if (form.provider_type === 'openai_compatible') {
    if (form.base_url.includes('api.anthropic.com')) form.base_url = ''
    if (form.model.trim().toLowerCase().startsWith('claude')) form.model = ''
  }
}

function openCreate(): void {
  editing.value = null
  Object.assign(form, emptyForm())
  dialog.value = true
}

function openEdit(provider: LLMProvider): void {
  editing.value = provider
  Object.assign(form, {
    provider_type: provider.provider_type,
    name: provider.name,
    base_url: provider.base_url ?? '',
    model: provider.model,
    api_key: '',
    timeout_seconds: provider.timeout_seconds,
    max_output_tokens: provider.max_output_tokens,
    temperature: provider.temperature,
    is_default: provider.is_default,
    enabled: provider.enabled,
    input_price_per_1k: Number((provider as unknown as { config?: Record<string, number> }).config?.input_price_per_1k ?? 0),
    output_price_per_1k: Number((provider as unknown as { config?: Record<string, number> }).config?.output_price_per_1k ?? 0),
  })
  dialog.value = true
}

function validationError(): string | null {
  if (!form.name.trim()) return '请填写 Provider 名称。'
  if (isRemoteType.value) {
    if (form.provider_type === 'openai_compatible' && !form.base_url.trim()) return '请填写 Base URL。'
    if (form.base_url.trim() && !/^https?:\/\//.test(form.base_url.trim())) {
      return 'Base URL 必须以 http:// 或 https:// 开头。'
    }
    if (!form.model.trim()) return '请填写模型 ID。'
    if (!editing.value && !form.api_key.trim()) {
      return form.provider_type === 'anthropic_native'
        ? '请填写 Anthropic API Key。'
        : '请填写 API Key；本地服务可填写任意非空占位符。'
    }
  }
  return null
}

async function save(): Promise<void> {
  const problem = validationError()
  if (problem) {
    ElMessage.warning(problem)
    return
  }
  const body: Record<string, unknown> = {
    provider_type: form.provider_type,
    name: form.name.trim(),
    base_url: isRemoteType.value ? form.base_url.trim() || null : null,
    model: form.provider_type === 'mock' ? (form.model.trim() || 'mock-model') : form.model.trim(),
    timeout_seconds: form.timeout_seconds,
    max_output_tokens: form.max_output_tokens,
    temperature: form.temperature,
    is_default: form.is_default,
    enabled: form.enabled,
    config: {
      input_price_per_1k: form.input_price_per_1k,
      output_price_per_1k: form.output_price_per_1k,
    },
  }
  if (form.api_key.trim()) body.api_key = form.api_key.trim()
  saving.value = true
  try {
    if (editing.value) {
      await api(`/providers/${editing.value.id}`, { method: 'PATCH', body })
      ElMessage.success('Provider 已更新。')
    } else {
      await api('/providers', { method: 'POST', body })
      ElMessage.success('Provider 已创建。')
    }
    dialog.value = false
    await load()
  } catch (err) {
    ElMessage.error(errorMessage(err))
  } finally {
    saving.value = false
  }
}

async function toggleEnabled(provider: LLMProvider, enabled: boolean): Promise<void> {
  try {
    await api(`/providers/${provider.id}`, { method: 'PATCH', body: { enabled } })
    ElMessage.success(enabled ? '已启用。' : '已停用。')
  } catch (err) {
    ElMessage.error(errorMessage(err))
  } finally {
    await load()
  }
}

async function makeDefault(provider: LLMProvider): Promise<void> {
  try {
    await api(`/providers/${provider.id}`, { method: 'PATCH', body: { is_default: true } })
    ElMessage.success(`已将「${provider.name}」设为默认模型。`)
    await load()
  } catch (err) {
    ElMessage.error(errorMessage(err))
  }
}

async function testProvider(provider: LLMProvider): Promise<void> {
  testingId.value = provider.id
  try {
    const result = await api<{
      ok: boolean
      message?: string | null
      error_code?: string | null
      details?: { elapsed_ms?: number | null; reply_preview?: string | null }
    }>(`/providers/${provider.id}/test`, { method: 'POST' })
    if (result.ok) {
      const details = result.details ?? {}
      ElMessage.success(
        `连接成功：${details.elapsed_ms ?? '—'} ms${details.reply_preview ? ` · ${details.reply_preview}` : ''}`,
      )
    } else {
      ElMessage.error(`连接失败（${result.error_code ?? 'UNKNOWN'}）：${result.message || '未知错误'}`)
    }
  } catch (err) {
    ElMessage.error(errorMessage(err))
  } finally {
    testingId.value = null
    await load()
  }
}

async function deleteProvider(provider: LLMProvider): Promise<void> {
  try {
    await ElMessageBox.confirm(
      `确定删除 Provider「${provider.name}」？删除后其 API Key 也会从本地数据库移除。`,
      '删除 Provider',
      { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' },
    )
  } catch {
    return
  }
  try {
    await api(`/providers/${provider.id}`, { method: 'DELETE' })
    ElMessage.success('Provider 已删除。')
    await load()
  } catch (err) {
    ElMessage.error(errorMessage(err))
  }
}

onMounted(load)
</script>

<style scoped>
.provider-name {
  display: flex;
  align-items: center;
  gap: 6px;
}

.error-text {
  font-size: 11px;
  margin-top: 2px;
  word-break: break-all;
}
</style>

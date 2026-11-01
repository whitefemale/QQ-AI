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
      title="凭据与测试说明"
      description="软件仅保存你填写的 API Key（Fernet 加密）。请求由本地后端直接发往你配置的 Base URL；请确认该服务可信。Mock 结果不能证明真实 API 可用；测试调用会写入本地用量与预算。"
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
            <div class="muted mono">{{ row.model || '—' }}</div>
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
        <el-table-column label="配置与测试证据" min-width="270">
          <template #default="{ row }">
            <ProviderReadinessTags :provider="row" />
            <div v-if="row.last_tested_at" class="muted error-text">最近测试：{{ formatTime(row.last_tested_at) }}</div>
            <div v-if="row.last_error" class="muted error-text">{{ row.last_error }}</div>
            <div v-if="row.last_test?.error_code" class="muted error-text">
              {{ providerActionHint(row.last_test.error_code, null) || row.last_test.error_code }}
            </div>
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
        <el-table-column label="操作" width="390" fixed="right">
          <template #default="{ row }">
            <div class="row-actions">
              <el-button
                size="small"
                :loading="activeTest?.kind === 'connectivity' && activeTest.providerId === row.id"
                :disabled="Boolean(activeTest) && activeTest?.kind !== 'connectivity'"
                @click="runConnectivity(row)"
              >
                连通性测试
              </el-button>
              <el-button
                size="small"
                :disabled="Boolean(activeTest) && (activeTest?.kind !== 'generation' || activeTest.providerId !== row.id)"
                @click="openGeneration(row)"
              >
                {{ row.is_mock ? '生成测试（Mock）' : '真实生成测试' }}
              </el-button>
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
            <div class="model-field">
              <el-select
                v-if="useModelSelect"
                v-model="form.model"
                filterable
                allow-create
                default-first-option
                style="width: 100%"
                placeholder="选择或输入模型 ID"
              >
                <el-option
                  v-for="model in modelList?.models ?? []"
                  :key="model.id"
                  :label="modelOptionLabel(model)"
                  :value="model.id"
                />
              </el-select>
              <el-input
                v-else
                v-model="form.model"
                :placeholder="form.provider_type === 'anthropic_native' ? '例如：claude-sonnet-5' : '例如：gpt-4o-mini、qwen2.5-7b-instruct'"
              />
              <el-button
                v-if="editing"
                size="small"
                :loading="modelsLoading"
                :disabled="form.provider_type === 'mock' || !editing.api_key_configured"
                @click="fetchModels"
              >
                获取模型列表
              </el-button>
            </div>
            <div v-if="editing && form.provider_type !== 'mock' && !editing.api_key_configured" class="form-tip">
              保存 API Key 后才能获取远端模型列表；也可以手动填写模型 ID。
            </div>
            <div v-else-if="!editing" class="form-tip">保存 Provider 后可获取远端模型列表；也可以手动填写。</div>
            <div v-if="modelList" class="form-tip">
              <el-tag :type="modelStateInfo.type" size="small">{{ modelStateInfo.label }}</el-tag>
              <span v-if="modelList.message"> {{ modelList.message }}</span>
              <span v-if="modelList.truncated">（列表已截断：最多显示 500 条）</span>
              <span v-if="modelList.current_model_listed === false">当前模型不在列表中，仍会按手动填写的 ID 调用。</span>
              <div v-if="modelList.note">{{ modelList.note }}</div>
            </div>
            <div v-if="modelsError" class="form-tip error-text">{{ modelsError }}</div>
          </el-form-item>
          <el-form-item label="API Key" :required="!editing">
            <el-input v-model="form.api_key" type="password" show-password :placeholder="editing ? '留空表示不修改现有 Key' : '粘贴 API Key'" />
            <div class="form-tip">
              <template v-if="form.provider_type === 'anthropic_native'">
                仅加密存储在本地数据库；不会显示明文。请使用你有权使用的 Anthropic API Key。
              </template>
              <template v-else>仅加密存储在本地数据库；不会显示明文。</template>
            </div>
            <div v-if="editing" class="form-tip key-status">
              <span v-if="editing.api_key_configured">已保存：<span class="mono">{{ editing.api_key_masked }}</span></span>
              <span v-else>尚未保存 Key</span>
              <el-button v-if="editing.api_key_configured" link type="danger" @click="clearKey">清除已保存 Key</el-button>
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

    <el-dialog
      v-model="testDialog"
      :title="testTitle"
      width="620px"
      :close-on-click-modal="false"
      :show-close="!activeTest"
    >
      <el-alert
        v-if="activeTest"
        type="info"
        show-icon
        :closable="false"
        title="正在等待模型响应"
        description="真实请求可能已开始计费。取消只停止本地等待，无法保证服务商停止生成或停止计费。"
      />
      <div v-if="testError" class="result-error">{{ testError }}</div>
      <ProviderTestResultView :result="testResult" />
      <template #footer>
        <el-button v-if="activeTest" type="danger" plain @click="cancelActiveTest">取消本地等待</el-button>
        <el-button v-else @click="testDialog = false">关闭</el-button>
      </template>
    </el-dialog>

    <el-dialog
      v-model="generationDialog"
      :title="generationProvider ? `真实生成测试 · ${generationProvider.name}` : '真实生成测试'"
      width="640px"
      :close-on-click-modal="false"
      :show-close="!generationLoading"
    >
      <el-alert
        type="warning"
        show-icon
        :closable="false"
        :title="generationProvider?.is_mock ? '这是 Mock 生成测试，不会访问任何模型服务' : '这会发起真实模型请求，可能产生费用'"
        :description="
          generationProvider?.is_mock
            ? 'Mock 结果只验证本地流程，不能证明真实 API 可用。'
            : '费用未知时显示“无法估算”，不会补成 0；测试调用会写入本地用量与预算。'
        "
      />
      <el-form label-width="120px" class="generation-form">
        <el-form-item label="提示词" required>
          <el-input
            v-model="generationForm.prompt"
            type="textarea"
            :rows="4"
            maxlength="2000"
            show-word-limit
            :disabled="generationLoading"
            placeholder="输入用于验证生成能力的提示词，不要粘贴密钥或隐私数据。"
          />
        </el-form-item>
        <el-form-item label="最大输出 Token">
          <el-input-number v-model="generationForm.max_output_tokens" :min="1" :max="128" :disabled="generationLoading" />
        </el-form-item>
        <el-form-item label="Temperature">
          <el-input-number v-model="generationForm.temperature" :min="0" :max="2" :step="0.1" :disabled="generationLoading" />
        </el-form-item>
      </el-form>
      <div v-if="generationError" class="result-error">{{ generationError }}</div>
      <ProviderTestResultView :result="generationResult" />
      <template #footer>
        <template v-if="generationLoading">
          <el-button type="danger" plain @click="cancelActiveTest">取消本地等待</el-button>
        </template>
        <template v-else>
          <el-button @click="generationDialog = false">关闭</el-button>
          <el-button type="primary" @click="runGeneration">开始测试</el-button>
        </template>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'

import { api, errorMessage } from '@/api/client'
import {
  cancelProviderOperation,
  clearProviderApiKey,
  listProviderModels,
  testProviderConnectivity,
  testProviderGeneration,
} from '@/api/providers'
import type { LLMProvider, ProviderModelList, ProviderTestResult } from '@/api/types'
import PageHeader from '@/components/PageHeader.vue'
import ProviderReadinessTags from '@/components/ProviderReadinessTags.vue'
import ProviderTestResultView from '@/components/ProviderTestResult.vue'
import StateTag from '@/components/StateTag.vue'
import { formatTime } from '@/utils/format'
import { makeOperationId, providerActionHint, providerModelListState } from '@/utils/providers'
import { ElMessage, ElMessageBox } from 'element-plus'

interface ProviderTypeOption {
  value: string
  label: string
  available: boolean
  state?: string
  note: string
}

interface ActiveTest {
  providerId: string
  operationId: string
  kind: 'connectivity' | 'generation'
  controller: AbortController
}

const providers = ref<LLMProvider[]>([])
const types = ref<ProviderTypeOption[]>([])
const loading = ref(false)
const saving = ref(false)
const error = ref<string | null>(null)

const dialog = ref(false)
const editing = ref<LLMProvider | null>(null)
const modelList = ref<ProviderModelList | null>(null)
const modelsLoading = ref(false)
const modelsError = ref<string | null>(null)

const activeTest = ref<ActiveTest | null>(null)
const testDialog = ref(false)
const testTitle = ref('')
const testResult = ref<ProviderTestResult | null>(null)
const testError = ref<string | null>(null)

const generationDialog = ref(false)
const generationProvider = ref<LLMProvider | null>(null)
const generationResult = ref<ProviderTestResult | null>(null)
const generationError = ref<string | null>(null)
const generationForm = reactive({
  prompt: '请用一句中文介绍你自己。',
  max_output_tokens: 32,
  temperature: 0.7,
})

const generationLoading = computed(
  () => activeTest.value?.kind === 'generation' && activeTest.value.providerId === generationProvider.value?.id,
)

const modelStateInfo = computed(() => providerModelListState(modelList.value?.state))
const useModelSelect = computed(
  () => modelList.value?.state === 'available' && Boolean(modelList.value.models.length),
)

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

function modelOptionLabel(model: { id: string; display_name: string | null }): string {
  return model.display_name && model.display_name !== model.id ? `${model.display_name}（${model.id}）` : model.id
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

function resetEvidenceState(): void {
  modelList.value = null
  modelsError.value = null
}

function onTypeChange(): void {
  resetEvidenceState()
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
  resetEvidenceState()
  dialog.value = true
}

function openEdit(provider: LLMProvider): void {
  editing.value = provider
  resetEvidenceState()
  Object.assign(form, {
    provider_type: provider.provider_type,
    name: provider.name,
    base_url: provider.base_url ?? '',
    model: provider.model ?? '',
    api_key: '',
    timeout_seconds: provider.timeout_seconds,
    max_output_tokens: provider.max_output_tokens,
    temperature: provider.temperature,
    is_default: provider.is_default,
    enabled: provider.enabled,
    input_price_per_1k: Number(provider.config?.input_price_per_1k ?? 0),
    output_price_per_1k: Number(provider.config?.output_price_per_1k ?? 0),
  })
  dialog.value = true
}

async function fetchModels(): Promise<void> {
  if (!editing.value) return
  modelsLoading.value = true
  modelsError.value = null
  try {
    const data = await listProviderModels(editing.value.id, {
      timeoutMs: (editing.value.timeout_seconds + 20) * 1000,
    })
    modelList.value = data
    if (data.current_model_listed === false && form.model.trim()) {
      ElMessage.info('当前模型 ID 不在服务商返回的列表中，可能是自定义名称、代理别名或未公开模型。')
    }
  } catch (err) {
    modelsError.value = errorMessage(err)
  } finally {
    modelsLoading.value = false
  }
}

async function clearKey(): Promise<void> {
  const provider = editing.value
  if (!provider) return
  try {
    await ElMessageBox.confirm(
      `确定清除「${provider.name}」已保存的 API Key？清除后配置变为不完整，此前的连通性与真实生成测试证据也会一并失效。`,
      '清除 API Key',
      { type: 'warning', confirmButtonText: '清除 Key', cancelButtonText: '取消' },
    )
  } catch {
    return
  }
  try {
    await clearProviderApiKey(provider.id)
    form.api_key = ''
    resetEvidenceState()
    ElMessage.success('已清除 API Key，测试证据已失效。请重新填写 Key 后才能真实调用。')
    await load()
    editing.value = providers.value.find((item) => item.id === provider.id) ?? null
  } catch (err) {
    ElMessage.error(errorMessage(err))
  }
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
      ElMessage.success('Provider 已更新；配置变更会清空旧测试证据。')
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

/** 真实远端测试会计费；必须在发起前明确提示，Mock 除外。 */
async function confirmRealCall(provider: LLMProvider, action: string): Promise<boolean> {
  if (provider.is_mock) return true
  try {
    await ElMessageBox.confirm(
      `即将向「${provider.name}」发起${action}。这是真实模型请求，可能产生费用；` +
        '若未填写单价或服务商未返回用量，费用会显示“无法估算”，不会记为 0。' +
        '测试调用会写入本地用量与预算。取消只停止本地等待，无法保证服务商停止生成或停止计费。',
      '真实模型调用提醒',
      { type: 'warning', confirmButtonText: '继续测试', cancelButtonText: '取消' },
    )
    return true
  } catch {
    return false
  }
}

function beginOperation(provider: LLMProvider, kind: ActiveTest['kind']): ActiveTest {
  const active: ActiveTest = {
    providerId: provider.id,
    operationId: makeOperationId(),
    kind,
    controller: new AbortController(),
  }
  activeTest.value = active
  return active
}

function testTimeoutMs(provider: LLMProvider): number {
  return (provider.timeout_seconds + 15) * 1000
}

function operationErrorMessage(err: unknown, active: ActiveTest): string {
  if (active.controller.signal.aborted) {
    return '已取消本地等待；无法保证服务商停止生成或停止计费。'
  }
  return errorMessage(err)
}

async function runConnectivity(provider: LLMProvider): Promise<void> {
  if (activeTest.value) {
    ElMessage.warning('已有测试正在进行，请等待完成或先取消。')
    return
  }
  if (!(await confirmRealCall(provider, '连通性测试（极短真实请求）'))) return
  const active = beginOperation(provider, 'connectivity')
  testTitle.value = `连通性测试 · ${provider.name}`
  testResult.value = null
  testError.value = null
  testDialog.value = true
  try {
    testResult.value = await testProviderConnectivity(
      provider.id,
      { operation_id: active.operationId },
      { signal: active.controller.signal, timeoutMs: testTimeoutMs(provider) },
    )
  } catch (err) {
    testError.value = operationErrorMessage(err, active)
  } finally {
    activeTest.value = null
    await load()
  }
}

function openGeneration(provider: LLMProvider): void {
  if (activeTest.value) {
    ElMessage.warning('已有测试正在进行，请等待完成或先取消。')
    return
  }
  generationProvider.value = provider
  generationResult.value = null
  generationError.value = null
  generationDialog.value = true
}

async function runGeneration(): Promise<void> {
  const provider = generationProvider.value
  if (!provider) return
  const prompt = generationForm.prompt.trim()
  if (!prompt) {
    ElMessage.warning('请输入测试提示词。')
    return
  }
  if (prompt.length > 2000) {
    ElMessage.warning('提示词不能超过 2000 个字符。')
    return
  }
  if (
    !Number.isInteger(generationForm.max_output_tokens) ||
    generationForm.max_output_tokens < 1 ||
    generationForm.max_output_tokens > 128
  ) {
    ElMessage.warning('最大输出 Token 必须在 1–128 之间。')
    return
  }
  if (!(await confirmRealCall(provider, '真实生成测试'))) return
  const active = beginOperation(provider, 'generation')
  generationResult.value = null
  generationError.value = null
  try {
    generationResult.value = await testProviderGeneration(
      provider.id,
      {
        operation_id: active.operationId,
        prompt,
        max_output_tokens: generationForm.max_output_tokens,
        temperature: generationForm.temperature,
      },
      { signal: active.controller.signal, timeoutMs: testTimeoutMs(provider) },
    )
  } catch (err) {
    generationError.value = operationErrorMessage(err, active)
  } finally {
    activeTest.value = null
    await load()
  }
}

async function cancelActiveTest(): Promise<void> {
  const active = activeTest.value
  if (!active) return
  try {
    await cancelProviderOperation(active.providerId, active.operationId)
  } catch {
    // 取消端点只是尽力而为；即使失败也停止本地等待。
  }
  active.controller.abort()
  ElMessage.info('已请求取消本地等待；无法保证服务商停止生成或停止计费。')
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

.model-field {
  display: flex;
  gap: 8px;
  width: 100%;
}

.key-status {
  display: flex;
  align-items: center;
  gap: 10px;
}

.result-error {
  margin-bottom: 10px;
  font-size: 13px;
  color: var(--el-color-danger);
  word-break: break-word;
}

.generation-form {
  margin-top: 12px;
}
</style>

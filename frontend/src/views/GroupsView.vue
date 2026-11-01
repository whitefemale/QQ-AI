<template>
  <div class="page">
    <PageHeader
      title="群聊管理"
      description="只有登记并启用的白名单群才会触发 AI 回复。新建与导入的群默认「观察」，不会生成回复；频率、冷却、安静时段与关键词均在本地生效。"
    >
      <template #actions>
        <el-button :loading="loading" @click="load">刷新</el-button>
        <el-button type="primary" @click="openCreate">手动添加群</el-button>
      </template>
    </PageHeader>

    <el-alert
      type="warning"
      show-icon
      :closable="false"
      title="白名单为空时不会回复任何群。"
      description="首次接入建议选择「仅观察」或保持停用，确认群氛围与机器人边界后再开启。群消息始终是不可信内容，不会成为系统指令。"
    />
    <el-alert v-if="error" type="error" :title="error" show-icon :closable="false" />

    <div class="card">
      <el-table v-loading="loading" :data="groups" row-key="id">
        <el-table-column label="群" min-width="200">
          <template #default="{ row }">
            <div>{{ row.name || '未命名群' }}</div>
            <div class="muted mono">{{ row.platform_group_id }} · {{ row.account_name || '未知账号' }}</div>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="150">
          <template #default="{ row }">
            <StateTag :state="row.paused ? 'paused' : (row.enabled ? 'enabled' : 'disabled')" :label="row.paused ? '已暂停' : (row.enabled ? '启用' : '未启用')" />
          </template>
        </el-table-column>
        <el-table-column label="回复模式" width="130">
          <template #default="{ row }">
            <el-tag size="small" effect="plain">{{ replyModeLabel(row.reply_mode) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="人格" width="130">
          <template #default="{ row }">
            <span v-if="row.persona_name">{{ row.persona_name }}</span>
            <span v-else class="muted">使用默认</span>
          </template>
        </el-table-column>
        <el-table-column label="模型" min-width="170">
          <template #default="{ row }">
            <div v-if="row.llm_provider_id">
              <div class="model-line">
                <span>{{ row.llm_provider_name || 'Provider 已缺失' }}</span>
                <el-tag v-if="row.llm_provider_state === 'mock'" size="small" type="warning">Mock</el-tag>
                <el-tag v-else-if="row.llm_provider_state === 'disabled'" size="small" type="danger">已禁用</el-tag>
                <el-tag v-else-if="row.llm_provider_state === 'missing'" size="small" type="danger">已删除</el-tag>
              </div>
              <div v-if="row.llm_fallback_provider_id" class="muted model-fallback">
                备用：{{ row.llm_fallback_provider_name || '已缺失' }}
                <el-tag v-if="row.llm_fallback_provider_state === 'mock'" size="small" type="warning">Mock</el-tag>
                <el-tag v-else-if="row.llm_fallback_provider_state === 'disabled'" size="small" type="danger">已禁用</el-tag>
              </div>
              <div v-else class="muted model-fallback">无备用模型</div>
            </div>
            <span v-else class="muted">全局默认 Provider</span>
          </template>
        </el-table-column>
        <el-table-column label="限速" min-width="230">
          <template #default="{ row }">
            <div class="muted">
              群：冷却 {{ row.rate_limit.cooldown_seconds }}s · 时 {{ row.rate_limit.max_replies_per_hour }} · 日 {{ row.rate_limit.max_replies_per_day }} · 连续 {{ row.rate_limit.max_consecutive_replies }}
            </div>
            <div class="muted">
              每人：时 {{ row.rate_limit.max_replies_per_member_per_hour ?? '—' }} · 日 {{ row.rate_limit.max_replies_per_member_per_day ?? '—' }}
            </div>
            <div class="muted">
              回复 ≤ {{ row.max_reply_chars_effective ?? '—' }} 字 · 上下文 {{ row.context_message_limit_effective ?? '—' }} 条
            </div>
          </template>
        </el-table-column>
        <el-table-column label="能力" min-width="180">
          <template #default="{ row }">
            <div class="cap-tags">
              <el-tag size="small" :type="row.allow_memory ? 'success' : 'info'">记忆{{ row.allow_memory ? '开' : '关' }}</el-tag>
              <el-tag v-if="row.auto_memory_extraction" size="small" type="warning">自动提取候选</el-tag>
              <el-tag size="small" :type="row.allow_tools ? 'success' : 'info'">工具{{ row.allow_tools ? '开' : '关' }}</el-tag>
              <el-tag size="small" :type="row.allow_proactive ? 'warning' : 'info'">主动{{ row.allow_proactive ? '开' : '关' }}</el-tag>
              <el-tag v-if="row.quiet_hours.enabled" size="small" type="warning">
                安静 {{ row.quiet_hours.start }}–{{ row.quiet_hours.end }}
              </el-tag>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="启用" width="75">
          <template #default="{ row }">
            <el-switch :model-value="row.enabled" @change="(value: string | number | boolean) => setEnabled(row, Boolean(value))" />
          </template>
        </el-table-column>
        <el-table-column label="操作" width="220" fixed="right">
          <template #default="{ row }">
            <div class="row-actions">
              <el-button size="small" @click="openEdit(row)">配置</el-button>
              <el-button v-if="row.paused" size="small" type="success" @click="resumeGroup(row)">恢复</el-button>
              <el-button v-else size="small" @click="pauseGroup(row)">暂停</el-button>
              <el-button size="small" type="danger" text @click="deleteGroup(row)">删除</el-button>
            </div>
          </template>
        </el-table-column>
      </el-table>
      <el-empty v-if="!loading && !groups.length" description="还没有登记群。可以在「QQ 接入」中从连接器导入，或手动添加群号。" />
    </div>

    <el-dialog v-model="dialog" :title="editing ? '编辑群配置' : '手动添加群'" width="720px" :close-on-click-modal="false">
      <el-form label-width="130px">
        <el-form-item v-if="!editing" label="账号" required>
          <el-select v-model="form.account_id" style="width: 100%" placeholder="选择账号">
            <el-option v-for="account in accounts" :key="account.id" :label="account.display_name" :value="account.id" />
          </el-select>
        </el-form-item>
        <el-form-item v-if="!editing" label="平台群号" required>
          <el-input v-model="form.platform_group_id" placeholder="例如：100001" />
          <div class="form-tip">请填写 QQ 群号（由连接器上报的一致格式）。</div>
        </el-form-item>
        <el-form-item label="群名称">
          <el-input v-model="form.name" maxlength="256" />
        </el-form-item>
        <el-form-item label="启用 AI 回复">
          <el-switch v-model="form.enabled" />
          <span class="form-tip" style="margin-left: 10px">新登记的群建议先保持关闭。</span>
        </el-form-item>
        <el-form-item label="回复模式">
          <el-select v-model="form.reply_mode" style="width: 100%">
            <el-option
              v-for="mode in replyModes"
              :key="mode.value"
              :label="mode.label"
              :value="mode.value"
              :disabled="mode.state === 'planned'"
            >
              <span>{{ mode.label }}</span>
              <span class="muted" style="float: right; font-size: 12px">{{ mode.state === 'planned' ? '规划中' : mode.note }}</span>
            </el-option>
          </el-select>
          <div class="form-tip">{{ currentModeNote }}</div>
        </el-form-item>
        <div class="threshold-grid">
          <el-form-item label="回复字数上限">
            <el-input-number v-model="form.max_reply_chars" :min="50" :max="2000" placeholder="使用全局值" />
            <div class="form-tip">留空使用全局设置；范围 50–2000。</div>
          </el-form-item>
          <el-form-item label="上下文消息条数">
            <el-input-number v-model="form.context_message_limit" :min="1" :max="100" placeholder="使用全局值" />
            <div class="form-tip">留空使用全局设置；范围 1–100。</div>
          </el-form-item>
        </div>
        <el-form-item label="绑定人格">
          <el-select v-model="form.persona_id" style="width: 100%" clearable placeholder="使用账号默认/不绑定">
            <el-option v-for="persona in personas" :key="persona.id" :label="persona.name" :value="persona.id" />
          </el-select>
        </el-form-item>
        <el-divider content-position="left">模型路由</el-divider>
        <el-form-item label="主模型">
          <el-select
            v-model="form.llm_provider_id"
            style="width: 100%"
            clearable
            placeholder="使用全局默认 Provider"
            @change="onPrimaryChange"
          >
            <el-option
              v-for="provider in providers"
              :key="provider.id"
              :label="providerOptionLabel(provider)"
              :value="provider.id"
              :disabled="!provider.enabled && provider.id !== form.llm_provider_id"
            >
              <span>{{ providerOptionLabel(provider) }}</span>
              <span class="muted" style="float: right; font-size: 12px">
                {{ provider.enabled ? (provider.provider_type === 'mock' ? 'Mock 模拟' : '已启用') : '已禁用' }}
              </span>
            </el-option>
          </el-select>
          <div class="form-tip">
            未绑定或清空时使用「模型 API」中的全局默认 Provider；绑定后本群回复、记忆提取与人格成长均使用该模型。
          </div>
          <div v-if="selectedPrimary?.provider_type === 'mock'" class="form-tip warn-tip">
            当前主模型为 Mock，只会返回模拟回复，不代表真实模型能力。
          </div>
          <div v-if="selectedPrimary && !selectedPrimary.enabled" class="form-tip warn-tip">
            当前绑定的主模型 Provider 已被禁用，本群调用会失败；请重新启用或选择其他模型。
          </div>
          <div v-if="form.llm_provider_id && !selectedPrimary" class="form-tip warn-tip">
            原先绑定的主模型 Provider 已不存在，请重新选择或清空绑定。
          </div>
        </el-form-item>
        <el-form-item label="备用模型">
          <el-select
            v-model="form.llm_fallback_provider_id"
            style="width: 100%"
            clearable
            :disabled="!form.llm_provider_id"
            placeholder="不配置备用模型"
          >
            <el-option
              v-for="provider in fallbackProviders"
              :key="provider.id"
              :label="providerOptionLabel(provider)"
              :value="provider.id"
              :disabled="!provider.enabled && provider.id !== form.llm_fallback_provider_id"
            >
              <span>{{ providerOptionLabel(provider) }}</span>
              <span class="muted" style="float: right; font-size: 12px">
                {{ provider.enabled ? (provider.provider_type === 'mock' ? 'Mock 模拟' : '已启用') : '已禁用' }}
              </span>
            </el-option>
          </el-select>
          <div class="form-tip">
            仅在主模型发生超时、限流、网络、认证、额度或响应解析等调用错误时尝试一次；
            预算超限、全局暂停、Provider 配置或凭证错误不会触发回退，也不会静默改用 Mock。
          </div>
          <div v-if="selectedFallback?.provider_type === 'mock'" class="form-tip warn-tip">
            备用模型为 Mock：主模型失败后会出现模拟回复，请确认这是否符合预期。
          </div>
          <div v-if="form.llm_fallback_provider_id && !selectedFallback" class="form-tip warn-tip">
            原先绑定的备用模型 Provider 已不存在，请重新选择或清空绑定。
          </div>
        </el-form-item>

        <el-form-item label="关键词">
          <el-select
            v-model="form.keywords"
            multiple
            filterable
            allow-create
            default-first-option
            style="width: 100%"
            placeholder="仅在「关键词触发」模式下生效；输入后回车添加"
          />
        </el-form-item>
        <el-form-item label="管理员 ID">
          <el-select
            v-model="form.admin_user_ids"
            multiple
            filterable
            allow-create
            default-first-option
            style="width: 100%"
            placeholder="允许在群内使用管理命令的 QQ 号；建议仅填本人"
          />
        </el-form-item>
        <el-form-item label="群规则">
          <el-input v-model="form.group_rules_text" type="textarea" :rows="3" maxlength="4000" placeholder="作为不可覆盖的群级规则注入提示词。" />
        </el-form-item>
        <el-form-item label="时区">
          <el-input v-model="form.timezone" style="width: 240px" placeholder="Asia/Shanghai" />
        </el-form-item>

        <el-divider content-position="left">频率限制</el-divider>
        <div class="threshold-grid">
          <el-form-item label="冷却（秒）">
            <el-input-number v-model="form.rate_limit.cooldown_seconds" :min="0" :max="3600" />
          </el-form-item>
          <el-form-item label="每小时上限">
            <el-input-number v-model="form.rate_limit.max_replies_per_hour" :min="1" :max="1000" />
          </el-form-item>
          <el-form-item label="每日上限">
            <el-input-number v-model="form.rate_limit.max_replies_per_day" :min="1" :max="10000" />
          </el-form-item>
          <el-form-item label="连续回复上限">
            <el-input-number v-model="form.rate_limit.max_consecutive_replies" :min="1" :max="50" />
          </el-form-item>
          <el-form-item label="每人每小时">
            <el-input-number v-model="form.rate_limit.max_replies_per_member_per_hour" :min="1" :max="100" />
          </el-form-item>
          <el-form-item label="每人每天">
            <el-input-number v-model="form.rate_limit.max_replies_per_member_per_day" :min="1" :max="1000" />
          </el-form-item>
        </div>
        <div class="form-tip">
          每人限额只统计已发送（含状态未知）的 AI 回复，待审核草稿不占额度；命令回复不计入每人额度，但仍计入群级额度。
        </div>

        <el-divider content-position="left">安静时段</el-divider>
        <el-form-item label="启用">
          <el-switch v-model="form.quiet_hours.enabled" />
        </el-form-item>
        <template v-if="form.quiet_hours.enabled">
          <el-form-item label="开始时间">
            <el-time-picker v-model="quietStart" format="HH:mm" value-format="HH:mm" placeholder="22:00" style="width: 160px" />
          </el-form-item>
          <el-form-item label="结束时间">
            <el-time-picker v-model="quietEnd" format="HH:mm" value-format="HH:mm" placeholder="08:00" style="width: 160px" />
            <span class="form-tip" style="margin-left: 10px">支持跨午夜，例如 23:00 至 07:00。</span>
          </el-form-item>
          <el-form-item label="安静时段时区">
            <el-input v-model="form.quiet_hours.timezone" style="width: 240px" />
          </el-form-item>
        </template>

        <el-divider content-position="left">权限与能力</el-divider>
        <el-form-item label="允许工具">
          <el-switch v-model="form.allow_tools" />
          <div class="form-tip">群内工具默认关闭；高风险工具仍需额外授权。</div>
        </el-form-item>
        <el-form-item label="允许长期记忆">
          <el-switch v-model="form.allow_memory" />
          <div class="form-tip">开启后只检索本群及当前发送者的普通敏感度记忆；语义检索仍为规划能力。</div>
        </el-form-item>
        <el-form-item label="后台提取记忆候选">
          <el-switch v-model="form.auto_memory_extraction" :disabled="!form.allow_memory" />
          <div class="form-tip">
            默认关闭。开启后后台按增量扫描本群新消息，只生成待审核候选，不会自动批准、写入正式记忆或注入提示词；
            至少需要 3 条新消息，全局暂停时停止。关闭长期记忆会同时关闭此选项。
          </div>
          <div v-if="editing?.memory_extraction_last_error" class="form-tip">
            上次自动提取失败：{{ editing.memory_extraction_last_error }}
          </div>
        </el-form-item>
        <el-form-item label="允许主动发言">
          <el-switch v-model="form.allow_proactive" />
          <div class="form-tip">「上下文参与」回复模式与定时主动话题仍在规划中，当前版本无法选择或保存该模式。</div>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialog = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="saveGroup">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'

import { api, errorMessage } from '@/api/client'
import type { Account, Group, LLMProvider, Persona } from '@/api/types'
import PageHeader from '@/components/PageHeader.vue'
import StateTag from '@/components/StateTag.vue'
import { DELETE_PHRASE, typedConfirm } from '@/utils/confirmation'
import { ElMessage } from 'element-plus'

interface ReplyMode {
  value: string
  label: string
  note: string
  state?: string
}

interface GroupForm {
  account_id: string
  platform_group_id: string
  name: string
  enabled: boolean
  reply_mode: string
  max_reply_chars: number | null
  context_message_limit: number | null
  persona_id: string | null
  llm_provider_id: string | null
  llm_fallback_provider_id: string | null
  keywords: string[]
  admin_user_ids: string[]
  group_rules_text: string
  timezone: string
  rate_limit: {
    cooldown_seconds: number
    max_replies_per_hour: number
    max_replies_per_day: number
    max_consecutive_replies: number
    max_replies_per_member_per_hour: number
    max_replies_per_member_per_day: number
  }
  quiet_hours: {
    enabled: boolean
    start: string
    end: string
    timezone: string
  }
  allow_tools: boolean
  allow_memory: boolean
  auto_memory_extraction: boolean
  allow_proactive: boolean
}

const groups = ref<Group[]>([])
const accounts = ref<Account[]>([])
const personas = ref<Persona[]>([])
const providers = ref<LLMProvider[]>([])
const replyModes = ref<ReplyMode[]>([])
const loading = ref(false)
const saving = ref(false)
const error = ref<string | null>(null)

const dialog = ref(false)
const editing = ref<Group | null>(null)

const DEFAULT_RATE_LIMIT = {
  cooldown_seconds: 20,
  max_replies_per_hour: 8,
  max_replies_per_day: 60,
  max_consecutive_replies: 2,
  max_replies_per_member_per_hour: 10,
  max_replies_per_member_per_day: 50,
}

function emptyForm(): GroupForm {
  return {
    account_id: '',
    platform_group_id: '',
    name: '',
    enabled: false,
    reply_mode: 'observe',
    max_reply_chars: null,
    context_message_limit: null,
    persona_id: null,
    llm_provider_id: null,
    llm_fallback_provider_id: null,
    keywords: [],
    admin_user_ids: [],
    group_rules_text: '',
    timezone: 'Asia/Shanghai',
    rate_limit: { ...DEFAULT_RATE_LIMIT },
    quiet_hours: { enabled: false, start: '23:00', end: '07:00', timezone: 'Asia/Shanghai' },
    allow_tools: false,
    allow_memory: false,
    auto_memory_extraction: false,
    allow_proactive: false,
  }
}

const form = reactive<GroupForm>(emptyForm())
const quietStart = ref<string | null>('23:00')
const quietEnd = ref<string | null>('07:00')

const currentModeNote = computed(
  () => replyModes.value.find((mode) => mode.value === form.reply_mode)?.note ?? '',
)

const selectedPrimary = computed(
  () => providers.value.find((provider) => provider.id === form.llm_provider_id) ?? null,
)
const selectedFallback = computed(
  () => providers.value.find((provider) => provider.id === form.llm_fallback_provider_id) ?? null,
)
const fallbackProviders = computed(() =>
  providers.value.filter((provider) => provider.id !== form.llm_provider_id),
)

function providerOptionLabel(provider: LLMProvider): string {
  const typeLabel =
    provider.provider_type === 'mock'
      ? 'Mock'
      : provider.provider_type === 'anthropic_native'
        ? 'Anthropic'
        : 'OpenAI 兼容'
  return `${provider.name}（${typeLabel} · ${provider.model || '未填写模型'}）`
}

function onPrimaryChange(): void {
  if (
    !form.llm_provider_id ||
    form.llm_fallback_provider_id === form.llm_provider_id
  ) {
    form.llm_fallback_provider_id = null
  }
}

function replyModeLabel(value: string): string {
  return replyModes.value.find((mode) => mode.value === value)?.label ?? value
}

async function load(): Promise<void> {
  loading.value = true
  error.value = null
  try {
    const [groupData, accountData, personaData, providerData] = await Promise.all([
      api<{ items: Group[]; reply_modes: ReplyMode[]; rate_limit_defaults: Record<string, number> }>('/groups'),
      api<{ items: Account[] }>('/accounts'),
      api<{ items: Persona[] }>('/personas'),
      api<{ items: LLMProvider[] }>('/providers'),
    ])
    groups.value = groupData.items
    replyModes.value = groupData.reply_modes
    accounts.value = accountData.items
    personas.value = personaData.items
    providers.value = providerData.items
    if (groupData.rate_limit_defaults) Object.assign(DEFAULT_RATE_LIMIT, groupData.rate_limit_defaults)
  } catch (err) {
    error.value = errorMessage(err)
  } finally {
    loading.value = false
  }
}

function openCreate(): void {
  editing.value = null
  Object.assign(form, emptyForm())
  form.account_id = accounts.value[0]?.id ?? ''
  quietStart.value = '23:00'
  quietEnd.value = '07:00'
  dialog.value = true
}

function openEdit(group: Group): void {
  editing.value = group
  const quiet = group.quiet_hours ?? {}
  Object.assign(form, {
    account_id: group.account_id,
    platform_group_id: group.platform_group_id,
    name: group.name ?? '',
    enabled: group.enabled,
    reply_mode: group.reply_mode,
    max_reply_chars: group.max_reply_chars ?? null,
    context_message_limit: group.context_message_limit ?? null,
    persona_id: group.persona_id,
    llm_provider_id: group.llm_provider_id,
    llm_fallback_provider_id: group.llm_fallback_provider_id,
    keywords: [...group.keywords],
    admin_user_ids: [...group.admin_user_ids],
    group_rules_text: group.group_rules_text ?? '',
    timezone: group.timezone,
    rate_limit: { ...DEFAULT_RATE_LIMIT, ...group.rate_limit },
    quiet_hours: {
      enabled: Boolean(quiet.enabled),
      start: typeof quiet.start === 'string' ? quiet.start : '23:00',
      end: typeof quiet.end === 'string' ? quiet.end : '07:00',
      timezone: typeof quiet.timezone === 'string' ? quiet.timezone : group.timezone,
    },
    allow_tools: group.allow_tools,
    allow_memory: group.allow_memory,
    auto_memory_extraction: group.auto_memory_extraction,
    allow_proactive: group.allow_proactive,
  })
  quietStart.value = form.quiet_hours.start
  quietEnd.value = form.quiet_hours.end
  dialog.value = true
}

async function saveGroup(): Promise<void> {
  if (!editing.value) {
    if (!form.account_id) {
      ElMessage.warning('请选择账号。')
      return
    }
    if (!form.platform_group_id.trim()) {
      ElMessage.warning('请填写平台群号。')
      return
    }
  }
  if (form.quiet_hours.enabled && (!quietStart.value || !quietEnd.value)) {
    ElMessage.warning('启用安静时段时必须填写开始与结束时间。')
    return
  }
  const quiet = form.quiet_hours.enabled
    ? {
        enabled: true,
        start: quietStart.value,
        end: quietEnd.value,
        timezone: form.quiet_hours.timezone || form.timezone,
      }
    : { enabled: false, timezone: form.quiet_hours.timezone || form.timezone }
  const body: Record<string, unknown> = {
    name: form.name.trim(),
    enabled: form.enabled,
    reply_mode: form.reply_mode,
    max_reply_chars: form.max_reply_chars ?? null,
    context_message_limit: form.context_message_limit ?? null,
    persona_id: form.persona_id || null,
    llm_provider_id: form.llm_provider_id || null,
    llm_fallback_provider_id: form.llm_provider_id ? form.llm_fallback_provider_id || null : null,
    keywords: form.keywords,
    admin_user_ids: form.admin_user_ids,
    group_rules_text: form.group_rules_text,
    timezone: form.timezone,
    rate_limit: form.rate_limit,
    quiet_hours: quiet,
    allow_tools: form.allow_tools,
    allow_memory: form.allow_memory,
    auto_memory_extraction: form.allow_memory && form.auto_memory_extraction,
    allow_proactive: form.allow_proactive,
  }
  saving.value = true
  try {
    if (editing.value) {
      await api(`/groups/${editing.value.id}`, { method: 'PATCH', body })
      ElMessage.success('群配置已保存。')
    } else {
      body.account_id = form.account_id
      body.platform_group_id = form.platform_group_id.trim()
      await api('/groups', { method: 'POST', body })
      ElMessage.success('群已加入白名单（默认未启用）。')
    }
    dialog.value = false
    await load()
  } catch (err) {
    ElMessage.error(errorMessage(err))
  } finally {
    saving.value = false
  }
}

async function setEnabled(group: Group, enabled: boolean): Promise<void> {
  try {
    await api(`/groups/${group.id}`, { method: 'PATCH', body: { enabled } })
    ElMessage.success(enabled ? '已启用该群的 AI 回复。' : '已停用该群。')
  } catch (err) {
    ElMessage.error(errorMessage(err))
  } finally {
    await load()
  }
}

async function pauseGroup(group: Group): Promise<void> {
  try {
    await api(`/groups/${group.id}/pause`, { method: 'POST' })
    ElMessage.success('群已暂停。')
    await load()
  } catch (err) {
    ElMessage.error(errorMessage(err))
  }
}

async function resumeGroup(group: Group): Promise<void> {
  try {
    await api(`/groups/${group.id}/resume`, { method: 'POST' })
    ElMessage.success('群已恢复。')
    await load()
  } catch (err) {
    ElMessage.error(errorMessage(err))
  }
}

async function deleteGroup(group: Group): Promise<void> {
  const confirmed = await typedConfirm(
    `移除「${group.name || group.platform_group_id}」会删除群配置、记忆与待审核候选，并取消该群所有待发送消息。历史消息会保留，但不再关联该群；此操作不可恢复。`,
    DELETE_PHRASE,
    '移除群',
  )
  if (!confirmed) return
  try {
    await api(`/groups/${group.id}`, { method: 'DELETE', query: { confirm: DELETE_PHRASE } })
    ElMessage.success('群已移除，历史消息已保留。')
    await load()
  } catch (err) {
    ElMessage.error(errorMessage(err))
  }
}

onMounted(load)
</script>

<style scoped>
.cap-tags {
  display: flex;
  gap: 4px;
  flex-wrap: wrap;
}

.threshold-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  column-gap: 18px;
}

.model-line {
  display: flex;
  align-items: center;
  gap: 4px;
  flex-wrap: wrap;
}

.model-fallback {
  margin-top: 2px;
  font-size: 12px;
}

.warn-tip {
  color: var(--el-color-warning);
}
</style>

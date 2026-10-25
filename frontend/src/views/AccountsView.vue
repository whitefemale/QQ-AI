<template>
  <div class="page">
    <PageHeader
      title="QQ 接入"
      description="通过用户自行安装并登录的 OneBot 11 连接器（如 NapCat）接入 QQ，或使用完全本地的 Mock 连接器演示。软件不收集 QQ 密码，不提供验证码绕过或风控规避。"
    >
      <template #actions>
        <el-button :loading="loading" @click="load">刷新</el-button>
        <el-button type="primary" @click="openCreate">新建账号</el-button>
      </template>
    </PageHeader>

    <el-alert
      type="warning"
      show-icon
      :closable="false"
      title="请使用你本人拥有并授权管理的专用 QQ 账号；账号出现验证或封禁风险时应立即暂停。"
      description="默认只允许连接本机/私网连接器。填写公网地址必须显式开启风险确认；Token 仅加密保存在本地。"
    />

    <el-alert v-if="error" type="error" :title="error" show-icon :closable="false" />

    <div class="card">
      <el-table v-loading="loading" :data="accounts" row-key="id" size="default">
        <el-table-column type="expand">
          <template #default="{ row }">
            <div class="instance-panel">
              <div class="instance-head">
                <span class="muted">连接器实例</span>
                <el-button size="small" @click="openInstanceDialog(row, null)">添加连接器</el-button>
              </div>
              <el-empty v-if="!row.instances.length" description="该账号还没有连接器实例" :image-size="50" />
              <el-table v-else :data="row.instances" size="small">
                <el-table-column prop="name" label="名称" width="140" />
                <el-table-column label="方式" width="100">
                  <template #default="{ row: instance }">
                    <el-tag size="small">{{ modeLabel(instance.connection_mode) }}</el-tag>
                  </template>
                </el-table-column>
                <el-table-column label="状态" width="100">
                  <template #default="{ row: instance }">
                    <StateTag :state="instance.status" />
                  </template>
                </el-table-column>
                <el-table-column label="地址" min-width="190">
                  <template #default="{ row: instance }">
                    <span class="mono">{{ instance.endpoint || '本地 Mock' }}</span>
                    <div v-if="instance.api_endpoint" class="muted mono">{{ instance.api_endpoint }}</div>
                  </template>
                </el-table-column>
                <el-table-column label="Token" width="110">
                  <template #default="{ row: instance }">
                    <span class="mono">{{ instance.token_configured ? instance.token_masked : '未配置' }}</span>
                  </template>
                </el-table-column>
                <el-table-column label="心跳" width="110">
                  <template #default="{ row: instance }">
                    <span class="muted">{{ heartbeatText(instance) }}</span>
                  </template>
                </el-table-column>
                <el-table-column label="操作" min-width="330">
                  <template #default="{ row: instance }">
                    <div class="row-actions">
                      <el-button size="small" :disabled="instance.status === 'online'" @click="connectInstance(row, instance)">连接</el-button>
                      <el-button size="small" :disabled="instance.status !== 'online'" @click="disconnectInstance(row, instance)">断开</el-button>
                      <el-button size="small" @click="testSavedInstance(row, instance)">测试</el-button>
                      <el-button size="small" :disabled="instance.status !== 'online'" @click="fetchGroups(row, instance)">拉取群列表</el-button>
                      <el-button size="small" @click="openInstanceDialog(row, instance)">编辑</el-button>
                      <el-button size="small" type="danger" text @click="deleteInstance(row, instance)">删除</el-button>
                    </div>
                  </template>
                </el-table-column>
                <el-table-column type="expand">
                  <template #default="{ row: instance }">
                    <div class="capability-grid">
                      <el-tag v-for="(value, key) in instance.capabilities" :key="key" size="small" :type="value ? 'success' : 'info'">
                        {{ capabilityLabel(String(key)) }}：{{ value ? '支持' : '不支持' }}
                      </el-tag>
                    </div>
                    <el-alert
                      v-if="instance.last_error_message"
                      class="instance-error"
                      type="error"
                      :title="instance.last_error_message"
                      :closable="false"
                      show-icon
                    />
                    <div v-if="instance.connection_mode === 'mock'" class="muted">
                      Mock 连接器不会连接真实 QQ；可通过「模拟测试」页面注入事件。
                    </div>
                  </template>
                </el-table-column>
              </el-table>
            </div>
          </template>
        </el-table-column>
        <el-table-column prop="display_name" label="账号" min-width="170">
          <template #default="{ row }">
            <div>{{ row.display_name }}</div>
            <div class="muted mono">{{ row.self_platform_user_id ? `QQ ${row.self_platform_user_id}` : '自身 QQ 号未确定' }}</div>
          </template>
        </el-table-column>
        <el-table-column label="方式" width="110">
          <template #default="{ row }">{{ modeLabel(row.adapter_type) }}</template>
        </el-table-column>
        <el-table-column label="状态" width="100">
          <template #default="{ row }"><StateTag :state="row.status" /></template>
        </el-table-column>
        <el-table-column label="启用" width="80">
          <template #default="{ row }">
            <el-switch :model-value="row.enabled" @change="(value: string | number | boolean) => setAccountEnabled(row, Boolean(value))" />
          </template>
        </el-table-column>
        <el-table-column label="私聊回复" width="100">
          <template #default="{ row }">
            <el-tag size="small" :type="row.allow_private ? 'warning' : 'info'">
              {{ row.allow_private ? '已开启' : '未开启' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="notes" label="备注" min-width="150" show-overflow-tooltip />
        <el-table-column label="操作" width="220" fixed="right">
          <template #default="{ row }">
            <div class="row-actions">
              <el-button size="small" @click="showStatus(row)">状态</el-button>
              <el-button size="small" @click="showMockSent(row)">Mock 已发送</el-button>
              <el-button size="small" type="danger" text @click="deleteAccount(row)">删除</el-button>
            </div>
          </template>
        </el-table-column>
      </el-table>
      <el-empty v-if="!loading && !accounts.length" description="还没有 QQ 账号。可以先初始化 Mock 演示环境，或新建 OneBot 11 账号。" />
    </div>

    <el-dialog v-model="createDialog" title="新建账号" width="560px" :close-on-click-modal="false">
      <el-form label-width="110px">
        <el-form-item label="账号名称" required>
          <el-input v-model="form.display_name" maxlength="128" placeholder="例如：群友助手（专用小号）" />
        </el-form-item>
        <el-form-item label="备注">
          <el-input v-model="form.notes" type="textarea" :rows="2" maxlength="2000" />
        </el-form-item>
        <el-form-item label="允许私聊回复">
          <el-switch v-model="form.allow_private" />
          <span class="form-tip" style="margin-left: 10px">默认关闭。私聊回复风险更高，建议保持关闭。</span>
        </el-form-item>
        <el-divider content-position="left">首个连接器</el-divider>
        <InstanceFormFields v-model="form.instance" />
      </el-form>

      <el-alert
        v-if="testResult"
        :type="testResult.ok ? 'success' : 'error'"
        :title="testResult.ok ? '连接测试成功' : '连接测试失败'"
        :description="testSummary"
        :closable="false"
        show-icon
      />

      <template #footer>
        <el-button @click="testConnection" :loading="testing">测试连接（不保存）</el-button>
        <el-button @click="createDialog = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="createAccount">创建</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="instanceDialog" :title="editingInstance ? '编辑连接器' : '添加连接器'" width="540px" :close-on-click-modal="false">
      <el-form label-width="110px">
        <InstanceFormFields v-model="instanceForm" />
      </el-form>
      <template #footer>
        <el-button @click="instanceDialog = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="saveInstance">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="groupsDialog" title="从连接器导入群" width="560px">
      <el-alert
        type="info"
        :closable="false"
        show-icon
        title="导入的群默认关闭 AI 回复；请在「群聊管理」中逐群确认后再启用。"
      />
      <el-empty v-if="!connectorGroups.length" description="连接器没有返回群列表" :image-size="55" />
      <el-table v-else :data="connectorGroups" size="small" max-height="320">
        <el-table-column prop="name" label="群名称" />
        <el-table-column prop="platform_group_id" label="平台群号" width="160" />
      </el-table>
      <template #footer>
        <el-button @click="groupsDialog = false">取消</el-button>
        <el-button type="primary" :loading="importing" :disabled="!connectorGroups.length" @click="importGroups">确认导入</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="statusDialog" title="账号实时状态" width="600px">
      <pre class="status-pre">{{ statusJson }}</pre>
      <template #footer>
        <el-button @click="statusDialog = false">关闭</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="mockSentDialog" title="Mock 已发送消息（仅当前进程）" width="620px">
      <el-empty v-if="!mockSent.length" description="Mock 连接器还没有发送过消息" :image-size="55" />
      <el-table v-else :data="mockSent" size="small" max-height="360">
        <el-table-column prop="platform_message_id" label="消息 ID" width="170" />
        <el-table-column prop="conversation_id" label="会话" width="110" />
        <el-table-column label="内容" min-width="200">
          <template #default="{ row }">{{ row.raw?.text ?? '—' }}</template>
        </el-table-column>
      </el-table>
      <template #footer>
        <el-button @click="mockSentDialog = false">关闭</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, defineComponent, h, onMounted, reactive, ref } from 'vue'

import { api, errorMessage } from '@/api/client'
import type { Account, AdapterInstance } from '@/api/types'
import PageHeader from '@/components/PageHeader.vue'
import StateTag from '@/components/StateTag.vue'
import { ElAlert, ElDivider, ElFormItem, ElInput, ElMessage, ElMessageBox, ElOption, ElSelect, ElSwitch } from 'element-plus'

interface InstanceForm {
  name: string
  connection_mode: string
  endpoint: string
  api_endpoint: string
  token: string
  allow_remote: boolean
  auto_connect: boolean
  enabled: boolean
}

const MODE_LABELS: Record<string, string> = {
  mock: 'Mock',
  onebot11: 'OneBot 11',
  official: '官方机器人（规划中）',
}

const CAPABILITY_LABELS: Record<string, string> = {
  receive_group_message: '接收群消息',
  receive_private_message: '接收私聊',
  send_text: '发送文本',
  send_image: '发送图片',
  send_reply: '引用回复',
  mention_support: '支持 @',
  group_member_info: '群成员信息',
  group_list: '群列表',
  message_recall_event: '撤回事件',
  file_upload: '文件上传',
  voice_message: '语音消息',
  video_message: '视频消息',
  typing_indicator: '输入状态',
  official_api: '官方接口',
}

function emptyInstance(): InstanceForm {
  return {
    name: '默认连接',
    connection_mode: 'mock',
    endpoint: '',
    api_endpoint: '',
    token: '',
    allow_remote: false,
    auto_connect: true,
    enabled: true,
  }
}

const InstanceFormFields = defineComponent({
  name: 'InstanceFormFields',
  props: {
    modelValue: { type: Object as () => InstanceForm, required: true },
  },
  emits: ['update:modelValue'],
  setup(props, { emit }) {
    const update = (patch: Partial<InstanceForm>) => {
      emit('update:modelValue', { ...props.modelValue, ...patch })
    }
    return () =>
      h('div', [
        h(ElFormItem, { label: '连接方式' }, () =>
          h(ElSelect, {
            modelValue: props.modelValue.connection_mode,
            'onUpdate:modelValue': (value: string) => update({ connection_mode: value }),
            style: 'width: 100%',
          }, () => [
            h(ElOption, { label: 'Mock 连接器（本地演示）', value: 'mock' }),
            h(ElOption, { label: 'OneBot 11（NapCat 等）', value: 'onebot11' }),
            h(ElOption, { label: '官方 QQ 机器人（规划中，不可用）', value: 'official', disabled: true }),
          ]),
        ),
        h(ElFormItem, { label: '实例名称' }, () =>
          h(ElInput, {
            modelValue: props.modelValue.name,
            'onUpdate:modelValue': (value: string) => update({ name: value }),
            maxlength: 128,
          }),
        ),
        props.modelValue.connection_mode === 'onebot11'
          ? h('div', [
              h(ElFormItem, { label: 'WebSocket 地址' }, () =>
                h(ElInput, {
                  modelValue: props.modelValue.endpoint,
                  'onUpdate:modelValue': (value: string) => update({ endpoint: value }),
                  placeholder: 'ws://127.0.0.1:3001',
                }),
              ),
              h(ElFormItem, { label: 'HTTP API 地址' }, () =>
                h(ElInput, {
                  modelValue: props.modelValue.api_endpoint,
                  'onUpdate:modelValue': (value: string) => update({ api_endpoint: value }),
                  placeholder: 'http://127.0.0.1:3000（可选，优先用于发送）',
                }),
              ),
              h(ElFormItem, { label: '连接器 Token' }, () =>
                h(ElInput, {
                  modelValue: props.modelValue.token,
                  'onUpdate:modelValue': (value: string) => update({ token: value }),
                  type: 'password',
                  showPassword: true,
                  placeholder: '独立 Token；留空表示不修改',
                }),
              ),
              h(ElFormItem, { label: '允许远程地址' }, () =>
                h(ElSwitch, {
                  modelValue: props.modelValue.allow_remote,
                  'onUpdate:modelValue': (value: string | number | boolean) => update({ allow_remote: Boolean(value) }),
                }),
              ),
              h('div', { class: 'form-tip', style: 'margin: -4px 0 12px 110px' },
                '默认仅允许回环/私网地址。开启后公网连接风险由你自行承担；请确保 Token 足够强。'),
            ])
          : null,
        h(ElDivider),
        h(ElFormItem, { label: '自动连接' }, () =>
          h(ElSwitch, {
            modelValue: props.modelValue.auto_connect,
            'onUpdate:modelValue': (value: string | number | boolean) => update({ auto_connect: Boolean(value) }),
          }),
        ),
        h(ElFormItem, { label: '启用实例' }, () =>
          h(ElSwitch, {
            modelValue: props.modelValue.enabled,
            'onUpdate:modelValue': (value: string | number | boolean) => update({ enabled: Boolean(value) }),
          }),
        ),
      ])
  },
})

const accounts = ref<Account[]>([])
const loading = ref(false)
const saving = ref(false)
const testing = ref(false)
const importing = ref(false)
const error = ref<string | null>(null)

const createDialog = ref(false)
const form = reactive({
  display_name: '',
  notes: '',
  allow_private: false,
  instance: emptyInstance(),
})

const instanceDialog = ref(false)
const instanceForm = ref<InstanceForm>(emptyInstance())
const instanceContext = ref<{ account: Account; instance: AdapterInstance | null } | null>(null)
const editingInstance = computed(() => instanceContext.value?.instance ?? null)

const testResult = ref<Record<string, unknown> | null>(null)
const testSummary = computed(() => {
  if (!testResult.value) return ''
  const ok = Boolean(testResult.value.ok)
  const latency = testResult.value.latency_ms
  return ok ? `耗时 ${latency ?? '—'} ms` : String(testResult.value.error_message ?? testResult.value.message ?? '请检查地址与 Token。')
})

const groupsDialog = ref(false)
const connectorGroups = ref<Array<{ platform_group_id: string; name: string | null }>>([])
const groupsContext = ref<{ account: Account; instance: AdapterInstance } | null>(null)

const statusDialog = ref(false)
const statusJson = ref('')
const mockSentDialog = ref(false)
const mockSent = ref<Array<Record<string, unknown>>>([])

function modeLabel(mode: string): string {
  return MODE_LABELS[mode] ?? mode
}

function capabilityLabel(key: string): string {
  return CAPABILITY_LABELS[key] ?? key
}

function heartbeatText(instance: AdapterInstance): string {
  if (instance.heartbeat_age_seconds === null || instance.heartbeat_age_seconds === undefined) return '—'
  return `${Math.round(instance.heartbeat_age_seconds)} 秒前`
}

function instancePayload(value: InstanceForm): Record<string, unknown> {
  const payload: Record<string, unknown> = {
    name: value.name,
    connection_mode: value.connection_mode,
    allow_remote: value.allow_remote,
    auto_connect: value.auto_connect,
    enabled: value.enabled,
  }
  if (value.connection_mode === 'onebot11') {
    payload.endpoint = value.endpoint
    payload.api_endpoint = value.api_endpoint
    if (value.token) payload.token = value.token
  }
  return payload
}

async function load(): Promise<void> {
  loading.value = true
  error.value = null
  try {
    const data = await api<{ items: Account[] }>('/accounts')
    accounts.value = data.items
  } catch (err) {
    error.value = errorMessage(err)
  } finally {
    loading.value = false
  }
}

function openCreate(): void {
  form.display_name = ''
  form.notes = ''
  form.allow_private = false
  form.instance = emptyInstance()
  testResult.value = null
  createDialog.value = true
}

async function testConnection(): Promise<void> {
  testing.value = true
  testResult.value = null
  try {
    testResult.value = await api<Record<string, unknown>>('/accounts/test-connection', {
      method: 'POST',
      body: instancePayload(form.instance),
    })
  } catch (err) {
    testResult.value = { ok: false, error_message: errorMessage(err) }
  } finally {
    testing.value = false
  }
}

async function createAccount(): Promise<void> {
  if (!form.display_name.trim()) {
    ElMessage.warning('请填写账号名称。')
    return
  }
  if (form.instance.connection_mode === 'onebot11' && !form.instance.endpoint.trim()) {
    ElMessage.warning('请填写 OneBot WebSocket 地址。')
    return
  }
  saving.value = true
  try {
    await api('/accounts', {
      method: 'POST',
      body: {
        display_name: form.display_name.trim(),
        notes: form.notes.trim(),
        allow_private: form.allow_private,
        instance: instancePayload(form.instance),
      },
    })
    ElMessage.success('账号已创建。')
    createDialog.value = false
    await load()
  } catch (err) {
    ElMessage.error(errorMessage(err))
  } finally {
    saving.value = false
  }
}

function openInstanceDialog(account: Account, instance: AdapterInstance | null): void {
  instanceContext.value = { account, instance }
  instanceForm.value = instance
    ? {
        name: instance.name,
        connection_mode: instance.connection_mode,
        endpoint: instance.endpoint ?? '',
        api_endpoint: instance.api_endpoint ?? '',
        token: '',
        allow_remote: instance.allow_remote,
        auto_connect: instance.auto_connect,
        enabled: instance.enabled,
      }
    : emptyInstance()
  instanceDialog.value = true
}

async function saveInstance(): Promise<void> {
  const context = instanceContext.value
  if (!context) return
  if (instanceForm.value.connection_mode === 'onebot11' && !instanceForm.value.endpoint.trim()) {
    ElMessage.warning('请填写 OneBot WebSocket 地址。')
    return
  }
  saving.value = true
  try {
    if (context.instance) {
      await api(`/accounts/${context.account.id}/instances/${context.instance.id}`, {
        method: 'PATCH',
        body: instancePayload(instanceForm.value),
      })
    } else {
      await api(`/accounts/${context.account.id}/instances`, {
        method: 'POST',
        body: instancePayload(instanceForm.value),
      })
    }
    ElMessage.success('连接器已保存。')
    instanceDialog.value = false
    await load()
  } catch (err) {
    ElMessage.error(errorMessage(err))
  } finally {
    saving.value = false
  }
}

async function setAccountEnabled(account: Account, enabled: boolean): Promise<void> {
  try {
    await api(`/accounts/${account.id}`, { method: 'PATCH', body: { enabled } })
    ElMessage.success(enabled ? '账号已启用。' : '账号已停用，连接器已断开。')
  } catch (err) {
    ElMessage.error(errorMessage(err))
  } finally {
    await load()
  }
}

async function connectInstance(account: Account, instance: AdapterInstance): Promise<void> {
  try {
    await api(`/accounts/${account.id}/instances/${instance.id}/connect`, { method: 'POST' })
    ElMessage.success('已发起连接。')
  } catch (err) {
    ElMessage.error(errorMessage(err))
  } finally {
    await load()
  }
}

async function disconnectInstance(account: Account, instance: AdapterInstance): Promise<void> {
  try {
    await api(`/accounts/${account.id}/instances/${instance.id}/disconnect`, { method: 'POST' })
    ElMessage.success('已断开连接。')
  } catch (err) {
    ElMessage.error(errorMessage(err))
  } finally {
    await load()
  }
}

async function testSavedInstance(account: Account, instance: AdapterInstance): Promise<void> {
  try {
    const result = await api<Record<string, unknown>>(
      `/accounts/${account.id}/instances/${instance.id}/test`,
      { method: 'POST', body: {} },
    )
    ElMessage.success(`连接测试成功：${result.latency_ms ?? '—'} ms`)
  } catch (err) {
    ElMessage.error(errorMessage(err))
  }
}

async function fetchGroups(account: Account, instance: AdapterInstance): Promise<void> {
  try {
    const data = await api<{ groups: Array<{ platform_group_id: string; name: string | null }> }>(
      `/accounts/${account.id}/instances/${instance.id}/groups`,
    )
    connectorGroups.value = data.groups
    groupsContext.value = { account, instance }
    groupsDialog.value = true
  } catch (err) {
    ElMessage.error(errorMessage(err))
  }
}

async function importGroups(): Promise<void> {
  const context = groupsContext.value
  if (!context) return
  importing.value = true
  try {
    const result = await api<{ created: number; updated: number; skipped: number }>('/groups/import-connector', {
      method: 'POST',
      body: { account_id: context.account.id, instance_id: context.instance.id },
    })
    ElMessage.success(`导入完成：新增 ${result.created}，更新 ${result.updated}，跳过 ${result.skipped}。`)
    groupsDialog.value = false
    await load()
  } catch (err) {
    ElMessage.error(errorMessage(err))
  } finally {
    importing.value = false
  }
}

async function showStatus(account: Account): Promise<void> {
  try {
    const data = await api<Record<string, unknown>>(`/accounts/${account.id}/status`)
    statusJson.value = JSON.stringify(data, null, 2)
    statusDialog.value = true
  } catch (err) {
    ElMessage.error(errorMessage(err))
  }
}

async function showMockSent(account: Account): Promise<void> {
  try {
    const data = await api<{ items: Array<Record<string, unknown>> }>(`/accounts/${account.id}/mock/sent`)
    mockSent.value = data.items
    mockSentDialog.value = true
  } catch (err) {
    ElMessage.error(errorMessage(err))
  }
}

async function deleteInstance(account: Account, instance: AdapterInstance): Promise<void> {
  try {
    await ElMessageBox.confirm(`确定删除连接器「${instance.name}」？`, '删除连接器', {
      type: 'warning',
      confirmButtonText: '删除',
      cancelButtonText: '取消',
    })
  } catch {
    return
  }
  try {
    await api(`/accounts/${account.id}/instances/${instance.id}`, { method: 'DELETE' })
    ElMessage.success('连接器已删除。')
    await load()
  } catch (err) {
    ElMessage.error(errorMessage(err))
  }
}

async function deleteAccount(account: Account): Promise<void> {
  try {
    await ElMessageBox.confirm(
      `确定删除账号「${account.display_name}」？其连接器会先断开。群与消息记录不会自动删除。`,
      '删除账号',
      { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' },
    )
  } catch {
    return
  }
  try {
    await api(`/accounts/${account.id}`, { method: 'DELETE' })
    ElMessage.success('账号已删除。')
    await load()
  } catch (err) {
    ElMessage.error(errorMessage(err))
  }
}

onMounted(load)
</script>

<style scoped>
.instance-panel {
  padding: 12px 18px 18px;
  background: var(--app-surface-soft);
}

.instance-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
}

.capability-grid {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
  padding: 8px 12px;
}

.instance-error {
  margin: 8px 12px;
}

.status-pre {
  max-height: 420px;
  overflow: auto;
  background: var(--app-surface-soft);
  border-radius: 8px;
  padding: 12px;
  font-size: 12px;
}
</style>

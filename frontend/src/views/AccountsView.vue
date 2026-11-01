<template>
  <div class="page">
    <PageHeader
      title="QQ 接入"
      description="通过用户自行安装并登录的 OneBot 11 连接器（如 NapCat）接入 QQ，或使用完全本地的 Mock 连接器演示。软件不收集 QQ 密码，不提供验证码绕过或风控规避。"
    >
      <template #actions>
        <el-button :loading="loading" @click="load">刷新</el-button>
        <el-button @click="goConnectors">连接器管理</el-button>
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
    <el-alert
      type="info"
      show-icon
      :closable="false"
      title="安装 ≠ 登录 ≠ 身份验证 ≠ 真实收发"
      description="「连接器」页可管理下载、官方安装器、进程、配置与诊断；本页保留为高级手动设置。诊断最多验证到身份与动作通道，真实群收发仍需人工验收。"
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
              <el-empty
                v-if="!row.instances.length"
                description="该账号还没有连接器实例；添加 Mock 或 OneBot 11 连接器。"
                :image-size="50"
              />
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
                <el-table-column label="操作" min-width="360">
                  <template #default="{ row: instance }">
                    <div class="row-actions">
                      <el-button
                        size="small"
                        :disabled="!instanceActions(instance.status).canConnect"
                        @click="connectInstance(row, instance)"
                      >
                        {{ instance.status === 'connected_unverified' ? '重新连接' : '连接' }}
                      </el-button>
                      <el-button
                        size="small"
                        :disabled="!instanceActions(instance.status).canDisconnect"
                        @click="disconnectInstance(row, instance)"
                      >
                        断开
                      </el-button>
                      <el-button size="small" @click="testSavedInstance(row, instance)">测试并诊断</el-button>
                      <el-button
                        v-if="instance.connection_mode === 'onebot11'"
                        size="small"
                        :disabled="instance.status !== 'online'"
                        @click="confirmIdentity(row, instance)"
                      >
                        确认登录身份
                      </el-button>
                      <el-button
                        size="small"
                        :disabled="!instanceActions(instance.status).canFetchGroups"
                        @click="fetchGroups(row, instance)"
                      >
                        拉取群列表
                      </el-button>
                      <el-button size="small" @click="openInstanceDialog(row, instance)">编辑</el-button>
                      <el-button size="small" type="danger" text @click="deleteInstance(row, instance)">删除</el-button>
                    </div>
                  </template>
                </el-table-column>
                <el-table-column type="expand">
                  <template #default="{ row: instance }">
                    <div class="instance-state">
                      <div class="state-line">
                        <span class="muted">状态</span>
                        <StateTag :state="instance.status" />
                        <el-tag
                          v-if="instance.connection_mode === 'onebot11'"
                          size="small"
                          :type="instance.live_health?.identity_verified ? 'warning' : 'info'"
                        >
                          身份{{ instance.live_health?.identity_verified ? '已验证' : '未验证' }}
                        </el-tag>
                        <span class="muted">
                          来源：{{ instance.live_health?.status_source || '数据库快照（当前进程无适配器）' }}
                        </span>
                        <span class="muted">观测：{{ formatTime(instance.live_health?.observed_at) }}</span>
                      </div>
                      <div class="state-line muted">
                        下一步：{{ instanceStatusNextStep(instance.status, instance.connection_mode, instance.last_error_message) }}
                      </div>
                      <div v-if="instance.last_error_code || instance.last_error_message" class="state-line">
                        <span class="mono">{{ instance.last_error_code || 'ERROR' }}</span>
                        <span>{{ instance.last_error_message || '—' }}</span>
                      </div>
                    </div>
                    <div class="capability-grid">
                      <el-tag v-for="(value, key) in instance.capabilities" :key="key" size="small" :type="value ? 'success' : 'info'">
                        {{ capabilityLabel(String(key)) }}：{{ value ? '支持' : '不支持' }}
                      </el-tag>
                    </div>
                    <div v-if="instance.connection_mode === 'mock'" class="muted instance-mock-note">
                      Mock 在线不代表真实 QQ；Mock 连接器可通过「模拟测试」页面注入事件。
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
      <el-empty
        v-if="!loading && !accounts.length"
        description="尚未配置连接实例；可添加 Mock 或 OneBot 11，或从接入向导开始。"
      >
        <el-button size="small" @click="router.push('/onboarding')">打开接入向导</el-button>
      </el-empty>
    </div>

    <el-dialog v-model="createDialog" title="新建账号" width="900px" :close-on-click-modal="false">
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

      <el-alert v-if="testError" type="error" :title="testError" :closable="false" show-icon />
      <ConnectionDiagnostics v-if="testResult" :report="testResult" />

      <template #footer>
        <el-button @click="testConnection" :loading="testing">测试并诊断（不保存）</el-button>
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

    <el-dialog v-model="diagnosticsDialog" :title="diagnosticsTitle" width="900px">
      <div v-loading="diagnosticsLoading" class="diagnostics-body">
        <el-alert
          type="info"
          :closable="false"
          show-icon
          title="诊断会临时建立独立连接；若连接器只允许一个连接，请先断开当前实例。"
        />
        <el-alert v-if="diagnosticsError" type="error" :title="diagnosticsError" :closable="false" show-icon />
        <ConnectionDiagnostics v-if="diagnosticsReport" :report="diagnosticsReport" />
      </div>
      <template #footer>
        <el-button @click="diagnosticsDialog = false">关闭</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="groupsDialog" title="从连接器导入群" width="560px">
      <el-alert
        type="info"
        :closable="false"
        show-icon
        title="导入的群默认关闭 AI 回复；请在「群聊管理」中逐群确认后再启用。"
      />
      <el-alert
        type="warning"
        :closable="false"
        show-icon
        class="mt8"
        title="导入真实群列表前必须确认当前登录身份"
        description="请填写你本人当前登录的 QQ 号；后端会与在线连接器上报的身份核对，不一致或 Mock 实例会被拒绝。"
      />
      <div class="identity-hint muted">
        在线适配器报告身份：
        <span class="mono">{{ groupsContext?.instance.live_health?.self_platform_user_id || '尚未报告' }}</span>
      </div>
      <el-input
        v-model="importSelfUserId"
        placeholder="当前登录 QQ 号（confirm_self_user_id）"
        maxlength="128"
        class="mt8"
      />
      <el-empty v-if="!connectorGroups.length" description="连接器没有返回群列表" :image-size="55" />
      <el-table v-else :data="connectorGroups" size="small" max-height="320">
        <el-table-column prop="name" label="群名称" />
        <el-table-column prop="platform_group_id" label="平台群号" width="160" />
      </el-table>
      <template #footer>
        <el-button @click="groupsDialog = false">取消</el-button>
        <el-button
          type="primary"
          :loading="importing"
          :disabled="!connectorGroups.length || !importSelfUserId.trim()"
          @click="importGroups"
        >确认导入</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="statusDialog" title="账号实时状态" width="760px">
      <el-alert
        type="info"
        :closable="false"
        show-icon
        title="实时状态来自当前后端进程；数据库状态可能滞后，重启后需重新连接。"
      />
      <template v-if="statusSnapshot">
        <el-descriptions :column="2" border size="small" class="mt8">
          <el-descriptions-item label="账号启用">{{ statusSnapshot.account.enabled ? '是' : '否' }}</el-descriptions-item>
          <el-descriptions-item label="账号状态"><StateTag :state="statusSnapshot.account.status" /></el-descriptions-item>
          <el-descriptions-item label="全局暂停">
            <StateTag :state="statusSnapshot.global_pause.paused ? 'paused' : 'available'" :label="statusSnapshot.global_pause.paused ? '暂停中' : '未暂停'" />
          </el-descriptions-item>
          <el-descriptions-item label="实例数量">{{ statusSnapshot.account.instances.length }}</el-descriptions-item>
        </el-descriptions>
        <el-table v-if="statusSnapshot.account.instances.length" :data="statusSnapshot.account.instances" size="small" class="mt8">
          <el-table-column label="#" width="46">
            <template #default="{ $index }">{{ $index + 1 }}</template>
          </el-table-column>
          <el-table-column label="方式" width="110">
            <template #default="{ row: instance }">{{ modeLabel(instance.connection_mode) }}</template>
          </el-table-column>
          <el-table-column label="数据库状态" width="130">
            <template #default="{ row: instance }"><StateTag :state="instance.status" /></template>
          </el-table-column>
          <el-table-column label="实时适配器" width="130">
            <template #default="{ row: instance }">
              <StateTag v-if="instance.live_health?.status" :state="String(instance.live_health.status)" />
              <span v-else class="muted">当前进程无适配器</span>
            </template>
          </el-table-column>
          <el-table-column label="身份验证" width="100">
            <template #default="{ row: instance }">
              <el-tag size="small" :type="instance.live_health?.identity_verified ? 'success' : 'info'">
                {{ instance.live_health?.identity_verified ? '已验证' : '未验证' }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="实时观测时间" min-width="150">
            <template #default="{ row: instance }">{{ formatTime(instance.live_health?.observed_at) }}</template>
          </el-table-column>
          <el-table-column label="心跳" width="110">
            <template #default="{ row: instance }">
              <span class="muted">{{ instance.live_health?.heartbeat_age_seconds == null ? '—' : `${instance.live_health.heartbeat_age_seconds} 秒` }}</span>
            </template>
          </el-table-column>
        </el-table>
        <el-empty v-else description="该账号还没有连接器实例。" :image-size="50" />
        <div class="row-actions status-actions">
          <el-button size="small" type="primary" plain @click="copyAccountStatus">复制脱敏状态</el-button>
          <span class="muted">不含账号名、QQ 号、实例名、地址、Token 或错误正文。</span>
        </div>
        <el-collapse class="mt8">
          <el-collapse-item title="查看原始 JSON（可能含 QQ 标识，请勿公开粘贴）" name="raw">
            <pre class="status-pre">{{ statusJson }}</pre>
          </el-collapse-item>
        </el-collapse>
      </template>
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
import { CONNECTOR_CONFIRMATIONS, confirmConnectorIdentity } from '@/api/connectors'
import type {
  Account,
  AccountStatusSnapshot,
  AdapterInstance,
  ConnectionDiagnostics as ConnectionDiagnosticsReport,
} from '@/api/types'
import ConnectionDiagnostics from '@/components/ConnectionDiagnostics.vue'
import PageHeader from '@/components/PageHeader.vue'
import StateTag from '@/components/StateTag.vue'
import { DELETE_PHRASE, typedConfirm } from '@/utils/confirmation'
import { accountStatusCopy, instanceActions, instanceStatusNextStep } from '@/utils/diagnostics'
import { formatTime } from '@/utils/format'
import { ElAlert, ElDivider, ElFormItem, ElInput, ElMessage, ElMessageBox, ElOption, ElSelect, ElSwitch } from 'element-plus'
import { useRouter } from 'vue-router'

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

const testResult = ref<ConnectionDiagnosticsReport | null>(null)
const testError = ref<string | null>(null)

const diagnosticsDialog = ref(false)
const diagnosticsLoading = ref(false)
const diagnosticsReport = ref<ConnectionDiagnosticsReport | null>(null)
const diagnosticsError = ref<string | null>(null)
const diagnosticsTitle = ref('测试并诊断')

const groupsDialog = ref(false)
const connectorGroups = ref<Array<{ platform_group_id: string; name: string | null }>>([])
const groupsContext = ref<{ account: Account; instance: AdapterInstance } | null>(null)
const importSelfUserId = ref('')

const router = useRouter()

function goConnectors(): void {
  void router.push('/connectors')
}

const statusDialog = ref(false)
const statusJson = ref('')
const statusSnapshot = ref<AccountStatusSnapshot | null>(null)
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
  testError.value = null
  createDialog.value = true
}

async function testConnection(): Promise<void> {
  testing.value = true
  testResult.value = null
  testError.value = null
  try {
    testResult.value = await api<ConnectionDiagnosticsReport>('/accounts/test-connection', {
      method: 'POST',
      body: instancePayload(form.instance),
      timeoutMs: 60_000,
    })
  } catch (err) {
    testError.value = errorMessage(err)
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
    ElMessage.success('已发起连接；只有身份验证通过后才会显示在线。')
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
  diagnosticsTitle.value = `测试并诊断 · ${instance.name}`
  diagnosticsReport.value = null
  diagnosticsError.value = null
  diagnosticsDialog.value = true
  diagnosticsLoading.value = true
  try {
    diagnosticsReport.value = await api<ConnectionDiagnosticsReport>(
      `/accounts/${account.id}/instances/${instance.id}/test`,
      { method: 'POST', body: {}, timeoutMs: 60_000 },
    )
  } catch (err) {
    diagnosticsError.value = errorMessage(err)
  } finally {
    diagnosticsLoading.value = false
  }
  await load()
}

async function fetchGroups(account: Account, instance: AdapterInstance): Promise<void> {
  try {
    const data = await api<{ groups: Array<{ platform_group_id: string; name: string | null }> }>(
      `/accounts/${account.id}/instances/${instance.id}/groups`,
    )
    connectorGroups.value = data.groups
    groupsContext.value = { account, instance }
    importSelfUserId.value = ''
    groupsDialog.value = true
  } catch (err) {
    ElMessage.error(errorMessage(err))
  }
}

async function confirmIdentity(account: Account, instance: AdapterInstance): Promise<void> {
  if (instance.connection_mode === 'mock' || instance.status !== 'online') return
  let userId: string
  try {
    const result = await ElMessageBox.prompt(
      '请输入当前登录的 QQ 号。后端会与在线适配器上报的身份核对；该确认不代表真实群收发已验证。',
      '确认登录身份',
      {
        confirmButtonText: '确认',
        cancelButtonText: '取消',
        inputPlaceholder: '当前登录 QQ 号',
        inputValidator: (value: string) => Boolean(value && value.trim()) || '请输入 QQ 号',
      },
    )
    userId = result.value.trim()
  } catch {
    return
  }
  try {
    await confirmConnectorIdentity(account.id, userId, CONNECTOR_CONFIRMATIONS.confirmIdentity)
    ElMessage.success('登录身份已确认；真实收发仍需独立验收。')
    await load()
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
      body: {
        account_id: context.account.id,
        instance_id: context.instance.id,
        confirm_self_user_id: importSelfUserId.value.trim(),
      },
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
    const data = await api<AccountStatusSnapshot>(`/accounts/${account.id}/status`)
    statusSnapshot.value = data
    statusJson.value = JSON.stringify(data, null, 2)
    statusDialog.value = true
  } catch (err) {
    ElMessage.error(errorMessage(err))
  }
}

async function copyAccountStatus(): Promise<void> {
  if (!statusSnapshot.value) return
  try {
    await navigator.clipboard.writeText(accountStatusCopy(statusSnapshot.value))
    ElMessage.success('已复制脱敏账号状态。')
  } catch (err) {
    ElMessage.error(`复制失败：${err instanceof Error ? err.message : String(err)}。请手动查看结构化字段。`)
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
  const confirmed = await typedConfirm(
    `删除账号「${account.display_name}」会永久删除其群配置、消息记录、记忆与发送队列，并清理不再被其他账号引用的媒体文件。连接器会先断开，此操作不可恢复。`,
    DELETE_PHRASE,
    '删除账号',
  )
  if (!confirmed) return
  try {
    await api(`/accounts/${account.id}`, { method: 'DELETE', query: { confirm: DELETE_PHRASE } })
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

.instance-state {
  margin: 8px 12px;
  padding: 8px 10px;
  border-radius: 6px;
  background: var(--app-surface);
}

.state-line {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  margin: 2px 0;
  font-size: 13px;
}

.instance-mock-note {
  padding: 0 12px 8px;
}

.diagnostics-body {
  min-height: 120px;
  display: flex;
  flex-direction: column;
  gap: 10px;
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

.mt8 {
  margin-top: 8px;
}

.status-actions {
  margin-top: 10px;
  align-items: center;
}

.identity-hint {
  margin-top: 8px;
  font-size: 12px;
}
</style>

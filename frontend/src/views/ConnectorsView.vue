<template>
  <div class="page">
    <PageHeader
      title="连接器"
      description="在本机管理 NapCat 等 OneBot 11 连接器：下载、校验、解压、运行官方安装器、启动/停止、写配置与回滚。平台不接触 QQ 密码，也不会静默执行第三方程序。"
    >
      <template #actions>
        <el-button :loading="loading" @click="load">刷新</el-button>
        <el-button :loading="scanning" @click="scan">重新扫描</el-button>
        <el-button @click="openImportDialog">导入配置</el-button>
        <el-button v-if="desktopMode" @click="chooseDirectory">选择连接器目录</el-button>
        <el-button v-if="desktopMode" @click="openConnectorsFolder">打开连接器目录</el-button>
        <el-button @click="goAdvanced">高级手动设置</el-button>
      </template>
    </PageHeader>

    <el-alert
      type="info"
      show-icon
      :closable="false"
      title="首次接入建议使用自动配置：无需手动填写 WebSocket/HTTP 地址或端口"
      description="接入向导会为受管、版本兼容的 NapCat 自动分配本机回环端口、生成随机 Token 并创建受管账号；随后仍需你自行完成 QQ 登录与身份确认。"
    >
      <el-button size="small" @click="router.push('/onboarding')">打开接入向导</el-button>
    </el-alert>
    <el-alert
      type="warning"
      show-icon
      :closable="false"
      title="安装包已解压 ≠ 已安装 ≠ 安装器完成 ≠ 已登录 ≠ 身份已验证 ≠ 真实收发"
      description="只有身份确认之后同时观察到真实入站消息与成功出站记录，才会显示「观察到真实双向收发」。诊断、进程存活与 WebSocket 在线都不能替代该证据。"
    />
    <el-alert
      type="info"
      show-icon
      :closable="false"
      title="所有连接器接口仅允许本机回环访问"
      description="即使开启远程管理，浏览器/其他设备也不能访问本页面接口。高风险动作需要输入确认词，平台不会自动启动安装器或连接器。"
    />

    <el-alert v-if="desktopMode" type="info" show-icon :closable="false" :title="desktopDirHint">
      <template #default>
        <span class="mono">{{ desktopConnectorsDir || '使用仓库默认 connectors/napcat' }}</span>
      </template>
    </el-alert>
    <el-alert v-else type="info" show-icon :closable="false" :title="desktopDirHint" />
    <el-alert v-if="error" type="error" show-icon :closable="false" :title="error" />

    <div v-if="capabilities" class="card capability-card">
      <div class="card-title">本机能力与边界</div>
      <div class="capability-tags">
        <el-tag v-for="(enabled, key) in capabilities.supports" :key="key" size="small" :type="enabled ? 'success' : 'info'">
          {{ supportLabel(String(key)) }}：{{ enabled ? '可用' : '不支持' }}
        </el-tag>
        <el-tag size="small" type="warning">真实 QQ 收发：未验证</el-tag>
        <el-tag size="small" :type="capabilities.root_exists ? 'success' : 'info'">
          连接器根目录：{{ capabilities.root_exists ? '存在' : '不存在（安装时创建）' }}
        </el-tag>
      </div>
      <ul class="note-list">
        <li v-for="note in capabilities.notes" :key="note">{{ note }}</li>
      </ul>
      <el-alert v-if="summary?.staging_orphans.length" type="warning" show-icon :closable="false"
        :title="`检测到残留暂存目录：${summary.staging_orphans.join('、')}。平台不会自动删除，请确认后手动处理。`" />
    </div>

    <div class="card">
      <div class="card-title">下载与版本查询</div>
      <div class="inline-row">
        <el-select v-model="installVersion" clearable placeholder="最新稳定版（不指定版本）" style="min-width: 260px">
          <el-option v-for="item in releases" :key="item.version" :label="releaseLabel(item)" :value="item.version" />
        </el-select>
        <el-button :loading="checkingRelease" @click="checkLatest">检查最新版</el-button>
        <el-button :loading="loadingReleases" @click="loadReleases">查询版本列表</el-button>
        <el-button type="primary" :disabled="!capabilities?.supports.download_verify_extract" @click="installConnector">
          下载、校验并解压
        </el-button>
      </div>
      <div class="muted small">
        下载/校验/解压成功只代表安装包已就绪。后端不会传 <span class="mono">--launch</span>，也不会自动运行安装器。
        <span v-if="latestRelease" class="inline-strong">最新版本：{{ latestRelease.version }}</span>
      </div>

      <div v-if="job" class="job-panel">
        <div class="job-head">
          <span>安装任务 <span class="mono">{{ job.id }}</span></span>
          <el-tag size="small" :type="jobTag(job.state)">{{ job.state }}</el-tag>
        </div>
        <el-progress :percentage="job.progress" :status="job.state === 'failed' ? 'exception' : job.state === 'succeeded' ? 'success' : undefined" />
        <div class="muted small">{{ jobProgressText(job) }}</div>
        <div v-if="job.error_message" class="error-text">{{ job.error_code }} · {{ job.error_message }}</div>
        <div class="inline-row">
          <el-button size="small" :disabled="!jobCanCancel(job)" @click="cancelJob">取消任务</el-button>
          <el-button size="small" @click="pollJob(job.id)">刷新任务</el-button>
        </div>
        <pre v-if="job.log_tail" class="log-tail">{{ job.log_tail }}</pre>
      </div>

      <el-table v-if="recentJobs.length" :data="recentJobs" size="small" class="recent-jobs">
        <el-table-column prop="version" label="版本" width="110" />
        <el-table-column prop="state" label="状态" width="110" />
        <el-table-column label="进度" min-width="200">
          <template #default="{ row }">{{ jobProgressText(row) }}</template>
        </el-table-column>
        <el-table-column prop="created_at" label="创建时间" width="190" />
      </el-table>
    </div>

    <el-empty v-if="!loading && !installations.length" description="尚未检测到连接器；选择版本下载或导入已有配置。" />

    <el-card v-for="item in installations" :key="item.id" class="connector-card" shadow="never">
      <template #header>
        <div class="connector-head">
          <div>
            <strong>{{ item.display_name }} · {{ item.version }}</strong>
            <el-tag size="small" class="ml8" :type="connectorStateTag(item.state.state)">{{ connectorStateLabel(item.state.state) }}</el-tag>
            <el-tag v-if="item.active" size="small" type="primary" class="ml8">活动版本</el-tag>
            <el-tag v-if="item.managed" size="small" type="info" class="ml8">受管</el-tag>
            <el-tag v-else size="small" type="warning" class="ml8">外部 / 只读</el-tag>
            <el-tag v-if="item.state.inferred" size="small" type="warning" class="ml8">推断状态</el-tag>
            <el-tag v-if="isRealTrafficVerified(item)" size="small" type="success" class="ml8">真实双向收发</el-tag>
          </div>
          <div class="muted small">观测：{{ formatTime(item.last_seen_at) }}</div>
        </div>
      </template>

      <el-alert
        :type="item.state.severity === 'error' ? 'error' : item.state.severity === 'warning' ? 'warning' : 'info'"
        :title="connectorStateLabel(item.state.state)"
        :description="connectorStateNote(item.state.state)"
        show-icon
        :closable="false"
      />

      <el-descriptions :column="2" size="small" border class="mt12">
        <el-descriptions-item label="来源">{{ item.source }}</el-descriptions-item>
        <el-descriptions-item label="布局置信度">{{ item.layout_confidence }}</el-descriptions-item>
        <el-descriptions-item label="版本兼容性">{{ item.version_compatibility }}</el-descriptions-item>
        <el-descriptions-item label="自动写配置">{{ item.auto_configure_allowed ? `仅 ${item.documented_config_version}` : '不允许' }}</el-descriptions-item>
        <el-descriptions-item label="安装包路径" :span="2"><span class="mono">{{ item.root_path }}</span></el-descriptions-item>
        <el-descriptions-item label="Shell 路径" :span="2"><span class="mono">{{ item.shell_path || '未安装 shell' }}</span></el-descriptions-item>
        <el-descriptions-item label="进程">{{ connectorProcessText(item) }}</el-descriptions-item>
        <el-descriptions-item label="安装器">{{ connectorInstallerText(item) }}</el-descriptions-item>
        <el-descriptions-item label="端口">
          {{ item.ports.length ? item.ports.join(', ') : '未探测' }}
          <span v-if="item.port_listening" class="error-text">（有端口在监听）</span>
        </el-descriptions-item>
        <el-descriptions-item label="许可证">{{ licenseText(item.license) }}</el-descriptions-item>
      </el-descriptions>

      <div class="mt12">
        <div class="muted small">证据与下一步</div>
        <ul class="evidence-list">
          <li v-for="(evidence, index) in item.state.evidence" :key="`${evidence.source}-${index}`">
            <span class="mono">{{ evidence.source }}</span>
            <span>{{ evidence.detail }}</span>
            <span class="muted">{{ formatTime(evidence.observed_at) }}</span>
          </li>
        </ul>
        <ul class="note-list">
          <li v-for="step in connectorStateNextSteps(item)" :key="step">{{ step }}</li>
        </ul>
      </div>

      <div class="action-row">
        <el-button
          size="small"
          :disabled="!item.can_run_installer || paused"
          @click="runInstaller(item)"
        >运行官方安装器</el-button>
        <el-button size="small" type="primary" :disabled="!item.can_start || paused" @click="startConnector(item)">启动连接器</el-button>
        <el-button size="small" type="danger" plain :disabled="!item.can_stop" @click="stopConnector(item)">停止本会话进程</el-button>
        <el-button size="small" :disabled="!item.shell_installed" @click="openConfigPreview(item)">配置预览与写入</el-button>
        <el-button size="small" @click="openSnapshots(item)">配置快照</el-button>
        <el-button size="small" :disabled="!item.can_activate" @click="activateVersion(item)">设为活动版本</el-button>
      </div>
      <div v-if="paused" class="muted small mt8">全局紧急暂停中：启动、安装器与写配置均被禁止。</div>

      <el-divider content-position="left">连接与诊断</el-divider>
      <div v-if="item.instance" class="instance-block">
        <div class="inline-row">
          <el-tag size="small">{{ item.instance.name }}</el-tag>
          <el-tag size="small" :type="item.instance.status === 'online' ? 'warning' : 'info'">{{ item.instance.status }}</el-tag>
          <span class="mono small">{{ item.instance.endpoint || '—' }}</span>
          <span v-if="item.instance.api_endpoint" class="mono small muted">{{ item.instance.api_endpoint }}</span>
          <span class="muted small">Token：{{ item.instance.token_masked || '未配置' }}</span>
        </div>
        <div class="inline-row mt8">
          <el-tag v-if="item.instance.identity_confirmed_at" size="small" type="warning">
            身份已确认：{{ item.instance.identity_confirmed_user_id }} · {{ formatTime(item.instance.identity_confirmed_at) }}
          </el-tag>
          <el-tag v-else size="small" type="warning">身份未确认</el-tag>
          <el-button size="small" :disabled="!['disconnected', 'offline', 'unconfigured', 'error', 'connected_unverified'].includes(item.instance.status)" @click="connectInstance(item)">连接实例</el-button>
          <el-button size="small" :disabled="!['online', 'connected_unverified', 'reconnecting'].includes(item.instance.status)" @click="disconnectInstance(item)">断开实例</el-button>
          <el-button size="small" :disabled="!item.can_diagnose" @click="diagnose(item)">测试并诊断</el-button>
          <el-button size="small" :disabled="item.instance.status !== 'online'" @click="openIdentity(item)">确认登录身份</el-button>
          <el-button size="small" :disabled="item.instance.status !== 'online' || !item.instance.identity_confirmed_at" @click="goGroups">前往群聊管理</el-button>
        </div>
        <div class="muted small mt8">
          诊断只验证连接与身份，不发送消息；实例已在线时复用现有适配器，未在线时会临时建连，
          可能受连接器单连接限制。即使诊断通过，真实群收发仍需在受控群人工验收。
        </div>
      </div>
      <div v-else class="muted small">尚未关联账号实例。请先写入配置，或使用「配置导入 / 高级手动设置」接入。</div>
    </el-card>

    <el-dialog v-model="installDialog" title="下载与解压连接器" width="620px" :close-on-click-modal="false">
      <el-alert type="warning" show-icon :closable="false" title="将执行固定安装脚本：下载官方 Release、校验 SHA-256 并安全解压。不会运行安装器。" />
      <p>目标版本：<span class="mono">{{ installVersion || '最新稳定版' }}</span></p>
      <p class="muted">确认词：<span class="mono">INSTALL</span></p>
      <el-input v-model="confirmInput" placeholder="请输入 INSTALL" />
      <template #footer>
        <el-button @click="installDialog = false">取消</el-button>
        <el-button type="primary" :disabled="!confirmationMatches(confirmInput, CONNECTOR_CONFIRMATIONS.install)" @click="doInstall">开始任务</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="configDialog" title="配置预览" width="760px">
      <div v-loading="configLoading">
        <el-alert v-if="configError" type="error" :title="configError" show-icon :closable="false" />
        <template v-if="preview">
          <el-alert
            v-if="!preview.can_apply"
            type="warning"
            show-icon
            :closable="false"
            title="当前不能写入配置"
            :description="preview.reasons.join('；')"
          />
          <el-descriptions :column="2" size="small" border class="mt12">
            <el-descriptions-item label="目标文件"><span class="mono">{{ preview.target_file || '—' }}</span></el-descriptions-item>
            <el-descriptions-item label="目标已存在">{{ preview.target_exists ? '是（将先快照）' : '否（将创建）' }}</el-descriptions-item>
            <el-descriptions-item label="计划 HTTP 端口">{{ preview.planned_ports.http ?? '—' }}</el-descriptions-item>
            <el-descriptions-item label="计划 WebSocket 端口">{{ preview.planned_ports.websocket ?? '—' }}</el-descriptions-item>
            <el-descriptions-item label="Token">{{ preview.token_masked }}</el-descriptions-item>
            <el-descriptions-item label="进程已停止">{{ preview.process_stopped ? '是' : '否' }}</el-descriptions-item>
            <el-descriptions-item label="保留根字段" :span="2"><span class="mono">{{ preview.preserved_root_keys.join(', ') || '—' }}</span></el-descriptions-item>
          </el-descriptions>
          <div class="inline-row mt12">
            <el-select v-model="requestedRelative" clearable placeholder="自动选择配置目标" style="min-width: 240px">
              <el-option v-for="file in preview.available_files" :key="file.relative_path" :label="file.relative_path" :value="file.relative_path" :disabled="!file.parseable" />
            </el-select>
            <el-button @click="loadPreview(itemForConfig, requestedRelative)">重新预览</el-button>
          </div>
          <ul class="note-list">
            <li v-for="note in preview.notes" :key="note">{{ note }}</li>
          </ul>
          <el-input v-model="confirmInput" placeholder="输入 WRITE CONFIG 以写入" class="mt12" />
        </template>
      </div>
      <template #footer>
        <el-button @click="configDialog = false">关闭</el-button>
        <el-button
          type="primary"
          :loading="configApplying"
          :disabled="!preview?.can_apply || !confirmationMatches(confirmInput, CONNECTOR_CONFIRMATIONS.applyConfig)"
          @click="applyConfig"
        >快照并写入配置</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="snapshotDialog" title="加密配置快照" width="720px">
      <el-alert type="info" show-icon :closable="false" title="接口只返回摘要，不返回配置正文或 Token。恢复会同时写回关联实例的加密 Token。" />
      <el-empty v-if="!snapshots.length" description="应用配置后才创建加密快照。" :image-size="55" />
      <el-table v-else :data="snapshots" size="small" max-height="360">
        <el-table-column prop="snapshot_group" label="快照组" width="150" />
        <el-table-column prop="relative_path" label="文件" min-width="170" />
        <el-table-column prop="reason" label="原因" width="110" />
        <el-table-column label="创建" width="170">
          <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
        </el-table-column>
        <el-table-column label="恢复" width="100">
          <template #default="{ row }">
            <el-button size="small" :disabled="!row.restorable" @click="restoreSnapshot(row)">恢复</el-button>
          </template>
        </el-table-column>
      </el-table>
      <template #footer><el-button @click="snapshotDialog = false">关闭</el-button></template>
    </el-dialog>

    <el-dialog v-model="diagnosticsDialog" title="连接器诊断" width="900px">
      <div v-loading="diagnosticsLoading">
        <el-alert v-if="diagnosticsError" type="error" :title="diagnosticsError" show-icon :closable="false" />
        <el-alert
          v-if="diagnosticsReport"
          type="info"
          show-icon
          :closable="false"
          :title="diagnosticsReport.note"
          :description="`来源：${diagnosticsReport.diagnostic_source}；复用在线适配器：${diagnosticsReport.reused_live_adapter ? '是' : '否'}；是否发送消息：${diagnosticsReport.message_send_attempted ? '是' : '否'}`"
        />
        <ConnectionDiagnosticsPanel v-if="diagnosticsReport" :report="diagnosticsReport" />
      </div>
      <template #footer><el-button @click="diagnosticsDialog = false">关闭</el-button></template>
    </el-dialog>

    <el-dialog v-model="identityDialog" title="确认登录身份" width="520px">
      <el-alert type="warning" show-icon :closable="false" title="确认身份不会验证真实收发；它只记录当前在线连接器返回的登录 QQ 号。" />
      <el-input v-model="identityUserId" placeholder="当前登录的 QQ 号" maxlength="128" class="mt12" />
      <el-input v-model="confirmInput" placeholder="输入 CONFIRM IDENTITY" class="mt12" />
      <template #footer>
        <el-button @click="identityDialog = false">取消</el-button>
        <el-button type="primary" :disabled="!identityUserId.trim() || !confirmationMatches(confirmInput, CONNECTOR_CONFIRMATIONS.confirmIdentity)" @click="confirmIdentity">确认身份</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="importDialog" title="导入 OneBot 11 配置（只读）" width="680px">
      <el-alert type="info" show-icon :closable="false" title="仅解析本机/私网已启用的 WebSocket 服务；不会修改外部文件，Token 加密保存并只返回掩码。" />
      <input type="file" accept="application/json,.json" class="mt12" @change="readConfigFile" />
      <el-input v-model="importText" type="textarea" :rows="8" class="mt8" placeholder="或粘贴 onebot11.json 内容（≤128 KiB）" />
      <el-input v-model="importName" placeholder="显示名称（可选）" maxlength="128" class="mt8" />
      <el-input v-model="confirmInput" placeholder="输入 IMPORT CONFIG" class="mt8" />
      <template #footer>
        <el-button @click="importDialog = false">取消</el-button>
        <el-button type="primary" :disabled="!importText.trim() || !confirmationMatches(confirmInput, CONNECTOR_CONFIRMATIONS.importConfig)" @click="importConfig">导入</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'

import { api, errorMessage } from '@/api/client'
import {
  CONNECTOR_CONFIRMATIONS,
  activateConnectorVersion,
  applyConnectorConfig,
  cancelConnectorJob,
  checkConnectorRelease,
  confirmConnectorIdentity,
  connectorCapabilities as fetchCapabilities,
  connectorSnapshots,
  connectorSummary,
  diagnoseConnector,
  importConnectorConfig,
  listConnectorReleases,
  previewConnectorConfig,
  rollbackConnectorConfig,
  runConnectorInstaller,
  scanConnectors,
  startConnectorInstall,
  startManagedConnector,
  stopManagedConnector,
  getConnectorJob,
} from '@/api/connectors'
import {
  chooseDesktopConnectorsDir,
  getDesktopSettings,
  isDesktop,
  openDesktopConnectorsFolder,
} from '@/api/desktop'
import type {
  ConnectorCapabilities,
  ConnectorConfigPreview,
  ConnectorInstallation,
  ConnectorJob,
  ConnectorRelease,
  ConnectorSnapshot,
  ConnectorSummary,
  ConnectionDiagnostics as ConnectionDiagnosticsReport,
} from '@/api/types'
import ConnectionDiagnosticsPanel from '@/components/ConnectionDiagnostics.vue'
import PageHeader from '@/components/PageHeader.vue'
import {
  confirmationMatches,
  connectorInstallerText,
  connectorProcessText,
  connectorStateLabel,
  connectorStateNextSteps,
  connectorStateNote,
  connectorStateTag,
  desktopConnectorDirHint,
  isRealTrafficVerified,
  jobCanCancel,
  jobProgressText,
  licenseText,
} from '@/utils/connectors'
import { formatBytes, formatTime } from '@/utils/format'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useRouter } from 'vue-router'

const router = useRouter()
const desktopMode = isDesktop()
const desktopDirHint = desktopConnectorDirHint(desktopMode)
const desktopConnectorsDir = ref('')

const loading = ref(false)
const scanning = ref(false)
const error = ref<string | null>(null)
const summary = ref<ConnectorSummary | null>(null)
const capabilities = ref<ConnectorCapabilities | null>(null)
const paused = computed(() => summary.value?.global_pause.paused === true)
const installations = computed(() => summary.value?.installations ?? [])
const recentJobs = computed(() => summary.value?.recent_jobs ?? [])

const releases = ref<ConnectorRelease[]>([])
const loadingReleases = ref(false)
const checkingRelease = ref(false)
const latestRelease = ref<ConnectorRelease | null>(null)
const installVersion = ref('')

const installDialog = ref(false)
const confirmInput = ref('')

const job = ref<ConnectorJob | null>(null)
let jobTimer: ReturnType<typeof setInterval> | null = null

const configDialog = ref(false)
const configLoading = ref(false)
const configApplying = ref(false)
const configError = ref<string | null>(null)
const preview = ref<ConnectorConfigPreview | null>(null)
const requestedRelative = ref('')
const itemForConfig = ref('')

const snapshotDialog = ref(false)
const snapshots = ref<ConnectorSnapshot[]>([])
const itemForSnapshots = ref('')

const diagnosticsDialog = ref(false)
const diagnosticsLoading = ref(false)
const diagnosticsError = ref<string | null>(null)
interface ConnectorDiagnosticsReport extends ConnectionDiagnosticsReport {
  reused_live_adapter?: boolean
  diagnostic_source?: string
}

const diagnosticsReport = ref<ConnectorDiagnosticsReport | null>(null)

const identityDialog = ref(false)
const identityUserId = ref('')
const itemForIdentity = ref<ConnectorInstallation | null>(null)

const importDialog = ref(false)
const importText = ref('')
const importName = ref('')

function supportLabel(key: string): string {
  const labels: Record<string, string> = {
    detect: '检测安装',
    download_verify_extract: '下载/校验/解压',
    run_official_installer: '运行官方安装器',
    start_stop_managed_process: '受管进程控制',
    automatic_config: '自动写配置',
    rollback_config: '配置回滚',
    import_config: '配置导入',
    in_place_upgrade: '原地升级',
    auto_update: '自动更新',
    uninstall_or_delete: '卸载/删除',
    remote_management: '远程管理',
  }
  return labels[key] ?? key
}

function releaseLabel(item: ConnectorRelease): string {
  const size = item.size ? ` · ${formatBytes(item.size)}` : ''
  return `${item.version}${item.auto_configure_allowed ? ' · 可自动配置' : ' · 需手动配置'}${size}`
}

function jobTag(state: string): 'success' | 'danger' | 'warning' | 'info' {
  if (state === 'succeeded') return 'success'
  if (state === 'failed') return 'danger'
  if (state === 'interrupted' || state === 'cancelled') return 'warning'
  return 'info'
}

async function load(): Promise<void> {
  loading.value = true
  error.value = null
  try {
    const [nextSummary, nextCapabilities] = await Promise.all([connectorSummary(), fetchCapabilities()])
    summary.value = nextSummary
    capabilities.value = nextCapabilities
    if (!job.value) {
      const active = nextSummary.recent_jobs.find((entry) => ['queued', 'running'].includes(entry.state))
      if (active) pollJob(active.id)
    }
  } catch (err) {
    error.value = errorMessage(err)
  } finally {
    loading.value = false
  }
}

async function scan(): Promise<void> {
  scanning.value = true
  try {
    const result = await scanConnectors()
    ElMessage.success(`扫描完成：检测到 ${result.count} 项。`)
    await load()
  } catch (err) {
    ElMessage.error(errorMessage(err))
  } finally {
    scanning.value = false
  }
}

async function chooseDirectory(): Promise<void> {
  try {
    const result = await chooseDesktopConnectorsDir()
    if (result.canceled) return
    desktopConnectorsDir.value = result.settings.connectorsDir || ''
    ElMessage.success(
      result.settings.connectorsDir
        ? '连接器目录已保存；请重启后端后生效。'
        : '已恢复默认连接器目录；请重启后端后生效。',
    )
  } catch (err) {
    ElMessage.error(errorMessage(err))
  }
}

async function loadDesktopDirectory(): Promise<void> {
  if (!desktopMode) return
  try {
    const settings = await getDesktopSettings()
    desktopConnectorsDir.value = settings.connectorsDir || ''
  } catch {
    // 桌面桥接不可用时保持空值，不伪造目录。
  }
}

async function openConnectorsFolder(): Promise<void> {
  try {
    await openDesktopConnectorsFolder()
  } catch (err) {
    ElMessage.error(errorMessage(err))
  }
}

async function loadReleases(): Promise<void> {
  loadingReleases.value = true
  try {
    const result = await listConnectorReleases()
    releases.value = result.items
    ElMessage.success(`已查询 ${result.items.length} 个可用版本；不会自动下载。`)
  } catch (err) {
    ElMessage.error(errorMessage(err))
  } finally {
    loadingReleases.value = false
  }
}

async function checkLatest(): Promise<void> {
  checkingRelease.value = true
  try {
    latestRelease.value = await checkConnectorRelease()
    ElMessage.success(`最新版本：${latestRelease.value.version}`)
  } catch (err) {
    ElMessage.error(errorMessage(err))
  } finally {
    checkingRelease.value = false
  }
}

function installConnector(): void {
  confirmInput.value = ''
  installDialog.value = true
}

async function doInstall(): Promise<void> {
  try {
    job.value = await startConnectorInstall(installVersion.value || null, confirmInput.value.trim())
    installDialog.value = false
    ElMessage.success('安装任务已创建；下载/校验/解压完成不等于已安装。')
    pollJob(job.value.id)
    await load()
  } catch (err) {
    ElMessage.error(errorMessage(err))
  }
}

function stopPolling(): void {
  if (jobTimer !== null) {
    clearInterval(jobTimer)
    jobTimer = null
  }
}

async function pollJob(jobId: string): Promise<void> {
  stopPolling()
  const tick = async (): Promise<void> => {
    try {
      job.value = await getConnectorJob(jobId)
      if (!['queued', 'running'].includes(job.value.state)) {
        stopPolling()
        await load()
      }
    } catch (err) {
      stopPolling()
      error.value = errorMessage(err)
    }
  }
  await tick()
  if (['queued', 'running'].includes(job.value?.state ?? '')) {
    jobTimer = setInterval(() => void tick(), 1000)
  }
}

async function cancelJob(): Promise<void> {
  const current = job.value
  if (!current) return
  try {
    job.value = await cancelConnectorJob(current.id, CONNECTOR_CONFIRMATIONS.cancel)
    ElMessage.success('已请求取消任务。')
    stopPolling()
    await load()
  } catch (err) {
    ElMessage.error(errorMessage(err))
  }
}

async function promptAction(
  title: string,
  message: string,
  word: string,
  action: (input: string) => Promise<unknown>,
  success: string,
): Promise<void> {
  let input: string
  try {
    const result = await ElMessageBox.prompt(message, title, {
      confirmButtonText: '确认',
      cancelButtonText: '取消',
      inputPlaceholder: word,
      inputValidator: (value: string) => confirmationMatches(value, word) || `请输入确认词：${word}`,
    })
    input = result.value
  } catch {
    return
  }
  try {
    await action(input.trim())
    ElMessage.success(success)
    await load()
  } catch (err) {
    ElMessage.error(errorMessage(err))
  }
}

function runInstaller(item: ConnectorInstallation): void {
  void promptAction(
    '运行官方安装器',
    '安装器是交互式第三方程序，会在可见控制台运行；平台不会代你完成安装或登录。',
    CONNECTOR_CONFIRMATIONS.runInstaller,
    (input) => runConnectorInstaller(item.id, input),
    '已启动安装器；完成后请重新扫描。',
  )
}

function startConnector(item: ConnectorInstallation): void {
  void promptAction(
    '启动连接器',
    '将启动受管安装内的 napcat.bat（经固定 cmd.exe 参数）。登录 QQ 由你在其窗口内完成。',
    CONNECTOR_CONFIRMATIONS.start,
    (input) => startManagedConnector(item.id, input),
    '已启动连接器；进程存活不代表已登录。',
  )
}

function stopConnector(item: ConnectorInstallation): void {
  void promptAction(
    '停止连接器',
    '只会停止本会话拥有且仍在运行的进程树；不会按端口或进程名强杀其他程序。',
    CONNECTOR_CONFIRMATIONS.stop,
    (input) => stopManagedConnector(item.id, input),
    '已停止本会话进程。',
  )
}

function activateVersion(item: ConnectorInstallation): void {
  void promptAction(
    '切换活动版本',
    '只切换数据库活动指针，不删除旧版本；旧版本进程必须已停止。',
    CONNECTOR_CONFIRMATIONS.switchVersion,
    (input) => activateConnectorVersion(item.id, input),
    '已切换活动版本。',
  )
}

async function loadPreview(installationId: string, requested: string): Promise<void> {
  configLoading.value = true
  configError.value = null
  try {
    preview.value = await previewConnectorConfig(installationId, requested || null)
  } catch (err) {
    configError.value = errorMessage(err)
  } finally {
    configLoading.value = false
  }
}

async function openConfigPreview(item: ConnectorInstallation): Promise<void> {
  itemForConfig.value = item.id
  requestedRelative.value = ''
  preview.value = null
  configError.value = null
  confirmInput.value = ''
  configDialog.value = true
  await loadPreview(item.id, '')
}

async function applyConfig(): Promise<void> {
  configApplying.value = true
  try {
    await applyConnectorConfig(itemForConfig.value, requestedRelative.value, confirmInput.value.trim())
    ElMessage.success('配置已写入并创建关联实例；实例默认不自动连接。')
    configDialog.value = false
    await load()
  } catch (err) {
    ElMessage.error(errorMessage(err))
  } finally {
    configApplying.value = false
  }
}

async function openSnapshots(item: ConnectorInstallation): Promise<void> {
  itemForSnapshots.value = item.id
  snapshotDialog.value = true
  try {
    const result = await connectorSnapshots(item.id)
    snapshots.value = result.items
  } catch (err) {
    snapshots.value = []
    ElMessage.error(errorMessage(err))
  }
}

function restoreSnapshot(row: ConnectorSnapshot): void {
  void promptAction(
    '恢复配置快照',
    `将恢复 ${row.relative_path}，并同步写回快照中的加密 Token。连接器必须已停止。`,
    CONNECTOR_CONFIRMATIONS.restoreConfig,
    (input) => rollbackConnectorConfig(itemForSnapshots.value, row.snapshot_group, input),
    '已恢复配置；请重新连接并诊断。',
  )
}

async function diagnose(item: ConnectorInstallation): Promise<void> {
  diagnosticsDialog.value = true
  diagnosticsLoading.value = true
  diagnosticsError.value = null
  diagnosticsReport.value = null
  if (!item.instance) {
    diagnosticsError.value = '尚未关联实例；请先写入配置或导入配置。'
    diagnosticsLoading.value = false
    return
  }
  try {
    diagnosticsReport.value = (await diagnoseConnector(item.id)) as ConnectorDiagnosticsReport
  } catch (err) {
    diagnosticsError.value = errorMessage(err)
  } finally {
    diagnosticsLoading.value = false
    await load()
  }
}

async function connectInstance(item: ConnectorInstallation): Promise<void> {
  if (!item.instance) return
  try {
    await api(`/accounts/${item.instance.account_id}/instances/${item.instance.id}/connect`, { method: 'POST' })
    ElMessage.success('已发起连接；身份验证通过后才会显示在线。')
  } catch (err) {
    ElMessage.error(errorMessage(err))
  } finally {
    await load()
  }
}

async function disconnectInstance(item: ConnectorInstallation): Promise<void> {
  if (!item.instance) return
  try {
    await api(`/accounts/${item.instance.account_id}/instances/${item.instance.id}/disconnect`, { method: 'POST' })
    ElMessage.success('已断开实例。')
  } catch (err) {
    ElMessage.error(errorMessage(err))
  } finally {
    await load()
  }
}

function openIdentity(item: ConnectorInstallation): void {
  itemForIdentity.value = item
  identityUserId.value = item.instance?.identity_confirmed_user_id ?? ''
  confirmInput.value = ''
  identityDialog.value = true
}

async function confirmIdentity(): Promise<void> {
  const item = itemForIdentity.value
  if (!item?.instance) return
  try {
    await confirmConnectorIdentity(item.instance.account_id, identityUserId.value.trim(), confirmInput.value.trim())
    ElMessage.success('身份已确认；真实收发仍需独立验收。')
    identityDialog.value = false
    await load()
  } catch (err) {
    ElMessage.error(errorMessage(err))
  }
}

function goAdvanced(): void {
  void router.push('/accounts')
}

function goGroups(): void {
  void router.push('/groups')
}

function openImportDialog(): void {
  importText.value = ''
  importName.value = ''
  confirmInput.value = ''
  importDialog.value = true
}

async function readConfigFile(event: Event): Promise<void> {
  const file = (event.target as HTMLInputElement).files?.[0]
  if (!file) return
  if (file.size > 128 * 1024) {
    ElMessage.error('配置文件超过 128 KiB，拒绝导入。')
    return
  }
  try {
    importText.value = await file.text()
  } catch (err) {
    ElMessage.error(errorMessage(err))
  }
}

async function importConfig(): Promise<void> {
  try {
    await importConnectorConfig(importText.value, importName.value.trim(), confirmInput.value.trim())
    ElMessage.success('配置已导入（未验证）；请连接并诊断。')
    importDialog.value = false
    await load()
  } catch (err) {
    ElMessage.error(errorMessage(err))
  }
}

onMounted(async () => {
  await Promise.all([load(), loadDesktopDirectory()])
})

onBeforeUnmount(stopPolling)
</script>

<style scoped>
.card-title {
  font-weight: 700;
  margin-bottom: 10px;
}

.capability-card {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.capability-tags,
.inline-row,
.action-row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
}

.action-row {
  margin-top: 12px;
}

.note-list,
.evidence-list {
  margin: 8px 0 0;
  padding-left: 20px;
  color: var(--app-muted);
  font-size: 12px;
  line-height: 1.7;
}

.evidence-list li {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.connector-card {
  margin-bottom: 14px;
}

.connector-head {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
  align-items: center;
}

.job-panel {
  margin-top: 14px;
  padding: 12px;
  border-radius: 8px;
  background: var(--app-surface-soft);
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.job-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.log-tail {
  max-height: 160px;
  overflow: auto;
  margin: 0;
  padding: 8px;
  border-radius: 6px;
  background: rgba(11, 42, 91, 0.08);
  font-size: 12px;
  white-space: pre-wrap;
}

.recent-jobs {
  margin-top: 12px;
}

.small {
  font-size: 12px;
}

.mt8 {
  margin-top: 8px;
}

.mt12 {
  margin-top: 12px;
}

.ml8 {
  margin-left: 8px;
}

.inline-strong {
  margin-left: 10px;
  font-weight: 600;
}

.error-text {
  color: var(--el-color-danger);
}

.instance-block {
  padding: 10px 12px;
  border-radius: 8px;
  background: var(--app-surface-soft);
}
</style>

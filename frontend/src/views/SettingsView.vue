<template>
  <div class="page">
    <PageHeader
      title="系统设置"
      description="全局暂停、数据保留、备份恢复与安全状态。所有管理写操作都会写入本地审计日志；密钥不会显示明文。"
    >
      <template #actions>
        <el-button :loading="loading" @click="loadAll">刷新</el-button>
      </template>
    </PageHeader>

    <el-alert v-if="error" type="error" :title="error" show-icon :closable="false" />
    <el-alert
      v-if="settings?.security.allow_remote_admin"
      type="warning"
      show-icon
      :closable="false"
      title="已允许远程管理访问。"
      description="请确认已设置强管理 Token 并通过安全通道访问；默认仅允许本机管理。"
    />

    <el-tabs v-model="activeTab">
      <el-tab-pane label="基础与安全" name="general">
        <div class="grid grid-2">
          <div class="card">
            <div class="card-title">应用信息</div>
            <el-descriptions :column="1" border size="small">
              <el-descriptions-item label="应用">{{ settings?.app.name ?? '—' }}</el-descriptions-item>
              <el-descriptions-item label="版本">{{ settings?.app.version ?? '—' }}</el-descriptions-item>
              <el-descriptions-item label="环境">{{ settings?.app.env ?? '—' }}</el-descriptions-item>
              <el-descriptions-item label="API 前缀"><span class="mono">{{ settings?.app.api_prefix ?? '—' }}</span></el-descriptions-item>
              <el-descriptions-item label="后端就绪">
                <StateTag :state="appStore.ready ? 'available' : 'error'" :label="appStore.ready ? '就绪' : '异常'" />
              </el-descriptions-item>
            </el-descriptions>
          </div>

          <div class="card">
            <div class="card-title">安全状态</div>
            <el-descriptions :column="1" border size="small">
              <el-descriptions-item label="凭证加密密钥">
                <StateTag :state="settings?.security.credential_key_configured ? 'available' : 'unconfigured'" :label="settings?.security.credential_key_configured ? '已配置' : '未配置'" />
              </el-descriptions-item>
              <el-descriptions-item label="远程管理 Token">
                <StateTag :state="settings?.security.admin_token_configured ? 'available' : 'unconfigured'" :label="settings?.security.admin_token_configured ? '已配置' : '未配置'" />
              </el-descriptions-item>
              <el-descriptions-item label="允许远程管理">
                <StateTag :state="settings?.security.allow_remote_admin ? 'warning' : 'disabled'" :label="settings?.security.allow_remote_admin ? '已开启' : '未开启（推荐）'" />
              </el-descriptions-item>
              <el-descriptions-item label="CORS 来源">
                <span class="mono">{{ settings?.security.cors_origins.join('、') || '无' }}</span>
              </el-descriptions-item>
            </el-descriptions>
            <el-alert
              v-if="!settings?.security.credential_key_configured"
              class="mt"
              type="error"
              :closable="false"
              show-icon
              title="缺少 CREDENTIAL_ENCRYPTION_KEY，无法保存 Token / API Key。"
              description="请在 .env 中配置由 scripts/gen_keys.py 生成的密钥后重启后端。"
            />
          </div>
        </div>

        <div class="card">
          <div class="card-title">
            <span>全局紧急暂停</span>
            <StateTag :state="appStore.paused ? 'paused' : 'available'" :label="appStore.paused ? '暂停中' : '正常运行'" />
          </div>
          <p class="muted">
            暂停后所有账号停止自动回复，发送队列不会发送任何消息。该开关始终有效，优先级高于所有群级配置。
          </p>
          <div v-if="settings?.global_pause.paused" class="pause-info">
            <div>原因：{{ settings.global_pause.reason || '未填写' }}</div>
            <div class="muted">操作者：{{ settings.global_pause.actor || '—' }} · {{ formatTime(settings.global_pause.updated_at) }}</div>
            <el-button type="success" size="small" :loading="pausing" @click="resumeAll">恢复运行</el-button>
          </div>
          <div v-else class="row-actions">
            <el-input v-model="pauseReason" placeholder="暂停原因（写入审计）" style="width: 320px" maxlength="500" />
            <el-button type="danger" :loading="pausing" @click="pauseAll">启用紧急暂停</el-button>
          </div>
        </div>

        <div class="card">
          <div class="card-title">数据保留</div>
          <el-form label-width="190px" class="retention-form">
            <el-form-item label="消息保留天数">
              <el-input-number v-model="retention.message_retention_days" :min="1" :max="3650" />
            </el-form-item>
            <el-form-item label="日志保留天数">
              <el-input-number v-model="retention.log_retention_days" :min="1" :max="3650" />
            </el-form-item>
            <el-form-item label="媒体保留天数">
              <el-input-number v-model="retention.media_retention_days" :min="1" :max="3650" />
            </el-form-item>
            <el-form-item>
              <el-button type="primary" :loading="savingRetention" @click="saveRetention">保存保留策略</el-button>
              <span class="form-tip" style="margin-left: 10px">当前版本保存策略配置；自动清理任务会在后台按策略执行已实现的清理项。</span>
            </el-form-item>
          </el-form>
        </div>
      </el-tab-pane>

      <el-tab-pane label="备份与恢复" name="backups">
        <div class="card">
          <div class="card-title">
            <span>数据库备份</span>
            <div class="filter-line">
              <el-input v-model="backupNote" placeholder="备份备注（可选）" maxlength="500" style="width: 240px" />
              <el-button type="primary" :loading="creatingBackup" @click="createBackup">立即备份</el-button>
            </div>
          </div>
          <el-alert
            type="info"
            :closable="false"
            show-icon
            title="备份仅包含 SQLite 数据库，不包含媒体文件、日志和加密密钥。"
            description="凭证密文只有在使用同一 CREDENTIAL_ENCRYPTION_KEY 时才能解密。恢复前必须启用全局暂停。"
          />
          <el-table v-loading="loading" :data="backups" size="small">
            <el-table-column label="文件" min-width="240">
              <template #default="{ row }">
                <div class="mono">{{ row.filename }}</div>
                <div class="muted">{{ row.manifest?.note || '无备注' }}</div>
              </template>
            </el-table-column>
            <el-table-column label="大小" width="100">
              <template #default="{ row }">{{ formatBytes(row.size_bytes) }}</template>
            </el-table-column>
            <el-table-column label="状态" width="110">
              <template #default="{ row }"><StateTag :state="row.status" /></template>
            </el-table-column>
            <el-table-column label="创建时间" width="152">
              <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
            </el-table-column>
            <el-table-column label="SHA-256" width="170">
              <template #default="{ row }">
                <el-tooltip :content="row.sha256" placement="top">
                  <span class="mono">{{ truncate(row.sha256, 16) }}</span>
                </el-tooltip>
              </template>
            </el-table-column>
            <el-table-column label="操作" width="300" fixed="right">
              <template #default="{ row }">
                <div class="row-actions">
                  <el-button size="small" :loading="verifyingId === row.id" @click="verifyBackup(row)">校验</el-button>
                  <el-button size="small" @click="downloadBackup(row)">下载</el-button>
                  <el-button size="small" type="warning" plain @click="previewRestore(row)">恢复预览</el-button>
                  <el-button size="small" type="danger" text @click="deleteBackup(row)">删除</el-button>
                </div>
              </template>
            </el-table-column>
          </el-table>
          <el-empty v-if="!loading && !backups.length" description="还没有备份。建议在修改配置或升级前创建一次备份。" />
        </div>
      </el-tab-pane>

      <el-tab-pane label="隐私与数据" name="privacy">
        <div class="grid grid-2">
          <div class="card">
            <div class="card-title">本地数据概览</div>
            <el-table :data="privacyRows" size="small">
              <el-table-column prop="label" label="数据" width="180" />
              <el-table-column prop="count" label="数量" width="100" />
              <el-table-column prop="note" label="说明" />
            </el-table>
          </div>
          <div class="card">
            <div class="card-title">隐私说明</div>
            <ul class="privacy-notes">
              <li v-for="(note, index) in settings?.privacy.notes ?? []" :key="index">{{ note }}</li>
              <li>长期记忆只在显式开启的群内检索，且不会跨群读取；AI 候选提取可手动触发或在群内显式开启后台增量提取，结果都必须人工审核，批准前不会注入。</li>
              <li>人格成长默认隔离在当前群；跨群学习默认关闭。</li>
              <li>删除来源消息会清理对应特征证据，证据不足的稳定特征会降级。</li>
            </ul>
          </div>
        </div>
      </el-tab-pane>

      <el-tab-pane label="审计日志" name="audit">
        <div class="card">
          <div class="filter-bar">
            <el-input v-model="auditAction" placeholder="动作前缀，例如 persona / backup" clearable style="width: 240px" />
            <el-select v-model="auditTargetType" placeholder="目标类型" clearable style="width: 180px">
              <el-option label="账号" value="account" />
              <el-option label="群" value="group" />
              <el-option label="人格" value="persona" />
              <el-option label="Provider" value="llm_provider" />
              <el-option label="备份" value="backup" />
              <el-option label="系统设置" value="system_settings" />
              <el-option label="工具" value="tool" />
              <el-option label="插件" value="plugin_registry" />
              <el-option label="预算策略" value="budget_policy" />
              <el-option label="模型用量" value="llm_usage" />
            </el-select>
            <el-button type="primary" @click="loadAudit(1)">查询</el-button>
          </div>
          <el-table v-loading="auditLoading" :data="audit" size="small">
            <el-table-column label="时间" width="152">
              <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
            </el-table-column>
            <el-table-column prop="actor" label="操作者" width="130" />
            <el-table-column prop="action" label="动作" min-width="180">
              <template #default="{ row }"><span class="mono">{{ row.action }}</span></template>
            </el-table-column>
            <el-table-column label="目标" min-width="180">
              <template #default="{ row }">
                <span class="muted">{{ row.target_type }}</span>
                <span v-if="row.target_id" class="mono"> · {{ truncate(row.target_id, 24) }}</span>
              </template>
            </el-table-column>
            <el-table-column label="请求 ID" width="150">
              <template #default="{ row }"><span class="mono">{{ truncate(row.request_id, 16) }}</span></template>
            </el-table-column>
            <el-table-column type="expand">
              <template #default="{ row }">
                <pre class="audit-pre">{{ JSON.stringify(row.details, null, 2) }}</pre>
              </template>
            </el-table-column>
          </el-table>
          <el-empty v-if="!auditLoading && !audit.length" description="没有匹配的审计记录。" />
          <div class="pager">
            <el-pagination
              v-model:current-page="auditPage"
              v-model:page-size="auditPageSize"
              :total="auditTotal"
              :page-sizes="[20, 50, 100]"
              layout="total, sizes, prev, pager, next"
              @current-change="loadAudit()"
              @size-change="loadAudit(1)"
            />
          </div>
        </div>
      </el-tab-pane>
    </el-tabs>

    <el-dialog v-model="restoreDialog" title="恢复预览" width="660px" :close-on-click-modal="false">
      <template v-if="restorePreview">
        <el-alert
          :type="restorePreview.verification.checksum_ok && restorePreview.verification.integrity_ok ? 'success' : 'error'"
          :closable="false"
          show-icon
          :title="restorePreview.verification.checksum_ok && restorePreview.verification.integrity_ok ? '备份校验通过' : '备份校验失败，不能恢复'"
        />
        <el-descriptions :column="2" border size="small" class="mt">
          <el-descriptions-item label="文件">{{ restorePreview.backup.filename }}</el-descriptions-item>
          <el-descriptions-item label="Schema">{{ restorePreview.verification.schema_version }}</el-descriptions-item>
          <el-descriptions-item label="当前账号数">{{ restorePreview.current_state.accounts }}</el-descriptions-item>
          <el-descriptions-item label="全局暂停">
            <StateTag :state="restorePreview.paused ? 'paused' : 'available'" :label="restorePreview.paused ? '已暂停（满足要求）' : '未暂停'" />
          </el-descriptions-item>
          <el-descriptions-item label="备份时间" :span="2">{{ formatTime(restorePreview.backup.created_at) }}</el-descriptions-item>
        </el-descriptions>
        <div class="warning-block">
          <div v-for="(warning, index) in restorePreview.warnings" :key="index">· {{ warning }}</div>
        </div>
        <el-alert
          v-if="!restorePreview.paused"
          type="error"
          :closable="false"
          show-icon
          title="恢复前必须启用全局紧急暂停。"
        >
          <el-button size="small" type="danger" :loading="pausing" @click="pauseForRestore">立即暂停</el-button>
        </el-alert>
        <el-form label-width="120px" class="mt">
          <el-form-item label="确认短语">
            <el-input v-model="restoreConfirm" :placeholder="`请输入 ${restorePreview.confirm_phrase}`" />
          </el-form-item>
        </el-form>
      </template>
      <template #footer>
        <el-button @click="restoreDialog = false">取消</el-button>
        <el-button
          type="danger"
          :disabled="!restorePreview || !restorePreview.paused || restoreConfirm !== restorePreview.confirm_phrase"
          :loading="restoring"
          @click="doRestore"
        >
          执行恢复（覆盖当前数据库）
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'

import { api, errorMessage, getAdminToken } from '@/api/client'
import type { AppSettings, BackupRecord } from '@/api/types'
import PageHeader from '@/components/PageHeader.vue'
import StateTag from '@/components/StateTag.vue'
import { useAppStore } from '@/stores/app'
import { formatBytes, formatTime, truncate } from '@/utils/format'
import { ElMessage, ElMessageBox } from 'element-plus'

interface BackupView extends BackupRecord {
  manifest?: { note?: string; tables?: Record<string, number>; [key: string]: unknown }
}

interface VerifyResult {
  filename: string
  size_bytes: number
  sha256: string
  checksum_ok: boolean
  integrity_ok: boolean
  integrity_message: string
  schema_version: string
  tables: Record<string, number>
  verified_at: string
}

interface RestorePreview {
  backup: BackupView
  verification: VerifyResult
  current_state: { accounts: number }
  requires_pause: boolean
  paused: boolean
  confirm_phrase: string
  warnings: string[]
}

interface AuditRecord {
  id: string
  actor: string
  action: string
  target_type: string
  target_id: string | null
  details: Record<string, unknown>
  request_id: string | null
  ip_address: string | null
  created_at: string
}

const appStore = useAppStore()
const activeTab = ref('general')
const loading = ref(false)
const error = ref<string | null>(null)

const settings = ref<AppSettings | null>(null)
const retention = reactive({
  message_retention_days: 90,
  log_retention_days: 30,
  media_retention_days: 30,
})
const savingRetention = ref(false)
const pauseReason = ref('管理员手动暂停')
const pausing = ref(false)

const backups = ref<BackupView[]>([])
const backupNote = ref('')
const creatingBackup = ref(false)
const verifyingId = ref<string | null>(null)
const restoreDialog = ref(false)
const restorePreview = ref<RestorePreview | null>(null)
const restoreConfirm = ref('')
const restoring = ref(false)

const audit = ref<AuditRecord[]>([])
const auditLoading = ref(false)
const auditAction = ref('')
const auditTargetType = ref('')
const auditPage = ref(1)
const auditPageSize = ref(50)
const auditTotal = ref(0)

const privacyRows = computed(() => {
  const counts = settings.value?.privacy.counts ?? {}
  const labels: Record<string, { label: string; note: string }> = {
    accounts: { label: 'QQ 账号', note: '不含 QQ 密码' },
    groups: { label: '群白名单', note: '仅登记配置' },
    personas: { label: '人格档案', note: '含版本与特征' },
    providers: { label: '模型 Provider', note: '密钥加密存储' },
    messages: { label: '消息记录', note: '按保留策略管理' },
    media_assets: { label: '媒体资源', note: '不下载真实 QQ 媒体' },
    memories: { label: '长期记忆', note: '仅本群范围内检索' },
    memory_candidates: { label: 'AI 记忆候选', note: '待审核/已审核记录' },
  }
  return Object.entries(counts).map(([key, count]) => ({
    key,
    label: labels[key]?.label ?? key,
    count,
    note: labels[key]?.note ?? '',
  }))
})

async function loadSettings(): Promise<void> {
  const data = await api<AppSettings>('/settings')
  settings.value = data
  Object.assign(retention, {
    message_retention_days: Number(data.retention.message_retention_days ?? 90),
    log_retention_days: Number(data.retention.log_retention_days ?? 30),
    media_retention_days: Number(data.retention.media_retention_days ?? 30),
  })
  await appStore.refresh()
}

async function loadBackups(): Promise<void> {
  const data = await api<{ items: BackupView[] }>('/backups')
  backups.value = data.items
}

async function loadAudit(targetPage?: number): Promise<void> {
  if (targetPage) auditPage.value = targetPage
  auditLoading.value = true
  try {
    const query: Record<string, string | number> = {
      page: auditPage.value,
      page_size: auditPageSize.value,
    }
    if (auditAction.value.trim()) query.action = auditAction.value.trim()
    if (auditTargetType.value) query.target_type = auditTargetType.value
    const data = await api<{ items: AuditRecord[]; total: number }>('/audit', { query })
    audit.value = data.items
    auditTotal.value = data.total
  } catch (err) {
    ElMessage.error(errorMessage(err))
  } finally {
    auditLoading.value = false
  }
}

async function loadAll(): Promise<void> {
  loading.value = true
  error.value = null
  try {
    await Promise.all([loadSettings(), loadBackups(), loadAudit()])
  } catch (err) {
    error.value = errorMessage(err)
  } finally {
    loading.value = false
  }
}

async function pauseAll(): Promise<void> {
  pausing.value = true
  try {
    await appStore.pauseAll(pauseReason.value || '管理员手动暂停')
    ElMessage.success('已启用全局紧急暂停。')
    await loadSettings()
  } catch (err) {
    ElMessage.error(errorMessage(err))
  } finally {
    pausing.value = false
  }
}

async function resumeAll(): Promise<void> {
  try {
    await ElMessageBox.confirm('恢复后将重新允许自动回复与发送队列。请确认群配置与预算。', '恢复运行', {
      type: 'warning',
      confirmButtonText: '恢复',
      cancelButtonText: '取消',
    })
  } catch {
    return
  }
  pausing.value = true
  try {
    await appStore.resumeAll()
    ElMessage.success('已恢复运行。')
    await loadSettings()
  } catch (err) {
    ElMessage.error(errorMessage(err))
  } finally {
    pausing.value = false
  }
}

async function pauseForRestore(): Promise<void> {
  pausing.value = true
  try {
    await appStore.pauseAll('恢复备份前的安全暂停')
    await loadSettings()
    if (restorePreview.value) {
      restorePreview.value = await api<RestorePreview>(`/backups/${restorePreview.value.backup.id}/restore/preview`, {
        method: 'POST',
      })
    }
    ElMessage.success('已暂停。请再次确认恢复。')
  } catch (err) {
    ElMessage.error(errorMessage(err))
  } finally {
    pausing.value = false
  }
}

async function saveRetention(): Promise<void> {
  savingRetention.value = true
  try {
    const data = await api<AppSettings>('/settings', {
      method: 'PUT',
      body: { retention },
    })
    settings.value = data
    ElMessage.success('保留策略已保存。')
  } catch (err) {
    ElMessage.error(errorMessage(err))
  } finally {
    savingRetention.value = false
  }
}

async function createBackup(): Promise<void> {
  creatingBackup.value = true
  try {
    const result = await api<BackupView>('/backups', {
      method: 'POST',
      body: { note: backupNote.value },
    })
    ElMessage.success(`备份已创建：${result.filename}`)
    backupNote.value = ''
    await loadBackups()
  } catch (err) {
    ElMessage.error(errorMessage(err))
  } finally {
    creatingBackup.value = false
  }
}

async function verifyBackup(backup: BackupView): Promise<void> {
  verifyingId.value = backup.id
  try {
    const result = await api<VerifyResult>(`/backups/${backup.id}/verify`, { method: 'POST' })
    if (result.checksum_ok && result.integrity_ok) {
      ElMessage.success(`校验通过：${result.tables ? Object.keys(result.tables).length : 0} 张表。`)
    } else {
      ElMessage.error(`校验失败：${result.integrity_message}`)
    }
    await loadBackups()
  } catch (err) {
    ElMessage.error(errorMessage(err))
  } finally {
    verifyingId.value = null
  }
}

async function downloadBackup(backup: BackupView): Promise<void> {
  try {
    const token = getAdminToken()
    const headers: Record<string, string> = token ? { 'X-Admin-Token': token } : {}
    const response = await fetch(`/api/backups/${backup.id}/download`, { headers })
    if (!response.ok) {
      throw new Error(`下载失败（HTTP ${response.status}）`)
    }
    const blob = await response.blob()
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = backup.filename
    link.click()
    URL.revokeObjectURL(url)
  } catch (err) {
    ElMessage.error(err instanceof Error ? err.message : '下载失败')
  }
}

async function previewRestore(backup: BackupView): Promise<void> {
  try {
    restorePreview.value = await api<RestorePreview>(`/backups/${backup.id}/restore/preview`, { method: 'POST' })
    restoreConfirm.value = ''
    restoreDialog.value = true
    await loadBackups()
  } catch (err) {
    ElMessage.error(errorMessage(err))
  }
}

async function doRestore(): Promise<void> {
  const preview = restorePreview.value
  if (!preview) return
  if (restoreConfirm.value !== preview.confirm_phrase) {
    ElMessage.warning(`请输入 ${preview.confirm_phrase} 以确认。`)
    return
  }
  restoring.value = true
  try {
    const result = await api<{ restored: boolean; safety_backup: BackupView; next_steps: string[] }>(
      `/backups/${preview.backup.id}/restore`,
      { method: 'POST', body: { confirm: restoreConfirm.value } },
    )
    restoreDialog.value = false
    ElMessage.success(`恢复完成；已创建安全备份 ${result.safety_backup.filename}。`)
    await ElMessageBox.alert(result.next_steps.join('\n'), '恢复完成', {
      confirmButtonText: '知道了',
      type: 'success',
    })
    await loadAll()
  } catch (err) {
    ElMessage.error(errorMessage(err))
  } finally {
    restoring.value = false
  }
}

async function deleteBackup(backup: BackupView): Promise<void> {
  try {
    await ElMessageBox.confirm(
      `确定删除备份「${backup.filename}」？备份文件和记录都会删除。`,
      '删除备份',
      { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' },
    )
  } catch {
    return
  }
  try {
    await api(`/backups/${backup.id}`, { method: 'DELETE' })
    ElMessage.success('备份已删除。')
    await loadBackups()
  } catch (err) {
    ElMessage.error(errorMessage(err))
  }
}

onMounted(loadAll)
</script>

<style scoped>
.mt {
  margin-top: 12px;
}

.pause-info {
  display: flex;
  flex-direction: column;
  gap: 6px;
  align-items: flex-start;
  background: #fff5f5;
  border-radius: 8px;
  padding: 12px;
}

.retention-form {
  max-width: 620px;
}

.filter-line {
  display: flex;
  gap: 8px;
  align-items: center;
}

.filter-bar {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  margin-bottom: 12px;
}

.warning-block {
  background: #fff8ec;
  border-radius: 8px;
  padding: 10px 12px;
  margin-top: 12px;
  font-size: 13px;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.privacy-notes {
  margin: 0;
  padding-left: 18px;
  display: flex;
  flex-direction: column;
  gap: 8px;
  font-size: 13px;
  line-height: 1.6;
}

.audit-pre {
  background: #f7f8fb;
  border-radius: 6px;
  padding: 10px;
  font-size: 12px;
  max-height: 260px;
  overflow: auto;
  margin: 8px 48px;
}

.pager {
  display: flex;
  justify-content: flex-end;
  margin-top: 12px;
}
</style>

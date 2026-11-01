<template>
  <div class="page">
    <PageHeader
      title="诊断与日志"
      description="查看后端只读诊断摘要并复制已脱敏文本。本页不会运行新的诊断、发送消息、调用模型或读取日志正文。"
    >
      <template #actions>
        <el-button :loading="loading" @click="load">刷新摘要</el-button>
        <el-button v-if="isDesktopMode" @click="openLogs">打开日志目录</el-button>
      </template>
    </PageHeader>

    <el-alert v-if="error" type="error" :title="error" show-icon :closable="false">
      <el-button size="small" :loading="loading" @click="load">重试</el-button>
    </el-alert>
    <el-alert v-if="copyError" type="error" :title="copyError" show-icon :closable="false" />

    <el-alert
      type="info"
      show-icon
      :closable="false"
      title="诊断摘要来自后端 allowlist，不包含日志正文。"
      description="需要新的连接诊断请前往 QQ 接入或连接器页手动执行；需要模型测试请前往模型 API 页。真实测试可能产生计费。"
    >
      <div class="link-actions">
        <el-button size="small" @click="router.push('/accounts')">前往 QQ 接入诊断</el-button>
        <el-button size="small" @click="router.push('/connectors')">前往连接器诊断</el-button>
        <el-button size="small" @click="router.push('/providers')">前往模型 API 测试</el-button>
      </div>
    </el-alert>

    <template v-if="payload">
      <div class="generated muted">生成时间：{{ formatTime(payload.generated_at) }} · 应用 {{ payload.app.version }}（{{ payload.app.env }}）</div>

      <div class="grid grid-2">
        <div class="card">
          <div class="card-title">运行环境</div>
          <el-descriptions :column="1" border size="small">
            <el-descriptions-item label="本地数据库">
              <StateTag :state="payload.readiness.database ? 'available' : 'error'" :label="payload.readiness.database ? '可用' : '不可用'" />
            </el-descriptions-item>
            <el-descriptions-item label="凭证加密密钥">
              <StateTag
                :state="payload.readiness.credential_key_configured ? 'available' : 'unconfigured'"
                :label="payload.readiness.credential_key_configured ? '已配置' : '未配置'"
              />
            </el-descriptions-item>
            <el-descriptions-item label="全局紧急暂停">
              <StateTag :state="payload.readiness.global_paused ? 'paused' : 'available'" :label="payload.readiness.global_paused ? '暂停中' : '未暂停'" />
              <span v-if="payload.readiness.global_paused" class="muted"> · {{ formatTime(payload.readiness.global_pause_updated_at) }}</span>
            </el-descriptions-item>
            <el-descriptions-item label="事件流订阅">{{ payload.readiness.event_stream_subscribers }} 个</el-descriptions-item>
          </el-descriptions>
        </div>

        <div class="card">
          <div class="card-title">数据计数</div>
          <div class="stat-grid">
            <div v-for="row in countRows" :key="row.key" class="stat">
              <span class="muted">{{ row.label }}</span>
              <span class="stat-value">{{ formatNumber(row.value) }}</span>
            </div>
          </div>
        </div>
      </div>

      <div class="grid grid-2">
        <div class="card">
          <div class="card-title">账号与实时在线</div>
          <el-descriptions :column="1" border size="small">
            <el-descriptions-item label="连接方式">
              Mock {{ payload.accounts.modes.mock }} · OneBot 11 {{ payload.accounts.modes.onebot11 }} · 其他 {{ payload.accounts.modes.other }}
            </el-descriptions-item>
            <el-descriptions-item label="真实实例实时在线">{{ payload.accounts.live_online_instances }}</el-descriptions-item>
            <el-descriptions-item label="已确认身份">{{ payload.accounts.identity_confirmed_instances }}</el-descriptions-item>
            <el-descriptions-item label="已连接未验证">{{ payload.accounts.connected_unverified_instances }}</el-descriptions-item>
          </el-descriptions>
          <p class="muted small">在线数来自当前进程内适配器；重启后需重新连接。Mock 不计入真实在线。</p>
        </div>

        <div class="card">
          <div class="card-title">连接器</div>
          <el-descriptions :column="1" border size="small">
            <el-descriptions-item label="安装数量">{{ payload.connectors.installation_count }}</el-descriptions-item>
            <el-descriptions-item label="状态分布">
              <div v-if="payload.connectors.states.length" class="tag-row">
                <el-tag v-for="item in payload.connectors.states" :key="item.state" size="small" effect="plain">
                  {{ item.state }} × {{ item.count }}
                </el-tag>
              </div>
              <span v-else class="muted">未检测到连接器安装</span>
            </el-descriptions-item>
            <el-descriptions-item label="已确认身份">{{ payload.connectors.identity_confirmed }}</el-descriptions-item>
            <el-descriptions-item label="真实双向收发证据">{{ payload.connectors.real_traffic_verified }}</el-descriptions-item>
            <el-descriptions-item label="真实 QQ 已验证">
              <StateTag state="not_verified" label="否（尚未由用户完成真实验收）" />
            </el-descriptions-item>
          </el-descriptions>
        </div>
      </div>

      <div class="grid grid-2">
        <div class="card">
          <div class="card-title">模型 Provider</div>
          <div class="stat-grid">
            <div class="stat"><span class="muted">总数</span><span class="stat-value">{{ payload.providers.total }}</span></div>
            <div class="stat"><span class="muted">Mock</span><span class="stat-value">{{ payload.providers.mock }}</span></div>
            <div class="stat"><span class="muted">真实</span><span class="stat-value">{{ payload.providers.real }}</span></div>
            <div class="stat"><span class="muted">配置完整</span><span class="stat-value">{{ payload.providers.real_config_complete }}</span></div>
            <div class="stat"><span class="muted">测试通过</span><span class="stat-value">{{ payload.providers.real_test_passed }}</span></div>
            <div class="stat"><span class="muted">测试失败</span><span class="stat-value">{{ payload.providers.real_test_failed }}</span></div>
            <div class="stat"><span class="muted">从未测试</span><span class="stat-value">{{ payload.providers.real_never_tested }}</span></div>
          </div>
          <p class="muted small">只统计测试记录；Mock 测试不计为真实模型可用。测试通过不代表长期稳定，调用仍可能计费。</p>
        </div>

        <div class="card">
          <div class="card-title">群策略</div>
          <div class="stat-grid">
            <div class="stat"><span class="muted">群总数</span><span class="stat-value">{{ payload.groups.total }}</span></div>
            <div class="stat"><span class="muted">已启用</span><span class="stat-value">{{ payload.groups.enabled }}</span></div>
            <div class="stat"><span class="muted">仅观察</span><span class="stat-value">{{ payload.groups.observe_only }}</span></div>
            <div class="stat"><span class="muted">自动回复模式</span><span class="stat-value">{{ payload.groups.auto_reply_modes }}</span></div>
            <div class="stat"><span class="muted">已暂停</span><span class="stat-value">{{ payload.groups.paused }}</span></div>
            <div class="stat"><span class="muted">Provider 可解析</span><span class="stat-value">{{ payload.groups.provider_resolved }}</span></div>
            <div class="stat"><span class="muted">Provider 不可解析</span><span class="stat-value">{{ payload.groups.provider_unresolved }}</span></div>
          </div>
        </div>
      </div>

      <div class="grid grid-2">
        <div class="card">
          <div class="card-title">消息与发送队列</div>
          <div class="stat-grid">
            <div class="stat"><span class="muted">入站</span><span class="stat-value">{{ payload.messages.received }}</span></div>
            <div class="stat"><span class="muted">仅观察</span><span class="stat-value">{{ payload.messages.observed }}</span></div>
            <div class="stat"><span class="muted">已回复</span><span class="stat-value">{{ payload.messages.replied }}</span></div>
            <div class="stat"><span class="muted">出站</span><span class="stat-value">{{ payload.messages.sent }}</span></div>
            <div class="stat"><span class="muted">队列待处理</span><span class="stat-value">{{ payload.messages.outbox_pending }}</span></div>
            <div class="stat"><span class="muted">队列失败</span><span class="stat-value">{{ payload.messages.outbox_failed }}</span></div>
          </div>
        </div>

        <div class="card">
          <div class="card-title">
            <span>最近连接测试</span>
            <el-tag size="small" :type="freshnessTag(payload.connection_test.freshness)" effect="plain">
              {{ freshnessLabel(payload.connection_test.freshness) }}
            </el-tag>
          </div>
          <el-descriptions :column="1" border size="small">
            <el-descriptions-item label="结果">
              <StateTag
                :state="payload.connection_test.last_outcome === 'success' ? 'available' : payload.connection_test.last_outcome === 'failure' ? 'error' : 'not_verified'"
                :label="payload.connection_test.last_outcome === 'success' ? '成功' : payload.connection_test.last_outcome === 'failure' ? '失败' : '无证据'"
              />
              <span class="muted" v-if="payload.connection_test.tested_at"> · {{ formatTime(payload.connection_test.tested_at) }}</span>
            </el-descriptions-item>
            <el-descriptions-item label="来源">{{ payload.connection_test.last_source || '—' }}</el-descriptions-item>
            <el-descriptions-item label="证据范围">
              <div class="tag-row">
                <el-tag size="small" :type="payload.connection_test.identity_verified ? 'success' : 'info'">
                  身份{{ payload.connection_test.identity_verified ? '已验证' : '未验证' }}
                </el-tag>
                <el-tag size="small" :type="payload.connection_test.action_path_verified ? 'success' : 'info'">
                  动作通道{{ payload.connection_test.action_path_verified ? '已验证' : '未验证' }}
                </el-tag>
                <el-tag size="small" :type="payload.connection_test.group_list_verified ? 'success' : 'info'">
                  群列表{{ payload.connection_test.group_list_verified ? '已验证' : '未验证' }}
                </el-tag>
                <el-tag size="small" :type="payload.connection_test.real_inbound_verified ? 'success' : 'warning'">
                  真实入站{{ payload.connection_test.real_inbound_verified ? '已验证' : '未验证' }}
                </el-tag>
                <el-tag size="small" :type="payload.connection_test.real_outbound_verified ? 'success' : 'warning'">
                  真实出站{{ payload.connection_test.real_outbound_verified ? '已验证' : '未验证' }}
                </el-tag>
              </div>
            </el-descriptions-item>
            <el-descriptions-item label="测试发送消息">否（诊断从不发送消息）</el-descriptions-item>
          </el-descriptions>
        </div>
      </div>

      <div class="card">
        <div class="card-title">
          <span>最近 200 条审计动作</span>
          <span class="muted">仅动作名与计数，不含目标、详情或 IP</span>
        </div>
        <div v-if="payload.recent_audit_actions.length" class="tag-row">
          <el-tag v-for="item in payload.recent_audit_actions" :key="item.action" size="small" effect="plain">
            {{ item.action }} × {{ item.count }}
          </el-tag>
        </div>
        <el-empty v-else description="还没有审计记录。" :image-size="55" />
      </div>

      <div class="card">
        <div class="card-title">
          <span>脱敏诊断摘要</span>
          <el-button type="primary" size="small" @click="copySummary">复制脱敏摘要</el-button>
        </div>
        <el-alert
          type="warning"
          :closable="false"
          show-icon
          title="默认排除敏感字段；分享前仍请自行检查。"
        >
          <ul class="excluded-list">
            <li v-for="(item, index) in payload.excluded" :key="index">{{ item }}</li>
          </ul>
        </el-alert>
        <el-input v-model="summaryText" type="textarea" :rows="14" readonly class="summary-text" />
        <p class="muted small">
          完整日志只保存在本机。
          <template v-if="isDesktopMode">桌面版可通过右上角「打开日志目录」查看；分享前请自行检查。</template>
          <template v-else>浏览器模式不能读取日志文件；请在本机数据目录或桌面版中查看。</template>
        </p>
      </div>

      <div class="card">
        <el-collapse>
          <el-collapse-item title="查看脱敏 JSON" name="json">
            <pre class="json-pre">{{ jsonText }}</pre>
          </el-collapse-item>
        </el-collapse>
      </div>
    </template>

    <div v-else-if="loading" class="card">
      <el-skeleton :rows="6" animated />
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'

import { api, errorMessage } from '@/api/client'
import { desktopErrorMessage, isDesktop, openDesktopFolder } from '@/api/desktop'
import type { DiagnosticsPayload } from '@/api/types'
import PageHeader from '@/components/PageHeader.vue'
import StateTag from '@/components/StateTag.vue'
import { freshnessLabel, freshnessTag } from '@/utils/onboarding'
import { formatNumber, formatTime } from '@/utils/format'
import { ElMessage } from 'element-plus'
import { useRouter } from 'vue-router'

const router = useRouter()
const isDesktopMode = isDesktop()
const payload = ref<DiagnosticsPayload | null>(null)
const loading = ref(false)
const error = ref<string | null>(null)
const copyError = ref<string | null>(null)
const summaryText = ref('')

const jsonText = computed(() => (payload.value ? JSON.stringify(payload.value, null, 2) : ''))
const countRows = computed(() => {
  const counts = payload.value?.counts
  if (!counts) return []
  return [
    { key: 'accounts', label: '账号', value: counts.accounts },
    { key: 'adapter_instances', label: '连接器实例', value: counts.adapter_instances },
    { key: 'groups', label: '群', value: counts.groups },
    { key: 'personas', label: '人格', value: counts.personas },
    { key: 'providers', label: 'Provider', value: counts.providers },
    { key: 'messages', label: '消息', value: counts.messages },
    { key: 'media_assets', label: '媒体资源', value: counts.media_assets },
    { key: 'memories', label: '长期记忆', value: counts.memories },
    { key: 'memory_candidates', label: '记忆候选', value: counts.memory_candidates },
    { key: 'outbox_messages', label: '发送队列', value: counts.outbox_messages },
  ]
})

watch(payload, (value) => {
  summaryText.value = value?.text ?? ''
})

async function load(): Promise<void> {
  loading.value = true
  error.value = null
  copyError.value = null
  try {
    payload.value = await api<DiagnosticsPayload>('/diagnostics')
  } catch (err) {
    error.value = errorMessage(err)
  } finally {
    loading.value = false
  }
}

async function copySummary(): Promise<void> {
  copyError.value = null
  const text = payload.value?.text ?? ''
  if (!text) {
    copyError.value = '没有可复制的诊断摘要，请先刷新。'
    return
  }
  try {
    await navigator.clipboard.writeText(text)
    ElMessage.success('已复制脱敏诊断摘要。')
  } catch (err) {
    copyError.value = `复制失败：${err instanceof Error ? err.message : String(err)}。文本仍保留在下方，可手动选择复制。`
    ElMessage.error('复制失败，请手动选择下方文本。')
  }
}

async function openLogs(): Promise<void> {
  try {
    await openDesktopFolder('logs')
  } catch (err) {
    ElMessage.error(desktopErrorMessage(err))
  }
}

onMounted(load)
</script>

<style scoped>
.generated {
  margin: 14px 0 10px;
  font-size: 12px;
}

.link-actions {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  margin-top: 8px;
}

.stat-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(130px, 1fr));
  gap: 10px;
}

.stat {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 8px 10px;
  border-radius: 8px;
  background: var(--app-surface-soft);
  font-size: 12px;
}

.stat-value {
  font-size: 18px;
  font-weight: 650;
}

.tag-row {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}

.small {
  font-size: 12px;
  margin: 8px 0 0;
  line-height: 1.6;
}

.excluded-list {
  margin: 6px 0 0;
  padding-left: 18px;
  display: grid;
  gap: 3px;
  font-size: 12.5px;
}

.summary-text {
  margin-top: 10px;
}

.summary-text :deep(textarea) {
  font-family: var(--app-mono, monospace);
  font-size: 12.5px;
  line-height: 1.6;
}

.json-pre {
  margin: 0;
  max-height: 420px;
  overflow: auto;
  background: var(--app-surface-soft);
  border-radius: 8px;
  padding: 12px;
  font-size: 12px;
}
</style>

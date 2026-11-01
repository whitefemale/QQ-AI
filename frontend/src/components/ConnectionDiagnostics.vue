<template>
  <div class="diagnostics">
    <el-alert
      :type="summary.type"
      :title="summary.title"
      :description="summary.description"
      :closable="false"
      show-icon
    />

    <el-descriptions :column="2" size="small" border class="diagnostics-meta">
      <el-descriptions-item label="测试时间">{{ formatTime(report.tested_at) }}</el-descriptions-item>
      <el-descriptions-item label="耗时">{{ report.latency_ms }} ms</el-descriptions-item>
      <el-descriptions-item label="连接方式">
        {{ report.connection_mode }}
        <el-tag v-if="report.is_mock" size="small" type="info" class="inline-tag">Mock</el-tag>
      </el-descriptions-item>
      <el-descriptions-item label="QQ 身份">{{ loginText }}</el-descriptions-item>
      <el-descriptions-item label="群列表">
        {{ report.group_count }} 个{{ report.group_list_verified ? '' : '（未验证）' }}
      </el-descriptions-item>
      <el-descriptions-item label="测试发送消息">
        {{ report.message_send_attempted ? '是（请检查是否符合预期）' : '否（本测试不发送任何消息）' }}
      </el-descriptions-item>
    </el-descriptions>

    <div class="scope-title">证据范围</div>
    <div class="scope-grid">
      <span v-for="item in scopeItems" :key="item.label" class="scope-item">
        <span class="muted">{{ item.label }}</span>
        <el-tag size="small" :type="item.verified ? 'success' : 'warning'" effect="light">
          {{ item.verified ? '已验证' : '未验证' }}
        </el-tag>
      </span>
    </div>

    <el-alert
      type="warning"
      :closable="false"
      show-icon
      class="scope-warning"
      title="连接与身份检查不等于真实 QQ 群消息收发验证。"
      :description="report.note"
    />

    <el-table :data="report.checks" size="small" class="checks-table">
      <el-table-column prop="label" label="检查项" width="120" />
      <el-table-column label="状态" width="88">
        <template #default="{ row }">
          <el-tag size="small" :type="checkStateTag(row.state)" effect="light">{{ checkStateLabel(row.state) }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="说明" min-width="240">
        <template #default="{ row }">
          <span>{{ checkDetail(row) }}</span>
        </template>
      </el-table-column>
      <el-table-column label="耗时" width="82">
        <template #default="{ row }">
          <span class="muted">{{ row.duration_ms == null ? '—' : `${row.duration_ms} ms` }}</span>
        </template>
      </el-table-column>
      <el-table-column label="下一步" min-width="200">
        <template #default="{ row }">
          <span class="muted">{{ row.next_step || '—' }}</span>
        </template>
      </el-table-column>
    </el-table>

    <div v-if="report.next_step" class="muted next-step">下一步：{{ report.next_step }}</div>

    <div class="copy-actions">
      <el-button size="small" plain @click="copySummary">复制脱敏摘要</el-button>
      <span class="muted">不含 QQ 号、昵称、群名、地址、Token 或错误正文中的端点。</span>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'

import type { ConnectionDiagnostics } from '@/api/types'
import {
  checkDetail,
  checkStateLabel,
  checkStateTag,
  connectionDiagnosticsCopy,
  diagnosticsSummary,
} from '@/utils/diagnostics'
import { formatTime } from '@/utils/format'
import { ElMessage } from 'element-plus'

const props = defineProps<{ report: ConnectionDiagnostics }>()

const summary = computed(() => diagnosticsSummary(props.report))

const loginText = computed(() => {
  const login = props.report.login
  if (!login?.user_id) return '未获取到 QQ 身份'
  const source = login.source === 'mock' ? '（Mock 本地身份，非真实 QQ）' : ''
  return `${login.user_id}${login.nickname ? ` · ${login.nickname}` : ''}${source}`
})

const scopeItems = computed(() => [
  { label: '身份验证', verified: props.report.identity_verified },
  { label: '动作通道', verified: props.report.action_path_verified },
  { label: '群列表', verified: props.report.group_list_verified },
  { label: '真实入站消息', verified: props.report.real_inbound_verified },
  { label: '真实出站发送', verified: props.report.real_outbound_verified },
])

async function copySummary(): Promise<void> {
  try {
    await navigator.clipboard.writeText(connectionDiagnosticsCopy(props.report))
    ElMessage.success('已复制脱敏诊断摘要。')
  } catch (err) {
    ElMessage.error(`复制失败：${err instanceof Error ? err.message : String(err)}。`)
  }
}
</script>

<style scoped>
.diagnostics-meta {
  margin-top: 12px;
}

.inline-tag {
  margin-left: 6px;
}

.scope-title {
  margin: 14px 0 8px;
  font-size: 13px;
  font-weight: 600;
}

.scope-grid {
  display: flex;
  flex-wrap: wrap;
  gap: 8px 18px;
}

.scope-item {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

.scope-warning {
  margin: 12px 0;
}

.checks-table {
  margin-top: 4px;
}

.next-step {
  margin-top: 10px;
}

.copy-actions {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  margin-top: 14px;
}
</style>

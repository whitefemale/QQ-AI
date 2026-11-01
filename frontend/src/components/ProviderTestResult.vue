<template>
  <div v-if="result" class="provider-test-result">
    <div class="result-head">
      <el-tag :type="providerTestOutcomeTag(result.outcome)" size="small">
        {{ result.kind === 'generation' ? '真实生成' : '连通性' }}：{{ providerTestOutcomeLabel(result.outcome) }}
      </el-tag>
      <el-tag v-if="result.is_mock" type="warning" size="small">Mock 模拟，不是真实 API 结果</el-tag>
      <el-tag v-else type="info" size="small">真实请求（可能已产生费用）</el-tag>
      <el-tag v-if="!result.provider_enabled" type="info" size="small">Provider 已停用</el-tag>
    </div>

    <el-alert
      v-if="result.is_mock"
      type="warning"
      :closable="false"
      show-icon
      title="Mock 结果不能证明真实模型可用"
      description="Mock 只验证本地流程；不会访问任何模型服务。"
    />

    <div class="result-meta">
      <span>模型：{{ result.model || '—' }}</span>
      <span>延迟：{{ result.latency_ms ?? '—' }} ms</span>
      <span>尝试：{{ result.attempts }} 次</span>
      <span v-if="result.retry_after_seconds">建议等待：{{ result.retry_after_seconds }}s</span>
    </div>

    <div v-if="result.error_code" class="result-line">
      <span class="muted">错误码：</span><span class="mono">{{ result.error_code }}</span>
    </div>
    <div v-if="result.message" class="result-line">{{ result.message }}</div>

    <el-alert
      v-if="actionHint"
      type="info"
      :closable="false"
      show-icon
      title="下一步建议"
      :description="actionHint"
    />

    <div v-if="result.text" class="result-text">
      <div class="muted">返回文本（已截断并脱敏）</div>
      <pre>{{ result.text }}</pre>
    </div>

    <div v-if="result.usage" class="result-line">
      <span class="muted">用量与费用：</span>{{ formatProviderUsage(result.usage) }}
    </div>
    <div v-if="result.upstream_request_id" class="result-line">
      <span class="muted">上游 Request ID：</span>
      <span class="mono">{{ result.upstream_request_id }}</span>
    </div>
    <div v-if="result.outcome === 'cancelled'" class="muted result-line">
      已请求取消本地等待；无法保证服务商停止生成或停止计费。
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'

import type { ProviderTestResult } from '@/api/types'
import {
  formatProviderUsage,
  providerActionHint,
  providerTestOutcomeLabel,
  providerTestOutcomeTag,
} from '@/utils/providers'

const props = defineProps<{ result: ProviderTestResult | null }>()

const actionHint = computed(() =>
  providerActionHint(props.result?.error_code, props.result?.next_step ?? null),
)
</script>

<style scoped>
.provider-test-result {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.result-head {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.result-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

.result-line {
  font-size: 13px;
  line-height: 1.5;
  word-break: break-word;
}

.result-text pre {
  margin: 4px 0 0;
  padding: 8px;
  max-height: 220px;
  overflow: auto;
  white-space: pre-wrap;
  word-break: break-word;
  border-radius: 4px;
  background: var(--el-fill-color-light);
  font-family: inherit;
  font-size: 13px;
}

.mono {
  font-family: ui-monospace, SFMono-Regular, Consolas, monospace;
}
</style>

<template>
  <div class="persona-diff">
    <el-alert v-if="!diff" type="info" :closable="false" show-icon :title="emptyText" />
    <template v-else>
      <div class="diff-impact">
        <el-tag size="small" effect="plain">{{ impactSummary(diff) }}</el-tag>
        <el-tag v-if="diff.impact.scopes.length" size="small" type="warning">
          作用域：{{ diff.impact.scopes.join('、') }}
        </el-tag>
        <el-tag v-if="diff.impact.skipped_locked.length" size="small" type="info">
          锁定跳过：{{ diff.impact.skipped_locked.join('、') }}
        </el-tag>
      </div>
      <el-table v-if="diff.fields.length" :data="diff.fields" size="small" border>
        <el-table-column prop="label" label="字段" width="130" />
        <el-table-column label="当前" min-width="180">
          <template #default="{ row }">
            <span class="diff-value">{{ diffValueText(row.before) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="变更后" min-width="180">
          <template #default="{ row }">
            <span class="diff-value">{{ diffValueText(row.after) }}</span>
          </template>
        </el-table-column>
      </el-table>
      <div v-else class="muted">没有配置字段变化。</div>

      <div v-if="diff.traits.added.length" class="trait-group">
        <div class="trait-title">新增/生效特征</div>
        <div v-for="trait in diff.traits.added" :key="`added-${trait.trait_key}-${trait.source_scope}`" class="trait-line">
          + {{ traitDiffLabel(trait) }}
        </div>
      </div>
      <div v-if="diff.traits.changed.length" class="trait-group">
        <div class="trait-title">修改特征</div>
        <div
          v-for="entry in diff.traits.changed"
          :key="`changed-${entry.trait_key}-${entry.source_scope}`"
          class="trait-line"
        >
          {{ entry.trait_key }}：{{ diffValueText(entry.before.trait_value) }} → {{ diffValueText(entry.after.trait_value) }}
        </div>
      </div>
      <div v-if="diff.traits.removed.length" class="trait-group">
        <div class="trait-title">移除特征</div>
        <div v-for="trait in diff.traits.removed" :key="`removed-${trait.trait_key}-${trait.source_scope}`" class="trait-line">
          − {{ traitDiffLabel(trait) }}
        </div>
      </div>
    </template>
  </div>
</template>

<script setup lang="ts">
import type { PersonaDiff } from '@/api/types'
import { diffValueText, impactSummary, traitDiffLabel } from '@/utils/personas'

defineProps<{
  diff?: PersonaDiff | null
  emptyText?: string
}>()
</script>

<style scoped>
.persona-diff {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.diff-impact {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}

.diff-value {
  white-space: pre-wrap;
  word-break: break-word;
}

.trait-group {
  font-size: 13px;
}

.trait-title {
  font-weight: 600;
  margin-bottom: 4px;
}

.trait-line {
  color: var(--el-text-color-regular);
  padding: 2px 0;
  word-break: break-word;
}
</style>

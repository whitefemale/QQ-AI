<template>
  <div class="provider-readiness-tags">
    <el-tooltip v-for="tag in tags" :key="tag.key" :content="tag.note" placement="top">
      <el-tag :type="tag.type" size="small" effect="light">{{ tag.label }}</el-tag>
    </el-tooltip>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'

import type { LLMProvider } from '@/api/types'
import { providerReadinessTags } from '@/utils/providers'

const props = defineProps<{ provider: LLMProvider }>()

const tags = computed(() => providerReadinessTags(props.provider))
</script>

<style scoped>
.provider-readiness-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}
</style>

<template>
  <el-tag :type="tagType" size="small" effect="light">{{ text }}</el-tag>
</template>

<script setup lang="ts">
import { computed } from 'vue'

import { stateLabel, stateTag } from '@/utils/format'

const props = defineProps<{ state?: string | null; label?: string }>()

const tagType = computed(() => stateTag(props.state))
const text = computed(() => props.label ?? stateLabel(props.state))
</script>

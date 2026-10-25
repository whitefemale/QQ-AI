<template>
  <div class="page-header">
    <div>
      <h1 class="page-header-title">{{ title }}</h1>
      <p v-if="description" class="page-header-desc">{{ description }}</p>
    </div>
    <div class="page-header-actions">
      <slot name="actions" />
    </div>
  </div>
</template>

<script setup lang="ts">
defineProps<{ title: string; description?: string }>()
</script>

<style scoped>
.page-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  flex-wrap: wrap;
}

.page-header-title {
  margin: 0;
  font-size: 21px;
  font-weight: 650;
  letter-spacing: -0.01em;
}

.page-header-desc {
  margin: 6px 0 0;
  color: var(--app-muted);
  font-size: 13px;
  line-height: 1.6;
  max-width: 780px;
}

.page-header-actions {
  display: flex;
  gap: 8px;
  align-items: center;
  flex-wrap: wrap;
}
</style>

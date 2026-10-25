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
  position: relative;
  margin: 0;
  padding-left: 13px;
  font-size: 22px;
  font-weight: 700;
  letter-spacing: -0.01em;
}

.page-header-title::before {
  content: '';
  position: absolute;
  left: 0;
  top: 3px;
  bottom: 3px;
  width: 4px;
  border-radius: 3px;
  background: linear-gradient(180deg, var(--app-accent), var(--app-orange));
}

.page-header-desc {
  margin: 7px 0 0 13px;
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

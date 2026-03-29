<script setup lang="ts">
defineProps<{
  agent: string
  step: string
}>()
</script>

<template>
  <div class="loading-indicator">
    <div class="dot-pulse" />
    <span class="status-text">
      <span class="agent-name">{{ agent }}</span>
      {{ step }}
    </span>
  </div>
</template>

<style scoped lang="scss">
.loading-indicator {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 16px;
  color: #909399;
  font-size: 13px;
}

.agent-name {
  color: #409eff;
  font-weight: 500;
  margin-right: 4px;
}

.dot-pulse {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #409eff;
  animation: pulse 1.2s ease-in-out infinite;
}

@keyframes pulse {
  0%, 100% { opacity: 0.3; transform: scale(0.8); }
  50% { opacity: 1; transform: scale(1.2); }
}
</style>

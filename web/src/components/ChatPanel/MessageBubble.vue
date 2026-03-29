<script setup lang="ts">
import { Cpu, User } from '@element-plus/icons-vue'
import MarkdownRenderer from '../common/MarkdownRenderer.vue'
import type { Message } from '../../types'

defineProps<{
  message: Message
}>()
</script>

<template>
  <div class="message-bubble" :class="message.role">
    <div class="avatar">
      <el-icon v-if="message.role === 'user'" :size="20"><User /></el-icon>
      <el-icon v-else :size="20"><Cpu /></el-icon>
    </div>
    <div class="content">
      <div v-if="message.role === 'user'" class="user-text">{{ message.content }}</div>
      <MarkdownRenderer v-else :content="message.content" />
    </div>
  </div>
</template>

<style scoped lang="scss">
.message-bubble {
  display: flex;
  gap: 12px;
  padding: 16px 0;

  &.user {
    flex-direction: row-reverse;

    .content {
      background: #409eff;
      color: #fff;
      border-radius: 12px 2px 12px 12px;
    }

    .avatar {
      background: #409eff;
      color: #fff;
    }
  }

  &.assistant {
    .content {
      background: #fff;
      border-radius: 2px 12px 12px 12px;
      box-shadow: 0 1px 4px rgba(0, 0, 0, 0.06);
    }

    .avatar {
      background: #f0f2f5;
      color: #409eff;
    }
  }
}

.avatar {
  width: 36px;
  height: 36px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.content {
  max-width: 70%;
  padding: 12px 16px;
  line-height: 1.6;
}

.user-text {
  white-space: pre-wrap;
}
</style>

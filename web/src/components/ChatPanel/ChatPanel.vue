<script setup lang="ts">
import { ref, watch, nextTick, onMounted } from 'vue'
import { ChatDotRound, Cpu } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { uploadPDF } from '../../api/upload'
import { useStreaming } from '../../composables/useStreaming'
import { useChatStore } from '../../stores/chat'
import InputBar from './InputBar.vue'
import MessageBubble from './MessageBubble.vue'
import LoadingIndicator from '../common/LoadingIndicator.vue'
import MarkdownRenderer from '../common/MarkdownRenderer.vue'

const suggestions = [
  '调研 2023-2025 RAG 优化的最新进展',
  '对比 RAG-Fusion、Self-RAG 和 CRAG 的优缺点',
  '帮我分析 LLM 幻觉问题的研究现状',
]

const chatStore = useChatStore()
const { connect, disconnect, send, isConnected } = useStreaming()
const messagesContainer = ref<HTMLElement>()
const inputBarRef = ref<InstanceType<typeof InputBar>>()

onMounted(() => {
  connect()
})

watch(
  () => chatStore.currentSessionId,
  (sessionId, previousSessionId) => {
    if (sessionId === previousSessionId) return
    disconnect()
    connect(sessionId || undefined)
  },
)

// Auto-scroll to bottom
watch(
  () => [chatStore.messages.length, chatStore.streamingContent],
  async () => {
    await nextTick()
    if (messagesContainer.value) {
      messagesContainer.value.scrollTop = messagesContainer.value.scrollHeight
    }
  },
)

function handleSend(content: string, attachmentIds: string[]) {
  send(content, attachmentIds)
}

async function handleUpload(file: File) {
  try {
    const sessionId = chatStore.currentSessionId
    if (!sessionId) {
      ElMessage.warning('请先开始对话')
      return
    }
    const result = await uploadPDF(sessionId, file)
    inputBarRef.value?.addAttachment(result.paper_id, result.filename)
    ElMessage.success(`已上传：${result.title}`)
  } catch (e: any) {
    ElMessage.error(e.message || '上传失败')
  }
}
</script>

<template>
  <div class="chat-panel">
    <div class="connection-status" v-if="!isConnected">
      <el-tag type="warning" size="small">连接中...</el-tag>
    </div>

    <div ref="messagesContainer" class="messages">
      <div v-if="chatStore.messages.length === 0 && !chatStore.isStreaming" class="empty-state">
        <el-icon :size="48" color="#c0c4cc"><ChatDotRound /></el-icon>
        <h3>Paper Agent</h3>
        <p>智能论文研究助手，支持文献调研、论文精读、方法对比</p>
        <div class="suggestions">
          <el-button
            v-for="s in suggestions"
            :key="s"
            size="small"
            round
            @click="handleSend(s, [])"
          >
            {{ s }}
          </el-button>
        </div>
      </div>

      <MessageBubble
        v-for="(msg, i) in chatStore.messages"
        :key="i"
        :message="msg"
      />

      <!-- Streaming message -->
      <div v-if="chatStore.isStreaming" class="message-bubble assistant">
        <div class="avatar">
          <el-icon :size="20"><Cpu /></el-icon>
        </div>
        <div class="content streaming">
          <LoadingIndicator
            v-if="chatStore.agentStatus"
            :agent="chatStore.agentStatus.agent"
            :step="chatStore.agentStatus.step"
          />
          <MarkdownRenderer
            v-if="chatStore.streamingContent"
            :content="chatStore.streamingContent"
          />
          <span v-if="chatStore.streamingContent" class="cursor">|</span>
        </div>
      </div>
    </div>

    <InputBar
      ref="inputBarRef"
      @send="handleSend"
      @upload="handleUpload"
    />
  </div>
</template>

<style scoped lang="scss">
.chat-panel {
  display: flex;
  flex-direction: column;
  height: 100%;
  background: #f0f2f5;
}

.connection-status {
  padding: 4px 20px;
  text-align: center;
}

.messages {
  flex: 1;
  overflow-y: auto;
  padding: 20px;
}

.empty-state {
  text-align: center;
  padding-top: 20vh;
  color: #909399;

  h3 {
    margin: 16px 0 8px;
    color: #303133;
    font-size: 20px;
  }

  p {
    margin-bottom: 24px;
    font-size: 14px;
  }

  .suggestions {
    display: flex;
    flex-wrap: wrap;
    justify-content: center;
    gap: 8px;
  }
}

.message-bubble.assistant {
  display: flex;
  gap: 12px;
  padding: 16px 0;

  .avatar {
    width: 36px;
    height: 36px;
    border-radius: 50%;
    display: flex;
    align-items: center;
    justify-content: center;
    background: #f0f2f5;
    color: #409eff;
    flex-shrink: 0;
  }

  .content.streaming {
    background: #fff;
    border-radius: 2px 12px 12px 12px;
    box-shadow: 0 1px 4px rgba(0, 0, 0, 0.06);
    padding: 12px 16px;
    max-width: 70%;
  }
}

.cursor {
  animation: blink 1s step-end infinite;
  color: #409eff;
  font-weight: bold;
}

@keyframes blink {
  50% { opacity: 0; }
}
</style>

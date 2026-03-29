<script setup lang="ts">
import { Delete, Plus } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { ref, onMounted } from 'vue'
import { createSession, deleteSession, getSessionMessages, listSessions } from '../../api/session'
import { useChatStore } from '../../stores/chat'
import { useSessionStore } from '../../stores/session'

const sessionStore = useSessionStore()
const chatStore = useChatStore()
const loading = ref(false)

const emit = defineEmits<{
  switchSession: [sessionId: string]
  newSession: []
}>()

onMounted(async () => {
  await loadSessions()
})

async function loadSessions() {
  loading.value = true
  try {
    const list = await listSessions()
    sessionStore.setSessions(list)
  } catch (e) {
    console.error('Failed to load sessions:', e)
  } finally {
    loading.value = false
  }
}

async function handleNew() {
  try {
    const result = await createSession()
    sessionStore.addSession({
      session_id: result.session_id,
      title: '新对话',
      created_at: result.created_at,
      last_message: '',
      message_count: 0,
    })
    sessionStore.setCurrentSession(result.session_id)
    chatStore.clearMessages()
    chatStore.currentSessionId = result.session_id
    emit('newSession')
  } catch {
    ElMessage.error('创建会话失败')
  }
}

async function handleSwitch(sessionId: string) {
  if (sessionId === sessionStore.currentSessionId) return

  sessionStore.setCurrentSession(sessionId)
  chatStore.currentSessionId = sessionId

  try {
    const data = await getSessionMessages(sessionId)
    chatStore.loadMessages(data.messages || [])
    emit('switchSession', sessionId)
  } catch {
    chatStore.clearMessages()
  }
}

async function handleDelete(sessionId: string) {
  try {
    await ElMessageBox.confirm('确定删除该会话？', '提示', {
      confirmButtonText: '删除',
      cancelButtonText: '取消',
      type: 'warning',
    })
    await deleteSession(sessionId)
    sessionStore.removeSession(sessionId)

    if (sessionStore.currentSessionId === sessionId) {
      sessionStore.setCurrentSession('')
      chatStore.clearMessages()
      chatStore.currentSessionId = ''
    }
  } catch {
    // User cancelled or delete failed
  }
}

function formatTime(dateStr: string): string {
  const date = new Date(dateStr)
  const now = new Date()
  const diff = now.getTime() - date.getTime()
  const minutes = Math.floor(diff / 60000)

  if (minutes < 1) return '刚刚'
  if (minutes < 60) return `${minutes}分钟前`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours}小时前`
  const days = Math.floor(hours / 24)
  if (days < 7) return `${days}天前`
  return date.toLocaleDateString()
}
</script>

<template>
  <div class="session-list">
    <div class="list-header">
      <el-button type="primary" size="small" @click="handleNew" :icon="Plus">
        新对话
      </el-button>
    </div>

    <div v-if="loading" class="loading">
      <el-skeleton :rows="3" animated />
    </div>

    <div v-else-if="sessionStore.sessions.length === 0" class="empty">
      <p>暂无会话</p>
    </div>

    <div v-else class="list-body">
      <div
        v-for="session in sessionStore.sessions"
        :key="session.session_id"
        class="session-item"
        :class="{ active: session.session_id === sessionStore.currentSessionId }"
        @click="handleSwitch(session.session_id)"
      >
        <div class="session-info">
          <div class="session-title">{{ session.title || '新对话' }}</div>
          <div class="session-meta">
            <span class="time">{{ formatTime(session.created_at) }}</span>
            <span v-if="session.message_count" class="count">{{ session.message_count }} 条</span>
          </div>
          <div v-if="session.last_message" class="session-preview">
            {{ session.last_message }}
          </div>
        </div>
        <el-button
          class="delete-btn"
          :icon="Delete"
          size="small"
          text
          type="danger"
          @click.stop="handleDelete(session.session_id)"
        />
      </div>
    </div>
  </div>
</template>

<style scoped lang="scss">
.session-list {
  display: flex;
  flex-direction: column;
  height: 100%;
}

.list-header {
  padding: 12px 16px;
}

.loading, .empty {
  padding: 20px 16px;
  color: #c0c4cc;
  text-align: center;
  font-size: 13px;
}

.list-body {
  flex: 1;
  overflow-y: auto;
}

.session-item {
  display: flex;
  align-items: center;
  padding: 12px 16px;
  cursor: pointer;
  border-bottom: 1px solid #f0f2f5;
  transition: background 0.2s;

  &:hover {
    background: #f5f7fa;

    .delete-btn { opacity: 1; }
  }

  &.active {
    background: #ecf5ff;
    border-left: 3px solid #409eff;
    padding-left: 13px;
  }
}

.session-info {
  flex: 1;
  min-width: 0;
}

.session-title {
  font-size: 14px;
  color: #303133;
  font-weight: 500;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.session-meta {
  display: flex;
  gap: 8px;
  margin-top: 4px;
  font-size: 12px;
  color: #c0c4cc;
}

.session-preview {
  margin-top: 4px;
  font-size: 12px;
  color: #909399;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.delete-btn {
  opacity: 0;
  transition: opacity 0.2s;
  flex-shrink: 0;
}
</style>

# Codex 执行指令 — 任务 7.6：会话管理侧边栏

## 任务目标

实现侧边栏会话列表，支持新建、切换、删除会话。

## 前置依赖

- 任务 7.1（项目初始化）、7.2（API 层）已完成

## 需要创建的文件

### 1. `web/src/components/Sidebar/SessionList.vue`

```vue
<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useSessionStore } from '../../stores/session'
import { useChatStore } from '../../stores/chat'
import { listSessions, createSession, deleteSession, getSessionMessages } from '../../api/session'

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
  } catch (e: any) {
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
  } catch (e) {
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
      chatStore.clearMessages()
      chatStore.currentSessionId = ''
    }
  } catch (e) {
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
      <el-button type="primary" size="small" @click="handleNew" :icon="'Plus'">
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
          :icon="'Delete'"
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
```

### 2. 更新 `web/src/views/ChatView.vue`

替换 sidebar 部分：

```vue
<script setup lang="ts">
import ChatPanel from '../components/ChatPanel/ChatPanel.vue'
import SessionList from '../components/Sidebar/SessionList.vue'
import { ref } from 'vue'

const chatPanelRef = ref<InstanceType<typeof ChatPanel>>()

function handleSwitchSession(sessionId: string) {
  // Reconnect WebSocket with new session
  // ChatPanel handles this internally via useStreaming
}
</script>

<template>
  <div class="chat-view">
    <div class="sidebar">
      <div class="sidebar-header">
        <h2>📄 Paper Agent</h2>
      </div>
      <SessionList
        @switch-session="handleSwitchSession"
      />
    </div>
    <div class="main">
      <ChatPanel ref="chatPanelRef" />
    </div>
  </div>
</template>
```

样式保持不变。

## 验收标准

- [ ] TypeScript 编译通过
- [ ] 显示会话列表（标题 + 时间 + 最后消息预览）
- [ ] 点击切换会话，加载历史消息
- [ ] 新建会话按钮，创建后自动切换
- [ ] 删除会话（二次确认弹窗）
- [ ] 当前会话高亮（蓝色左边框）
- [ ] 删除按钮 hover 时才显示
- [ ] 时间显示友好格式（刚刚/N分钟前/N小时前）

## 提交

```bash
git add web/src/
git commit -m "feat(web): implement session management sidebar

- Session list with title, time, preview
- Create/switch/delete sessions
- Active session highlight
- Delete confirmation dialog
- Friendly time formatting"
```

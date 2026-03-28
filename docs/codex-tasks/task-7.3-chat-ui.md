# Codex 执行指令 — 任务 7.3：聊天界面

## 任务目标

实现聊天主界面，支持消息发送、流式显示（打字机效果）、Agent 状态指示、Markdown 渲染。

## 前置依赖

- 任务 7.1（项目初始化）、7.2（WebSocket 通信层）已完成

## 需要创建/修改的文件

### 1. `web/src/components/common/MarkdownRenderer.vue`

```vue
<script setup lang="ts">
import { computed } from 'vue'
import MarkdownIt from 'markdown-it'

const props = defineProps<{
  content: string
}>()

const md = new MarkdownIt({
  html: false,
  linkify: true,
  typographer: true,
  breaks: true,
})

const rendered = computed(() => md.render(props.content))
</script>

<template>
  <div class="markdown-body" v-html="rendered" />
</template>

<style lang="scss">
.markdown-body {
  line-height: 1.7;
  color: #303133;
  word-break: break-word;

  h1, h2, h3, h4 {
    margin: 16px 0 8px;
    font-weight: 600;
  }

  h2 { font-size: 1.3em; }
  h3 { font-size: 1.1em; }

  p { margin: 8px 0; }

  ul, ol {
    padding-left: 24px;
    margin: 8px 0;
  }

  code {
    background: #f5f7fa;
    padding: 2px 6px;
    border-radius: 3px;
    font-size: 0.9em;
    font-family: 'Fira Code', monospace;
  }

  pre {
    background: #f5f7fa;
    padding: 12px 16px;
    border-radius: 6px;
    overflow-x: auto;
    margin: 12px 0;

    code {
      background: none;
      padding: 0;
    }
  }

  table {
    border-collapse: collapse;
    width: 100%;
    margin: 12px 0;

    th, td {
      border: 1px solid #dcdfe6;
      padding: 8px 12px;
      text-align: left;
    }

    th {
      background: #f5f7fa;
      font-weight: 600;
    }

    tr:hover td {
      background: #f5f7fa;
    }
  }

  blockquote {
    border-left: 4px solid #409eff;
    padding: 8px 16px;
    margin: 12px 0;
    background: #f5f7fa;
    color: #606266;
  }

  a {
    color: #409eff;
    text-decoration: none;
    &:hover { text-decoration: underline; }
  }
}
</style>
```

### 2. `web/src/components/common/LoadingIndicator.vue`

```vue
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
```

### 3. `web/src/components/ChatPanel/MessageBubble.vue`

```vue
<script setup lang="ts">
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
```

### 4. `web/src/components/ChatPanel/InputBar.vue`

```vue
<script setup lang="ts">
import { ref } from 'vue'

const emit = defineEmits<{
  send: [content: string, attachmentIds: string[]]
  upload: [file: File]
}>()

const inputText = ref('')
const attachedFiles = ref<{ id: string; name: string }[]>([])
const isComposing = ref(false)

function handleSend() {
  const content = inputText.value.trim()
  if (!content) return

  const ids = attachedFiles.value.map(f => f.id)
  emit('send', content, ids)
  inputText.value = ''
  attachedFiles.value = []
}

function handleKeydown(e: KeyboardEvent) {
  if (e.key === 'Enter' && !e.shiftKey && !isComposing.value) {
    e.preventDefault()
    handleSend()
  }
}

function handleFileChange(file: any) {
  const rawFile = file.raw || file
  if (rawFile.type !== 'application/pdf') {
    ElMessage.warning('仅支持 PDF 格式文件')
    return false
  }
  if (rawFile.size > 20 * 1024 * 1024) {
    ElMessage.warning('文件大小不能超过 20MB')
    return false
  }
  emit('upload', rawFile)
  return false // Prevent default upload
}

function addAttachment(id: string, name: string) {
  attachedFiles.value.push({ id, name })
}

function removeAttachment(index: number) {
  attachedFiles.value.splice(index, 1)
}

defineExpose({ addAttachment })
</script>

<template>
  <div class="input-bar">
    <div v-if="attachedFiles.length" class="attachments">
      <el-tag
        v-for="(file, index) in attachedFiles"
        :key="file.id"
        closable
        type="info"
        @close="removeAttachment(index)"
      >
        📄 {{ file.name }}
      </el-tag>
    </div>
    <div class="input-row">
      <el-upload
        :show-file-list="false"
        :before-upload="handleFileChange"
        accept=".pdf"
      >
        <el-button :icon="'UploadFilled'" circle />
      </el-upload>
      <el-input
        v-model="inputText"
        type="textarea"
        :autosize="{ minRows: 1, maxRows: 4 }"
        placeholder="输入你的研究问题..."
        @keydown="handleKeydown"
        @compositionstart="isComposing = true"
        @compositionend="isComposing = false"
        resize="none"
      />
      <el-button
        type="primary"
        :icon="'Promotion'"
        circle
        :disabled="!inputText.trim()"
        @click="handleSend"
      />
    </div>
  </div>
</template>

<style scoped lang="scss">
.input-bar {
  padding: 12px 20px;
  background: #fff;
  border-top: 1px solid #e4e7ed;
}

.attachments {
  display: flex;
  gap: 8px;
  margin-bottom: 8px;
  flex-wrap: wrap;
}

.input-row {
  display: flex;
  align-items: flex-end;
  gap: 8px;

  .el-input {
    flex: 1;
  }
}
</style>
```

### 5. `web/src/components/ChatPanel/ChatPanel.vue`

```vue
<script setup lang="ts">
import { ref, watch, nextTick, onMounted } from 'vue'
import { useChatStore } from '../../stores/chat'
import { useStreaming } from '../../composables/useStreaming'
import { uploadPDF } from '../../api/upload'
import MessageBubble from './MessageBubble.vue'
import InputBar from './InputBar.vue'
import LoadingIndicator from '../common/LoadingIndicator.vue'
import MarkdownRenderer from '../common/MarkdownRenderer.vue'

const chatStore = useChatStore()
const { connect, send, isConnected } = useStreaming()
const messagesContainer = ref<HTMLElement>()
const inputBarRef = ref<InstanceType<typeof InputBar>>()

onMounted(() => {
  connect()
})

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

<script lang="ts">
const suggestions = [
  '调研 2023-2025 RAG 优化的最新进展',
  '对比 RAG-Fusion、Self-RAG 和 CRAG 的优缺点',
  '帮我分析 LLM 幻觉问题的研究现状',
]
</script>

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
```

### 6. 更新 `web/src/views/ChatView.vue`

```vue
<script setup lang="ts">
import ChatPanel from '../components/ChatPanel/ChatPanel.vue'
</script>

<template>
  <div class="chat-view">
    <div class="sidebar">
      <div class="sidebar-header">
        <h2>Paper Agent</h2>
      </div>
      <div class="sidebar-content">
        <!-- SessionList 组件在任务 7.6 中实现 -->
        <p class="placeholder">会话列表开发中</p>
      </div>
    </div>
    <div class="main">
      <ChatPanel />
    </div>
  </div>
</template>

<style scoped lang="scss">
.chat-view {
  display: flex;
  height: 100vh;
}

.sidebar {
  width: 280px;
  border-right: 1px solid #e4e7ed;
  background: #fff;
  display: flex;
  flex-direction: column;

  .sidebar-header {
    padding: 16px;
    border-bottom: 1px solid #e4e7ed;

    h2 {
      font-size: 18px;
      color: #303133;
    }
  }

  .sidebar-content {
    flex: 1;
    overflow-y: auto;
  }

  .placeholder {
    padding: 20px;
    color: #c0c4cc;
    text-align: center;
    font-size: 13px;
  }
}

.main {
  flex: 1;
  display: flex;
  flex-direction: column;
}
</style>
```

## 验收标准

### 1. 编译检查

```bash
cd web
npx vue-tsc --noEmit
```

### 2. 验收 Checklist

- [ ] TypeScript 编译通过
- [ ] 消息气泡区分用户（蓝色右侧）/ 助手（白色左侧）
- [ ] 助手消息支持 Markdown 渲染（表格、代码块、列表、引用）
- [ ] 流式输出：逐字显示，有光标闪烁效果 `|`
- [ ] Agent 状态指示：消息上方显示脉冲动画 + "search_agent 正在检索 ArXiv..."
- [ ] 输入框支持 Enter 发送、Shift+Enter 换行
- [ ] 输入框支持中文输入法（compositionstart/end 处理）
- [ ] PDF 上传：点击按钮上传，仅接受 PDF，超 20MB 前端提示
- [ ] 上传成功后显示文件标签（可删除）
- [ ] 空状态显示欢迎语 + 建议问题按钮
- [ ] 消息列表自动滚动到底部

## 提交

```bash
git add web/src/
git commit -m "feat(web): implement chat interface with streaming and markdown

- MessageBubble with user/assistant styling
- Markdown rendering (tables, code, blockquotes, links)
- Streaming display with cursor blink animation
- Agent status indicator with pulse animation
- InputBar with Enter send, Shift+Enter newline, IME support
- PDF upload with drag-and-drop, type/size validation
- Empty state with suggestion buttons
- Auto-scroll to bottom on new messages"
```

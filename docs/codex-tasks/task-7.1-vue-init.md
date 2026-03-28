# Codex 执行指令 — 任务 7.1：Vue3 前端项目初始化

## 任务目标

使用 Vite 创建 Vue3 + TypeScript 项目，配置 Element Plus、Pinia、Vue Router、SCSS。

## 前置依赖

- 无代码依赖，可独立执行

## 执行步骤

### 1. 创建项目

```bash
cd paper-agent
npm create vite@latest web -- --template vue-ts
cd web
npm install
```

### 2. 安装依赖

```bash
npm install element-plus @element-plus/icons-vue
npm install pinia
npm install vue-router@4
npm install markdown-it
npm install sass
npm install @types/markdown-it -D
```

### 3. 创建目录结构

```bash
mkdir -p src/api
mkdir -p src/components/ChatPanel
mkdir -p src/components/ReportView
mkdir -p src/components/Sidebar
mkdir -p src/components/common
mkdir -p src/composables
mkdir -p src/stores
mkdir -p src/views
mkdir -p src/router
mkdir -p src/styles
mkdir -p src/types
```

### 4. `src/types/index.ts`

```typescript
// API 响应
export interface ApiResponse<T = any> {
  code: number
  message: string
  data?: T
}

// 会话
export interface Session {
  session_id: string
  title: string
  created_at: string
  last_message: string
  message_count: number
}

// 消息
export interface Message {
  role: 'user' | 'assistant'
  content: string
  timestamp: string
  metadata?: {
    agents_used?: string[]
  }
}

// WebSocket 事件
export interface StreamEvent {
  event: 'token' | 'agent_status' | 'done' | 'error' | 'session'
  data: StreamTokenData | StreamAgentStatusData | StreamErrorData | Record<string, string>
}

export interface StreamTokenData {
  content: string
}

export interface StreamAgentStatusData {
  agent: string
  step: string
}

export interface StreamErrorData {
  error: string
}

// 上传响应
export interface UploadResult {
  paper_id: string
  title: string
  page_count: number
  filename: string
}
```

### 5. `src/router/index.ts`

```typescript
import { createRouter, createWebHistory } from 'vue-router'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: '/',
      name: 'chat',
      component: () => import('../views/ChatView.vue'),
    },
    {
      path: '/history',
      name: 'history',
      component: () => import('../views/HistoryView.vue'),
    },
  ],
})

export default router
```

### 6. `src/stores/chat.ts`

```typescript
import { defineStore } from 'pinia'
import { ref } from 'vue'
import type { Message } from '../types'

export const useChatStore = defineStore('chat', () => {
  const messages = ref<Message[]>([])
  const currentSessionId = ref<string>('')
  const isStreaming = ref(false)
  const agentStatus = ref<{ agent: string; step: string } | null>(null)
  const streamingContent = ref('')

  function addUserMessage(content: string) {
    messages.value.push({
      role: 'user',
      content,
      timestamp: new Date().toISOString(),
    })
  }

  function appendStreamToken(token: string) {
    streamingContent.value += token
  }

  function finalizeAssistantMessage(content: string) {
    messages.value.push({
      role: 'assistant',
      content,
      timestamp: new Date().toISOString(),
    })
    streamingContent.value = ''
    isStreaming.value = false
    agentStatus.value = null
  }

  function setAgentStatus(agent: string, step: string) {
    agentStatus.value = { agent, step }
  }

  function clearMessages() {
    messages.value = []
    streamingContent.value = ''
    isStreaming.value = false
    agentStatus.value = null
  }

  function loadMessages(msgs: Message[]) {
    messages.value = msgs
  }

  return {
    messages,
    currentSessionId,
    isStreaming,
    agentStatus,
    streamingContent,
    addUserMessage,
    appendStreamToken,
    finalizeAssistantMessage,
    setAgentStatus,
    clearMessages,
    loadMessages,
  }
})
```

### 7. `src/stores/session.ts`

```typescript
import { defineStore } from 'pinia'
import { ref } from 'vue'
import type { Session } from '../types'

export const useSessionStore = defineStore('session', () => {
  const sessions = ref<Session[]>([])
  const currentSessionId = ref<string>('')

  function setSessions(list: Session[]) {
    sessions.value = list
  }

  function setCurrentSession(id: string) {
    currentSessionId.value = id
  }

  function addSession(session: Session) {
    sessions.value.unshift(session)
  }

  function removeSession(id: string) {
    sessions.value = sessions.value.filter(s => s.session_id !== id)
  }

  return {
    sessions,
    currentSessionId,
    setSessions,
    setCurrentSession,
    addSession,
    removeSession,
  }
})
```

### 8. `src/styles/variables.scss`

```scss
// Colors
$primary: #409eff;
$success: #67c23a;
$warning: #e6a23c;
$danger: #f56c6c;
$info: #909399;

$bg-primary: #f5f7fa;
$bg-sidebar: #ffffff;
$bg-chat: #f0f2f5;

$text-primary: #303133;
$text-regular: #606266;
$text-secondary: #909399;

// Layout
$sidebar-width: 280px;
$input-bar-height: 80px;
$header-height: 56px;

// Shadows
$shadow-light: 0 2px 12px 0 rgba(0, 0, 0, 0.1);
```

### 9. `src/main.ts`

```typescript
import { createApp } from 'vue'
import { createPinia } from 'pinia'
import ElementPlus from 'element-plus'
import 'element-plus/dist/index.css'
import * as ElementPlusIconsVue from '@element-plus/icons-vue'

import App from './App.vue'
import router from './router'

const app = createApp(App)

app.use(createPinia())
app.use(router)
app.use(ElementPlus)

// Register all icons
for (const [key, component] of Object.entries(ElementPlusIconsVue)) {
  app.component(key, component)
}

app.mount('#app')
```

### 10. `src/App.vue`

```vue
<script setup lang="ts">
import { RouterView } from 'vue-router'
</script>

<template>
  <RouterView />
</template>

<style>
* {
  margin: 0;
  padding: 0;
  box-sizing: border-box;
}

html, body, #app {
  height: 100%;
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
}
</style>
```

### 11. `src/views/ChatView.vue`

```vue
<script setup lang="ts">
</script>

<template>
  <div class="chat-view">
    <div class="sidebar">
      <!-- Sidebar placeholder -->
      <div class="sidebar-header">
        <h2>Paper Agent</h2>
      </div>
    </div>
    <div class="main">
      <div class="messages">
        <!-- Messages placeholder -->
        <p style="color: #909399; text-align: center; margin-top: 40vh;">
          开始你的学术研究之旅
        </p>
      </div>
      <div class="input-bar">
        <!-- Input placeholder -->
      </div>
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

  .sidebar-header {
    padding: 16px;
    border-bottom: 1px solid #e4e7ed;

    h2 {
      font-size: 18px;
      color: #303133;
    }
  }
}

.main {
  flex: 1;
  display: flex;
  flex-direction: column;
  background: #f0f2f5;
}

.messages {
  flex: 1;
  overflow-y: auto;
  padding: 20px;
}

.input-bar {
  padding: 16px 20px;
  background: #fff;
  border-top: 1px solid #e4e7ed;
}
</style>
```

### 12. `src/views/HistoryView.vue`

```vue
<script setup lang="ts">
</script>

<template>
  <div class="history-view">
    <h1>历史会话</h1>
    <p>开发中...</p>
  </div>
</template>

<style scoped>
.history-view {
  padding: 40px;
}
</style>
```

### 13. 更新 `vite.config.ts`

```typescript
import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  server: {
    port: 3000,
    proxy: {
      '/api': {
        target: 'http://localhost:8080',
        changeOrigin: true,
      },
      '/ws': {
        target: 'ws://localhost:8080',
        ws: true,
      },
    },
  },
  css: {
    preprocessorOptions: {
      scss: {
        additionalData: `@use "@/styles/variables.scss" as *;`,
      },
    },
  },
  resolve: {
    alias: {
      '@': '/src',
    },
  },
})
```

## 验收标准

### 1. 启动检查

```bash
cd web
npm run dev
```

预期：
- 控制台无报错
- 浏览器打开 http://localhost:3000 显示页面
- 左侧 sidebar 显示 "Paper Agent"
- 中间区域显示 "开始你的学术研究之旅"

### 2. 验收 Checklist

- [ ] `npm run dev` 启动成功，无 TypeScript 编译错误
- [ ] Element Plus 组件可正常使用
- [ ] Pinia store 正确初始化
- [ ] 路由配置：`/` 聊天页、`/history` 历史页
- [ ] Vite proxy 配置：`/api` → Go Gateway，`/ws` → WebSocket
- [ ] SCSS 变量文件全局可用
- [ ] TypeScript 类型定义完整（types/index.ts）
- [ ] 目录结构符合 `docs/01-architecture.md` 前端约定

## 提交

```bash
git add web/
git commit -m "feat(web): init Vue3 + Vite + TypeScript project

- Vue3 with Composition API and script setup
- Element Plus component library with icons
- Pinia stores for chat and session state
- Vue Router with chat and history views
- SCSS variables and global styles
- Vite proxy config for API and WebSocket
- TypeScript type definitions for all API interfaces"
```

## 注意事项

1. `npm run dev` 是开发服务器，不要在 Codex 中长时间运行
2. proxy 配置假设 Go Gateway 在 localhost:8080，Docker 环境下需调整
3. ChatView 和 HistoryView 当前是骨架，后续任务填充组件

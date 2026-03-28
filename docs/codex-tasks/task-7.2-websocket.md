# Codex 执行指令 — 任务 7.2：WebSocket 通信层

## 任务目标

实现 WebSocket 连接管理 composable，处理流式消息，支持断线重连。

## 前置依赖

- 任务 7.1 已完成（Vue3 项目初始化、类型定义、Pinia stores）

## 需要创建的文件

### 1. `web/src/composables/useWebSocket.ts`

```typescript
import { ref, onUnmounted } from 'vue'
import type { StreamEvent, StreamTokenData, StreamAgentStatusData, StreamErrorData } from '../types'

interface UseWebSocketOptions {
  onToken?: (data: StreamTokenData) => void
  onAgentStatus?: (data: StreamAgentStatusData) => void
  onDone?: (data: StreamTokenData) => void
  onError?: (data: StreamErrorData) => void
  onSessionId?: (sessionId: string) => void
}

export function useWebSocket(options: UseWebSocketOptions = {}) {
  const ws = ref<WebSocket | null>(null)
  const isConnected = ref(false)
  const sessionId = ref('')

  let reconnectAttempts = 0
  const maxReconnectAttempts = 3
  let reconnectTimer: ReturnType<typeof setTimeout> | null = null

  function getBaseUrl(): string {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    // In dev mode, Vite proxy handles /ws
    return `${protocol}//${window.location.host}`
  }

  function connect(sid?: string) {
    if (ws.value?.readyState === WebSocket.OPEN) return

    const url = sid
      ? `${getBaseUrl()}/ws?session_id=${sid}`
      : `${getBaseUrl()}/ws`

    ws.value = new WebSocket(url)

    ws.value.onopen = () => {
      isConnected.value = true
      reconnectAttempts = 0
    }

    ws.value.onmessage = (event: MessageEvent) => {
      try {
        const msg: StreamEvent = JSON.parse(event.data)
        handleMessage(msg)
      } catch (e) {
        console.error('Failed to parse WebSocket message:', e)
      }
    }

    ws.value.onclose = (event: CloseEvent) => {
      isConnected.value = false
      if (!event.wasClean && reconnectAttempts < maxReconnectAttempts) {
        scheduleReconnect()
      }
    }

    ws.value.onerror = () => {
      isConnected.value = false
    }
  }

  function handleMessage(msg: StreamEvent) {
    switch (msg.event) {
      case 'token':
        options.onToken?.(msg.data as StreamTokenData)
        break
      case 'agent_status':
        options.onAgentStatus?.(msg.data as StreamAgentStatusData)
        break
      case 'done':
        options.onDone?.(msg.data as StreamTokenData)
        break
      case 'error':
        options.onError?.(msg.data as StreamErrorData)
        break
      case 'session':
        const data = msg.data as Record<string, string>
        sessionId.value = data.session_id || ''
        options.onSessionId?.(sessionId.value)
        break
    }
  }

  function scheduleReconnect() {
    reconnectAttempts++
    const delay = Math.pow(2, reconnectAttempts - 1) * 1000 // 1s, 2s, 4s
    console.log(`WebSocket reconnecting in ${delay}ms (attempt ${reconnectAttempts})`)
    reconnectTimer = setTimeout(() => {
      connect(sessionId.value || undefined)
    }, delay)
  }

  function sendMessage(content: string, attachmentIds: string[] = []) {
    if (!ws.value || ws.value.readyState !== WebSocket.OPEN) {
      console.error('WebSocket not connected')
      return false
    }

    ws.value.send(JSON.stringify({
      type: 'chat',
      content,
      attachment_ids: attachmentIds,
    }))
    return true
  }

  function disconnect() {
    if (reconnectTimer) {
      clearTimeout(reconnectTimer)
      reconnectTimer = null
    }
    reconnectAttempts = maxReconnectAttempts // Prevent auto-reconnect
    ws.value?.close(1000, 'User disconnect')
    ws.value = null
    isConnected.value = false
  }

  onUnmounted(() => {
    disconnect()
  })

  return {
    connect,
    disconnect,
    sendMessage,
    isConnected,
    sessionId,
  }
}
```

### 2. `web/src/composables/useStreaming.ts`

```typescript
import { useChatStore } from '../stores/chat'
import { useWebSocket } from './useWebSocket'
import type { StreamTokenData, StreamAgentStatusData, StreamErrorData } from '../types'

/**
 * High-level composable that wires WebSocket events to the chat store.
 */
export function useStreaming() {
  const chatStore = useChatStore()

  const { connect, disconnect, sendMessage, isConnected, sessionId } = useWebSocket({
    onToken(data: StreamTokenData) {
      chatStore.appendStreamToken(data.content)
    },
    onAgentStatus(data: StreamAgentStatusData) {
      chatStore.setAgentStatus(data.agent, data.step)
    },
    onDone(data: StreamTokenData) {
      chatStore.finalizeAssistantMessage(data.content)
    },
    onError(data: StreamErrorData) {
      chatStore.finalizeAssistantMessage(`⚠️ 错误：${data.error}`)
    },
    onSessionId(id: string) {
      chatStore.currentSessionId = id
    },
  })

  function send(content: string, attachmentIds: string[] = []) {
    chatStore.addUserMessage(content)
    chatStore.isStreaming = true
    chatStore.streamingContent = ''
    sendMessage(content, attachmentIds)
  }

  return {
    connect,
    disconnect,
    send,
    isConnected,
    sessionId,
  }
}
```

### 3. `web/src/api/chat.ts`

```typescript
import type { ApiResponse, UploadResult } from '../types'

const API_BASE = '/api/v1'

/**
 * SSE-based chat (fallback when WebSocket unavailable).
 */
export async function chatSSE(
  sessionId: string,
  content: string,
  attachmentIds: string[],
  onEvent: (event: string, data: any) => void,
): Promise<void> {
  const response = await fetch(`${API_BASE}/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      session_id: sessionId,
      content,
      attachment_ids: attachmentIds,
    }),
  })

  if (!response.ok) {
    throw new Error(`Chat request failed: ${response.status}`)
  }

  const reader = response.body?.getReader()
  if (!reader) throw new Error('No response body')

  const decoder = new TextDecoder()
  let buffer = ''

  while (true) {
    const { done, value } = await reader.read()
    if (done) break

    buffer += decoder.decode(value, { stream: true })
    const lines = buffer.split('\n')
    buffer = lines.pop() || ''

    let currentEvent = ''
    for (const line of lines) {
      if (line.startsWith('event: ')) {
        currentEvent = line.slice(7).trim()
      } else if (line.startsWith('data: ') && currentEvent) {
        try {
          const data = JSON.parse(line.slice(6))
          onEvent(currentEvent, data)
        } catch (e) {
          // ignore parse errors
        }
        currentEvent = ''
      }
    }
  }
}
```

### 4. `web/src/api/session.ts`

```typescript
import type { ApiResponse, Session, Message } from '../types'

const API_BASE = '/api/v1'

export async function createSession(): Promise<{ session_id: string; created_at: string }> {
  const res = await fetch(`${API_BASE}/sessions`, { method: 'POST' })
  const json: ApiResponse = await res.json()
  if (json.code !== 0) throw new Error(json.message)
  return json.data
}

export async function listSessions(): Promise<Session[]> {
  const res = await fetch(`${API_BASE}/sessions`)
  const json: ApiResponse = await res.json()
  if (json.code !== 0) throw new Error(json.message)
  return json.data || []
}

export async function getSessionMessages(sessionId: string): Promise<{ session_id: string; messages: Message[] }> {
  const res = await fetch(`${API_BASE}/sessions/${sessionId}/messages`)
  const json: ApiResponse = await res.json()
  if (json.code !== 0) throw new Error(json.message)
  return json.data
}

export async function deleteSession(sessionId: string): Promise<void> {
  const res = await fetch(`${API_BASE}/sessions/${sessionId}`, { method: 'DELETE' })
  const json: ApiResponse = await res.json()
  if (json.code !== 0) throw new Error(json.message)
}
```

### 5. `web/src/api/upload.ts`

```typescript
import type { ApiResponse, UploadResult } from '../types'

const API_BASE = '/api/v1'

export async function uploadPDF(sessionId: string, file: File): Promise<UploadResult> {
  const formData = new FormData()
  formData.append('session_id', sessionId)
  formData.append('file', file)

  const res = await fetch(`${API_BASE}/upload`, {
    method: 'POST',
    body: formData,
  })

  const json: ApiResponse<UploadResult> = await res.json()

  if (json.code !== 0) {
    throw new Error(json.message)
  }

  return json.data!
}
```

## 验收标准

### 1. 编译检查

```bash
cd web
npx vue-tsc --noEmit
```

预期：TypeScript 编译无错误。

### 2. 验收 Checklist

- [ ] TypeScript 编译通过，无类型错误
- [ ] `useWebSocket` 支持连接、断开、发送消息
- [ ] WebSocket 断线自动重连（3 次，指数退避 1s/2s/4s）
- [ ] 组件卸载时自动断开连接（onUnmounted）
- [ ] `isConnected` ref 实时反映连接状态
- [ ] `useStreaming` 正确将 WebSocket 事件映射到 chat store
- [ ] SSE fallback 实现（chatSSE 函数）
- [ ] Session API 封装完整（create/list/messages/delete）
- [ ] Upload API 封装完整（multipart/form-data）
- [ ] 所有函数有正确的 TypeScript 类型

## 提交

```bash
git add web/src/
git commit -m "feat(web): implement WebSocket communication layer

- useWebSocket composable with auto-reconnect (3 attempts, exponential backoff)
- useStreaming composable wiring WS events to Pinia chat store
- SSE fallback for chat (chatSSE function)
- Session API client (create/list/messages/delete)
- Upload API client (multipart PDF upload)
- Full TypeScript typing for all API interfaces"
```

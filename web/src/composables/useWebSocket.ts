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
      case 'session': {
        const data = msg.data as Record<string, string>
        sessionId.value = data.session_id || ''
        options.onSessionId?.(sessionId.value)
        break
      }
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

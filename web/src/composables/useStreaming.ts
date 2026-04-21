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
      chatStore.finalizeAssistantMessage(`错误：${data.error}`)
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

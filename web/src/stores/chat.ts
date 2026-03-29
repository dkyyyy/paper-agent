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

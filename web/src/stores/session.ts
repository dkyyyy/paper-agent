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

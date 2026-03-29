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

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

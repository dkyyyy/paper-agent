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

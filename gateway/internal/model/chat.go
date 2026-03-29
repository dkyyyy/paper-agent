package model

// ChatRequest is the HTTP request body for chat.
type ChatRequest struct {
	SessionID     string   `json:"session_id"`
	Content       string   `json:"content" binding:"required"`
	AttachmentIDs []string `json:"attachment_ids"`
}

// Response is the unified HTTP response wrapper.
type Response struct {
	Code    int         `json:"code"`
	Message string      `json:"message"`
	Data    interface{} `json:"data,omitempty"`
}

// WSMessage is the WebSocket incoming message format.
type WSMessage struct {
	Type          string   `json:"type"`
	Content       string   `json:"content"`
	AttachmentIDs []string `json:"attachment_ids"`
}

// StreamEvent is the WebSocket and SSE outgoing event format.
type StreamEvent struct {
	Event string      `json:"event"`
	Data  interface{} `json:"data"`
}

// StreamTokenData is the token event payload.
type StreamTokenData struct {
	Content string `json:"content"`
}

// StreamAgentStatusData is the agent_status event payload.
type StreamAgentStatusData struct {
	Agent string `json:"agent"`
	Step  string `json:"step"`
}

// StreamErrorData is the error event payload.
type StreamErrorData struct {
	Error string `json:"error"`
}

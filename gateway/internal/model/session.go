package model

import "time"

// Session stores a chat session and its message history.
type Session struct {
	ID           string    `json:"session_id"`
	Title        string    `json:"title"`
	CreatedAt    time.Time `json:"created_at"`
	UpdatedAt    time.Time `json:"updated_at"`
	Messages     []Message `json:"messages"`
	MessageCount int       `json:"message_count"`
}

// SessionSummary is the condensed view returned by session list APIs.
type SessionSummary struct {
	ID           string    `json:"session_id"`
	Title        string    `json:"title"`
	CreatedAt    time.Time `json:"created_at"`
	LastMessage  string    `json:"last_message"`
	MessageCount int       `json:"message_count"`
}

// Message is a single chat message.
type Message struct {
	Role      string                 `json:"role"`
	Content   string                 `json:"content"`
	Metadata  map[string]interface{} `json:"metadata,omitempty"`
	Timestamp time.Time              `json:"timestamp"`
}

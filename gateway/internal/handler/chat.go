package handler

import (
	"encoding/json"
	"fmt"
	"io"
	"log/slog"
	"net/http"

	"github.com/dkyyyy/paper-agent/gateway/internal/grpc/agentpb"
	"github.com/dkyyyy/paper-agent/gateway/internal/model"
	"github.com/dkyyyy/paper-agent/gateway/internal/service"
	"github.com/gin-gonic/gin"
	"github.com/gorilla/websocket"
)

// ChatHandler handles SSE and WebSocket chat endpoints.
type ChatHandler struct {
	sessionSvc  service.SessionService
	agentClient *service.AgentClient
}

// NewChatHandler creates a chat handler.
func NewChatHandler(sessionSvc service.SessionService, agentClient *service.AgentClient) *ChatHandler {
	return &ChatHandler{
		sessionSvc:  sessionSvc,
		agentClient: agentClient,
	}
}

// ChatSSE handles POST /api/v1/chat with Server-Sent Events streaming.
func (h *ChatHandler) ChatSSE(c *gin.Context) {
	var req model.ChatRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, model.Response{Code: 40001, Message: "content is required"})
		return
	}

	if req.SessionID == "" {
		sess, err := h.sessionSvc.Create(c.Request.Context())
		if err != nil {
			c.JSON(http.StatusInternalServerError, model.Response{Code: 50001, Message: "failed to create session"})
			return
		}
		req.SessionID = sess.ID
	}

	if err := h.sessionSvc.AppendMessage(c.Request.Context(), req.SessionID, model.Message{
		Role:    "user",
		Content: req.Content,
	}); err != nil {
		slog.Error("append user message failed", "error", err, "session_id", req.SessionID)
		c.JSON(http.StatusInternalServerError, model.Response{Code: 50001, Message: "failed to save user message"})
		return
	}

	grpcReq := &agentpb.ChatRequest{
		SessionId:     req.SessionID,
		Content:       req.Content,
		AttachmentIds: req.AttachmentIDs,
	}

	eventCh, errCh := h.agentClient.Chat(c.Request.Context(), grpcReq)

	c.Header("Content-Type", "text/event-stream")
	c.Header("Cache-Control", "no-cache")
	c.Header("Connection", "keep-alive")
	c.Header("X-Session-ID", req.SessionID)

	fullContent := ""
	c.Stream(func(w io.Writer) bool {
		select {
		case event, ok := <-eventCh:
			if !ok {
				return false
			}

			var data interface{}
			switch event.EventType {
			case "token":
				fullContent += event.Content
				data = model.StreamTokenData{Content: event.Content}
			case "agent_status":
				data = model.StreamAgentStatusData{Agent: event.AgentName, Step: event.StepDescription}
			case "done":
				fullContent = event.Content
				data = model.StreamTokenData{Content: event.Content}
			case "error":
				data = model.StreamErrorData{Error: event.ErrorMessage}
			default:
				data = model.StreamErrorData{Error: "unknown event type"}
			}

			jsonData, err := json.Marshal(model.StreamEvent{Event: event.EventType, Data: data})
			if err != nil {
				slog.Error("marshal stream event failed", "error", err)
				return false
			}
			if _, err := fmt.Fprintf(w, "event: %s\ndata: %s\n\n", event.EventType, jsonData); err != nil {
				slog.Error("write sse event failed", "error", err)
				return false
			}
			return true

		case err, ok := <-errCh:
			if !ok {
				return false
			}
			slog.Error("agent stream error", "error", err)
			jsonData, marshalErr := json.Marshal(model.StreamEvent{Event: "error", Data: model.StreamErrorData{Error: err.Error()}})
			if marshalErr != nil {
				slog.Error("marshal error event failed", "error", marshalErr)
				return false
			}
			if _, writeErr := fmt.Fprintf(w, "event: error\ndata: %s\n\n", jsonData); writeErr != nil {
				slog.Error("write sse error event failed", "error", writeErr)
			}
			return false

		case <-c.Request.Context().Done():
			return false
		}
	})

	if fullContent != "" {
		if err := h.sessionSvc.AppendMessage(c.Request.Context(), req.SessionID, model.Message{
			Role:    "assistant",
			Content: fullContent,
		}); err != nil {
			slog.Error("append assistant message failed", "error", err, "session_id", req.SessionID)
		}
	}
}

var upgrader = websocket.Upgrader{
	CheckOrigin: func(r *http.Request) bool { return true },
}

// ChatWS handles GET /ws?session_id=xxx WebSocket connection.
func (h *ChatHandler) ChatWS(c *gin.Context) {
	sessionID := c.Query("session_id")

	if sessionID == "" {
		sess, err := h.sessionSvc.Create(c.Request.Context())
		if err != nil {
			c.JSON(http.StatusInternalServerError, model.Response{Code: 50001, Message: "failed to create session"})
			return
		}
		sessionID = sess.ID
	}

	conn, err := upgrader.Upgrade(c.Writer, c.Request, nil)
	if err != nil {
		slog.Error("websocket upgrade failed", "error", err)
		return
	}
	defer conn.Close()

	if err := conn.WriteJSON(model.StreamEvent{Event: "session", Data: map[string]string{"session_id": sessionID}}); err != nil {
		slog.Error("write websocket session event failed", "error", err)
		return
	}

	for {
		_, msgBytes, err := conn.ReadMessage()
		if err != nil {
			if websocket.IsUnexpectedCloseError(err, websocket.CloseGoingAway, websocket.CloseNormalClosure) {
				slog.Error("websocket read error", "error", err)
			}
			return
		}

		var wsMsg model.WSMessage
		if err := json.Unmarshal(msgBytes, &wsMsg); err != nil {
			if writeErr := conn.WriteJSON(model.StreamEvent{Event: "error", Data: model.StreamErrorData{Error: "invalid message format"}}); writeErr != nil {
				slog.Error("write websocket format error failed", "error", writeErr)
				return
			}
			continue
		}

		if wsMsg.Content == "" {
			if writeErr := conn.WriteJSON(model.StreamEvent{Event: "error", Data: model.StreamErrorData{Error: "content is required"}}); writeErr != nil {
				slog.Error("write websocket validation error failed", "error", writeErr)
				return
			}
			continue
		}

		if err := h.sessionSvc.AppendMessage(c.Request.Context(), sessionID, model.Message{
			Role:    "user",
			Content: wsMsg.Content,
		}); err != nil {
			slog.Error("append websocket user message failed", "error", err, "session_id", sessionID)
			if writeErr := conn.WriteJSON(model.StreamEvent{Event: "error", Data: model.StreamErrorData{Error: "failed to save user message"}}); writeErr != nil {
				slog.Error("write websocket persistence error failed", "error", writeErr)
				return
			}
			continue
		}

		grpcReq := &agentpb.ChatRequest{
			SessionId:     sessionID,
			Content:       wsMsg.Content,
			AttachmentIds: wsMsg.AttachmentIDs,
		}

		eventCh, errCh := h.agentClient.Chat(c.Request.Context(), grpcReq)
		fullContent := ""

		streaming := true
		for streaming {
			select {
			case event, ok := <-eventCh:
				if !ok {
					streaming = false
					break
				}

				var data interface{}
				switch event.EventType {
				case "token":
					fullContent += event.Content
					data = model.StreamTokenData{Content: event.Content}
				case "agent_status":
					data = model.StreamAgentStatusData{Agent: event.AgentName, Step: event.StepDescription}
				case "done":
					fullContent = event.Content
					data = model.StreamTokenData{Content: event.Content}
				case "error":
					data = model.StreamErrorData{Error: event.ErrorMessage}
				default:
					data = model.StreamErrorData{Error: "unknown event type"}
				}

				if err := conn.WriteJSON(model.StreamEvent{Event: event.EventType, Data: data}); err != nil {
					slog.Error("write websocket stream event failed", "error", err)
					return
				}

			case err, ok := <-errCh:
				if ok {
					slog.Error("agent stream error", "error", err)
					if writeErr := conn.WriteJSON(model.StreamEvent{Event: "error", Data: model.StreamErrorData{Error: err.Error()}}); writeErr != nil {
						slog.Error("write websocket agent error failed", "error", writeErr)
						return
					}
				}
				streaming = false
			}
		}

		if fullContent != "" {
			if err := h.sessionSvc.AppendMessage(c.Request.Context(), sessionID, model.Message{
				Role:    "assistant",
				Content: fullContent,
			}); err != nil {
				slog.Error("append websocket assistant message failed", "error", err, "session_id", sessionID)
			}
		}
	}
}

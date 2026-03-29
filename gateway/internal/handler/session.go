package handler

import (
	"net/http"

	"github.com/dkyyyy/paper-agent/gateway/internal/model"
	"github.com/dkyyyy/paper-agent/gateway/internal/service"
	"github.com/gin-gonic/gin"
)

// SessionHandler handles session CRUD endpoints.
type SessionHandler struct {
	sessionSvc service.SessionService
}

// NewSessionHandler creates a session handler.
func NewSessionHandler(sessionSvc service.SessionService) *SessionHandler {
	return &SessionHandler{sessionSvc: sessionSvc}
}

// Create handles POST /api/v1/sessions.
func (h *SessionHandler) Create(c *gin.Context) {
	sess, err := h.sessionSvc.Create(c.Request.Context())
	if err != nil {
		c.JSON(http.StatusInternalServerError, model.Response{Code: 50001, Message: "failed to create session"})
		return
	}
	c.JSON(http.StatusOK, model.Response{Code: 0, Data: gin.H{
		"session_id": sess.ID,
		"created_at": sess.CreatedAt,
	}})
}

// List handles GET /api/v1/sessions.
func (h *SessionHandler) List(c *gin.Context) {
	list, err := h.sessionSvc.List(c.Request.Context())
	if err != nil {
		c.JSON(http.StatusInternalServerError, model.Response{Code: 50001, Message: "failed to list sessions"})
		return
	}
	c.JSON(http.StatusOK, model.Response{Code: 0, Data: list})
}

// GetMessages handles GET /api/v1/sessions/:id/messages.
func (h *SessionHandler) GetMessages(c *gin.Context) {
	sessionID := c.Param("id")
	sess, err := h.sessionSvc.Get(c.Request.Context(), sessionID)
	if err != nil {
		c.JSON(http.StatusNotFound, model.Response{Code: 40004, Message: "会话不存在"})
		return
	}
	c.JSON(http.StatusOK, model.Response{Code: 0, Data: gin.H{
		"session_id": sess.ID,
		"messages":   sess.Messages,
	}})
}

// Delete handles DELETE /api/v1/sessions/:id.
func (h *SessionHandler) Delete(c *gin.Context) {
	sessionID := c.Param("id")
	if err := h.sessionSvc.Delete(c.Request.Context(), sessionID); err != nil {
		c.JSON(http.StatusNotFound, model.Response{Code: 40004, Message: "会话不存在"})
		return
	}
	c.JSON(http.StatusOK, model.Response{Code: 0, Message: "success"})
}

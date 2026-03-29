package handler

import (
	"log/slog"
	"net/http"
	"os"
	"path/filepath"
	"strings"

	"github.com/dkyyyy/paper-agent/gateway/internal/grpc/agentpb"
	"github.com/dkyyyy/paper-agent/gateway/internal/model"
	"github.com/dkyyyy/paper-agent/gateway/internal/service"
	"github.com/gin-gonic/gin"
)

// UploadHandler handles PDF upload requests.
type UploadHandler struct {
	fileSvc     *service.FileService
	agentClient *service.AgentClient
	maxRetry    int
}

// NewUploadHandler creates a new upload handler.
func NewUploadHandler(fileSvc *service.FileService, agentClient *service.AgentClient, maxRetry int) *UploadHandler {
	return &UploadHandler{
		fileSvc:     fileSvc,
		agentClient: agentClient,
		maxRetry:    maxRetry,
	}
}

// Upload handles POST /api/v1/upload.
func (h *UploadHandler) Upload(c *gin.Context) {
	sessionID := c.PostForm("session_id")
	if sessionID == "" {
		c.JSON(http.StatusBadRequest, model.Response{Code: 40001, Message: "session_id is required"})
		return
	}

	file, header, err := c.Request.FormFile("file")
	if err != nil {
		c.JSON(http.StatusBadRequest, model.Response{Code: 40001, Message: "file is required"})
		return
	}
	defer file.Close()

	ext := strings.ToLower(filepath.Ext(header.Filename))
	if ext != ".pdf" {
		c.JSON(http.StatusBadRequest, model.Response{Code: 40002, Message: "仅支持 PDF 格式文件"})
		return
	}

	result, err := h.fileSvc.Save(sessionID, header.Filename, file)
	if err != nil {
		if strings.Contains(err.Error(), "exceeds max size") {
			c.JSON(http.StatusRequestEntityTooLarge, model.Response{Code: 40003, Message: "文件大小不能超过 20MB"})
			return
		}
		slog.Error("save file failed", "error", err)
		c.JSON(http.StatusInternalServerError, model.Response{Code: 50001, Message: "文件保存失败"})
		return
	}

	fileContent, err := readFileBytes(result.FilePath)
	if err != nil {
		_ = h.fileSvc.Remove(result.FilePath)
		slog.Error("read file for grpc failed", "error", err)
		c.JSON(http.StatusInternalServerError, model.Response{Code: 50001, Message: "文件读取失败"})
		return
	}

	grpcReq := &agentpb.UploadPaperRequest{
		SessionId:   sessionID,
		Filename:    header.Filename,
		FileContent: fileContent,
	}

	resp, err := h.agentClient.UploadPaper(c.Request.Context(), grpcReq, h.maxRetry)
	if err != nil {
		_ = h.fileSvc.Remove(result.FilePath)
		slog.Error("agent upload paper failed", "error", err)
		c.JSON(http.StatusBadGateway, model.Response{Code: 50004, Message: "论文解析服务不可用"})
		return
	}

	if !resp.Success {
		_ = h.fileSvc.Remove(result.FilePath)
		c.JSON(http.StatusInternalServerError, model.Response{Code: 50001, Message: "PDF 解析失败，请检查文件是否损坏"})
		return
	}

	c.JSON(http.StatusOK, model.Response{
		Code:    0,
		Message: "success",
		Data: gin.H{
			"paper_id":   resp.PaperId,
			"title":      resp.Title,
			"page_count": resp.PageCount,
			"filename":   header.Filename,
		},
	})
}

func readFileBytes(path string) ([]byte, error) {
	return os.ReadFile(path)
}

# Codex 执行指令 — 任务 2.5：文件上传接口

## 任务目标

实现 PDF 文件上传接口，存储到本地磁盘，通过 gRPC 通知 Agent 服务解析。

## 前置依赖

- 任务 2.1（配置管理）、2.3（gRPC 客户端）已完成
- 参考文档：`docs/04-api-design.md` 文件上传接口

## 需要创建的文件

### 1. `gateway/internal/service/file.go`

```go
package service

import (
	"crypto/md5"
	"fmt"
	"io"
	"os"
	"path/filepath"

	"github.com/google/uuid"
)

type FileService struct {
	uploadDir string
	maxSize   int64
}

func NewFileService(uploadDir string, maxSize int64) *FileService {
	return &FileService{uploadDir: uploadDir, maxSize: maxSize}
}

// SaveResult contains the result of saving a file.
type SaveResult struct {
	FilePath string
	FileHash string
	FileSize int64
}

// Save writes the file content to disk under uploads/{sessionID}/{uuid}.pdf.
// Returns the file path, MD5 hash, and size.
func (s *FileService) Save(sessionID string, filename string, content io.Reader) (*SaveResult, error) {
	dir := filepath.Join(s.uploadDir, sessionID)
	if err := os.MkdirAll(dir, 0755); err != nil {
		return nil, fmt.Errorf("create upload dir: %w", err)
	}

	ext := filepath.Ext(filename)
	destPath := filepath.Join(dir, uuid.New().String()+ext)

	f, err := os.Create(destPath)
	if err != nil {
		return nil, fmt.Errorf("create file: %w", err)
	}
	defer f.Close()

	hash := md5.New()
	writer := io.MultiWriter(f, hash)

	size, err := io.Copy(writer, io.LimitReader(content, s.maxSize+1))
	if err != nil {
		os.Remove(destPath)
		return nil, fmt.Errorf("write file: %w", err)
	}
	if size > s.maxSize {
		os.Remove(destPath)
		return nil, fmt.Errorf("file exceeds max size %d bytes", s.maxSize)
	}

	return &SaveResult{
		FilePath: destPath,
		FileHash: fmt.Sprintf("%x", hash.Sum(nil)),
		FileSize: size,
	}, nil
}

// Remove deletes a file from disk.
func (s *FileService) Remove(path string) error {
	return os.Remove(path)
}
```

### 2. `gateway/internal/handler/upload.go`

```go
package handler

import (
	"log/slog"
	"net/http"
	"path/filepath"
	"strings"

	"github.com/dkyyyy/paper-agent/gateway/internal/grpc/agentpb"
	"github.com/dkyyyy/paper-agent/gateway/internal/model"
	"github.com/dkyyyy/paper-agent/gateway/internal/service"
	"github.com/gin-gonic/gin"
)

type UploadHandler struct {
	fileSvc     *service.FileService
	agentClient *service.AgentClient
	maxRetry    int
}

func NewUploadHandler(fileSvc *service.FileService, agentClient *service.AgentClient, maxRetry int) *UploadHandler {
	return &UploadHandler{
		fileSvc:     fileSvc,
		agentClient: agentClient,
		maxRetry:    maxRetry,
	}
}

// Upload handles POST /api/v1/upload
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

	// Validate file type
	ext := strings.ToLower(filepath.Ext(header.Filename))
	if ext != ".pdf" {
		c.JSON(http.StatusBadRequest, model.Response{Code: 40002, Message: "仅支持 PDF 格式文件"})
		return
	}

	// Save file to disk
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

	// Read file content for gRPC
	fileContent, err := readFileBytes(result.FilePath)
	if err != nil {
		h.fileSvc.Remove(result.FilePath)
		slog.Error("read file for grpc failed", "error", err)
		c.JSON(http.StatusInternalServerError, model.Response{Code: 50001, Message: "文件读取失败"})
		return
	}

	// Call Agent service to parse PDF
	grpcReq := &agentpb.UploadPaperRequest{
		SessionId:   sessionID,
		Filename:    header.Filename,
		FileContent: fileContent,
	}

	resp, err := h.agentClient.UploadPaper(c.Request.Context(), grpcReq, h.maxRetry)
	if err != nil {
		h.fileSvc.Remove(result.FilePath)
		slog.Error("agent upload paper failed", "error", err)
		c.JSON(http.StatusBadGateway, model.Response{Code: 50004, Message: "论文解析服务不可用"})
		return
	}

	if !resp.Success {
		h.fileSvc.Remove(result.FilePath)
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
```

注意：`readFileBytes` 需要 import `os`，请确保 import 列表包含 `"os"`。

### 3. 更新 `gateway/cmd/server/main.go`

在路由注册部分添加：

```go
fileSvc := service.NewFileService(cfg.Upload.Dir, cfg.Upload.MaxSize)
uploadHandler := handler.NewUploadHandler(fileSvc, agentClient, cfg.GRPC.MaxRetry)

// 在 api group 中添加：
api.POST("/upload", uploadHandler.Upload)
```

## 验收标准

### 1. 编译检查

```bash
cd gateway
go build ./cmd/server/
```

### 2. 验收 Checklist

- [ ] `go build` 编译通过
- [ ] 仅接受 PDF 文件，其他格式返回 `{"code": 40002, "message": "仅支持 PDF 格式文件"}`
- [ ] 文件大小限制 20MB，超出返回 `{"code": 40003}`
- [ ] 文件保存到 `uploads/{session_id}/{uuid}.pdf`
- [ ] 保存时计算 MD5 哈希（用于后续去重）
- [ ] 调用 gRPC UploadPaper 并返回解析结果
- [ ] gRPC 调用失败时清理已保存的文件
- [ ] 解析失败时清理已保存的文件
- [ ] session_id 为空时返回 400

## 提交

```bash
git add gateway/
git commit -m "feat(gateway): implement PDF upload endpoint

- POST /api/v1/upload with multipart form data
- PDF-only validation and 20MB size limit
- Save to uploads/{session_id}/{uuid}.pdf with MD5 hash
- Forward to agent service via gRPC for parsing
- Cleanup saved file on any downstream failure"
```

## 注意事项

1. `readFileBytes` 将整个文件读入内存再发 gRPC，20MB 以内可接受
2. 生产环境应考虑分块传输（gRPC streaming upload），当前阶段不需要
3. 上传目录需要在 `.gitignore` 中排除

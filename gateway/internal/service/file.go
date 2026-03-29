package service

import (
	"crypto/md5"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"strings"

	"github.com/google/uuid"
)

// FileService handles upload file persistence.
type FileService struct {
	uploadDir string
	maxSize   int64
}

// SaveResult is the result of saving an uploaded file.
type SaveResult struct {
	FilePath string
	FileHash string
	FileSize int64
}

// NewFileService creates a new file storage service.
func NewFileService(uploadDir string, maxSize int64) *FileService {
	return &FileService{uploadDir: uploadDir, maxSize: maxSize}
}

// Save writes the file content to disk under uploads/{sessionID}/{uuid}.pdf.
func (s *FileService) Save(sessionID string, filename string, content io.Reader) (*SaveResult, error) {
	dir := filepath.Join(s.uploadDir, sessionID)
	if err := os.MkdirAll(dir, 0o755); err != nil {
		return nil, fmt.Errorf("create upload dir: %w", err)
	}

	ext := strings.ToLower(filepath.Ext(filename))
	if ext == "" {
		ext = ".pdf"
	}
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
		_ = os.Remove(destPath)
		return nil, fmt.Errorf("write file: %w", err)
	}
	if size > s.maxSize {
		_ = os.Remove(destPath)
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

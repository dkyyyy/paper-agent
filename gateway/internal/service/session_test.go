package service

import (
	"context"
	"testing"

	"github.com/dkyyyy/paper-agent/gateway/internal/model"
	"github.com/redis/go-redis/v9"
)

func newTestRedis() *redis.Client {
	return redis.NewClient(&redis.Options{
		Addr: "localhost:6379",
		DB:   15,
	})
}

func TestSessionCRUD(t *testing.T) {
	rdb := newTestRedis()
	ctx := context.Background()
	defer rdb.FlushDB(ctx)

	svc := NewSessionService(rdb)

	sess, err := svc.Create(ctx)
	if err != nil {
		t.Fatalf("Create failed: %v", err)
	}
	if sess.ID == "" {
		t.Fatal("session ID should not be empty")
	}

	got, err := svc.Get(ctx, sess.ID)
	if err != nil {
		t.Fatalf("Get failed: %v", err)
	}
	if got.ID != sess.ID {
		t.Fatalf("expected ID %s, got %s", sess.ID, got.ID)
	}

	err = svc.AppendMessage(ctx, sess.ID, model.Message{
		Role:    "user",
		Content: "research RAG improvements",
	})
	if err != nil {
		t.Fatalf("AppendMessage failed: %v", err)
	}

	got, err = svc.Get(ctx, sess.ID)
	if err != nil {
		t.Fatalf("Get after append failed: %v", err)
	}
	if len(got.Messages) != 1 {
		t.Fatalf("expected 1 message, got %d", len(got.Messages))
	}
	if got.Title == "" {
		t.Fatal("title should be auto-generated from first user message")
	}

	list, err := svc.List(ctx)
	if err != nil {
		t.Fatalf("List failed: %v", err)
	}
	if len(list) < 1 {
		t.Fatal("expected at least 1 session in list")
	}

	err = svc.Delete(ctx, sess.ID)
	if err != nil {
		t.Fatalf("Delete failed: %v", err)
	}

	_, err = svc.Get(ctx, sess.ID)
	if err == nil {
		t.Fatal("expected error after delete, got nil")
	}
}

package service

import (
	"context"
	"testing"
	"time"

	"github.com/dkyyyy/paper-agent/gateway/internal/model"
	"github.com/DATA-DOG/go-sqlmock"
)

func TestSessionCreateAndGet(t *testing.T) {
	db, mock, err := sqlmock.New()
	if err != nil {
		t.Fatalf("sqlmock.New failed: %v", err)
	}
	defer db.Close()

	now := time.Date(2026, 4, 20, 12, 0, 0, 0, time.UTC)
	mock.ExpectQuery("INSERT INTO sessions").
		WithArgs(sqlmock.AnyArg()).
		WillReturnRows(sqlmock.NewRows([]string{"created_at", "updated_at"}).AddRow(now, now))

	mock.ExpectQuery("SELECT id, COALESCE\\(title, ''\\), created_at, updated_at FROM sessions").
		WithArgs("session-1").
		WillReturnRows(sqlmock.NewRows([]string{"id", "title", "created_at", "updated_at"}).AddRow("session-1", "RAG survey", now, now))
	mock.ExpectQuery("SELECT role, content, COALESCE\\(metadata, '\\{\\}'::jsonb\\), created_at FROM messages").
		WithArgs("session-1").
		WillReturnRows(sqlmock.NewRows([]string{"role", "content", "metadata", "created_at"}).AddRow("user", "research RAG improvements", []byte(`{"source":"ui"}`), now))

	svc := NewSessionService(db, nil)
	ctx := context.Background()

	sess, err := svc.Create(ctx)
	if err != nil {
		t.Fatalf("Create failed: %v", err)
	}
	if sess.ID == "" {
		t.Fatal("session ID should not be empty")
	}

	got, err := svc.Get(ctx, "session-1")
	if err != nil {
		t.Fatalf("Get failed: %v", err)
	}
	if got.ID != "session-1" {
		t.Fatalf("expected session-1, got %s", got.ID)
	}
	if len(got.Messages) != 1 {
		t.Fatalf("expected 1 message, got %d", len(got.Messages))
	}
	if got.Messages[0].Metadata["source"] != "ui" {
		t.Fatalf("expected metadata source=ui, got %#v", got.Messages[0].Metadata)
	}

	if err := mock.ExpectationsWereMet(); err != nil {
		t.Fatalf("unmet SQL expectations: %v", err)
	}
}

func TestSessionAppendListAndDelete(t *testing.T) {
	db, mock, err := sqlmock.New()
	if err != nil {
		t.Fatalf("sqlmock.New failed: %v", err)
	}
	defer db.Close()

	now := time.Date(2026, 4, 20, 12, 30, 0, 0, time.UTC)
	sessionID := "9d0b39f5-ccfb-41a4-badc-d740f0a3154e"

	mock.ExpectBegin()
	mock.ExpectExec("INSERT INTO sessions").
		WithArgs(sessionID, "research RAG improvements").
		WillReturnResult(sqlmock.NewResult(0, 1))
	mock.ExpectExec("INSERT INTO messages").
		WithArgs(sessionID, "user", "research RAG improvements", []byte(`{"source":"ui"}`)).
		WillReturnResult(sqlmock.NewResult(1, 1))
	mock.ExpectCommit()

	mock.ExpectQuery("SELECT\\s+s.id,\\s+COALESCE\\(s.title, ''\\),\\s+s.created_at,").
		WillReturnRows(sqlmock.NewRows([]string{"id", "title", "created_at", "last_message", "message_count"}).AddRow(sessionID, "research RAG improvements", now, "research RAG improvements", 1))

	mock.ExpectExec("DELETE FROM sessions").
		WithArgs(sessionID).
		WillReturnResult(sqlmock.NewResult(0, 1))

	svc := NewSessionService(db, nil)
	ctx := context.Background()

	err = svc.AppendMessage(ctx, sessionID, model.Message{
		Role:    "user",
		Content: "research RAG improvements",
		Metadata: map[string]interface{}{
			"source": "ui",
		},
	})
	if err != nil {
		t.Fatalf("AppendMessage failed: %v", err)
	}

	list, err := svc.List(ctx)
	if err != nil {
		t.Fatalf("List failed: %v", err)
	}
	if len(list) != 1 {
		t.Fatalf("expected 1 session in list, got %d", len(list))
	}
	if list[0].Title != "research RAG improvements" {
		t.Fatalf("expected generated title, got %q", list[0].Title)
	}
	if list[0].MessageCount != 1 {
		t.Fatalf("expected message count 1, got %d", list[0].MessageCount)
	}

	err = svc.Delete(ctx, sessionID)
	if err != nil {
		t.Fatalf("Delete failed: %v", err)
	}

	if err := mock.ExpectationsWereMet(); err != nil {
		t.Fatalf("unmet SQL expectations: %v", err)
	}
}

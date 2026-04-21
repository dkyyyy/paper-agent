package service

import (
	"context"
	"database/sql"
	"encoding/json"
	"fmt"
	"time"

	"github.com/dkyyyy/paper-agent/gateway/internal/model"
	"github.com/google/uuid"
	"github.com/redis/go-redis/v9"
)

const (
	sessionKeyPrefix = "session:"
	sessionTTL       = time.Hour
)

// SessionService manages persistent chat sessions backed by PostgreSQL.
type SessionService interface {
	Create(ctx context.Context) (*model.Session, error)
	Get(ctx context.Context, sessionID string) (*model.Session, error)
	AppendMessage(ctx context.Context, sessionID string, msg model.Message) error
	Delete(ctx context.Context, sessionID string) error
	List(ctx context.Context) ([]*model.SessionSummary, error)
}

type sessionService struct {
	db  *sql.DB
	rdb *redis.Client
}

// NewSessionService creates a PostgreSQL-backed session service with Redis hot-cache support.
func NewSessionService(db *sql.DB, rdb *redis.Client) SessionService {
	return &sessionService{
		db:  db,
		rdb: rdb,
	}
}

func sessionCacheKey(id string) string {
	return sessionKeyPrefix + id
}

func (s *sessionService) Create(ctx context.Context) (*model.Session, error) {
	sess := &model.Session{
		ID:       uuid.New().String(),
		Messages: []model.Message{},
	}

	if err := s.db.QueryRowContext(
		ctx,
		"INSERT INTO sessions (id, created_at, updated_at) VALUES ($1, NOW(), NOW()) RETURNING created_at, updated_at",
		sess.ID,
	).Scan(&sess.CreatedAt, &sess.UpdatedAt); err != nil {
		return nil, fmt.Errorf("insert session: %w", err)
	}

	s.cacheSession(ctx, sess)
	return sess, nil
}

func (s *sessionService) Get(ctx context.Context, sessionID string) (*model.Session, error) {
	if cached, ok := s.loadCachedSession(ctx, sessionID); ok {
		return cached, nil
	}

	sess, err := s.loadSessionFromDB(ctx, sessionID)
	if err != nil {
		return nil, err
	}

	s.cacheSession(ctx, sess)
	return sess, nil
}

func (s *sessionService) AppendMessage(ctx context.Context, sessionID string, msg model.Message) (err error) {
	if msg.Role == "" {
		return fmt.Errorf("message role is required")
	}
	if msg.Content == "" {
		return fmt.Errorf("message content is required")
	}

	if msg.Timestamp.IsZero() {
		msg.Timestamp = time.Now()
	}

	tx, err := s.db.BeginTx(ctx, nil)
	if err != nil {
		return fmt.Errorf("begin tx: %w", err)
	}
	defer func() {
		if err != nil {
			_ = tx.Rollback()
		}
	}()

	title := sessionTitleFromMessage(msg)
	if _, err = tx.ExecContext(
		ctx,
		`
		INSERT INTO sessions (id, title, created_at, updated_at)
		VALUES ($1, $2, NOW(), NOW())
		ON CONFLICT (id) DO UPDATE SET
			title = COALESCE(sessions.title, EXCLUDED.title),
			updated_at = NOW()
		`,
		sessionID,
		title,
	); err != nil {
		return fmt.Errorf("upsert session: %w", err)
	}

	metadataJSON := []byte("{}")
	if msg.Metadata != nil {
		metadataJSON, err = json.Marshal(msg.Metadata)
		if err != nil {
			return fmt.Errorf("marshal metadata: %w", err)
		}
	}

	if _, err = tx.ExecContext(
		ctx,
		"INSERT INTO messages (session_id, role, content, metadata, created_at) VALUES ($1, $2, $3, $4, NOW())",
		sessionID,
		msg.Role,
		msg.Content,
		metadataJSON,
	); err != nil {
		return fmt.Errorf("insert message: %w", err)
	}

	if err = tx.Commit(); err != nil {
		return fmt.Errorf("commit tx: %w", err)
	}

	s.invalidateCache(ctx, sessionID)
	return nil
}

func (s *sessionService) Delete(ctx context.Context, sessionID string) error {
	result, err := s.db.ExecContext(ctx, "DELETE FROM sessions WHERE id = $1", sessionID)
	if err != nil {
		return fmt.Errorf("delete session: %w", err)
	}

	rows, err := result.RowsAffected()
	if err != nil {
		return fmt.Errorf("delete session rows affected: %w", err)
	}
	if rows == 0 {
		return fmt.Errorf("session not found: %s", sessionID)
	}

	s.invalidateCache(ctx, sessionID)
	return nil
}

func (s *sessionService) List(ctx context.Context) ([]*model.SessionSummary, error) {
	rows, err := s.db.QueryContext(
		ctx,
		`
		SELECT
			s.id,
			COALESCE(s.title, ''),
			s.created_at,
			COALESCE(latest.content, ''),
			COALESCE(message_counts.message_count, 0)
		FROM sessions AS s
		LEFT JOIN (
			SELECT session_id, COUNT(*)::BIGINT AS message_count
			FROM messages
			GROUP BY session_id
		) AS message_counts
			ON message_counts.session_id = s.id
		LEFT JOIN LATERAL (
			SELECT content
			FROM messages
			WHERE session_id = s.id
			ORDER BY created_at DESC, id DESC
			LIMIT 1
		) AS latest ON TRUE
		ORDER BY s.updated_at DESC, s.created_at DESC
		`,
	)
	if err != nil {
		return nil, fmt.Errorf("list sessions: %w", err)
	}
	defer rows.Close()

	summaries := make([]*model.SessionSummary, 0)
	for rows.Next() {
		var summary model.SessionSummary
		var messageCount int64
		if err := rows.Scan(
			&summary.ID,
			&summary.Title,
			&summary.CreatedAt,
			&summary.LastMessage,
			&messageCount,
		); err != nil {
			return nil, fmt.Errorf("scan session summary: %w", err)
		}
		summary.MessageCount = int(messageCount)
		summaries = append(summaries, &summary)
	}
	if err := rows.Err(); err != nil {
		return nil, fmt.Errorf("iterate session summaries: %w", err)
	}

	return summaries, nil
}

func (s *sessionService) loadSessionFromDB(ctx context.Context, sessionID string) (*model.Session, error) {
	sess := &model.Session{}
	if err := s.db.QueryRowContext(
		ctx,
		"SELECT id, COALESCE(title, ''), created_at, updated_at FROM sessions WHERE id = $1",
		sessionID,
	).Scan(&sess.ID, &sess.Title, &sess.CreatedAt, &sess.UpdatedAt); err != nil {
		if err == sql.ErrNoRows {
			return nil, fmt.Errorf("session not found: %s", sessionID)
		}
		return nil, fmt.Errorf("query session: %w", err)
	}

	rows, err := s.db.QueryContext(
		ctx,
		"SELECT role, content, COALESCE(metadata, '{}'::jsonb), created_at FROM messages WHERE session_id = $1 ORDER BY created_at ASC, id ASC",
		sessionID,
	)
	if err != nil {
		return nil, fmt.Errorf("query messages: %w", err)
	}
	defer rows.Close()

	sess.Messages = make([]model.Message, 0)
	for rows.Next() {
		var msg model.Message
		var rawMetadata []byte
		if err := rows.Scan(&msg.Role, &msg.Content, &rawMetadata, &msg.Timestamp); err != nil {
			return nil, fmt.Errorf("scan message: %w", err)
		}
		if len(rawMetadata) > 0 && string(rawMetadata) != "null" {
			if err := json.Unmarshal(rawMetadata, &msg.Metadata); err != nil {
				return nil, fmt.Errorf("unmarshal message metadata: %w", err)
			}
		}
		sess.Messages = append(sess.Messages, msg)
	}
	if err := rows.Err(); err != nil {
		return nil, fmt.Errorf("iterate messages: %w", err)
	}

	sess.MessageCount = len(sess.Messages)
	return sess, nil
}

func (s *sessionService) loadCachedSession(ctx context.Context, sessionID string) (*model.Session, bool) {
	if s.rdb == nil {
		return nil, false
	}

	data, err := s.rdb.Get(ctx, sessionCacheKey(sessionID)).Bytes()
	if err == redis.Nil || err != nil {
		return nil, false
	}

	var sess model.Session
	if err := json.Unmarshal(data, &sess); err != nil {
		return nil, false
	}
	return &sess, true
}

func (s *sessionService) cacheSession(ctx context.Context, sess *model.Session) {
	if s.rdb == nil || sess == nil {
		return
	}

	data, err := json.Marshal(sess)
	if err != nil {
		return
	}
	_ = s.rdb.Set(ctx, sessionCacheKey(sess.ID), data, sessionTTL).Err()
}

func (s *sessionService) invalidateCache(ctx context.Context, sessionID string) {
	if s.rdb == nil {
		return
	}
	_ = s.rdb.Del(ctx, sessionCacheKey(sessionID)).Err()
}

func sessionTitleFromMessage(msg model.Message) string {
	if msg.Role != "user" {
		return ""
	}
	title := msg.Content
	if len(title) > 50 {
		return title[:50] + "..."
	}
	return title
}

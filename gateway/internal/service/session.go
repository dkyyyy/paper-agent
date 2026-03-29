package service

import (
	"context"
	"encoding/json"
	"fmt"
	"time"

	"github.com/dkyyyy/paper-agent/gateway/internal/model"
	"github.com/google/uuid"
	"github.com/redis/go-redis/v9"
)

const (
	sessionKeyPrefix = "session:"
	sessionTTL       = 1 * time.Hour
)

// SessionService manages chat session storage in Redis.
type SessionService interface {
	Create(ctx context.Context) (*model.Session, error)
	Get(ctx context.Context, sessionID string) (*model.Session, error)
	AppendMessage(ctx context.Context, sessionID string, msg model.Message) error
	Delete(ctx context.Context, sessionID string) error
	List(ctx context.Context) ([]*model.SessionSummary, error)
}

type sessionService struct {
	rdb *redis.Client
}

// NewSessionService creates a Redis-backed session service.
func NewSessionService(rdb *redis.Client) SessionService {
	return &sessionService{rdb: rdb}
}

func sessionKey(id string) string {
	return sessionKeyPrefix + id
}

func (s *sessionService) Create(ctx context.Context) (*model.Session, error) {
	now := time.Now()
	sess := &model.Session{
		ID:        uuid.New().String(),
		CreatedAt: now,
		UpdatedAt: now,
		Messages:  []model.Message{},
	}

	data, err := json.Marshal(sess)
	if err != nil {
		return nil, fmt.Errorf("marshal session: %w", err)
	}

	if err := s.rdb.Set(ctx, sessionKey(sess.ID), data, sessionTTL).Err(); err != nil {
		return nil, fmt.Errorf("redis set: %w", err)
	}

	return sess, nil
}

func (s *sessionService) Get(ctx context.Context, sessionID string) (*model.Session, error) {
	data, err := s.rdb.Get(ctx, sessionKey(sessionID)).Bytes()
	if err == redis.Nil {
		return nil, fmt.Errorf("session not found: %s", sessionID)
	}
	if err != nil {
		return nil, fmt.Errorf("redis get: %w", err)
	}

	var sess model.Session
	if err := json.Unmarshal(data, &sess); err != nil {
		return nil, fmt.Errorf("unmarshal session: %w", err)
	}

	return &sess, nil
}

func (s *sessionService) AppendMessage(ctx context.Context, sessionID string, msg model.Message) error {
	sess, err := s.Get(ctx, sessionID)
	if err != nil {
		return err
	}

	now := time.Now()
	msg.Timestamp = now
	sess.Messages = append(sess.Messages, msg)
	sess.MessageCount = len(sess.Messages)
	sess.UpdatedAt = now

	if sess.Title == "" && msg.Role == "user" {
		title := msg.Content
		if len(title) > 50 {
			title = title[:50] + "..."
		}
		sess.Title = title
	}

	data, err := json.Marshal(sess)
	if err != nil {
		return fmt.Errorf("marshal session: %w", err)
	}

	if err := s.rdb.Set(ctx, sessionKey(sessionID), data, sessionTTL).Err(); err != nil {
		return fmt.Errorf("redis set: %w", err)
	}

	return nil
}

func (s *sessionService) Delete(ctx context.Context, sessionID string) error {
	result, err := s.rdb.Del(ctx, sessionKey(sessionID)).Result()
	if err != nil {
		return fmt.Errorf("redis del: %w", err)
	}
	if result == 0 {
		return fmt.Errorf("session not found: %s", sessionID)
	}
	return nil
}

func (s *sessionService) List(ctx context.Context) ([]*model.SessionSummary, error) {
	keys, err := s.rdb.Keys(ctx, sessionKeyPrefix+"*").Result()
	if err != nil {
		return nil, fmt.Errorf("redis keys: %w", err)
	}

	summaries := make([]*model.SessionSummary, 0, len(keys))
	for _, key := range keys {
		data, err := s.rdb.Get(ctx, key).Bytes()
		if err != nil {
			continue
		}

		var sess model.Session
		if err := json.Unmarshal(data, &sess); err != nil {
			continue
		}

		summary := &model.SessionSummary{
			ID:           sess.ID,
			Title:        sess.Title,
			CreatedAt:    sess.CreatedAt,
			MessageCount: len(sess.Messages),
		}
		if len(sess.Messages) > 0 {
			last := sess.Messages[len(sess.Messages)-1]
			summary.LastMessage = last.Content
			if len(summary.LastMessage) > 100 {
				summary.LastMessage = summary.LastMessage[:100] + "..."
			}
		}

		summaries = append(summaries, summary)
	}

	return summaries, nil
}

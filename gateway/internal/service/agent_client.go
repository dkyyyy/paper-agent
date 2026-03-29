package service

import (
	"context"
	"fmt"
	"io"
	"log/slog"
	"time"

	pb "github.com/dkyyyy/paper-agent/gateway/internal/grpc/agentpb"
	"google.golang.org/grpc"
	"google.golang.org/grpc/credentials/insecure"
)

// AgentClient wraps the gRPC connection to the Python agent service.
type AgentClient struct {
	conn    *grpc.ClientConn
	client  pb.AgentServiceClient
	timeout time.Duration
}

// ChatEvent is a single event emitted from the streaming chat RPC.
type ChatEvent struct {
	EventType       string
	Content         string
	AgentName       string
	StepDescription string
	ErrorMessage    string
}

// NewAgentClient creates a gRPC client connected to the agent service.
func NewAgentClient(addr string, timeout time.Duration) (*AgentClient, error) {
	conn, err := grpc.NewClient(addr,
		grpc.WithTransportCredentials(insecure.NewCredentials()),
	)
	if err != nil {
		return nil, fmt.Errorf("grpc dial %s: %w", addr, err)
	}

	return &AgentClient{
		conn:    conn,
		client:  pb.NewAgentServiceClient(conn),
		timeout: timeout,
	}, nil
}

// Chat sends a chat request and returns streaming event and error channels.
func (c *AgentClient) Chat(ctx context.Context, req *pb.ChatRequest) (<-chan ChatEvent, <-chan error) {
	eventCh := make(chan ChatEvent, 32)
	errCh := make(chan error, 1)

	go func() {
		defer close(eventCh)
		defer close(errCh)

		ctx, cancel := context.WithTimeout(ctx, c.timeout)
		defer cancel()

		stream, err := c.client.Chat(ctx, req)
		if err != nil {
			errCh <- fmt.Errorf("start chat stream: %w", err)
			return
		}

		for {
			event, err := stream.Recv()
			if err == io.EOF {
				return
			}
			if err != nil {
				errCh <- fmt.Errorf("recv chat event: %w", err)
				return
			}

			eventCh <- ChatEvent{
				EventType:       eventTypeToString(event.EventType),
				Content:         event.Content,
				AgentName:       event.AgentName,
				StepDescription: event.StepDescription,
				ErrorMessage:    event.ErrorMessage,
			}
		}
	}()

	return eventCh, errCh
}

// UploadPaper sends a file to the agent service for parsing with retries.
func (c *AgentClient) UploadPaper(ctx context.Context, req *pb.UploadPaperRequest, maxRetry int) (*pb.UploadPaperResponse, error) {
	var lastErr error
	for i := 0; i <= maxRetry; i++ {
		if i > 0 {
			backoff := time.Duration(1<<uint(i-1)) * time.Second
			slog.Warn("retrying UploadPaper", "attempt", i+1, "backoff", backoff)
			time.Sleep(backoff)
		}

		rpcCtx, cancel := context.WithTimeout(ctx, c.timeout)
		resp, err := c.client.UploadPaper(rpcCtx, req)
		cancel()

		if err == nil {
			return resp, nil
		}
		lastErr = err
	}

	return nil, fmt.Errorf("upload paper after %d retries: %w", maxRetry+1, lastErr)
}

// HealthCheck checks if the agent service is healthy.
func (c *AgentClient) HealthCheck(ctx context.Context) (*pb.HealthCheckResponse, error) {
	rpcCtx, cancel := context.WithTimeout(ctx, 5*time.Second)
	defer cancel()
	return c.client.HealthCheck(rpcCtx, &pb.HealthCheckRequest{})
}

// Close closes the gRPC connection.
func (c *AgentClient) Close() error {
	return c.conn.Close()
}

func eventTypeToString(t pb.EventType) string {
	switch t {
	case pb.EventType_EVENT_TYPE_TOKEN:
		return "token"
	case pb.EventType_EVENT_TYPE_AGENT_STATUS:
		return "agent_status"
	case pb.EventType_EVENT_TYPE_DONE:
		return "done"
	case pb.EventType_EVENT_TYPE_ERROR:
		return "error"
	default:
		return "unknown"
	}
}

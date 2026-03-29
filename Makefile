.PHONY: up down build logs clean proto

# Start all services
up:
	docker-compose up -d

# Stop all services
down:
	docker-compose down

# Build all images
build:
	docker-compose build

# View logs
logs:
	docker-compose logs -f

# Clean volumes and images
clean:
	docker-compose down -v --rmi local

# Regenerate proto code
proto:
	protoc --proto_path=proto \
		--go_out=gateway/internal/grpc/agentpb --go_opt=paths=source_relative \
		--go-grpc_out=gateway/internal/grpc/agentpb --go-grpc_opt=paths=source_relative \
		proto/agent/v1/agent.proto
	python -m grpc_tools.protoc -Iproto \
		--python_out=agent/app/grpc/agentpb \
		--grpc_python_out=agent/app/grpc/agentpb \
		proto/agent/v1/agent.proto

# Dev: start infrastructure only
dev-infra:
	docker-compose up -d postgres redis chroma

"""gRPC server implementation for the Agent service."""

import logging
from concurrent import futures

import grpc

from app.grpc.agentpb import agent_pb2, agent_pb2_grpc

logger = logging.getLogger(__name__)


class AgentServicer(agent_pb2_grpc.AgentServiceServicer):
    """Implements the AgentService gRPC interface."""

    def Chat(self, request, context):
        """Handle chat request with streaming response.

        Currently returns mock events. Will be replaced with LangGraph
        workflow invocation in task 3.2.
        """
        session_id = request.session_id
        content = request.content
        logger.info("Chat request: session=%s, content=%s", session_id, content[:50])

        yield agent_pb2.ChatEvent(
            event_type=agent_pb2.EVENT_TYPE_AGENT_STATUS,
            agent_name="supervisor",
            step_description="正在分析您的需求...",
        )

        mock_response = f"收到您的问题：{content}。系统正在开发中，这是一条模拟回复。"
        for char in mock_response:
            yield agent_pb2.ChatEvent(
                event_type=agent_pb2.EVENT_TYPE_TOKEN,
                content=char,
            )

        yield agent_pb2.ChatEvent(
            event_type=agent_pb2.EVENT_TYPE_DONE,
            content=mock_response,
        )

    def UploadPaper(self, request, context):
        """Handle paper upload and parsing.

        Currently returns mock response. Will be replaced with actual
        PDF parsing in task 4.4.
        """
        logger.info(
            "UploadPaper: session=%s, file=%s",
            request.session_id,
            request.filename,
        )

        return agent_pb2.UploadPaperResponse(
            paper_id=f"mock_{request.filename}",
            title=f"Mock Title for {request.filename}",
            page_count=10,
            success=True,
        )

    def HealthCheck(self, request, context):
        """Report service health."""
        return agent_pb2.HealthCheckResponse(
            healthy=True,
            services={"llm": "ok", "chroma": "ok", "redis": "ok"},
        )


def create_server(port: int, max_workers: int = 10) -> grpc.Server:
    """Create and configure the gRPC server."""
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=max_workers))
    agent_pb2_grpc.add_AgentServiceServicer_to_server(AgentServicer(), server)
    server.add_insecure_port(f"[::]:{port}")
    return server

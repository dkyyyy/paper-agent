"""gRPC server implementation for the Agent service."""

import logging
from concurrent import futures

import grpc

from app.grpc.agentpb import agent_pb2, agent_pb2_grpc

logger = logging.getLogger(__name__)


class AgentServicer(agent_pb2_grpc.AgentServiceServicer):
    """Implements the AgentService gRPC interface."""

    def Chat(self, request, context):
        """Handle chat request by invoking the Supervisor Agent graph."""
        del context
        session_id = request.session_id
        content = request.content
        logger.info("Chat request: session=%s, content=%s", session_id, content[:50])

        initial_state = {
            "messages": [],
            "user_query": content,
            "intent": "",
            "topic": "",
            "research_plan": [],
            "sub_results": {},
            "final_output": "",
            "iteration": 0,
            "max_iterations": 2,
            "status": "pending",
            "events": [],
        }

        if request.HasField("context") and request.context.history:
            initial_state["messages"] = [
                {"role": msg.role, "content": msg.content}
                for msg in request.context.history
            ]

        try:
            from app.agents.supervisor import supervisor_graph

            result = supervisor_graph.invoke(initial_state)

            for event in result.get("events", []):
                if event.get("type") == "agent_status":
                    yield agent_pb2.ChatEvent(
                        event_type=agent_pb2.EVENT_TYPE_AGENT_STATUS,
                        agent_name=event.get("agent", ""),
                        step_description=event.get("step", ""),
                    )

            final_output = result.get("final_output") or "处理完成，但未生成输出。"
            chunk_size = 20
            for index in range(0, len(final_output), chunk_size):
                yield agent_pb2.ChatEvent(
                    event_type=agent_pb2.EVENT_TYPE_TOKEN,
                    content=final_output[index:index + chunk_size],
                )

            yield agent_pb2.ChatEvent(
                event_type=agent_pb2.EVENT_TYPE_DONE,
                content=final_output,
            )
        except Exception as exc:
            logger.error("Chat error: %s", exc, exc_info=True)
            yield agent_pb2.ChatEvent(
                event_type=agent_pb2.EVENT_TYPE_ERROR,
                error_message=str(exc),
            )

    def UploadPaper(self, request, context):
        """Handle paper upload and parsing.

        Currently returns mock response. Will be replaced with actual
        PDF parsing in task 4.4.
        """
        del context
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
        del request, context
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
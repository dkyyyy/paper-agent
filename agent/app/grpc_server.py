"""gRPC server implementation for the Agent service."""

import logging
from concurrent import futures

import grpc

from app.agents.llm import reset_current_token_budget, set_current_token_budget
from app.config import config
from app.grpc.agentpb import agent_pb2, agent_pb2_grpc
from app.services.health import probe_services
from app.services.paper_store import save_uploaded_paper
from app.services.token_budget import TokenBudget

logger = logging.getLogger(__name__)


class AgentServicer(agent_pb2_grpc.AgentServiceServicer):
    """Implements the AgentService gRPC interface."""

    def Chat(self, request, context):
        """Handle chat requests by invoking the supervisor workflow."""
        del context
        session_id = request.session_id
        logger.info("Chat request: session=%s, content=%s", session_id, request.content[:50])

        initial_state = {
            "messages": [],
            "session_id": session_id,
            "attachment_ids": list(request.attachment_ids),
            "user_query": request.content,
            "intent": "",
            "topic": "",
            "research_plan": [],
            "sub_results": {},
            "search_results": [],
            "analysis_results": [],
            "synthesis_output": "",
            "final_output": "",
            "error_message": "",
            "iteration": 0,
            "max_iterations": 2,
            "status": "pending",
            "events": [],
        }

        if request.HasField("context") and request.context.history:
            initial_state["messages"] = [
                {"role": message.role, "content": message.content}
                for message in request.context.history
            ]

        budget = TokenBudget(
            budget=config.session_token_budget,
            compress_threshold=config.token_compress_threshold,
        )
        budget_token = set_current_token_budget(budget)

        result = None
        try:
            from app.agents.supervisor import supervisor_graph

            for chunk in supervisor_graph.stream(initial_state):
                for node_name, node_output in chunk.items():
                    for event in node_output.get("events", []):
                        if event.get("type") == "agent_status":
                            yield agent_pb2.ChatEvent(
                                event_type=agent_pb2.EVENT_TYPE_AGENT_STATUS,
                                agent_name=event.get("agent", ""),
                                step_description=event.get("step", ""),
                            )
                    result = node_output
        except Exception as exc:
            logger.error("Chat error: %s", exc, exc_info=True)
            yield agent_pb2.ChatEvent(
                event_type=agent_pb2.EVENT_TYPE_ERROR,
                error_message=str(exc),
            )
            return
        finally:
            reset_current_token_budget(budget_token)
            logger.info(
                "Token budget usage for session %s: %s/%s",
                session_id,
                budget.used,
                budget.budget,
            )

        if not result:
            yield agent_pb2.ChatEvent(
                event_type=agent_pb2.EVENT_TYPE_ERROR,
                error_message="No result from supervisor",
            )
            return

        if result.get("status") == "failed":
            yield agent_pb2.ChatEvent(
                event_type=agent_pb2.EVENT_TYPE_ERROR,
                error_message=result.get("error_message", "Task execution failed."),
            )
            return

        final_output = result.get("final_output") or "Task completed, but no final output was produced."
        chunk_size = 256
        for index in range(0, len(final_output), chunk_size):
            yield agent_pb2.ChatEvent(
                event_type=agent_pb2.EVENT_TYPE_TOKEN,
                content=final_output[index:index + chunk_size],
            )

        yield agent_pb2.ChatEvent(
            event_type=agent_pb2.EVENT_TYPE_DONE,
            content=final_output,
        )

    def UploadPaper(self, request, context):
        """Persist an uploaded PDF and return stable metadata."""
        del context
        logger.info("UploadPaper: session=%s, file=%s", request.session_id, request.filename)

        try:
            metadata = save_uploaded_paper(
                session_id=request.session_id,
                filename=request.filename,
                file_content=request.file_content,
            )
            return agent_pb2.UploadPaperResponse(
                paper_id=metadata["paper_id"],
                title=metadata["title"],
                page_count=metadata["page_count"],
                success=True,
            )
        except Exception as exc:
            logger.error("UploadPaper failed: %s", exc, exc_info=True)
            return agent_pb2.UploadPaperResponse(
                success=False,
                error=str(exc),
            )

    def HealthCheck(self, request, context):
        """Report service health based on actual dependency probes."""
        del request, context
        healthy, services = probe_services()
        return agent_pb2.HealthCheckResponse(
            healthy=healthy,
            services=services,
        )


def create_server(port: int, max_workers: int = 10) -> grpc.Server:
    """Create and configure the gRPC server."""
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=max_workers))
    agent_pb2_grpc.add_AgentServiceServicer_to_server(AgentServicer(), server)
    server.add_insecure_port(f"[::]:{port}")
    return server
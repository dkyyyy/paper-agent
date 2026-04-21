"""Tests for the supervisor agent graph and gRPC integration."""

import json
from types import SimpleNamespace

from app.agents import analysis_agent as analysis_agent_module
from app.agents import llm as llm_module
from app.agents import supervisor as supervisor_module
from app.agents import synthesis_agent as synthesis_agent_module
from app.agents.supervisor import SupervisorState, build_supervisor_graph
from app.grpc.agentpb import agent_pb2
from app.grpc_server import AgentServicer
from app.services import paper_store as paper_store_module


class StubLLM:
    """Simple sequential stub for LangChain-like invoke calls."""

    def __init__(self, responses):
        self._responses = list(responses)

    def invoke(self, messages):
        del messages
        if not self._responses:
            raise AssertionError("No more stub responses available")
        return SimpleNamespace(content=self._responses.pop(0))


class DummySupervisorGraph:
    def __init__(self, result):
        self._result = result

    def invoke(self, state):
        assert state["user_query"] == "give me a RAG survey"
        return self._result


def make_state(query="test", attachment_ids=None):
    return {
        "messages": [],
        "session_id": "session-1",
        "attachment_ids": attachment_ids or [],
        "user_query": query,
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


def make_plan(intent):
    plan = [{"step": 1, "agent": "analysis_agent", "task": "Analyze uploaded papers", "params": {}}]
    if intent != "paper_reading":
        plan = [
            {"step": 1, "agent": "search_agent", "task": "Search papers", "params": {}},
            {"step": 2, "agent": "analysis_agent", "task": "Analyze papers", "depends_on": [1]},
            {"step": 3, "agent": "synthesis_agent", "task": "Write report", "depends_on": [2]},
        ]
    return json.dumps(
        {
            "intent": intent,
            "topic": "retrieval augmented generation",
            "plan": plan,
        }
    )


def test_graph_builds():
    graph = build_supervisor_graph()
    assert graph is not None
    assert {"intent_recognition", "dispatch_agents", "quality_check"}.issubset(
        set(graph.get_graph().nodes.keys())
    )


def test_initial_state_schema():
    state = SupervisorState(
        messages=[],
        session_id="s1",
        attachment_ids=[],
        user_query="test",
        intent="",
        topic="",
        research_plan=[],
        sub_results={},
        search_results=[],
        analysis_results=[],
        synthesis_output="",
        final_output="",
        error_message="",
        iteration=0,
        max_iterations=2,
        status="pending",
        events=[],
    )
    assert state["user_query"] == "test"
    assert state["max_iterations"] == 2


def test_intent_recognition_for_all_supported_types(monkeypatch):
    intents = [
        "literature_review",
        "paper_reading",
        "method_comparison",
        "gap_analysis",
    ]

    def fake_dispatch(agent_name, task, state):
        del task, state
        if agent_name == "synthesis_agent":
            return "final report", {"synthesis_output": "final report"}, []
        return f"{agent_name} ok", {}, []

    monkeypatch.setattr(supervisor_module, "_dispatch_single_agent", fake_dispatch)

    for intent in intents:
        stub_llm = StubLLM(
            [
                make_plan(intent),
                json.dumps({"passed": True, "score": 9, "feedback": ""}),
            ]
        )
        monkeypatch.setattr(llm_module, "get_llm", lambda stub=stub_llm: stub)

        result = build_supervisor_graph().invoke(make_state("analyze rag"))

        assert result["intent"] == intent
        assert result["status"] == "completed"
        assert result["final_output"]
        assert any(event["agent"] == "supervisor" for event in result["events"])


def test_quality_check_retry_until_pass(monkeypatch):
    calls = []

    def fake_dispatch(agent_name, task, state):
        del task, state
        calls.append(agent_name)
        if agent_name == "synthesis_agent":
            return "final report", {"synthesis_output": "final report"}, []
        return f"{agent_name} ok", {}, []

    stub_llm = StubLLM(
        [
            make_plan("literature_review"),
            json.dumps({"passed": False, "score": 4, "feedback": "Need more comparison"}),
            json.dumps({"passed": True, "score": 8, "feedback": ""}),
        ]
    )

    monkeypatch.setattr(supervisor_module, "_dispatch_single_agent", fake_dispatch)
    monkeypatch.setattr(llm_module, "get_llm", lambda: stub_llm)

    result = build_supervisor_graph().invoke(make_state("review rag"))

    assert result["status"] == "completed"
    assert result["iteration"] == 1
    assert calls.count("search_agent") == 2
    assert any("retry" in event["step"].lower() for event in result["events"])


def test_dispatch_analysis_uses_uploaded_paper_text(monkeypatch):
    captured = {}

    def fake_run_analysis(paper_id, paper_title, paper_content, persist_to_vectordb=True):
        captured["paper_id"] = paper_id
        captured["paper_title"] = paper_title
        captured["paper_content"] = paper_content
        captured["persist_to_vectordb"] = persist_to_vectordb
        return {
            "extracted_info": {"method": "full text analysis"},
            "summary": "analysis summary",
            "indexed": True,
            "index_error": "",
            "events": [{"type": "agent_status", "agent": "analysis_agent", "step": "analysis complete"}],
        }

    monkeypatch.setattr(
        paper_store_module,
        "get_paper_metadata",
        lambda paper_id: {"paper_id": paper_id, "title": "Uploaded Paper", "filename": "paper.pdf"},
    )
    monkeypatch.setattr(paper_store_module, "get_paper_text", lambda paper_id: "FULL TEXT CONTENT")
    monkeypatch.setattr(analysis_agent_module, "run_analysis", fake_run_analysis)

    output, updates, events = supervisor_module._dispatch_single_agent(
        "analysis_agent",
        "",
        make_state("read this paper", attachment_ids=["paper_1"]),
    )

    assert "Uploaded Paper" in output
    assert captured["paper_content"] == "FULL TEXT CONTENT"
    assert captured["persist_to_vectordb"] is True
    assert updates["analysis_results"][0]["analysis_source"] == "full_text"
    assert events[0]["step"] == "analysis complete"


def test_dispatch_synthesis_uses_analysis_results_not_search_results(monkeypatch):
    captured = {}

    def fake_run_synthesis(papers, topic, task_type="full"):
        captured["papers"] = papers
        captured["topic"] = topic
        captured["task_type"] = task_type
        return {
            "output": "synthesis report",
            "events": [{"type": "agent_status", "agent": "synthesis_agent", "step": "report ready"}],
        }

    monkeypatch.setattr(synthesis_agent_module, "run_synthesis", fake_run_synthesis)

    state = make_state("compare rag")
    state["intent"] = "method_comparison"
    state["topic"] = "RAG"
    state["search_results"] = [{"title": "search result paper"}]
    state["analysis_results"] = [{"title": "analysis result paper"}]

    output, updates, events = supervisor_module._dispatch_single_agent("synthesis_agent", "", state)

    assert output == "synthesis report"
    assert captured["papers"] == [{"title": "analysis result paper"}]
    assert captured["task_type"] == "comparison"
    assert updates["synthesis_output"] == "synthesis report"
    assert events[0]["step"] == "report ready"


def test_dispatch_failure_marks_graph_failed(monkeypatch):
    def fake_dispatch(agent_name, task, state):
        del task, state
        if agent_name == "analysis_agent":
            raise RuntimeError("indexing failed")
        return f"{agent_name} ok", {}, []

    stub_llm = StubLLM([make_plan("literature_review")])

    monkeypatch.setattr(supervisor_module, "_dispatch_single_agent", fake_dispatch)
    monkeypatch.setattr(llm_module, "get_llm", lambda: stub_llm)

    result = build_supervisor_graph().invoke(make_state("review rag"))

    assert result["status"] == "failed"
    assert result["error_message"] == "analysis_agent failed: indexing failed"


def test_grpc_chat_streams_supervisor_events(monkeypatch):
    final_output = "This is the final report body used to validate token streaming."
    monkeypatch.setattr(
        supervisor_module,
        "supervisor_graph",
        DummySupervisorGraph(
            {
                "status": "completed",
                "events": [
                    {"type": "agent_status", "agent": "supervisor", "step": "Intent recognized"},
                    {"type": "agent_status", "agent": "search_agent", "step": "Searching papers"},
                ],
                "final_output": final_output,
            }
        ),
    )

    request = agent_pb2.ChatRequest(session_id="s1", content="give me a RAG survey")
    events = list(AgentServicer().Chat(request, None))

    assert [event.event_type for event in events[:2]] == [
        agent_pb2.EVENT_TYPE_AGENT_STATUS,
        agent_pb2.EVENT_TYPE_AGENT_STATUS,
    ]
    token_events = [event for event in events if event.event_type == agent_pb2.EVENT_TYPE_TOKEN]
    assert "".join(event.content for event in token_events) == final_output
    assert events[-1].event_type == agent_pb2.EVENT_TYPE_DONE
    assert events[-1].content == final_output


def test_grpc_chat_emits_error_on_failed_result(monkeypatch):
    monkeypatch.setattr(
        supervisor_module,
        "supervisor_graph",
        DummySupervisorGraph(
            {
                "status": "failed",
                "events": [{"type": "agent_status", "agent": "supervisor", "step": "Intent recognized"}],
                "error_message": "analysis_agent failed: indexing failed",
            }
        ),
    )

    request = agent_pb2.ChatRequest(session_id="s1", content="give me a RAG survey")
    events = list(AgentServicer().Chat(request, None))

    assert events[0].event_type == agent_pb2.EVENT_TYPE_AGENT_STATUS
    assert events[-1].event_type == agent_pb2.EVENT_TYPE_ERROR
    assert events[-1].error_message == "analysis_agent failed: indexing failed"
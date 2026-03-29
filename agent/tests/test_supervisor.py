"""Tests for the Supervisor Agent graph and gRPC integration."""

import json
from types import SimpleNamespace

from app.agents import llm as llm_module
from app.agents import supervisor as supervisor_module
from app.agents.supervisor import SupervisorState, build_supervisor_graph
from app.config import config
from app.grpc.agentpb import agent_pb2
from app.grpc_server import AgentServicer


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
        assert state["user_query"] == "请给我一份 RAG 综述"
        return self._result


def make_state(query="test"):
    return {
        "messages": [],
        "user_query": query,
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


def make_plan(intent):
    return json.dumps(
        {
            "intent": intent,
            "topic": "retrieval augmented generation",
            "plan": [
                {"step": 1, "agent": "search_agent", "task": "检索相关论文", "params": {}},
                {"step": 2, "agent": "analysis_agent", "task": "分析论文", "depends_on": [1]},
                {"step": 3, "agent": "synthesis_agent", "task": "生成综述", "depends_on": [2]},
            ],
        },
        ensure_ascii=False,
    )


def test_graph_builds():
    """Graph should compile without errors."""
    graph = build_supervisor_graph()
    assert graph is not None
    assert {"intent_recognition", "dispatch_agents", "quality_check"}.issubset(
        set(graph.get_graph().nodes.keys())
    )


def test_initial_state_schema():
    """Verify SupervisorState has all required fields."""
    state = SupervisorState(
        messages=[],
        user_query="test",
        intent="",
        topic="",
        research_plan=[],
        sub_results={},
        final_output="",
        iteration=0,
        max_iterations=2,
        status="pending",
        events=[],
    )
    assert state["user_query"] == "test"
    assert state["max_iterations"] == 2


def test_intent_recognition_for_all_supported_types(monkeypatch):
    """Supported intents should be preserved through graph execution."""
    intents = [
        "literature_review",
        "paper_reading",
        "method_comparison",
        "gap_analysis",
    ]

    for intent in intents:
        stub_llm = StubLLM(
            [
                make_plan(intent),
                json.dumps({"passed": True, "score": 9, "feedback": ""}),
            ]
        )
        monkeypatch.setattr(llm_module, "get_llm", lambda stub=stub_llm: stub)

        result = build_supervisor_graph().invoke(make_state("请分析 RAG"))

        assert result["intent"] == intent
        assert result["status"] == "completed"
        assert "Step 1:" in result["final_output"]
        assert any(event["agent"] == "search_agent" for event in result["events"])


def test_quality_check_retry_until_pass(monkeypatch):
    """A failed quality check should re-run the dispatch stage once."""
    stub_llm = StubLLM(
        [
            make_plan("literature_review"),
            json.dumps({"passed": False, "score": 4, "feedback": "补充对比分析"}, ensure_ascii=False),
            json.dumps({"passed": True, "score": 8, "feedback": ""}),
        ]
    )
    monkeypatch.setattr(llm_module, "get_llm", lambda: stub_llm)

    result = build_supervisor_graph().invoke(make_state("请综述 RAG"))

    assert result["status"] == "completed"
    assert result["iteration"] == 1
    assert sum(1 for event in result["events"] if event["agent"] == "search_agent") == 2
    assert any("质量未达标" in event["step"] for event in result["events"])


def test_llm_factory_supports_dashscope_and_zhipu(monkeypatch):
    """LLM factory should create both configured provider clients."""
    llm_module.get_llm.cache_clear()
    monkeypatch.setattr(config, "llm_provider", "dashscope")
    monkeypatch.setattr(config, "llm_model", "qwen-plus")
    monkeypatch.setattr(config, "llm_api_key", "test-key")
    assert llm_module.get_llm().__class__.__name__ == "ChatTongyi"

    llm_module.get_llm.cache_clear()
    monkeypatch.setattr(config, "llm_provider", "zhipu")
    monkeypatch.setattr(config, "llm_model", "glm-4")
    monkeypatch.setattr(config, "llm_api_key", "test-key")
    assert llm_module.get_llm().__class__.__name__ == "ChatZhipuAI"

    llm_module.get_llm.cache_clear()


def test_grpc_chat_streams_supervisor_events(monkeypatch):
    """gRPC Chat should stream supervisor events, token chunks, and done."""
    final_output = "这是一个用于验证分块输出的最终报告。"
    monkeypatch.setattr(
        supervisor_module,
        "supervisor_graph",
        DummySupervisorGraph(
            {
                "events": [
                    {"type": "agent_status", "agent": "supervisor", "step": "意图识别完成"},
                    {"type": "agent_status", "agent": "search_agent", "step": "正在执行：检索相关论文"},
                ],
                "final_output": final_output,
            }
        ),
    )

    request = agent_pb2.ChatRequest(session_id="s1", content="请给我一份 RAG 综述")
    events = list(AgentServicer().Chat(request, None))

    assert [event.event_type for event in events[:2]] == [
        agent_pb2.EVENT_TYPE_AGENT_STATUS,
        agent_pb2.EVENT_TYPE_AGENT_STATUS,
    ]
    token_events = [event for event in events if event.event_type == agent_pb2.EVENT_TYPE_TOKEN]
    assert "".join(event.content for event in token_events) == final_output
    assert events[-1].event_type == agent_pb2.EVENT_TYPE_DONE
    assert events[-1].content == final_output
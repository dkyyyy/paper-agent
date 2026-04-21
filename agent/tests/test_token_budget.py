"""Tests for token budget control."""

from types import SimpleNamespace

from langchain_core.messages import HumanMessage

from app.agents import llm as llm_module
from app.services.token_budget import TokenBudget, compress_messages


class StubLLM:
    def __init__(self, response, usage_metadata=None):
        self._response = response
        self._usage_metadata = usage_metadata or {}

    def invoke(self, messages):
        del messages
        return SimpleNamespace(content=self._response, usage_metadata=self._usage_metadata)


def test_budget_tracking():
    budget = TokenBudget(budget=10000)
    assert budget.remaining == 10000
    assert budget.usage_ratio == 0.0
    assert not budget.should_compress
    assert not budget.is_exhausted

    budget.record(500, 200, source="search")
    assert budget.used == 700
    assert budget.remaining == 9300
    assert budget.history[-1]["source"] == "search"


def test_budget_compress_threshold():
    budget = TokenBudget(budget=10000)
    budget.record(4000, 4000, source="analysis")
    assert budget.should_compress


def test_budget_exhausted():
    budget = TokenBudget(budget=1000)
    budget.record(600, 500, source="test")
    assert budget.is_exhausted


def test_estimate_available():
    budget = TokenBudget(budget=5000)
    budget.record(1000, 500, source="test")
    assert budget.estimate_available() == 1500
    assert budget.estimate_available(reserved_for_output=1000) == 2500


def test_compress_messages_no_compression_needed():
    messages = [
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "hi"},
    ]
    result = compress_messages(messages, "system", keep_recent=3)
    assert len(result) == 3
    assert result[0] == {"role": "system", "content": "system"}
    assert result[1:] == messages


def test_compress_messages():
    messages = []
    for index in range(10):
        messages.append({"role": "user", "content": f"question {index}"})
        messages.append({"role": "assistant", "content": f"answer {index}" * 50})

    result = compress_messages(messages, "system", keep_recent=3)
    assert len(result) == 8
    assert result[0]["role"] == "system"
    assert "摘要" in result[1]["content"]
    assert result[-1]["content"].startswith("answer 9")


def test_budget_to_dict():
    budget = TokenBudget(budget=50000)
    budget.record(1000, 500, source="test")
    payload = budget.to_dict()
    assert payload["budget"] == 50000
    assert payload["used"] == 1500
    assert payload["remaining"] == 48500


def test_invoke_llm_records_token_usage(monkeypatch):
    stub_llm = StubLLM("ok", usage_metadata={"input_tokens": 12, "output_tokens": 5})
    budget = TokenBudget(budget=100)
    monkeypatch.setattr(llm_module, "get_llm", lambda: stub_llm)

    response = llm_module.invoke_llm([HumanMessage(content="hello")], source="unit.test", budget=budget)

    assert response.content == "ok"
    assert budget.used == 17
    assert budget.history[-1]["source"] == "unit.test"
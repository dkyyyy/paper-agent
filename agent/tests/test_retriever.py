"""Tests for retriever level detection and query wiring."""

from types import SimpleNamespace

from app.agents import llm as llm_module
from app.rag import retriever as retriever_module
from app.rag.retriever import LEVEL_TO_COLLECTION, RetrievalLevel, detect_level, retrieve


class StubLLM:
    def __init__(self, response):
        self._response = response

    def invoke(self, messages):
        del messages
        return SimpleNamespace(content=self._response)


class FakeEmbeddings:
    def embed_query(self, question):
        return [len(question)]


class FakeCollection:
    def __init__(self, name, captured):
        self.name = name
        self._captured = captured

    def query(self, query_embeddings, n_results, where=None):
        self._captured["query_embeddings"] = query_embeddings
        self._captured["n_results"] = n_results
        self._captured["where"] = where
        self._captured["collection_name"] = self.name
        return {
            "documents": [["doc-1", "doc-2"]],
            "metadatas": [[{"paper_id": "p1"}, {"paper_id": "p2"}]],
            "distances": [[0.1, 0.3]],
        }


class FakeClient:
    def __init__(self, captured):
        self._captured = captured

    def get_or_create_collection(self, name):
        return FakeCollection(name, self._captured)


def test_level_to_collection_mapping():
    assert LEVEL_TO_COLLECTION[RetrievalLevel.PARAGRAPH] == "papers_paragraph"
    assert LEVEL_TO_COLLECTION[RetrievalLevel.SECTION] == "papers_section"
    assert LEVEL_TO_COLLECTION[RetrievalLevel.PAPER] == "papers_summary"


def test_retrieval_level_enum():
    assert RetrievalLevel.PARAGRAPH.value == "paragraph"
    assert RetrievalLevel.SECTION.value == "section"
    assert RetrievalLevel.PAPER.value == "paper"


def test_detect_level_from_llm(monkeypatch):
    monkeypatch.setattr(llm_module, "get_llm", lambda: StubLLM("paper"))
    assert detect_level("Compare these RAG papers") == RetrievalLevel.PAPER

    monkeypatch.setattr(llm_module, "get_llm", lambda: StubLLM("paragraph"))
    assert detect_level("What loss is used?") == RetrievalLevel.PARAGRAPH

    monkeypatch.setattr(llm_module, "get_llm", lambda: StubLLM("section"))
    assert detect_level("What is the core method?") == RetrievalLevel.SECTION


def test_retrieve_uses_default_top_k_and_paper_filter(monkeypatch):
    captured = {}
    monkeypatch.setattr(retriever_module, "get_embeddings", lambda: FakeEmbeddings())
    monkeypatch.setattr(
        retriever_module.chromadb,
        "HttpClient",
        lambda host, port: FakeClient(captured),
    )

    docs = retrieve(
        question="What loss is used?",
        level=RetrievalLevel.PARAGRAPH,
        paper_id="paper_001",
    )

    assert captured["collection_name"] == "papers_paragraph"
    assert captured["n_results"] == 5
    assert captured["where"] == {"paper_id": "paper_001"}
    assert docs[0]["score"] == 0.9


def test_retrieve_auto_detects_level(monkeypatch):
    captured = {}
    monkeypatch.setattr(llm_module, "get_llm", lambda: StubLLM("paper"))
    monkeypatch.setattr(retriever_module, "get_embeddings", lambda: FakeEmbeddings())
    monkeypatch.setattr(
        retriever_module.chromadb,
        "HttpClient",
        lambda host, port: FakeClient(captured),
    )

    docs = retrieve(question="Compare these RAG papers", top_k=3)

    assert captured["collection_name"] == "papers_summary"
    assert captured["n_results"] == 3
    assert captured["where"] is None
    assert len(docs) == 2
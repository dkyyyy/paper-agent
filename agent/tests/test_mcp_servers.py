"""Tests for MCP server and client helpers."""

import asyncio
import json
import sys
from types import SimpleNamespace

import fitz
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from app.mcp_servers import client as client_module


def test_decode_tool_result_prefers_structured_content():
    result = SimpleNamespace(
        structuredContent=[{"paper_id": "arxiv:1", "title": "Paper"}],
        content=[SimpleNamespace(type="text", text='[{"paper_id": "wrong"}]')],
        isError=False,
    )

    assert client_module._decode_tool_result(result) == [{"paper_id": "arxiv:1", "title": "Paper"}]


def test_decode_tool_result_falls_back_to_text_content():
    result = SimpleNamespace(
        structuredContent=None,
        content=[SimpleNamespace(type="text", text=json.dumps([{"paper_id": "s2:1"}]))],
        isError=False,
    )

    assert client_module._decode_tool_result(result) == [{"paper_id": "s2:1"}]


def test_call_mcp_tool_runs_async_backend(monkeypatch):
    calls = {}

    async def fake_async_call(server_module: str, tool_name: str, arguments: dict):
        calls["server_module"] = server_module
        calls["tool_name"] = tool_name
        calls["arguments"] = arguments
        return [{"paper_id": "arxiv:demo"}]

    monkeypatch.setattr(client_module, "_call_mcp_tool_async", fake_async_call)

    result = client_module.call_mcp_tool(
        "app.mcp_servers.arxiv_server",
        "arxiv_search",
        {"query": "rag", "max_results": 5, "year_from": 2024},
    )

    assert result == [{"paper_id": "arxiv:demo"}]
    assert calls == {
        "server_module": "app.mcp_servers.arxiv_server",
        "tool_name": "arxiv_search",
        "arguments": {"query": "rag", "max_results": 5, "year_from": 2024},
    }


def test_call_mcp_tool_uses_current_python_executable(monkeypatch):
    captured = {}

    class FakeToolParams:
        def __init__(self, command, args):
            captured["command"] = command
            captured["args"] = args

    class FakeStdioClient:
        async def __aenter__(self):
            return ("read", "write")

        async def __aexit__(self, exc_type, exc, tb):
            del exc_type, exc, tb
            return False

    class FakeSession:
        def __init__(self, read_stream, write_stream):
            captured["streams"] = (read_stream, write_stream)

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            del exc_type, exc, tb
            return False

        async def initialize(self):
            return None

        async def list_tools(self):
            return SimpleNamespace(tools=[SimpleNamespace(name="arxiv_search")])

        async def call_tool(self, tool_name, arguments):
            captured["tool_name"] = tool_name
            captured["arguments"] = arguments
            return SimpleNamespace(
                structuredContent=[{"paper_id": "arxiv:1"}],
                content=[],
                isError=False,
            )

    monkeypatch.setattr(client_module, "StdioServerParameters", FakeToolParams)
    monkeypatch.setattr(client_module, "stdio_client", lambda params: FakeStdioClient())
    monkeypatch.setattr(client_module, "ClientSession", FakeSession)

    result = client_module.call_mcp_tool(
        "app.mcp_servers.arxiv_server",
        "arxiv_search",
        {"query": "rag", "max_results": 5, "year_from": 2024},
    )

    assert result == [{"paper_id": "arxiv:1"}]
    assert captured["command"] == sys.executable
    assert captured["args"] == ["-m", "app.mcp_servers.arxiv_server"]


async def _list_tool_names(server_module: str) -> list[str]:
    params = StdioServerParameters(command=sys.executable, args=["-m", server_module])
    async with stdio_client(params) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            tools = await session.list_tools()
            return [tool.name for tool in tools.tools]


def test_arxiv_server_lists_search_tool():
    from app.mcp_servers import arxiv_server

    tools = asyncio.run(arxiv_server.list_tools())

    assert [tool.name for tool in tools] == ["arxiv_search"]
    assert tools[0].inputSchema["required"] == ["query"]


def test_arxiv_server_call_tool_parses_feed_and_filters_year(monkeypatch):
    from app.mcp_servers import arxiv_server

    xml_payload = """<?xml version='1.0' encoding='UTF-8'?>
<feed xmlns='http://www.w3.org/2005/Atom'>
  <entry>
    <id>http://arxiv.org/abs/2401.12345</id>
    <title>Recent RAG Paper</title>
    <summary>Paper abstract.</summary>
    <published>2024-01-01T00:00:00Z</published>
    <author><name>Author A</name></author>
  </entry>
  <entry>
    <id>http://arxiv.org/abs/2101.11111</id>
    <title>Old Paper</title>
    <summary>Old abstract.</summary>
    <published>2021-01-01T00:00:00Z</published>
    <author><name>Author B</name></author>
  </entry>
</feed>
"""

    monkeypatch.setattr(arxiv_server, "_fetch_arxiv_payload", lambda query, max_results: xml_payload)

    response = asyncio.run(
        arxiv_server.call_tool(
            "arxiv_search",
            {"query": "rag", "max_results": 5, "year_from": 2023},
        )
    )

    payload = json.loads(response[0].text)
    assert [paper["paper_id"] for paper in payload] == ["arxiv:2401.12345"]
    assert payload[0]["source"] == "arxiv"
    assert payload[0]["citation_count"] == 0


def test_semantic_scholar_server_lists_search_tool():
    from app.mcp_servers import semantic_scholar

    tools = asyncio.run(semantic_scholar.list_tools())

    assert [tool.name for tool in tools] == ["s2_search"]


def test_semantic_scholar_tool_list_available_over_stdio():
    tool_names = asyncio.run(_list_tool_names("app.mcp_servers.semantic_scholar"))

    assert tool_names == ["s2_search"]


def test_semantic_scholar_server_call_tool_parses_json(monkeypatch):
    from app.mcp_servers import semantic_scholar

    payload = {
        "data": [
            {
                "paperId": "abc123",
                "title": "Semantic Search Paper",
                "abstract": "Paper abstract.",
                "year": 2025,
                "authors": [{"name": "Author B"}],
                "citationCount": 42,
                "externalIds": {"DOI": "10.1000/xyz"},
                "url": "https://example.org/paper",
            }
        ]
    }

    monkeypatch.setattr(semantic_scholar, "_fetch_s2_payload", lambda query, max_results, year_from: payload)

    response = asyncio.run(
        semantic_scholar.call_tool(
            "s2_search",
            {"query": "rag", "max_results": 5, "year_from": 2024},
        )
    )

    papers = json.loads(response[0].text)
    assert papers[0]["paper_id"] == "s2:abc123"
    assert papers[0]["source"] == "semantic_scholar"
    assert papers[0]["doi"] == "10.1000/xyz"


def test_pdf_parser_lists_parse_tool():
    from app.mcp_servers import pdf_parser

    tools = asyncio.run(pdf_parser.list_tools())

    assert [tool.name for tool in tools] == ["parse_pdf"]


def test_pdf_parser_tool_list_available_over_stdio():
    tool_names = asyncio.run(_list_tool_names("app.mcp_servers.pdf_parser"))

    assert tool_names == ["parse_pdf"]


def test_pdf_parser_returns_page_structured_text(tmp_path):
    from app.mcp_servers import pdf_parser

    pdf_path = tmp_path / "paper.pdf"

    document = fitz.open()
    page = document.new_page()
    page.insert_text((72, 72), "Page one text")
    document.set_metadata({"title": "Structured PDF"})
    document.save(pdf_path)
    document.close()

    response = asyncio.run(pdf_parser.call_tool("parse_pdf", {"file_path": str(pdf_path)}))
    payload = json.loads(response[0].text)

    assert payload["title"] == "Structured PDF"
    assert payload["page_count"] == 1
    assert payload["full_text"].strip() == "Page one text"
    assert payload["pages"] == [{"page_number": 1, "text": "Page one text"}]


def test_call_mcp_tool_invokes_pdf_parser_over_stdio(tmp_path):
    pdf_path = tmp_path / "roundtrip.pdf"

    document = fitz.open()
    page = document.new_page()
    page.insert_text((72, 72), "Roundtrip text")
    document.save(pdf_path)
    document.close()

    payload = client_module.call_mcp_tool(
        "app.mcp_servers.pdf_parser",
        "parse_pdf",
        {"file_path": str(pdf_path)},
    )

    assert payload["page_count"] == 1
    assert payload["pages"][0]["text"] == "Roundtrip text"


def test_arxiv_server_module_imports():
    import app.mcp_servers.arxiv_server as module

    assert module.app is not None

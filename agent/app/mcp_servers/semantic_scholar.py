"""Semantic Scholar MCP server."""

import asyncio
import json
import time
import urllib.parse
import urllib.request
from typing import Any
from urllib.error import HTTPError

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool

from app.config import config
from app.mcp_servers.common import build_url_opener, json_text_content

app = Server("semantic-scholar-server")


def _fetch_s2_payload(query: str, max_results: int, year_from: int) -> dict[str, Any]:
    """Fetch Semantic Scholar paper search results."""
    encoded_query = urllib.parse.quote(query)
    year_filter = f"&year={year_from}-" if year_from else ""
    url = (
        "https://api.semanticscholar.org/graph/v1/paper/search?"
        f"query={encoded_query}&limit={max_results}{year_filter}&"
        "fields=paperId,title,abstract,year,authors,citationCount,externalIds,url"
    )

    headers = {"User-Agent": "PaperAgent/1.0"}
    if config.semantic_scholar_api_key:
        headers["x-api-key"] = config.semantic_scholar_api_key

    request = urllib.request.Request(url, headers=headers)
    opener = build_url_opener()
    with opener.open(request, timeout=15) as response:
        return json.loads(response.read().decode("utf-8"))


def _normalize_s2_payload(payload: dict[str, Any], year_from: int) -> list[dict[str, Any]]:
    """Normalize Semantic Scholar payloads to the shared paper schema."""
    results: list[dict[str, Any]] = []
    for paper in payload.get("data", []):
        year = paper.get("year") or 0
        if year_from and year and year < year_from:
            continue

        results.append(
            {
                "paper_id": f"s2:{paper.get('paperId', '')}",
                "title": paper.get("title", ""),
                "authors": [author.get("name", "") for author in paper.get("authors", [])],
                "abstract": paper.get("abstract") or "",
                "year": year,
                "source": "semantic_scholar",
                "doi": (paper.get("externalIds") or {}).get("DOI", ""),
                "url": paper.get("url", ""),
                "citation_count": paper.get("citationCount") or 0,
            }
        )

    return results


@app.list_tools()
async def list_tools() -> list[Tool]:
    """List tools exposed by the Semantic Scholar MCP server."""
    return [
        Tool(
            name="s2_search",
            description="Search academic papers on Semantic Scholar.",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "max_results": {"type": "integer", "default": 20},
                    "year_from": {"type": "integer", "default": 0},
                },
                "required": ["query"],
            },
        )
    ]


@app.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[Any]:
    """Execute the requested Semantic Scholar tool."""
    if name != "s2_search":
        raise ValueError(f"Unknown tool: {name}")

    query = str(arguments["query"])
    max_results = int(arguments.get("max_results", 20))
    year_from = int(arguments.get("year_from", 0))

    for attempt in range(3):
        try:
            payload = _fetch_s2_payload(query, max_results, year_from)
            return json_text_content(_normalize_s2_payload(payload, year_from))
        except HTTPError as exc:
            if exc.code == 429 and attempt < 2:
                time.sleep((2 ** attempt) * 2)
                continue
            raise
        except Exception:
            if attempt == 2:
                raise
            time.sleep(2 ** attempt)

    return json_text_content([])


async def main() -> None:
    """Run the Semantic Scholar MCP server over stdio."""
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())

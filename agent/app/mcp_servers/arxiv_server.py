"""ArXiv MCP server."""

import asyncio
import re
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from typing import Any

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool

from app.mcp_servers.common import build_url_opener, json_text_content

app = Server("arxiv-server")


def _fetch_arxiv_payload(query: str, max_results: int) -> str:
    """Fetch the raw Atom feed payload for an ArXiv query."""
    arxiv_ids = re.findall(r"(?:arXiv:)?(\d{4}\.\d{4,5})", query, re.IGNORECASE)
    if arxiv_ids:
        url = f"http://export.arxiv.org/api/query?id_list={','.join(arxiv_ids)}"
    else:
        encoded_query = urllib.parse.quote(query)
        url = (
            "http://export.arxiv.org/api/query?"
            f"search_query=all:{encoded_query}&start=0&max_results={max_results}&sortBy=relevance"
        )

    request = urllib.request.Request(url, headers={"User-Agent": "PaperAgent/1.0"})
    opener = build_url_opener()
    with opener.open(request, timeout=15) as response:
        return response.read().decode("utf-8")


def _parse_arxiv_payload(payload: str, year_from: int) -> list[dict[str, Any]]:
    """Parse an ArXiv Atom feed payload into normalized paper records."""
    root = ET.fromstring(payload)
    namespace = {"atom": "http://www.w3.org/2005/Atom"}
    results: list[dict[str, Any]] = []

    for entry in root.findall("atom:entry", namespace):
        published = entry.find("atom:published", namespace)
        year = int(published.text[:4]) if published is not None and published.text else 0
        if year_from and year and year < year_from:
            continue

        paper_url = entry.find("atom:id", namespace)
        title = entry.find("atom:title", namespace)
        summary = entry.find("atom:summary", namespace)
        authors = [
            author.find("atom:name", namespace).text
            for author in entry.findall("atom:author", namespace)
            if author.find("atom:name", namespace) is not None
            and author.find("atom:name", namespace).text
        ]

        results.append(
            {
                "paper_id": f"arxiv:{paper_url.text.split('/')[-1]}" if paper_url is not None and paper_url.text else "",
                "title": title.text.strip().replace("\n", " ") if title is not None and title.text else "",
                "authors": authors,
                "abstract": summary.text.strip().replace("\n", " ") if summary is not None and summary.text else "",
                "year": year,
                "source": "arxiv",
                "doi": "",
                "url": paper_url.text if paper_url is not None and paper_url.text else "",
                "citation_count": 0,
            }
        )

    return results


@app.list_tools()
async def list_tools() -> list[Tool]:
    """List tools exposed by the ArXiv MCP server."""
    return [
        Tool(
            name="arxiv_search",
            description="Search academic papers on ArXiv.",
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
    """Execute the requested ArXiv tool."""
    if name != "arxiv_search":
        raise ValueError(f"Unknown tool: {name}")

    query = str(arguments["query"])
    max_results = int(arguments.get("max_results", 20))
    year_from = int(arguments.get("year_from", 0))

    for attempt in range(3):
        try:
            payload = _fetch_arxiv_payload(query, max_results)
            return json_text_content(_parse_arxiv_payload(payload, year_from))
        except Exception:
            if attempt == 2:
                raise
            time.sleep(2 ** attempt)

    return json_text_content([])


async def main() -> None:
    """Run the ArXiv MCP server over stdio."""
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())

"""PDF parser MCP server."""

import asyncio
from pathlib import Path
from typing import Any

import fitz
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool

from app.mcp_servers.common import json_text_content

app = Server("pdf-parser-server")


def _parse_pdf_file(file_path: str) -> dict[str, Any]:
    """Parse a local PDF file into page-structured text."""
    path = Path(file_path).expanduser().resolve()
    if not path.exists():
        raise FileNotFoundError(f"PDF file not found: {path}")

    with fitz.open(path) as document:
        title = (document.metadata or {}).get("title") or path.stem
        pages = [
            {
                "page_number": index,
                "text": page.get_text("text").strip(),
            }
            for index, page in enumerate(document, start=1)
        ]

    full_text = "\n\n".join(page["text"] for page in pages if page["text"])
    return {
        "title": title,
        "page_count": len(pages),
        "full_text": full_text,
        "pages": pages,
    }


@app.list_tools()
async def list_tools() -> list[Tool]:
    """List tools exposed by the PDF parser MCP server."""
    return [
        Tool(
            name="parse_pdf",
            description="Parse a local PDF file into structured text.",
            inputSchema={
                "type": "object",
                "properties": {
                    "file_path": {"type": "string"},
                },
                "required": ["file_path"],
            },
        )
    ]


@app.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[Any]:
    """Execute the requested PDF parser tool."""
    if name != "parse_pdf":
        raise ValueError(f"Unknown tool: {name}")

    return json_text_content(_parse_pdf_file(str(arguments["file_path"])))


async def main() -> None:
    """Run the PDF parser MCP server over stdio."""
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())

"""Client helpers for invoking local MCP server tools over stdio."""

import asyncio
import json
import sys
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


def _decode_tool_result(result: Any) -> Any:
    """Decode an MCP tool result into a Python payload."""
    structured_content = getattr(result, "structuredContent", None)
    if structured_content is not None:
        return structured_content

    for item in getattr(result, "content", []) or []:
        if getattr(item, "type", None) != "text":
            continue
        try:
            return json.loads(getattr(item, "text", ""))
        except json.JSONDecodeError as exc:
            raise ValueError("Unable to decode MCP tool result") from exc

    raise ValueError("Unable to decode MCP tool result")


async def _call_mcp_tool_async(server_module: str, tool_name: str, arguments: dict[str, Any]) -> Any:
    """Call an MCP tool exposed by a local Python module."""
    server_params = StdioServerParameters(command=sys.executable, args=["-m", server_module])

    async with stdio_client(server_params) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            tools_response = await session.list_tools()
            tool_names = {tool.name for tool in getattr(tools_response, "tools", [])}
            if tool_name not in tool_names:
                raise ValueError(
                    f"MCP server module '{server_module}' does not expose tool '{tool_name}'"
                )

            result = await session.call_tool(tool_name, arguments)
            if getattr(result, "isError", False):
                raise ValueError(f"MCP tool '{tool_name}' returned an error")
            return _decode_tool_result(result)


def call_mcp_tool(server_module: str, tool_name: str, arguments: dict[str, Any]) -> Any:
    """Synchronously call a local MCP tool."""
    return asyncio.run(_call_mcp_tool_async(server_module, tool_name, arguments))

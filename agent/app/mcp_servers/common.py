"""Common helpers shared by local MCP server modules."""

import json
import urllib.request
from typing import TYPE_CHECKING, Any

from app.config import config

if TYPE_CHECKING:
    from mcp.types import TextContent


def build_proxy_handler() -> urllib.request.ProxyHandler | None:
    """Build a urllib proxy handler from configured HTTP(S) proxies."""
    proxies: dict[str, str] = {}
    if config.http_proxy:
        proxies["http"] = config.http_proxy
    if config.https_proxy:
        proxies["https"] = config.https_proxy
    if not proxies:
        return None
    return urllib.request.ProxyHandler(proxies)


def build_url_opener() -> urllib.request.OpenerDirector:
    """Build a urllib opener that respects configured proxies when present."""
    proxy_handler = build_proxy_handler()
    if proxy_handler is None:
        return urllib.request.build_opener()
    return urllib.request.build_opener(proxy_handler)


def json_text_content(payload: Any) -> list["TextContent"]:
    """Encode a payload as JSON MCP text content."""
    from mcp.types import TextContent

    return [
        TextContent(
            type="text",
            text=json.dumps(payload, ensure_ascii=False, sort_keys=True),
        )
    ]

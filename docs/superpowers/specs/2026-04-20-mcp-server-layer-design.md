# MCP Server Layer Design

**Date:** 2026-04-20

**Goal**

Implement the missing MCP server layer under `agent/app/mcp_servers/` and replace direct provider HTTP calls in `agent/app/agents/search_agent.py` with MCP client calls, while preserving the current search planning, caching, deduplication, and ranking behavior.

**Scope**

- Add `agent/app/mcp_servers/arxiv_server.py`
- Add `agent/app/mcp_servers/semantic_scholar.py`
- Add `agent/app/mcp_servers/pdf_parser.py`
- Add shared MCP helpers for server/client integration
- Update `agent/app/agents/search_agent.py` to call ArXiv and Semantic Scholar through an MCP client
- Add or update tests covering MCP tool discovery, tool execution, and search-agent integration

**Non-Goals**

- Do not refactor the uploaded paper persistence flow in `agent/app/services/paper_store.py`
- Do not change the supervisor or analysis workflow beyond what is required for the search-agent integration
- Do not add new external providers such as DBLP in this change
- Do not introduce a persistent MCP daemon process; per-call stdio startup is sufficient for this phase

## Context

The architecture document defines an MCP tool layer between agents and external systems. The current codebase does not implement that layer. `search_agent.py` directly uses `urllib` to call the ArXiv API and the Semantic Scholar API, which violates the intended boundary and the acceptance criteria in `docs/05-unimplemented.md`.

The implementation must satisfy three conditions:

1. `python -m app.mcp_servers.arxiv_server` can start successfully
2. MCP tool discovery works so an inspector can list the available tools
3. `search_agent.py` uses an MCP client rather than direct `urllib` calls for provider access

## Chosen Approach

Use one MCP server module per external capability and a small shared MCP client helper used by agent code.

This keeps responsibilities narrow:

- `arxiv_server.py` owns ArXiv HTTP interaction and result normalization
- `semantic_scholar.py` owns Semantic Scholar HTTP interaction and result normalization
- `pdf_parser.py` owns PDF parsing and page-structured text extraction
- `client.py` owns server startup, MCP session initialization, tool lookup, tool invocation, and response decoding
- `search_agent.py` owns search planning, cache lookup, event emission, deduplication, and ranking

This matches the architecture document more closely than either a single aggregated server or a pseudo-MCP wrapper that still imports provider code directly.

## File Layout

### New files

- `agent/app/mcp_servers/__init__.py`
- `agent/app/mcp_servers/common.py`
- `agent/app/mcp_servers/client.py`
- `agent/app/mcp_servers/arxiv_server.py`
- `agent/app/mcp_servers/semantic_scholar.py`
- `agent/app/mcp_servers/pdf_parser.py`
- `agent/tests/test_mcp_servers.py`

### Modified files

- `agent/app/agents/search_agent.py`
- `agent/requirements.txt`
- `agent/tests/test_search.py`

## Data Contracts

### Search result contract

Both `arxiv_search` and `s2_search` return a JSON-serializable list of paper dictionaries matching the current `Paper` structure used by `search_agent.py`:

```python
{
    "paper_id": str,
    "title": str,
    "authors": list[str],
    "abstract": str,
    "year": int,
    "source": str,
    "doi": str,
    "url": str,
    "citation_count": int,
}
```

Provider-specific details are normalized inside each server so the search agent continues to consume a stable schema.

### PDF parser contract

`parse_pdf(file_path)` returns:

```python
{
    "title": str,
    "page_count": int,
    "full_text": str,
    "pages": [
        {
            "page_number": int,
            "text": str,
        }
    ],
}
```

This is the minimum page-structured format that satisfies the “structured text” requirement and leaves room for future RAG integration without forcing block-level parsing now.

## Component Design

### `agent/app/mcp_servers/common.py`

Shared helpers:

- Build `urllib` proxy handlers from `app.config.config`
- Perform HTTP requests with consistent headers and timeouts
- Serialize Python results into MCP `TextContent`
- Parse and validate integer/string inputs where needed

This prevents duplicated transport and JSON boilerplate across server modules.

### `agent/app/mcp_servers/client.py`

Responsibilities:

- Start an MCP server subprocess through stdio using `python -m <module>`
- Create and initialize an MCP client session
- Verify the requested tool exists in `list_tools()`
- Call the tool with provided arguments
- Prefer structured result data when available
- Fall back to JSON decoding of text content
- Raise a clear Python exception when protocol or tool execution fails

The helper will provide a synchronous wrapper so existing synchronous LangGraph nodes in `search_agent.py` do not need to become async.

### `agent/app/mcp_servers/arxiv_server.py`

Responsibilities:

- Expose one MCP tool: `arxiv_search(query, max_results, year_from)`
- Support direct ArXiv ID lookup when the query contains one or more ArXiv identifiers
- Otherwise call `http://export.arxiv.org/api/query`
- Parse Atom XML responses
- Normalize fields into the shared paper contract
- Apply local `year_from` filtering after parsing
- Retry transient failures up to three attempts with backoff

The module must expose a runnable `__main__` path compatible with `python -m app.mcp_servers.arxiv_server`.

### `agent/app/mcp_servers/semantic_scholar.py`

Responsibilities:

- Expose one MCP tool: `s2_search(query, max_results, year_from)`
- Call the Semantic Scholar paper search endpoint
- Include `x-api-key` when configured
- Request the fields needed by the paper contract
- Apply provider-side year filtering and local filtering as a safeguard
- Retry rate-limit failures with backoff
- Normalize all results into the shared paper contract

### `agent/app/mcp_servers/pdf_parser.py`

Responsibilities:

- Expose one MCP tool: `parse_pdf(file_path)`
- Open a local file with `fitz`
- Extract document title from metadata, falling back to the filename stem
- Extract plain text per page
- Build `full_text` by joining page texts with blank lines
- Return the page-structured contract

The tool should validate file existence and return a protocol-level error message when the path is invalid or unreadable.

## Search-Agent Integration

`agent/app/agents/search_agent.py` will keep:

- keyword extraction
- adaptive query expansion
- provider orchestration order
- cache lookups and writes
- result deduplication
- ranking
- event emission

The direct provider functions will change behavior:

- `_search_arxiv(...)` will call the MCP client helper targeting `app.mcp_servers.arxiv_server`
- `_search_semantic_scholar(...)` will call the MCP client helper targeting `app.mcp_servers.semantic_scholar`

The public behavior of these functions should remain the same:

- same input parameters
- same cache keys
- same result shape
- same failure behavior of returning `[]` after logging on unrecoverable provider errors

This keeps the rest of the graph and its tests stable.

## Execution Flow

For each pending search query inside `execute_search()`:

1. Check cache in `_search_semantic_scholar`
2. If cache miss, invoke MCP client for `s2_search`
3. Store normalized results in cache
4. Check cache in `_search_arxiv`
5. If cache miss, invoke MCP client for `arxiv_search`
6. Store normalized results in cache
7. Merge raw provider results and continue into deduplication/ranking

The search agent remains the only place that knows provider ordering and search orchestration. MCP servers remain stateless adapters around individual external systems.

## Error Handling

### Server-side failures

Each server handles provider- or file-specific failures locally:

- request timeout
- malformed provider payload
- rate limiting
- missing file
- unreadable PDF

Server tools should return an MCP error result instead of crashing the process where possible.

### Client-side failures

The MCP client helper raises descriptive exceptions when:

- the subprocess cannot start
- session initialization fails
- the requested tool is missing from `list_tools()`
- the tool result is marked as an error
- the returned content cannot be decoded into the expected structure

### Agent-level behavior

`search_agent.py` catches MCP client exceptions inside `_search_arxiv` and `_search_semantic_scholar`, logs them, and returns `[]` just as it currently does for provider failures. A failure in one provider must not prevent the other provider from being queried for the same search term.

## Configuration

The new MCP implementation must continue using the existing configuration source:

- `HTTP_PROXY` / `http_proxy`
- `HTTPS_PROXY` / `https_proxy`
- `SEMANTIC_SCHOLAR_API_KEY`

No new environment variables are required for this feature.

`agent/requirements.txt` must add the Python MCP SDK dependency needed for both server and client usage.

## Testing Strategy

### New tests: `agent/tests/test_mcp_servers.py`

Cover:

- ArXiv server tool discovery includes `arxiv_search`
- Semantic Scholar server tool discovery includes `s2_search`
- PDF parser tool discovery includes `parse_pdf`
- ArXiv tool execution parses XML into normalized results
- Semantic Scholar tool execution parses JSON into normalized results
- PDF parser returns page-structured output for a temporary PDF

Tests should mock external HTTP interaction rather than using live network calls.

### Updated tests: `agent/tests/test_search.py`

Update the search-agent tests so they no longer patch `urllib` directly. Instead:

- monkeypatch the shared MCP client helper used by `_search_arxiv`
- monkeypatch the shared MCP client helper used by `_search_semantic_scholar`
- verify cache hits avoid repeated MCP calls
- verify `run_search()` still merges provider results, emits events, and preserves ranking behavior

### Smoke verification

Add a lightweight test or command check that importing and starting `app.mcp_servers.arxiv_server` does not fail at module load time. This supports the acceptance criterion that `python -m app.mcp_servers.arxiv_server` is startable.

## Acceptance Criteria Mapping

### `python -m app.mcp_servers.arxiv_server` can start independently

- Achieved by giving `arxiv_server.py` a runnable stdio entrypoint
- Verified by a smoke test and a manual command run during verification

### MCP Inspector can see the tool list

- Achieved by implementing MCP `list_tools()` correctly for each server
- Verified in tests by listing tools through the server/session boundary

### `search_agent.py` uses an MCP client rather than direct `urllib`

- Achieved by removing direct provider HTTP logic from `search_agent.py`
- Verified by code changes plus search-agent tests that patch the MCP client helper instead of `urllib`

## Risks and Mitigations

### Risk: MCP SDK API mismatch

Mitigation:

- Confirm the installed SDK API before implementation
- Isolate MCP SDK usage inside `client.py` and server entrypoints so later adjustments stay localized

### Risk: Per-call stdio startup overhead

Mitigation:

- Accept the overhead for this feature because current search volume is small and the primary goal is boundary correctness
- Keep cache behavior unchanged so repeated searches still avoid redundant provider calls

### Risk: Response shape drift between provider servers and search agent

Mitigation:

- Define and test the normalized paper contract explicitly
- Reuse the same contract in both provider tests and search-agent integration tests

## Implementation Notes

- Use the same logger style already present in the agent service
- Keep the search-agent API stable so supervisor code does not need to change
- Keep comments minimal and only where behavior is not obvious
- Preserve ASCII-only edits unless existing files require otherwise

## Out of Scope Follow-ups

- Switch uploaded-paper ingestion to call `parse_pdf` instead of parsing directly in `paper_store.py`
- Add `dblp_server.py`
- Reuse long-lived MCP server processes if stdio startup cost becomes measurable

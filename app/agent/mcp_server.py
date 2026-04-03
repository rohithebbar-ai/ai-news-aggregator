"""
Day 6: MCP server exposing RAG and DB tools for the agent loop.

Tools exposed:
  - search_similar: vector similarity search over articles
  - get_recent_themes: fetch latest theme groups
  - get_recent_insights: fetch latest synthesized insights

Optional: set MCP_API_KEY to require matching HTTP header x-api-key on every tool call
(HTTP transports). If unset, the server logs a warning and accepts unauthenticated calls.

Usage: uv run python -m app.agent.mcp_server
"""

import hashlib
import hmac
import logging
import os

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.server.dependencies import get_http_headers
from fastmcp.server.middleware import Middleware, MiddlewareContext

from app.db.connection import get_session
from app.db.schema import InsightTable, ThemeTable
from app.embeddings.vector_store import search_by_text

logger = logging.getLogger(__name__)

mcp = FastMCP("ai-news-tools")


def _api_key_matches(provided: str | None, expected: str) -> bool:
    """Constant-time comparison without requiring equal-length raw strings."""
    pa = hashlib.sha256((provided or "").encode("utf-8")).digest()
    pb = hashlib.sha256(expected.encode("utf-8")).digest()
    return hmac.compare_digest(pa, pb)


class ApiKeyMiddleware(Middleware):
    """Require x-api-key header when an expected key is configured."""

    def __init__(self, expected_key: str) -> None:
        self._expected_key = expected_key

    async def on_call_tool(self, context: MiddlewareContext, call_next):
        headers = get_http_headers() or {}
        api_key = next(
            (v for k, v in headers.items() if k.lower() == "x-api-key"),
            None,
        )
        if not _api_key_matches(str(api_key) if api_key is not None else None, self._expected_key):
            raise ToolError("Unauthorized: invalid or missing x-api-key header")
        return await call_next(context)


_mcp_api_key = os.environ.get("MCP_API_KEY", "").strip()
if _mcp_api_key:
    mcp.add_middleware(ApiKeyMiddleware(_mcp_api_key))
else:
    logger.warning(
        "MCP_API_KEY is not set; MCP tool calls are not authenticated (server unsecured)."
    )


@mcp.tool()
def search_similar(query: str, top_k: int = 5) -> list[dict]:
    """Search for articles semantically similar to the query using pgvector."""
    with get_session() as session:
        results = search_by_text(session, query, top_k=top_k)
    return [
        {"title": r["title"], "url": r["url"], "summary": r["summary"], "score": round(r["score"], 3)}
        for r in results
    ]


@mcp.tool()
def get_recent_themes(limit: int = 10) -> list[dict]:
    """Return the most recently stored theme groups."""
    from sqlalchemy import select

    with get_session() as session:
        rows = session.execute(
            select(ThemeTable.theme_json).order_by(ThemeTable.created_at.desc()).limit(limit)
        ).all()
    return [r.theme_json for r in rows]


@mcp.tool()
def get_recent_insights(limit: int = 10) -> list[dict]:
    """Return the most recently synthesized insights."""
    from sqlalchemy import select

    with get_session() as session:
        rows = session.execute(
            select(InsightTable.insight_json).order_by(InsightTable.created_at.desc()).limit(limit)
        ).all()
    return [r.insight_json for r in rows]


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    mcp.run()

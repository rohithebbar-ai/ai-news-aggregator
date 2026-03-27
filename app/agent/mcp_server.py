"""
Day 6: MCP server exposing RAG and DB tools for the agent loop.

Tools exposed:
  - search_similar: vector similarity search over articles
  - get_recent_themes: fetch latest theme groups
  - get_recent_insights: fetch latest synthesized insights

Usage: uv run python -m app.agent.mcp_server
"""

import logging

from fastmcp import FastMCP

from app.db.connection import get_session
from app.db.schema import InsightTable, ThemeTable
from app.embeddings.vector_store import search_by_text

logger = logging.getLogger(__name__)

mcp = FastMCP("ai-news-tools")


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

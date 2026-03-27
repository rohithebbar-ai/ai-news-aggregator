"""
Day 6: LangGraph ReAct agent loop for agentic insight synthesis.

The agent autonomously decides when to call RAG tools to enrich context
before synthesizing a trend insight for each theme.

Usage: uv run python -m app.agent.agent_loop
"""

import json
import logging
import os

from dotenv import load_dotenv
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI
from langgraph.prebuilt import create_react_agent

load_dotenv()

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are an AI trend analyst with access to a RAG search tool and theme history.

For the given theme:
1. Use rag_search to find historically similar articles (1-2 searches with relevant queries)
2. Use get_recent_themes if you need broader context on current trends
3. Synthesize everything into a JSON insight

Return ONLY a valid JSON object with exactly these fields:
{
  "trend_name": "<concise trend name>",
  "analysis": "<2-3 paragraph analysis>",
  "evidence": ["<url1>", "<url2>"],
  "historical_context": "<how this compares to past trends>",
  "confidence_level": "<high|medium|low>",
  "direction": "<accelerating|stable|emerging|declining>"
}"""


def _make_tools(session):
    """Build LangChain tools bound to the current DB session."""

    @tool
    def rag_search(query: str) -> str:
        """Search for articles semantically similar to the query."""
        from app.embeddings.vector_store import search_by_text

        results = search_by_text(session, query, top_k=5)
        if not results:
            return "No similar articles found."
        lines = [f"- {r['title']} ({r['url']}) score={r['score']:.2f}" for r in results]
        return "\n".join(lines)

    @tool
    def get_recent_themes() -> str:
        """Return recent theme names for broader context."""
        from sqlalchemy import select
        from app.db.schema import ThemeTable

        rows = session.execute(
            select(ThemeTable.theme_json).order_by(ThemeTable.created_at.desc()).limit(10)
        ).all()
        names = [r.theme_json.get("theme_name", "unknown") for r in rows]
        return ", ".join(names) if names else "No themes found."

    return [rag_search, get_recent_themes]


def _build_prompt(theme: dict, article_urls: dict) -> str:
    lines = [
        f"Theme: {theme.get('theme_name', 'unknown')}",
        f"Description: {theme.get('description', '')}",
        "Current articles:",
    ]
    for aid in theme.get("article_ids", []):
        url = article_urls.get(str(aid), f"article #{aid}")
        lines.append(f"  - {url}")
    return "\n".join(lines)


def run_agent_for_theme(session, theme: dict, article_urls: dict) -> dict:
    """Run the ReAct agent for a single theme and return the insight dict."""
    # Use Groq's OpenAI-compatible endpoint — avoids langchain-groq/groq version conflict
    llm = ChatOpenAI(
        model="llama-3.3-70b-versatile",
        api_key=os.getenv("GROQ_API_KEY", ""),
        base_url="https://api.groq.com/openai/v1",
        temperature=0.3,
    )
    tools = _make_tools(session)
    agent = create_react_agent(llm, tools, prompt=SYSTEM_PROMPT)

    prompt = _build_prompt(theme, article_urls)
    result = agent.invoke({"messages": [("user", prompt)]})

    # Extract last AI message content
    last_msg = result["messages"][-1].content
    # Strip markdown fences if present
    if "```" in last_msg:
        last_msg = last_msg.split("```")[1].lstrip("json").strip()

    return json.loads(last_msg)


def run() -> None:
    """Run the agent loop for all themes in the latest batch."""
    from app.db.connection import get_session as db_session
    from app.llm.synthesizer import _get_article_urls, _get_latest_themes, _persist_insight

    with db_session() as session:
        batch_id, themes = _get_latest_themes(session)
        if not themes:
            print("No themes found — run the LLM pipeline first.")
            return

        logger.info("Agent loop: processing %d themes (batch %s)", len(themes), batch_id)
        success = 0
        for theme in themes:
            article_ids = theme.get("article_ids", [])
            article_urls = _get_article_urls(session, article_ids)
            theme_name = theme.get("theme_name", "?")
            try:
                insight = run_agent_for_theme(session, theme, article_urls)
                _persist_insight(session, batch_id, insight)
                logger.info("  ✓ %s (%s)", insight.get("trend_name", "?"), insight.get("direction", "?"))
                success += 1
            except Exception as e:
                logger.error("  ✗ Failed for theme '%s': %s", theme_name, e)

    print(f"Agent loop complete: {success}/{len(themes)} insights generated for batch {batch_id}.")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run()

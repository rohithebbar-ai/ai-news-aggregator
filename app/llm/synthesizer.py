"""
Stage 3: Insight synthesis with RAG-enhanced historical context.
For each theme from Stage 2, retrieves similar past articles via pgvector,
then calls Groq to produce trend insights.

Usage: uv run python -m app.llm.synthesizer
"""

import json
import logging
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.schema import ArticleTable, InsightTable, ThemeTable
from app.llm.groq_client import call_llm_json

logger = logging.getLogger(__name__)


def _parse_valid_article_ids(raw: Any) -> list[uuid.UUID]:
    """Keep only well-formed UUIDs from LLM output; skip hallucinated or malformed strings."""
    out: list[uuid.UUID] = []
    if not isinstance(raw, list):
        return out
    for item in raw:
        try:
            if isinstance(item, uuid.UUID):
                out.append(item)
            else:
                out.append(uuid.UUID(str(item).strip()))
        except (ValueError, TypeError, AttributeError):
            logger.warning("Skipping invalid article_id from theme JSON: %r", item)
    return out


SYSTEM_PROMPT = """You are an AI trend analyst producing intelligence reports for a professional audience.

Given a theme and its supporting articles, produce a detailed insight analysis.

QUALITY RULES — your output MUST follow all of these:
- Name specific companies, products, model versions, and benchmark results from the articles. No vague phrases like "leading AI companies" or "significant developments".
- The `analysis` field must contain at least 3 concrete named entities (company names, model names, version numbers, or specific metrics).
- The `evidence` field must list the exact URLs of the articles most relevant to this theme.
- The `historical_context` must reference something specific from the past (a named earlier model, a previous year's benchmark, a prior company announcement).
- If the articles contain numbers or metrics (accuracy %, latency ms, parameter count, cost), include them.
- Do NOT use filler phrases: "remains to be seen", "rapidly evolving", "game-changing", "significant implications", "exciting developments".

Return a JSON object with exactly these fields:
{
  "trend_name": "<concise name — must mention the specific technology or company driving the trend>",
  "analysis": "<3 paragraphs: (1) what specifically happened and who did it, (2) technical details and numbers from the evidence, (3) second-order effects and who is affected>",
  "evidence": ["<url1>", "<url2>", ...],
  "historical_context": "<concrete comparison: name a prior model/event/year and how this differs>",
  "confidence_level": "<high|medium|low>",
  "direction": "<accelerating|stable|emerging|declining>"
}

Return ONLY valid JSON. No markdown, no explanation."""


def _get_latest_themes(session: Session) -> tuple[str, list[dict[str, Any]]]:
    """Get all themes from the most recent batch using a two-step SQL query."""
    # Step 1: find the batch_id of the most recently created theme
    latest_batch_id: str | None = session.execute(
        select(ThemeTable.batch_id).order_by(ThemeTable.created_at.desc()).limit(1)
    ).scalar_one_or_none()

    if not latest_batch_id:
        return "", []

    # Step 2: fetch ALL themes for that batch_id (no Python-side break needed)
    rows = session.execute(
        select(ThemeTable.theme_json).where(ThemeTable.batch_id == latest_batch_id)
    ).all()

    themes = []
    for r in rows:
        data = r.theme_json if isinstance(r.theme_json, dict) else json.loads(r.theme_json)
        themes.append(data)

    return latest_batch_id, themes


def _get_article_details(
    session: Session, article_ids: list[uuid.UUID]
) -> dict[str, dict[str, Any]]:
    """Return a mapping of article_id → {url, title, published_at} for the given IDs."""
    if not article_ids:
        return {}
    stmt = select(ArticleTable.id, ArticleTable.url, ArticleTable.title, ArticleTable.published_at).where(
        ArticleTable.id.in_(article_ids)
    )
    rows = session.execute(stmt).all()
    result: dict[str, dict[str, Any]] = {}
    for r in rows:
        pub = r.published_at.date().isoformat() if r.published_at else "unknown date"
        result[str(r.id)] = {"url": r.url, "title": r.title, "published_at": pub}
    return result


def _get_article_urls(session: Session, article_ids: list[uuid.UUID]) -> dict[str, str]:
    """Thin wrapper kept for backward compatibility with agent_loop.py."""
    details = _get_article_details(session, article_ids)
    return {aid: d["url"] for aid, d in details.items()}


def _build_user_prompt(
    theme: dict[str, Any],
    article_details: dict[str, dict[str, Any]],
    historical: list[dict[str, Any]],
    article_ids: list[uuid.UUID],
) -> str:
    parts = [f"Theme: {theme.get('theme_name', 'unknown')}"]
    parts.append(f"Description: {theme.get('description', '')}")
    parts.append("Current articles:")
    for aid in article_ids:
        detail = article_details.get(str(aid))
        if detail:
            title = detail.get("title", "Untitled")
            pub = detail.get("published_at", "unknown date")
            url = detail.get("url", f"article #{aid}")
            parts.append(f"  - {title} (published: {pub}) — {url}")
        else:
            parts.append(f"  - article #{aid}")
    if historical:
        parts.append("\nHistorically similar articles from our database:")
        for h in historical:
            parts.append(f"  - {h.get('title', '')} ({h.get('url', '')}), similarity={h.get('score', 0):.2f}")
    else:
        parts.append("\nNo historical articles found for context.")
    return "\n".join(parts)


def _persist_insight(session: Session, batch_id: str, insight_json: dict) -> None:
    row = InsightTable(batch_id=batch_id, insight_json=insight_json)
    session.add(row)
    session.flush()


def run() -> None:
    """Synthesize insights for each theme in the latest batch."""
    from app.db.connection import get_session
    from app.embeddings.vector_store import search_by_text

    with get_session() as session:
        batch_id, themes = _get_latest_themes(session)
        if not themes:
            print("No themes to synthesize.")
            return
        logger.info("Synthesizing insights for %d themes (batch %s) …", len(themes), batch_id)
        for theme in themes:
            article_ids = _parse_valid_article_ids(theme.get("article_ids", []))
            article_details = _get_article_details(session, article_ids)
            theme_name = theme.get("theme_name", "")
            try:
                historical = search_by_text(session, theme_name, top_k=5)
            except Exception as e:
                logger.warning("RAG search failed for theme '%s': %s", theme_name, e)
                historical = []
            prompt = _build_user_prompt(theme, article_details, historical, article_ids)
            try:
                insight = call_llm_json(SYSTEM_PROMPT, prompt)
                _persist_insight(session, batch_id, insight)
                logger.info("  Insight: %s (%s)", insight.get("trend_name", "?"), insight.get("direction", "?"))
            except Exception as e:
                logger.error("  Failed to synthesize theme '%s': %s", theme_name, e)
    print(f"Synthesized {len(themes)} insights for batch {batch_id}.")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run()

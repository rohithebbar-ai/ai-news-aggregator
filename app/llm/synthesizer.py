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


SYSTEM_PROMPT = """You are an AI trend analyst. Given a theme with its current articles and historically similar articles retrieved from our database, produce an insight analysis.

Return a JSON object with exactly these fields:
{
  "trend_name": "<concise trend name>",
  "analysis": "<2-3 paragraph analysis of this trend>",
  "evidence": ["<url1>", "<url2>", ...],
  "historical_context": "<how this trend compares to what we've seen before>",
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


def _get_article_urls(session: Session, article_ids: list[uuid.UUID]) -> dict[str, str]:
    if not article_ids:
        return {}
    stmt = select(ArticleTable.id, ArticleTable.url).where(ArticleTable.id.in_(article_ids))
    rows = session.execute(stmt).all()
    return {str(r.id): r.url for r in rows}


def _build_user_prompt(
    theme: dict[str, Any],
    article_urls: dict[str, str],
    historical: list[dict[str, Any]],
    article_ids: list[uuid.UUID],
) -> str:
    parts = [f"Theme: {theme.get('theme_name', 'unknown')}"]
    parts.append(f"Description: {theme.get('description', '')}")
    parts.append("Current articles:")
    for aid in article_ids:
        url = article_urls.get(str(aid), f"article #{aid}")
        parts.append(f"  - {url}")
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
            article_urls = _get_article_urls(session, article_ids)
            theme_name = theme.get("theme_name", "")
            try:
                historical = search_by_text(session, theme_name, top_k=5)
            except Exception as e:
                logger.warning("RAG search failed for theme '%s': %s", theme_name, e)
                historical = []
            prompt = _build_user_prompt(theme, article_urls, historical, article_ids)
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

"""
Stage 2: Theme grouping across article summaries.
Takes summaries from Stage 1, groups them into themes, and persists the result.

Usage: uv run python -m app.llm.theme_grouper
"""


import json
import logging
import uuid
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.db.schema import ArticleSummaryTable, ArticleTable, ThemeTable
from app.llm.groq_client import call_llm_json

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are an AI research analyst. Given a list of article summaries (each with an article_id), group them into coherent themes.

Return a JSON object with a single key "themes" containing an array. Each theme object has:
{
  "theme_name": "<short descriptive name>",
  "description": "<1-2 sentence description of what unites these articles>",
  "article_ids": ["<article_id_string>", ...],
  "cross_source_signal": <true if articles come from multiple source types (rss, youtube, etc), false otherwise>
}

Return ONLY valid JSON. No markdown, no explanation."""


def _get_recent_summaries(session: Session) -> list[dict[str, Any]]:
    """Fetch the most recent batch of summaries (last 48 hours)."""
    stmt = (
        select(
            ArticleSummaryTable.article_id,
            ArticleSummaryTable.summary_json,
            ArticleTable.source_type,
        )
        .join(ArticleTable, ArticleTable.id == ArticleSummaryTable.article_id)
        .where(ArticleSummaryTable.created_at > func.now() - text("INTERVAL '48 hours'"))
        .order_by(ArticleSummaryTable.article_id)
    )
    rows = session.execute(stmt).all()
    return [
        {
            "article_id": str(r.article_id),
            "summary_json": r.summary_json,
            "source_type": r.source_type,
        }
        for r in rows
    ]


def _build_user_prompt(summaries: list[dict[str, Any]]) -> str:
    lines = []
    for s in summaries:
        sj = s["summary_json"] if isinstance(s["summary_json"], dict) else json.loads(s["summary_json"])
        lines.append(
            f"article_id={s['article_id']} source={s['source_type']}: "
            f"{sj.get('one_sentence_summary', sj.get('title', ''))}"
        )
    return "Article summaries:\n" + "\n".join(lines)


def _persist_themes(session: Session, batch_id: str, themes: list[dict]) -> None:
    for theme in themes:
        row = ThemeTable(batch_id=batch_id, theme_json=theme)
        session.add(row)
    session.flush()


def run() -> None:
    """Group recent summaries into themes and persist."""
    from app.db.connection import get_session
    with get_session() as session:
        summaries = _get_recent_summaries(session)
        if not summaries:
            print("No recent summaries to group.")
            return
        logger.info("Grouping %d summaries into themes …", len(summaries))
        prompt = _build_user_prompt(summaries)
        result = call_llm_json(SYSTEM_PROMPT, prompt)
        themes = result.get("themes", [])
        batch_id = uuid.uuid4().hex[:16]
        _persist_themes(session, batch_id, themes)
    print(f"Grouped into {len(themes)} themes (batch {batch_id}).")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run()

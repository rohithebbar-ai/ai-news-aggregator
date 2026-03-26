"""
Stage 1: Structured article summarization.
For each new article, call Groq to produce a structured JSON summary and persist it.

Usage: uv run python -m app.llm.summarizer
"""

import logging
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.db.schema import ArticleSummaryTable, ArticleTable
from app.llm.groq_client import call_llm_json

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are an AI research analyst. Given an article's title and content, produce a structured JSON summary with exactly these fields:
{
  "title": "<original title>",
  "one_sentence_summary": "<concise 1-sentence summary>",
  "key_points": ["<point 1>", "<point 2>", ...],
  "technical_depth": <1-5 integer, 1=general audience, 5=deep technical>,
  "relevance_tags": ["<tag1>", "<tag2>", ...]
}
Return ONLY valid JSON. No markdown, no explanation."""


def summarize_article(title: str, content: str) -> dict[str, Any]:
    """Summarize a single article via Groq. Returns the parsed JSON dict."""
    user_prompt = f"Title: {title}\n\nContent:\n{content[:6000]}"
    return call_llm_json(SYSTEM_PROMPT, user_prompt)


def _get_unsummarized_articles(session: Session) -> list[dict[str, Any]]:
    """Articles that don't yet have a row in article_summaries."""
    stmt = (
        select(
            ArticleTable.id,
            ArticleTable.title,
            ArticleTable.summary,
            ArticleTable.raw_content,
        )
        .outerjoin(
            ArticleSummaryTable,
            ArticleSummaryTable.article_id == ArticleTable.id,
        )
        .where(ArticleSummaryTable.id.is_(None))
        .order_by(ArticleTable.id)
    )
    rows = session.execute(stmt).all()
    return [
        {
            "id": r.id,
            "title": r.title,
            "summary": r.summary,
            "raw_content": r.raw_content,
        }
        for r in rows
    ]


def _persist_summary(session: Session, article_id: uuid.UUID, summary_json: dict) -> None:
    stmt = (
        insert(ArticleSummaryTable)
        .values(article_id=article_id, summary_json=summary_json)
        .on_conflict_do_nothing(index_elements=["article_id"])
    )
    session.execute(stmt)


def run() -> None:
    """Summarize all unsummarized articles and persist results."""
    from app.db.connection import get_session

    with get_session() as session:
        rows = _get_unsummarized_articles(session)
        if not rows:
            print("No unsummarized articles.")
            return
        logger.info("Summarizing %d articles …", len(rows))
        for row in rows:
            body = (row["raw_content"] or "").strip()
            if not body:
                body = (row["summary"] or row["title"] or "")
            try:
                result = summarize_article(row["title"], body)
                _persist_summary(session, row["id"], result)
                logger.info("  Summarized: %s", row["title"][:60])
            except Exception as e:
                logger.error("  Failed to summarize article %s: %s", row["id"], e)
    print(f"Summarized {len(rows)} articles.")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run()

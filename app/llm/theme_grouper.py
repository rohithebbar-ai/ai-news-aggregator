"""
Stage 2: Theme grouping across article summaries.
Takes summaries from Stage 1, groups them into themes, and persists the result.

Usage: uv run python -m app.llm.theme_grouper
"""


import json
import logging
import uuid
from typing import Any

from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.schema import ArticleSummaryTable, ArticleTable, ThemeTable
from app.llm.groq_client import call_llm_json

logger = logging.getLogger(__name__)

CHUNK_SIZE = 50

SYSTEM_PROMPT = """You are an AI research analyst. Given a list of article summaries (each with an article_id), group them into coherent themes.

Return a JSON object with a single key "themes" containing an array. Each theme object has:
{
  "theme_name": "<short descriptive name>",
  "description": "<1-2 sentence description of what unites these articles>",
  "article_ids": ["<article_id_string>", ...],
  "cross_source_signal": <true if articles come from multiple source types (rss, youtube, etc), false otherwise>
}

Return ONLY valid JSON. No markdown, no explanation."""

MERGE_SYSTEM_PROMPT = """You are an AI research analyst. You have received multiple sets of themes, each grouped from a subset of articles. Merge these intermediate themes into a final consolidated set by:
- Combining themes that are clearly about the same topic
- Keeping themes that represent distinct topics
- Preserving all article_ids across merged themes (union of article_ids)
- Setting cross_source_signal to true if any merged theme had it as true

Return a JSON object with a single key "themes" containing an array. Each theme object has:
{
  "theme_name": "<short descriptive name>",
  "description": "<1-2 sentence description of what unites these articles>",
  "article_ids": ["<article_id_string>", ...],
  "cross_source_signal": <true or false>
}

Return ONLY valid JSON. No markdown, no explanation."""


def _parse_summary_json(raw: Any) -> dict:
    """Consistently parse summary_json regardless of whether it arrives as a dict or string."""
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("Failed to parse summary_json string: %r", raw[:200])
            return {}
    logger.warning("Unexpected summary_json type %s, returning empty dict", type(raw))
    return {}


def _get_recent_summaries(session: Session) -> list[dict[str, Any]]:
    """Fetch the most recent batch of summaries (last 48 hours)."""
    stmt = (
        select(
            ArticleSummaryTable.article_id,
            ArticleSummaryTable.summary_json,
            ArticleTable.source_type,
        )
        .join(ArticleTable, ArticleTable.id == ArticleSummaryTable.article_id)
        .where(ArticleSummaryTable.created_at > func.now() - timedelta(hours=48))
        .order_by(ArticleSummaryTable.article_id)
    )
    rows = session.execute(stmt).all()
    return [
        {
            "article_id": str(r.article_id),
            "summary_json": _parse_summary_json(r.summary_json),
            "source_type": r.source_type,
        }
        for r in rows
    ]


def _build_user_prompt(summaries: list[dict[str, Any]]) -> str:
    lines = []
    for s in summaries:
        sj = s["summary_json"]  # already a dict, normalised in _get_recent_summaries
        lines.append(
            f"article_id={s['article_id']} source={s['source_type']}: "
            f"{sj.get('one_sentence_summary', sj.get('title', ''))}"
        )
    return "Article summaries:\n" + "\n".join(lines)


def _chunk_summaries(summaries: list[dict], chunk_size: int = CHUNK_SIZE) -> list[list[dict]]:
    """Split summaries list into chunks of at most chunk_size."""
    return [summaries[i : i + chunk_size] for i in range(0, len(summaries), chunk_size)]


def _merge_themes(intermediate_themes: list[dict]) -> list[dict]:
    """Merge intermediate theme lists from multiple chunks into a single consolidated list via LLM."""
    lines = []
    for i, theme in enumerate(intermediate_themes):
        article_ids_str = ", ".join(str(a) for a in theme.get("article_ids", []))
        lines.append(
            f"Theme {i + 1}: {theme.get('theme_name', 'unknown')} — "
            f"{theme.get('description', '')} "
            f"(article_ids: [{article_ids_str}], "
            f"cross_source: {theme.get('cross_source_signal', False)})"
        )
    user_prompt = "Intermediate themes to merge:\n" + "\n".join(lines)
    result = call_llm_json(MERGE_SYSTEM_PROMPT, user_prompt)
    themes = result.get("themes", [])
    if not isinstance(themes, list):
        logger.error("Merge LLM returned unexpected format: %r", result)
        return intermediate_themes  # fall back to unmerged list
    return themes


def _persist_themes(session: Session, batch_id: str, themes: list[dict]) -> None:
    for theme in themes:
        row = ThemeTable(batch_id=batch_id, theme_json=theme)
        session.add(row)
    session.flush()


def run() -> None:
    """Group recent summaries into themes and persist, using chunk+merge to respect LLM context limits."""
    from app.db.connection import get_session
    with get_session() as session:
        summaries = _get_recent_summaries(session)
        if not summaries:
            print("No recent summaries to group.")
            return

        logger.info("Grouping %d summaries into themes (chunk_size=%d) …", len(summaries), CHUNK_SIZE)
        chunks = _chunk_summaries(summaries)
        logger.info("Split into %d chunk(s)", len(chunks))

        all_intermediate_themes: list[dict] = []
        for idx, chunk in enumerate(chunks, 1):
            logger.info("  Processing chunk %d/%d (%d summaries) …", idx, len(chunks), len(chunk))
            prompt = _build_user_prompt(chunk)
            try:
                result = call_llm_json(SYSTEM_PROMPT, prompt)
            except Exception:
                logger.exception("LLM call failed for chunk %d — skipping chunk.", idx)
                continue
            chunk_themes = result.get("themes")
            if not isinstance(chunk_themes, list) or len(chunk_themes) == 0:
                logger.error("Chunk %d returned unexpected or empty themes: %r", idx, result)
                continue
            all_intermediate_themes.extend(chunk_themes)
            logger.info("  Chunk %d produced %d intermediate theme(s)", idx, len(chunk_themes))

        if not all_intermediate_themes:
            logger.error("No themes produced from any chunk — aborting persist.")
            return

        # Merge pass: only run if more than one chunk was processed
        if len(chunks) > 1:
            logger.info("Running merge pass over %d intermediate themes …", len(all_intermediate_themes))
            try:
                themes = _merge_themes(all_intermediate_themes)
            except Exception:
                logger.exception("Merge LLM call failed — falling back to unmerged intermediate themes.")
                themes = all_intermediate_themes
        else:
            themes = all_intermediate_themes

        batch_id = uuid.uuid4().hex[:16]
        _persist_themes(session, batch_id, themes)

    print(f"Grouped into {len(themes)} themes (batch {batch_id}).")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run()
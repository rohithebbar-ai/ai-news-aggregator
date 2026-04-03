"""
Data access layer for articles (SQLAlchemy).
Handles insert and duplicate-URL checks against the Neon articles table.
"""

from __future__ import annotations

import logging
from typing import Any, cast

from sqlalchemy import select
from sqlalchemy.engine import CursorResult
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.db.models import Article
from app.db.schema import ArticleTable

logger = logging.getLogger(__name__)

INSERT_BATCH_SIZE = 100


def _article_row_values(a: Article) -> dict:
    return {
        "url": a.url,
        "title": a.title,
        "summary": a.summary,
        "raw_content": a.raw_content,
        "published_at": a.published_at,
        "image": a.image,
        "images": [img.model_dump() for img in a.images] if a.images else None,
        "source_type": a.source_type,
        "source_url": a.source_url,
    }


class ArticleRepository:
    """Repository for article CRUD and duplicate checks. Requires a SQLAlchemy Session."""

    def __init__(self, session: Session):
        self._session = session

    def get_existing_urls(self, urls: list[str]) -> set[str]:
        """Return the set of URLs that already exist in the articles table."""
        if not urls:
            return set()
        stmt = select(ArticleTable.url).where(ArticleTable.url.in_(urls))
        rows = self._session.execute(stmt).all()
        return {r.url for r in rows}

    def insert_articles(self, articles: list[Article]) -> int:
        """
        Bulk-insert articles in batches. Skips rows that would violate UNIQUE(url).
        Returns the number of rows inserted.
        """
        if not articles:
            return 0
        inserted = 0
        for start in range(0, len(articles), INSERT_BATCH_SIZE):
            batch = articles[start : start + INSERT_BATCH_SIZE]
            try:
                with self._session.begin_nested():
                    stmt = insert(ArticleTable).on_conflict_do_nothing(index_elements=["url"])
                    result = self._session.execute(stmt, [_article_row_values(a) for a in batch])
                    inserted += cast(CursorResult[Any], result).rowcount or 0
            except Exception as e:
                logger.warning(
                    "Batch insert failed (%d rows), falling back to per-row: %s",
                    len(batch),
                    e,
                )
                for a in batch:
                    try:
                        with self._session.begin_nested():
                            stmt = (
                                insert(ArticleTable)
                                .values(_article_row_values(a))
                                .on_conflict_do_nothing(index_elements=["url"])
                            )
                            r = self._session.execute(stmt)
                            inserted += cast(CursorResult[Any], r).rowcount or 0
                    except Exception as row_e:
                        logger.warning("Insert failed for url=%s: %s", a.url, row_e)
        return inserted

"""
Data access layer for articles (SQLAlchemy).
Handles insert and duplicate-URL checks against the Neon articles table.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.db.models import Article
from app.db.schema import ArticleTable

logger = logging.getLogger(__name__)


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
        Bulk-insert articles. Skips rows that would violate UNIQUE(url).
        Returns the number of rows inserted.
        """
        if not articles:
            return 0
        inserted = 0
        for a in articles:
            try:
                stmt = (
                    insert(ArticleTable)
                    .values(
                        url=a.url,
                        title=a.title,
                        summary=a.summary,
                        raw_content=a.raw_content,
                        published_at=a.published_at,
                        image=a.image,
                        images=[img.model_dump() for img in a.images] if a.images else None,
                        source_type=a.source_type,
                        source_url=a.source_url,
                    )
                    .on_conflict_do_nothing(index_elements=["url"])
                )
                result = self._session.execute(stmt)
                inserted += result.rowcount
            except Exception as e:
                logger.warning("Insert failed for url=%s: %s", a.url, e)
        self._session.flush()
        return inserted

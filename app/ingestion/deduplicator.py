"""
Deduplication: filter out articles whose URL already exists in the database.
Uses the repository to check the url column (UNIQUE) before insert.
"""

from __future__ import annotations

from app.db.models import Article
from app.db.repository import ArticleRepository


def deduplicate(
    articles: list[Article],
    repository: ArticleRepository,
) -> list[Article]:
    """Return only articles whose url is not already in the database."""
    if not articles:
        return []
    urls = [a.url for a in articles]
    existing = repository.get_existing_urls(urls)
    return [a for a in articles if a.url not in existing]

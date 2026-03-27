"""
Run full ingestion: RSS + YouTube, deduplicate, insert into Neon.
Usage: uv run python -m app.ingestion.run
"""

from __future__ import annotations

import logging

from app.db.connection import get_session
from app.db.repository import ArticleRepository
from app.ingestion.deduplicator import deduplicate
from app.ingestion.rss_scraper import RSSScraper
from app.ingestion.youtube_scraper import YouTubeScraper

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def run() -> None:
    rss = RSSScraper()
    yt = YouTubeScraper()
    rss_articles = rss.scrape()
    yt_articles = yt.scrape()
    all_articles = rss_articles + yt_articles
    logger.info("RSS: %d, YouTube: %d, total: %d", len(rss_articles), len(yt_articles), len(all_articles))
    if not all_articles:
        print("No articles in lookback window.")
        return
    with get_session() as session:
        repo = ArticleRepository(session)
        new_articles = deduplicate(all_articles, repo)
        inserted = repo.insert_articles(new_articles)
    print(f"Ingestion complete: {len(all_articles)} fetched, {len(new_articles)} new, {inserted} inserted.")


if __name__ == "__main__":
    run()

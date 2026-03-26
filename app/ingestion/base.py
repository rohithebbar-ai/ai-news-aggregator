"""
Base scraper interface for all content sources.
Every scraper (RSS, YouTube, Hacker News, etc.) inherits from BaseScraper
and returns validated Article Pydantic models.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from app.db.models import Article


class BaseScraper(ABC):
    """Interface that all scrapers must implement. New sources extend this class."""

    @abstractmethod
    def scrape(self) -> list[Article]:
        """
        Fetch content from the source and return a list of validated Article models.
        Callers are responsible for filtering by date and deduplication.
        """
        ...

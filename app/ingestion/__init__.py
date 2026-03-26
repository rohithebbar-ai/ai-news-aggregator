from app.ingestion.base import BaseScraper
from app.ingestion.deduplicator import deduplicate
from app.ingestion.rss_scraper import RSSScraper
from app.ingestion.youtube_scraper import YouTubeScraper

__all__ = ["BaseScraper", "deduplicate", "RSSScraper", "YouTubeScraper"]

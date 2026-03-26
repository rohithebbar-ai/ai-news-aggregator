"""
RSS feed scraper. Fetches AI-related blog feeds, filters by recency, and returns Article models.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from html import unescape
from typing import Any

import feedparser  # type: ignore[import-untyped]
from bs4 import BeautifulSoup  

from app.config import HTTP_USER_AGENT, INGESTION_LOOKBACK_HOURS, RSS_FEEDS
from app.db.models import Article, ArticleImage
from app.ingestion.base import BaseScraper

logger = logging.getLogger(__name__)


def _parse_feed_date(entry: Any) -> datetime | None:
    """Parse published/updated date from feed entry to timezone-aware datetime."""
    for key in ("published_parsed", "updated_parsed", "created_parsed"):
        parsed = getattr(entry, key, None)
        if parsed is not None:
            try:
                # time.struct_time -> datetime
                return datetime(*parsed[:6], tzinfo=timezone.utc)
            except (TypeError, ValueError):
                pass
    return None


def _extract_images_from_html(html: str) -> list[ArticleImage]:
    """Extract img src and alt from HTML summary/content."""
    if not html:
        return []
    images: list[ArticleImage] = []
    try:
        soup = BeautifulSoup(html, "html.parser")
        for img in soup.find_all("img"):
            src = (img.get("src") or "").strip()
            if not src:
                continue
            alt = (img.get("alt") or "").strip()
            images.append(ArticleImage(src=src, alt=alt))
    except Exception:
        pass
    return images


def _strip_html(html: str) -> str:
    """Convert HTML to plain text; optionally tables to markdown later."""
    if not html:
        return ""
    try:
        soup = BeautifulSoup(html, "html.parser")
        return soup.get_text(separator=" ", strip=True)
    except Exception:
        return re.sub(r"<[^>]+>", "", unescape(html)).strip()


def _get_main_image(entry: Any) -> str | None:
    """Get main image URL from entry (media_content, enclosure, or first img in summary)."""
    # media_content (e.g. Media RSS)
    media = getattr(entry, "media_content", None) or getattr(entry, "media_content_medium", None)
    if media and len(media) > 0:
        url = media[0].get("url") if isinstance(media[0], dict) else getattr(media[0], "url", None)
        if url:
            return url
    # enclosure
    enclosures = getattr(entry, "enclosures", None) or []
    for enc in enclosures:
        href = enc.get("href") if isinstance(enc, dict) else getattr(enc, "href", None)
        if href and (enc.get("type") or "").startswith("image/"):
            return href
    # first image in summary
    summary = getattr(entry, "summary", None) or getattr(entry, "description", None) or ""
    if summary:
        imgs = _extract_images_from_html(summary)
        if imgs:
            return imgs[0].src
    return None


class RSSScraper(BaseScraper):
    """Scrapes configured RSS feeds and returns recent articles as Article models."""

    def __init__(
        self,
        feed_urls: list[str] | None = None,
        lookback_hours: int | None = None,
        user_agent: str | None = None,
    ):
        self.feed_urls = feed_urls or RSS_FEEDS
        self.lookback_hours = lookback_hours if lookback_hours is not None else INGESTION_LOOKBACK_HOURS
        self.user_agent = user_agent or HTTP_USER_AGENT

    def scrape(self) -> list[Article]:
        cutoff = datetime.now(timezone.utc)
        try:
            from datetime import timedelta
            cutoff = cutoff - timedelta(hours=self.lookback_hours)
        except Exception:
            pass

        articles: list[Article] = []
        for feed_url in self.feed_urls:
            try:
                parsed = feedparser.parse(
                    feed_url,
                    request_headers={"User-Agent": self.user_agent},
                )
            except Exception as e:
                logger.warning("Failed to fetch feed %s: %s", feed_url, e)
                continue

            for entry in getattr(parsed, "entries", []):
                link = (getattr(entry, "link", None) or "").strip()
                if not link:
                    continue
                published = _parse_feed_date(entry)
                if published is not None and published < cutoff:
                    continue
                title = (getattr(entry, "title", None) or "").strip() or "(No title)"
                summary_raw = getattr(entry, "summary", None) or getattr(entry, "description", None) or ""
                summary_text = _strip_html(summary_raw)
                raw_content = summary_text  # RSS often only has summary; full body would require fetch
                image = _get_main_image(entry)
                images = _extract_images_from_html(summary_raw) if summary_raw else []

                try:
                    articles.append(
                        Article(
                            title=title,
                            url=link,
                            summary=summary_text[:2000] if summary_text else None,
                            raw_content=raw_content[:100_000] if raw_content else "",
                            published_at=published,
                            image=image,
                            images=images,
                            source_type="rss",
                        )
                    )
                except Exception as e:
                    logger.debug("Skip entry %s: %s", link, e)
        return articles


def main() -> None:
    """Run RSS scraper, deduplicate, insert into Neon, and log count."""
    logging.basicConfig(level=logging.INFO)
    scraper = RSSScraper()
    articles = scraper.scrape()
    if not articles:
        print("RSS scraper: no articles in lookback window.")
        return
    from app.db.connection import get_session
    from app.db.repository import ArticleRepository
    from app.ingestion.deduplicator import deduplicate
    with get_session() as session:
        repo = ArticleRepository(session)
        new_articles = deduplicate(articles, repo)
        inserted = repo.insert_articles(new_articles)
    print(f"RSS: fetched {len(articles)}, new {len(new_articles)}, inserted {inserted}.")


if __name__ == "__main__":
    main()

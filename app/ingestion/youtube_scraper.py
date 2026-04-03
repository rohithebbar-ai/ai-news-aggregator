"""
YouTube channel scraper. Fetches recent videos via channel RSS, extracts transcripts,
and returns Article models (transcript as raw_content).
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import feedparser  # type: ignore[import-untyped]

from app.config import HTTP_USER_AGENT, INGESTION_LOOKBACK_HOURS, YOUTUBE_CHANNEL_IDS
from app.db.models import Article
from app.ingestion.base import BaseScraper

logger = logging.getLogger(__name__)

# Channel uploads RSS (no API key): https://www.youtube.com/feeds/videos.xml?channel_id=ID
YOUTUBE_CHANNEL_FEED_URL = "https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"


def _parse_yt_feed_date(entry: Any) -> datetime | None:
    """Parse published_parsed from YouTube feed entry."""
    parsed = getattr(entry, "published_parsed", None)
    if parsed is None:
        return None
    try:
        return datetime(*parsed[:6], tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def _video_id_from_link(link: str) -> str | None:
    """Extract video ID from youtube watch URL."""
    if not link:
        return None
    # ...?v=VIDEO_ID or .../watch?v=VIDEO_ID
    if "v=" in link:
        return link.split("v=")[-1].split("&")[0].strip()
    return None


def _fetch_transcript(video_id: str) -> str:
    """Fetch transcript for a video; returns concatenated text or empty string."""
    try:
        from youtube_transcript_api import YouTubeTranscriptApi  # type: ignore[import-untyped]
        api = YouTubeTranscriptApi()
        transcript = api.fetch(video_id)
        if not transcript:
            return ""
        return " ".join((s.text or "").strip() for s in transcript).strip()
    except Exception as e:
        logger.debug("No transcript for video %s: %s", video_id, e)
        return ""


class YouTubeScraper(BaseScraper):
    """
    Scrapes configured YouTube channels via RSS, fetches transcripts,
    and returns one Article per video (transcript = raw_content).
    """

    def __init__(
        self,
        channel_ids: list[str] | None = None,
        lookback_hours: int | None = None,
        user_agent: str | None = None,
    ):
        self.channel_ids = channel_ids or YOUTUBE_CHANNEL_IDS
        self.lookback_hours = lookback_hours if lookback_hours is not None else INGESTION_LOOKBACK_HOURS
        self.user_agent = user_agent or HTTP_USER_AGENT

    def scrape(self) -> list[Article]:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=self.lookback_hours)

        articles: list[Article] = []
        for channel_id in self.channel_ids:
            feed_url = YOUTUBE_CHANNEL_FEED_URL.format(channel_id=channel_id)
            try:
                parsed = feedparser.parse(
                    feed_url,
                    request_headers={"User-Agent": self.user_agent},
                )
            except Exception as e:
                logger.warning("Failed to fetch YouTube feed %s: %s", feed_url, e)
                continue

            for entry in getattr(parsed, "entries", []):
                link = (getattr(entry, "link", None) or "").strip()
                video_id = _video_id_from_link(link)
                if not video_id:
                    continue
                published = _parse_yt_feed_date(entry)
                if published is not None and published < cutoff:
                    continue
                title = (getattr(entry, "title", None) or "").strip() or "(No title)"
                # Optional: media:description in some feeds
                summary = (getattr(entry, "summary", None) or "").strip()
                if summary:
                    from bs4 import BeautifulSoup
                    try:
                        summary = BeautifulSoup(summary, "html.parser").get_text(separator=" ", strip=True)
                    except Exception:
                        pass
                raw_content = _fetch_transcript(video_id)
                # Thumbnail: media:thumbnail or standard pattern
                image = None
                thumb = getattr(entry, "media_thumbnail", None)
                if thumb and len(thumb) > 0:
                    url = thumb[0].get("url") if isinstance(thumb[0], dict) else getattr(thumb[0], "url", None)
                    if url:
                        image = url
                if not image:
                    image = f"https://img.youtube.com/vi/{video_id}/maxresdefault.jpg"

                try:
                    articles.append(
                        Article(
                            title=title,
                            url=f"https://www.youtube.com/watch?v={video_id}",
                            summary=summary[:2000] if summary else None,
                            raw_content=raw_content[:100_000] if raw_content else "",
                            published_at=published,
                            image=image,
                            images=[],
                            source_type="youtube",
                        )
                    )
                except Exception as e:
                    logger.debug("Skip video %s: %s", video_id, e)
        return articles


def main() -> None:
    """Run YouTube scraper, deduplicate, insert into Neon, and log count."""
    logging.basicConfig(level=logging.INFO)
    scraper = YouTubeScraper()
    articles = scraper.scrape()
    if not articles:
        print("YouTube scraper: no videos in lookback window.")
        return
    from app.db.connection import get_session
    from app.db.repository import ArticleRepository
    from app.ingestion.deduplicator import deduplicate
    with get_session() as session:
        repo = ArticleRepository(session)
        new_articles = deduplicate(articles, repo)
        inserted = repo.insert_articles(new_articles)
    print(f"YouTube: fetched {len(articles)}, new {len(new_articles)}, inserted {inserted}.")


if __name__ == "__main__":
    main()

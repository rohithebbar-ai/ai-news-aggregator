"""
Configuration for the AI Trend Intelligence Engine.
Define RSS feed URLs and YouTube channel IDs to scrape.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# RSS Feeds — AI-focused blogs and research outlets
# ---------------------------------------------------------------------------
RSS_FEEDS: list[str] = [
    "https://www.anthropic.com/news/rss.xml",
    "https://openai.com/blog/rss.xml",
    "https://huggingface.co/blog/rss.xml",
    "https://blog.google/technology/ai/rss/",
    "https://www.mit.edu/news/topic/artificial-intelligence/feed",
    "https://ai.meta.com/blog/feed/",
    "https://deepmind.google/blog/rss.xml",
    "https://aws.amazon.com/blogs/machine-learning/feed/",
    "https://blog.research.google/rss.xml",
    "https://venturebeat.com/category/ai/feed/",
]

# ---------------------------------------------------------------------------
# YouTube Channels — AI-focused creators (channel IDs)
# ---------------------------------------------------------------------------
YOUTUBE_CHANNEL_IDS: list[str] = [
    "UCZHmQk67mN31JjD7LT0SC4Q",   # Yannic Kilcher
    "UCbfYPyITQ-7l4upoX8nvctg",   # Two Minute Papers
    "UCXUPKJO5M3RLYLVb2LsAeOA",   # AI Explained
    "UCXZCJLdBC09xxGZ6gcdrc6A",   # StatQuest (stats/ML)
    "UCvzxXb-YL9pFSHQgL2Pm1Yw",   # What's AI (Louis Bouchard)
    "UCsBjURrPoezykLs9EqgamOA",   # Fireship (often covers AI tools)
]

# ---------------------------------------------------------------------------
# Ingestion settings
# ---------------------------------------------------------------------------
# Only ingest articles/videos from the last N hours
INGESTION_LOOKBACK_HOURS: int = 48

# User-Agent for HTTP requests (some feeds block default clients)
HTTP_USER_AGENT: str = (
    "Mozilla/5.0 (compatible; AITrendEngine/1.0; +https://github.com/ai-trend-engine)"
)

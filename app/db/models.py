"""
Pydantic models for article data validation.
Used by scrapers and the repository layer.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class ArticleImage(BaseModel):
    """A single image extracted from source content (for display with attribution)."""

    src: str = Field(..., description="Image URL")
    alt: str = Field(default="", description="Alt text from source or empty")


class Article(BaseModel):
    """
    Validated article/video item from any source (RSS, YouTube, etc.).
    All scrapers produce this shape for deduplication and storage.
    """

    title: str = Field(..., min_length=1)
    url: str = Field(..., min_length=1)
    summary: str | None = Field(default=None, description="Short summary or description")
    raw_content: str = Field(default="", description="Full text body or transcript")
    published_at: datetime | None = Field(default=None)
    image: str | None = Field(default=None, description="Main thumbnail / og:image URL")
    images: list[ArticleImage] = Field(
        default_factory=list,
        description="Embedded images from article (src + alt) for display with attribution",
    )
    source_type: Literal["rss", "youtube", "hackernews"] = Field(
        ..., description="Origin of the content"
    )
    # Optional: for Hacker News, store discussion URL separately; main url = content link
    source_url: str | None = Field(default=None, description="e.g. HN discussion URL")

    model_config = {"str_strip_whitespace": True}

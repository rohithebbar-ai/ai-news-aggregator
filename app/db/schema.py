"""
SQLAlchemy schema for the AI Trend Intelligence Engine.
Defines tables in Python so you can create/alter the DB without a separate SQL file.
Run: uv run python -m app.db.schema
"""

from __future__ import annotations

import os
from datetime import datetime

from dotenv import load_dotenv
import uuid as _uuid

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from pgvector.sqlalchemy import Vector  # type: ignore[import-untyped]

load_dotenv()


class Base(DeclarativeBase):
    """Declarative base for all models."""


class ArticleTable(Base):
    """
    Articles table: raw ingested content from RSS, YouTube, Hacker News, etc.
    Matches the shape expected by app.db.repository and app.db.models.Article.
    """

    __tablename__ = "articles"
    __table_args__ = (
        Index("idx_articles_source_type", "source_type"),
        Index("idx_articles_published_at", "published_at", postgresql_ops={"published_at": "DESC"}),
        Index("idx_articles_created_at", "created_at", postgresql_ops={"created_at": "DESC"}),
    )

    id: Mapped[_uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid.uuid4)
    url: Mapped[str] = mapped_column(Text, unique=True, nullable=False, index=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    image: Mapped[str | None] = mapped_column(Text, nullable=True)
    images: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    source_type: Mapped[str] = mapped_column(Text, nullable=False)
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("NOW()"))


# ---------------------------------------------------------------------------
# Day 4: Embedding table for pgvector similarity search
# ---------------------------------------------------------------------------

class ArticleEmbeddingTable(Base):
    __tablename__ = "article_embeddings"
    __table_args__ = (
        Index(
            "idx_article_embeddings_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_with={"m": 16, "ef_construction": 64},
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    article_id: Mapped[_uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("articles.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    embedding = mapped_column(Vector(384), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("NOW()"))


# ---------------------------------------------------------------------------
# Day 5: LLM pipeline output tables
# ---------------------------------------------------------------------------

class ArticleSummaryTable(Base):
    __tablename__ = "article_summaries"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    article_id: Mapped[_uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("articles.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    summary_json: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("NOW()"))


class ThemeTable(Base):
    __tablename__ = "themes"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    batch_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    theme_json: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("NOW()"))


class InsightTable(Base):
    __tablename__ = "insights"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    batch_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    insight_json: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("NOW()"))


# ---------------------------------------------------------------------------
# Day 7: Blog post output table
# ---------------------------------------------------------------------------

class BlogPostTable(Base):
    __tablename__ = "blog_posts"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    batch_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    slug: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    markdown: Mapped[str] = mapped_column(Text, nullable=False)
    meta: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("NOW()"))


def create_all_tables() -> None:
    """Create all tables and enable pgvector. Uses DATABASE_URL from env."""
    from sqlalchemy import create_engine
    url = os.getenv("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL environment variable is not set")
    engine = create_engine(url)
    with engine.connect() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        conn.commit()
    Base.metadata.create_all(engine)
    engine.dispose()


if __name__ == "__main__":
    create_all_tables()
    print("Tables created.")

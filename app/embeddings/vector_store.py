"""
pgvector-backed store for article embeddings (SQLAlchemy implementation).
Handles upsert, unembedded article lookup, and cosine similarity search.
"""

import logging
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.db.schema import ArticleEmbeddingTable, ArticleTable

logger = logging.getLogger(__name__)


def get_unembedded_articles(session: Session) -> list[dict[str, Any]]:
    """Return articles that have no row in article_embeddings yet."""
    stmt = (
        select(
            ArticleTable.id,
            ArticleTable.title,
            ArticleTable.summary,
            ArticleTable.raw_content,
        )
        .outerjoin(
            ArticleEmbeddingTable,
            ArticleEmbeddingTable.article_id == ArticleTable.id,
        )
        .where(ArticleEmbeddingTable.id.is_(None))
        .order_by(ArticleTable.id)
    )
    rows = session.execute(stmt).all()
    return [
        {
            "id": r.id,
            "title": r.title,
            "summary": r.summary,
            "raw_content": r.raw_content,
        }
        for r in rows
    ]


def upsert_embedding(
    session: Session, article_id: uuid.UUID, embedding: list[float]
) -> None:
    """Insert or update the embedding for an article."""
    stmt = (
        insert(ArticleEmbeddingTable)
        .values(article_id=article_id, embedding=embedding)
        .on_conflict_do_update(
            index_elements=["article_id"],
            set_={"embedding": embedding},
        )
    )
    session.execute(stmt)


def similar_articles(
    session: Session,
    query_embedding: list[float],
    top_k: int = 5,
    exclude_article_id: uuid.UUID | None = None,
) -> list[dict[str, Any]]:
    """
    Return the top_k most similar articles by cosine distance.
    Returns dicts with id, title, url, summary, score.
    """
    distance = ArticleEmbeddingTable.embedding.cosine_distance(query_embedding)
    stmt = (
        select(
            ArticleTable.id,
            ArticleTable.title,
            ArticleTable.url,
            ArticleTable.summary,
            (1 - distance).label("score"),
        )
        .join(ArticleTable, ArticleTable.id == ArticleEmbeddingTable.article_id)
        .order_by(distance)
        .limit(top_k)
    )
    if exclude_article_id is not None:
        stmt = stmt.where(ArticleTable.id != exclude_article_id)

    rows = session.execute(stmt).all()
    return [
        {
            "id": r.id,
            "title": r.title,
            "url": r.url,
            "summary": r.summary,
            "score": r.score,
        }
        for r in rows
    ]


def search_by_text(
    session: Session,
    query: str,
    top_k: int = 5,
) -> list[dict[str, Any]]:
    """Convenience: embed a text query and return similar articles."""
    from app.embeddings.embed_service import embed_text

    vec = embed_text(query)
    return similar_articles(session, vec, top_k=top_k)

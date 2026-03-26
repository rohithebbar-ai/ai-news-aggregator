"""
Embedding service using all-MiniLM-L6-v2 (384-dim vectors).
Loads the model once, provides embed_text / embed_batch, and a batch runner
that embeds all unembedded articles.

Usage: uv run python -m app.embeddings.embed_service
"""

import logging


from sentence_transformers import SentenceTransformer  # type: ignore[import-untyped]
import numpy as np

logger = logging.getLogger(__name__)

MODEL_NAME = "all-MiniLM-L6-v2"
_model: SentenceTransformer | None = None


def _get_model() -> SentenceTransformer:
    global _model
    if _model is None:
        logger.info("Loading embedding model %s …", MODEL_NAME)
        _model = SentenceTransformer(MODEL_NAME)
    return _model


def embed_text(text: str) -> list[float]:
    """Embed a single string and return a 384-dim float list."""
    model = _get_model()
    vec: np.ndarray = model.encode(text, convert_to_numpy=True, show_progress_bar=False)
    return vec.tolist()


def embed_batch(texts: list[str], batch_size: int = 64) -> list[list[float]]:
    """Embed a list of strings. Returns list of 384-dim float lists."""
    if not texts:
        return []
    model = _get_model()
    vecs: np.ndarray = model.encode(
        texts, convert_to_numpy=True, show_progress_bar=False, batch_size=batch_size
    )
    return vecs.tolist()


def _prepare_text(title: str, summary: str | None, raw_content: str) -> str:
    """
    Build the string to embed.
    Prefer raw_content; fall back to title+summary if empty.
    """
    body = raw_content.strip() if raw_content else ""
    if not body:
        parts = [title.strip()]
        if summary:
            parts.append(summary.strip())
        body = " — ".join(parts)
    return body[:2000]


def run_batch() -> None:
    """Embed all articles that don't yet have an embedding row."""
    from app.db.connection import get_session
    from app.embeddings.vector_store import get_unembedded_articles, upsert_embedding

    with get_session() as session:
        rows = get_unembedded_articles(session)
        if not rows:
            print("No unembedded articles.")
            return
        logger.info("Embedding %d articles …", len(rows))
        texts = [_prepare_text(r["title"], r["summary"], r["raw_content"]) for r in rows]
        vectors = embed_batch(texts)
        for row, vec in zip(rows, vectors):
            upsert_embedding(session, row["id"], vec)
    print(f"Embedded {len(rows)} new articles.")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run_batch()

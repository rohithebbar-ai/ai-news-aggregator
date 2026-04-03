"""
Day 7: Blog post generator with hybrid image citations and Mermaid diagrams.

For each insight in the latest batch:
  1. Fetches og:images from evidence articles
  2. Calls Groq to write a markdown blog post (hero image + inline images + 1 Mermaid diagram)
  3. Stores the post in BlogPostTable

Usage: uv run python -m app.publishing.blog_generator
"""

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.schema import ArticleTable, BlogPostTable, InsightTable
from app.llm.groq_client import call_llm_json

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are a technical blog writer for an AI trend intelligence platform.

Given an insight and its source articles (with image URLs), write a full markdown blog post.

Return a JSON object with exactly these fields:
{
  "title": "<specific, descriptive title — name the actual technology or development, NOT generic phrases like 'Accelerating X' or 'Advancements in X'>",
  "slug": "<url-safe lowercase hyphenated slug, max 60 chars>",
  "summary": "<2-3 sentences explaining WHAT specifically happened, WHY it matters, and WHO is affected — cite real product names or companies from the evidence>",
  "markdown": "<full markdown content — see format instructions>"
}

Title rules:
- BAD: "Accelerating AI Model Development", "Advancements in AI"
- GOOD: "Google Gemini 2.0 Rewrites the Rules for Multimodal AI", "Why OpenAI's New Safety Spec Changes Developer Trust"
- Name specific products, companies, or technical breakthroughs

Summary rules:
- BAD: "This trend is expected to continue with significant implications."
- GOOD: "Google launched live translation in Pixel earbuds powered by Gemini Nano, marking the first on-device real-time translation. This matters because it works offline, cutting latency from seconds to milliseconds and shifting inference from cloud to edge."

Markdown format to follow exactly:
```
# {title}

{If hero_image_url is available:}
![{hero_title}]({hero_image_url})
*Source: [{hero_title}]({hero_url})*

{2-3 paragraph introduction — specific facts, product names, numbers from the analysis}

## Key Developments
- {concrete bullet points — name specific models, tools, companies}

{If second_image_url is available, embed it here:}
![{second_title}]({second_image_url})
*Source: [{second_title}]({second_url})*

## Historical Context
{historical_context from the insight}

## What This Means
{1-2 forward-looking paragraphs with concrete implications}

## Theme Map
\`\`\`mermaid
graph LR
  A[Sub-theme 1] --> B[Main Trend]
  C[Sub-theme 2] --> B
  B --> D[Outcome]
\`\`\`

Mermaid syntax rules — follow exactly:
- Edges: A --> B  or  A -->|label| B  (never use |label|> — no trailing >)
- Node labels in square brackets only: A[Label text]
- No special characters inside labels (no quotes, colons, slashes)
- Max 4 nodes, keep labels under 30 chars

---
*Confidence: {confidence_level} | Direction: {direction}*
```

Return ONLY valid JSON. No explanation outside the JSON."""


def _get_latest_insights(session: Session) -> tuple[str, list[dict]]:
    """Return (batch_id, list of insight_json) for the most recent batch."""
    rows = session.execute(
        select(InsightTable.batch_id, InsightTable.insight_json)
        .order_by(InsightTable.created_at.desc())
    ).all()
    if not rows:
        return "", []
    batch_id = rows[0].batch_id
    insights = [r.insight_json for r in rows if r.batch_id == batch_id]
    return batch_id, insights


def _get_evidence_articles(session: Session, evidence_urls: list[str]) -> list[dict]:
    """Fetch title and og:image for each evidence URL."""
    if not evidence_urls:
        return []
    rows = session.execute(
        select(ArticleTable.title, ArticleTable.url, ArticleTable.image)
        .where(ArticleTable.url.in_(evidence_urls))
    ).all()
    return [{"title": r.title, "url": r.url, "image": r.image} for r in rows]


def _build_prompt(insight: dict, articles: list[dict]) -> str:
    # Pick hero + second image from articles that have images
    images = [a for a in articles if a.get("image")]
    hero = images[0] if images else None
    second = images[1] if len(images) > 1 else None

    lines = [
        f"Trend: {insight.get('trend_name', '')}",
        f"Analysis: {insight.get('analysis', '')}",
        f"Historical context: {insight.get('historical_context', '')}",
        f"Confidence: {insight.get('confidence_level', 'medium')}",
        f"Direction: {insight.get('direction', 'stable')}",
        "",
        "Source articles:",
    ]
    for a in articles[:5]:
        img = a.get("image") or "none"
        lines.append(f"  - title={a['title']} | url={a['url']} | image={img}")

    if hero:
        lines.append(f"\nhero_image_url={hero['image']} | hero_title={hero['title']} | hero_url={hero['url']}")
    if second:
        lines.append(f"second_image_url={second['image']} | second_title={second['title']} | second_url={second['url']}")

    return "\n".join(lines)


def _save_post(session: Session, batch_id: str, post: dict, evidence_articles: list[dict] | None = None) -> None:
    base_slug = post.get("slug", "post")[:60]
    # Ensure slug uniqueness: try base, then base-batchprefix, then base-batchprefix-N
    slug = base_slug
    for suffix in ["", f"-{batch_id[:8]}"] + [f"-{batch_id[:8]}-{i}" for i in range(2, 10)]:
        candidate = f"{base_slug}{suffix}"
        exists = session.execute(
            select(BlogPostTable.slug).where(BlogPostTable.slug == candidate)
        ).scalar_one_or_none()
        if not exists:
            slug = candidate
            break

    sources = [
        {"title": a["title"], "url": a["url"]}
        for a in (evidence_articles or [])
        if a.get("url")
    ]
    row = BlogPostTable(
        batch_id=batch_id,
        slug=slug,
        markdown=post.get("markdown", ""),
        meta={
            "title": post.get("title", ""),
            "summary": post.get("summary", ""),
            "sources": sources,
        },
    )
    session.add(row)
    session.flush()


def run() -> None:
    from app.db.connection import get_session

    with get_session() as session:
        batch_id, insights = _get_latest_insights(session)
        if not insights:
            print("No insights found — run synthesize or agent stage first.")
            return

        logger.info("Generating blog posts for %d insights (batch %s)", len(insights), batch_id)
        success = 0
        for insight in insights:
            evidence_urls = insight.get("evidence", [])
            articles = _get_evidence_articles(session, evidence_urls)
            prompt = _build_prompt(insight, articles)
            try:
                post = call_llm_json(SYSTEM_PROMPT, prompt, temperature=0.5)
                with session.begin_nested():
                    _save_post(session, batch_id, post, evidence_articles=articles)
                logger.info("%s", post.get("title", "?"))
                success += 1
            except Exception as e:
                logger.error("Failed for insight '%s': %s", insight.get("trend_name", "?"), e)

    print(f"Blog generation complete: {success}/{len(insights)} posts created for batch {batch_id}.")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run()

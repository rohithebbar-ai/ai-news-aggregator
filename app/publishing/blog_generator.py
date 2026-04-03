"""
Day 7: Blog post generator with hybrid image citations and Mermaid diagrams.

For each insight in the latest batch:
  1. Fetches og:images from evidence articles
  2. Calls Groq to write a markdown blog post (hero image + inline images + 1 Mermaid diagram)
  3. Stores the post in BlogPostTable

Usage: uv run python -m app.publishing.blog_generator
"""

import logging
import re
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.schema import ArticleTable, ArticleSummaryTable, BlogPostTable, InsightTable
from app.llm.groq_client import call_llm_json

logger = logging.getLogger(__name__)

# Load style profile at module level — injected at top of SYSTEM_PROMPT
_STYLE_PROFILE_PATH = Path(__file__).parent / "style_profile.md"
_STYLE_PROFILE: str = (
    _STYLE_PROFILE_PATH.read_text(encoding="utf-8") if _STYLE_PROFILE_PATH.exists() else ""
)

# Temperature for the final body generation pass — lower than creative writing, higher than factual lookup
_BODY_TEMPERATURE = 0.3

# Phrases that disqualify a generated title (compare against title.lower(); keep aligned with style_profile.md)
_BANNED_TITLE_PHRASES = [
    "rapidly evolving",
    "advancements in ai",  # narrow: bans generic "Advancements in AI" titles, not "advancements in <other field>"
    "game-changing",
    "revolutionary",
    "the future of",
]

_SLUG_STOPWORDS = {
    "the", "a", "an", "and", "or", "but", "in", "on", "at", "to",
    "of", "for", "is", "are", "was", "were", "be", "it", "its",
}


def _extract_key_facts(raw_content: str, max_facts: int = 3) -> list[str]:
    """Extract short factual sentences containing numbers or named entities from raw text."""
    if not raw_content:
        return []
    sentences = re.split(r'(?<=[.!?])\s+', raw_content[:3000])
    facts = []
    for s in sentences:
        s = s.strip()
        if len(s) < 20 or len(s) > 120:
            continue
        if re.search(r'\d|%|v\d|\bv\d+\b', s) or re.search(r'[A-Z][a-z]+(?:\s+[A-Z][a-z]+)+', s):
            facts.append(s)
        if len(facts) >= max_facts:
            break
    return facts

SYSTEM_PROMPT = _STYLE_PROFILE[:600] + "\n\n---\n\n" + """You are a technical blog writer for an AI trend intelligence platform.

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

TITLE_LEDE_PROMPT = """You are a headline editor for an AI trend intelligence newsletter.

Given an insight and its source articles, produce a punchy title and opening lede only.

Rules:
- Title MUST name the specific company, product, or model version driving the trend. No generic phrases.
- Lede (1 sentence): state the single most important fact from the evidence — who did what and why it matters.
- BAD title: "The Rise of Agentic AI"
- GOOD title: "Anthropic Releases Claude 3.5 Haiku with 3x Faster Tool Use Than GPT-4o mini"

Return ONLY valid JSON:
{"title": "<headline>", "lede": "<one sentence opening>"}"""

OUTLINE_PROMPT = """You are a structural editor for an AI trend intelligence blog.

Given an insight and its source articles, return a JSON outline for the blog post.

Return a JSON object with exactly these fields:
{
  "title": "<specific title naming the product, company, or mechanism — no generic phrases>",
  "sections": ["<intro thesis>", "<key development 1>", "<key development 2>", "<historical framing>", "<implications>"],
  "key_facts": ["<fact with company/version/number>", "<fact>", "<fact>"]
}

Return ONLY valid JSON. No explanation outside the JSON."""


def _get_latest_insights(session: Session) -> tuple[str, list[dict]]:
    """Return (batch_id, list of insight_json) for the most recent batch."""
    batch_id = session.execute(
        select(InsightTable.batch_id)
        .order_by(InsightTable.created_at.desc())
        .limit(1)
    ).scalar_one_or_none()
    if not batch_id:
        return "", []
    rows = session.execute(
        select(InsightTable.insight_json)
        .where(InsightTable.batch_id == batch_id)
        .order_by(InsightTable.created_at.desc())
    ).scalars().all()
    return batch_id, list(rows)


def _get_evidence_articles(session: Session, evidence_urls: list[str]) -> list[dict]:
    """Fetch title, og:image, published_at, source_type, one_sentence_summary, and key facts for each evidence URL."""
    if not evidence_urls:
        return []
    rows = session.execute(
        select(
            ArticleTable.title,
            ArticleTable.url,
            ArticleTable.image,
            ArticleTable.published_at,
            ArticleTable.source_type,
            ArticleTable.raw_content,
            ArticleSummaryTable.summary_json,
        )
        .outerjoin(ArticleSummaryTable, ArticleSummaryTable.article_id == ArticleTable.id)
        .where(ArticleTable.url.in_(evidence_urls))
    ).all()

    result = []
    for r in rows:
        summary: str | None = None
        if r.summary_json:
            summary = (
                r.summary_json.get("one_sentence_summary")
                or (r.summary_json.get("summary") or "")[:200]
                or None
            )
        result.append({
            "title": r.title,
            "url": r.url,
            "image": r.image,
            "published_at": r.published_at,
            "source_type": r.source_type,
            "summary": summary,
            "key_facts": _extract_key_facts(r.raw_content or ""),
        })
    return result


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

    lines.append("\nArticle summaries:")
    for a in articles[:5]:
        pub = a.get("published_at")
        pub_str = pub.strftime("%Y-%m-%d") if pub else "unknown"
        summary_text = a.get("summary") or "no summary"
        lines.append(f"  - {a['title']} ({pub_str}): {summary_text}")

    facts_articles = [a for a in articles[:5] if a.get("key_facts")]
    if facts_articles:
        lines.append("\nKey facts from articles:")
        for a in facts_articles:
            facts_str = " | ".join(a["key_facts"])
            lines.append(f"  - {a['title']}: {facts_str}")

    return "\n".join(lines)


def _generate_outline(insight: dict, articles: list[dict]) -> dict:
    """First-pass structural outline; result is injected into the full-draft prompt."""
    prompt = _build_prompt(insight, articles)
    return call_llm_json(OUTLINE_PROMPT, prompt, temperature=_BODY_TEMPERATURE)


def _generate_title_lede(insight: dict, articles: list[dict]) -> dict:
    """Separate LLM call at lower temperature focused solely on headline and lede."""
    prompt = _build_prompt(insight, articles)
    return call_llm_json(TITLE_LEDE_PROMPT, prompt, temperature=0.2)


def _validate_mermaid(markdown: str) -> str:
    """Remove malformed mermaid blocks rather than rendering broken diagrams."""
    pattern = r"```mermaid\s*\n(.*?)```"

    def check_block(match: re.Match) -> str:
        body = match.group(1)
        lines = [l.strip() for l in body.splitlines() if l.strip()]
        for line in lines:
            if "|>" in line:
                logger.warning("Mermaid block removed: invalid edge label '|>' in: %r", line)
                return ""
            if re.search(r'[:"\/\\]', line):
                logger.warning("Mermaid block removed: special char in label: %r", line)
                return ""
        if len(lines) > 10:
            logger.warning("Mermaid block removed: too many lines (%d)", len(lines))
            return ""
        return match.group(0)

    return re.sub(pattern, check_block, markdown, flags=re.DOTALL)


def _validate_post(post: dict, insight: dict) -> tuple[bool, str]:
    """Return (ok, reason). Enforces minimum quality before saving."""
    markdown = post.get("markdown", "")
    title = post.get("title", "").lower()

    word_count = len(markdown.split())
    if word_count < 300:
        return False, f"Too short: {word_count} words (minimum 300)"

    evidence_urls = insight.get("evidence", [])
    # If the insight has no evidence URLs, we cannot require links in the body — skip this check.
    # Intentional: empty evidence is an upstream data issue, not something _validate_post can fix here.
    if evidence_urls and not any(url in markdown for url in evidence_urls):
        return False, "No evidence URLs cited in markdown body"

    for phrase in _BANNED_TITLE_PHRASES:
        if phrase in title:
            return False, f"Banned phrase in title: '{phrase}'"

    slug = post.get("slug", "").strip().lower()
    if not slug:
        return False, "Post has no slug"
    if slug:
        slug_words = [w for w in slug.split("-") if w]
        meaningful = [w for w in slug_words if w not in _SLUG_STOPWORDS]
        if not meaningful:
            return False, f"Slug contains only stopwords: '{slug}'"
        if len(slug) < 10:
            return False, f"Slug too short: '{slug}' (minimum 10 chars)"
        if slug.startswith("-") or slug.endswith("-"):
            return False, f"Slug has leading/trailing hyphen: '{slug}'"

    return True, ""


def _save_post(session: Session, batch_id: str, post: dict, evidence_articles: list[dict] | None = None) -> None:
    base_slug = post.get("slug", "post")[:60]
    # Ensure slug uniqueness: try base, then base-batchprefix, then base-batchprefix-N
    slug: str | None = None
    for suffix in ["", f"-{batch_id[:8]}"] + [f"-{batch_id[:8]}-{i}" for i in range(2, 10)]:
        candidate = f"{base_slug}{suffix}"
        exists = session.execute(
            select(BlogPostTable.slug).where(BlogPostTable.slug == candidate)
        ).scalar_one_or_none()
        if not exists:
            slug = candidate
            break

    if slug is None:
        raise RuntimeError(
            f"All slug candidates exhausted for base slug {base_slug!r} (batch {batch_id!r}); "
            "every variant from base through suffix -9 is already taken in blog_posts."
        )

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
        rejected = 0
        for insight in insights:
            evidence_urls = insight.get("evidence", [])
            articles = _get_evidence_articles(session, evidence_urls)
            prompt = _build_prompt(insight, articles)
            try:
                outline = _generate_outline(insight, articles)
                outline_section = (
                    f"\nOutline to follow:\n"
                    f"  Title: {outline.get('title', '')}\n"
                    f"  Sections: {', '.join(outline.get('sections', []))}\n"
                    f"  Key facts: {'; '.join(outline.get('key_facts', []))}"
                )
                tl = _generate_title_lede(insight, articles)
                outline_section += f"\n  Suggested title: {tl.get('title', '')}\n  Opening lede: {tl.get('lede', '')}"
                post = call_llm_json(SYSTEM_PROMPT, prompt + outline_section, temperature=_BODY_TEMPERATURE)
                if post.get("markdown"):
                    post["markdown"] = _validate_mermaid(post["markdown"])
                ok, reason = _validate_post(post, insight)
                if not ok:
                    logger.warning("Post rejected for '%s': %s", insight.get("trend_name", "?"), reason)
                    rejected += 1
                    continue
                with session.begin_nested():
                    _save_post(session, batch_id, post, evidence_articles=articles)
                logger.info("%s", post.get("title", "?"))
                success += 1
            except Exception as e:
                logger.error("Failed for insight '%s': %s", insight.get("trend_name", "?"), e)

    print(f"Blog generation complete: {success}/{len(insights)} posts created, {rejected} rejected for batch {batch_id}.")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run()

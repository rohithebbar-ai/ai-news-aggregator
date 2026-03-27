"""
Day 9: Email digest sender via AWS SES.

Reads the latest batch's blog posts and sends a formatted HTML digest.
Falls back to a dry-run (prints the email) if AWS credentials are not set.

Usage: uv run python main.py email
"""

import json
import logging
import os
import time

logger = logging.getLogger(__name__)


def _build_html(posts: list[dict]) -> str:
    """Build a simple HTML email body from blog post metadata."""
    # Build items from post metadata
    items = []
    for post in posts:
        meta = post.get("meta", {})
        title = meta.get("title", post.get("slug", "Untitled"))
        summary = meta.get("summary", "")
        items.append(f"<h3>{title}</h3><p>{summary}</p><hr>")

    body = "\n".join(items) if items else "<p>No posts this batch.</p>"
    return f"""
    <html><body>
    <h2>AI Trend Intelligence — Daily Digest</h2>
    {body}
    </body></html>
    """


def _send_via_ses(subject: str, html_body: str, from_addr: str, to_addr: str) -> dict:
    """Send email via AWS SES. Returns response dict."""
    import boto3
    region = os.getenv("AWS_REGION", "us-east-1")
    client = boto3.client("ses", region_name=region)
    response = client.send_email(
        Source=from_addr,
        Destination={"ToAddresses": [to_addr]},
        Message={
            "Subject": {"Data": subject},
            "Body": {"Html": {"Data": html_body}},
        },
    )
    return response


def send_digest(session) -> dict:
    """
    Read latest blog posts, build digest, send via SES (or dry-run).
    Returns a log dict for persistence.
    """
    from sqlalchemy import select
    from app.db.schema import BlogPostTable, EmailLogTable

    # Get latest batch posts
    try:
        rows = session.execute(
            select(BlogPostTable).order_by(BlogPostTable.created_at.desc()).limit(10)
        ).scalars().all()
        posts = [{"slug": r.slug, "meta": r.meta} for r in rows]
        batch_id = rows[0].batch_id if rows else "unknown"
    except Exception as e:
        logger.warning("Could not fetch blog posts (schema may need migration): %s", e)
        session.rollback()
        rows = []
        posts = []
        batch_id = "unknown"

    subject = f"AI Trend Intelligence — {len(posts)} new insights"
    html_body = _build_html(posts)

    from_addr = os.getenv("EMAIL_FROM", "")
    to_addr = os.getenv("EMAIL_TO", "")
    has_credentials = bool(from_addr and to_addr and os.getenv("AWS_ACCESS_KEY_ID"))

    start = time.time()
    result = {"batch_id": batch_id, "post_count": len(posts), "dry_run": not has_credentials}

    if has_credentials:
        try:
            response = _send_via_ses(subject, html_body, from_addr, to_addr)
            result["status"] = "sent"
            result["message_id"] = response.get("MessageId", "")
            logger.info("Email digest sent: %s → %s", from_addr, to_addr)
        except Exception as e:
            result["status"] = "failed"
            result["error"] = str(e)
            logger.error("Email send failed: %s", e)
    else:
        result["status"] = "dry_run"
        logger.info("No AWS credentials — dry run. Email would contain %d posts.", len(posts))
        print(f"\n--- DRY RUN EMAIL ---\nSubject: {subject}\n{html_body[:500]}...\n")

    result["latency_ms"] = int((time.time() - start) * 1000)

    # Persist to email_logs
    try:
        log = EmailLogTable(
            batch_id=batch_id,
            status=result["status"],
            model_used="ses",
            skip_reason="" if has_credentials else "no_aws_credentials",
            details_json=result,
        )
        session.add(log)
        session.commit()
    except Exception as e:
        logger.warning("Failed to log email: %s", e)
        try:
            session.rollback()
        except Exception:
            pass

    return result


def run() -> None:
    from app.db.connection import get_session as db_session
    with db_session() as session:
        result = send_digest(session)
        print(f"Email digest: {result['status']} ({result['post_count']} posts, {result['latency_ms']}ms)")

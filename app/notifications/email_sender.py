"""
Day 9: Email digest sender.

Supports three modes (controlled by EMAIL_PROVIDER env var):
  smtp    — Gmail / any SMTP server (SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD)
  ses     — AWS SES (AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, AWS_REGION)
  dry_run — prints email to stdout (default when no credentials set)

Usage: uv run python main.py email
"""

import logging
import os
import smtplib
import time
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

logger = logging.getLogger(__name__)


def _build_html(posts: list[dict]) -> str:
    """Build HTML email body from blog post metadata."""
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


def _send_via_smtp(subject: str, html_body: str, from_addr: str, to_addr: str) -> None:
    """Send email via SMTP (Gmail or any SMTP server)."""
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = from_addr
    msg["To"] = to_addr
    msg.attach(MIMEText(html_body, "html"))

    host = os.getenv("SMTP_HOST", "smtp.gmail.com")
    port = int(os.getenv("SMTP_PORT", "587"))
    user = os.getenv("SMTP_USER", from_addr)
    password = os.getenv("SMTP_PASSWORD", "")

    with smtplib.SMTP(host, port) as server:
        server.starttls()
        server.login(user, password)
        server.sendmail(from_addr, to_addr, msg.as_string())


def _send_via_ses(subject: str, html_body: str, from_addr: str, to_addr: str) -> dict:
    """Send email via AWS SES."""
    import boto3
    region = os.getenv("AWS_REGION", "us-east-1")
    client = boto3.client("ses", region_name=region)
    return client.send_email(
        Source=from_addr,
        Destination={"ToAddresses": [to_addr]},
        Message={
            "Subject": {"Data": subject},
            "Body": {"Html": {"Data": html_body}},
        },
    )


def send_digest(session) -> dict:
    """
    Read latest blog posts, build digest, send via SMTP / SES / dry-run.
    Provider selected by EMAIL_PROVIDER env var (smtp | ses | dry_run).
    """
    from sqlalchemy import select
    from app.db.schema import BlogPostTable, EmailLogTable

    # Fetch latest batch posts
    try:
        rows = session.execute(
            select(BlogPostTable).order_by(BlogPostTable.created_at.desc()).limit(10)
        ).scalars().all()
        posts = [{"slug": r.slug, "meta": r.meta} for r in rows]
        batch_id = rows[0].batch_id if rows else "unknown"
    except Exception as e:
        logger.warning("Could not fetch blog posts: %s", e)
        session.rollback()
        posts = []
        batch_id = "unknown"

    subject = f"AI Trend Intelligence — {len(posts)} new insights"
    html_body = _build_html(posts)

    from_addr = os.getenv("EMAIL_FROM", "")
    to_addr = os.getenv("EMAIL_TO", "")
    provider = os.getenv("EMAIL_PROVIDER", "dry_run").lower()

    start = time.time()
    result = {"batch_id": batch_id, "post_count": len(posts), "provider": provider}

    if provider == "smtp" and from_addr and to_addr:
        try:
            _send_via_smtp(subject, html_body, from_addr, to_addr)
            result["status"] = "sent"
            logger.info("Email sent via SMTP: %s → %s", from_addr, to_addr)
        except Exception as e:
            result["status"] = "failed"
            result["error"] = str(e)
            logger.error("SMTP send failed: %s", e)

    elif provider == "ses" and os.getenv("AWS_ACCESS_KEY_ID"):
        try:
            response = _send_via_ses(subject, html_body, from_addr, to_addr)
            result["status"] = "sent"
            result["message_id"] = response.get("MessageId", "")
            logger.info("Email sent via SES: %s → %s", from_addr, to_addr)
        except Exception as e:
            result["status"] = "failed"
            result["error"] = str(e)
            logger.error("SES send failed: %s", e)

    else:
        result["status"] = "dry_run"
        print(f"\n--- DRY RUN EMAIL ---\nSubject: {subject}\n{html_body[:500]}...\n")

    result["latency_ms"] = int((time.time() - start) * 1000)

    # Persist to email_logs
    try:
        log = EmailLogTable(
            batch_id=batch_id,
            status=result["status"],
            model_used=provider,
            skip_reason="" if result["status"] == "sent" else result.get("error", ""),
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

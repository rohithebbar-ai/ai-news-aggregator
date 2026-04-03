"""
Day 9: Email digest sender.

Supports three modes (controlled by EMAIL_PROVIDER env var):
  smtp    — Gmail / any SMTP server (SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD)
  ses     — AWS SES (AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, AWS_REGION)
  dry_run — prints email to stdout (default when no credentials set)

Usage: uv run python main.py email
"""

import html
import logging
import os
import smtplib
import time
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from urllib.parse import urlparse

logger = logging.getLogger(__name__)


def _safe_http_href(url: str) -> str | None:
    """
    Allow only http/https with a non-empty netloc for use in href.
    Returns HTML-escaped URL safe for a double-quoted attribute, or None if disallowed.
    """
    if not url or not isinstance(url, str):
        return None
    url = url.strip()
    if not url:
        return None
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return None
    return html.escape(url, quote=True)


def _build_html(posts: list[dict], portfolio_url: str) -> str:
    """Build HTML email body from blog post metadata with links."""
    items = []
    for post in posts:
        meta = post.get("meta", {})
        raw_title = meta.get("title", post.get("slug", "Untitled"))
        title = html.escape(str(raw_title))
        summary = html.escape(str(meta.get("summary", "")))
        slug = post.get("slug", "")
        direction = html.escape(str(meta.get("direction", "")))
        confidence = html.escape(str(meta.get("confidence", "")))

        post_href: str | None = None
        if portfolio_url and slug:
            post_href = _safe_http_href(f"{portfolio_url.rstrip('/')}/blog/{slug}")
        read_more = (
            f'<p><a href="{post_href}" style="color:#4F46E5;font-weight:600">→ Read full post</a></p>'
            if post_href
            else ""
        )
        badge = (
            f'<span style="font-size:12px;color:#6B7280">{direction} · {confidence} confidence</span>'
            if direction
            else ""
        )

        sources = meta.get("sources", [])
        source_parts: list[str] = []
        for s in sources[:3]:
            if not isinstance(s, dict):
                continue
            stitle = html.escape(str((s.get("title") or ""))[:50])
            surl = s.get("url")
            href = _safe_http_href(str(surl)) if surl else None
            if href and stitle:
                source_parts.append(
                    f'<a href="{href}" style="color:#6B7280;font-size:12px">{stitle}</a>'
                )
            elif stitle:
                source_parts.append(stitle)
        source_links = " · ".join(source_parts)
        sources_html = f'<p style="margin:6px 0">📰 Sources: {source_links}</p>' if source_links else ""

        items.append(f"""
        <div style="margin-bottom:24px;padding-bottom:24px;border-bottom:1px solid #E5E7EB">
          <h3 style="margin:0 0 6px 0;font-size:18px">{title}</h3>
          {badge}
          <p style="color:#374151;margin:8px 0">{summary}</p>
          {sources_html}
          {read_more}
        </div>""")

    body = "\n".join(items) if items else "<p>No posts this batch.</p>"
    return f"""
    <html>
    <body style="font-family:sans-serif;max-width:640px;margin:0 auto;padding:24px;color:#111">
      <h2 style="border-bottom:2px solid #4F46E5;padding-bottom:12px">
        🤖 AI Trend Intelligence — Daily Digest
      </h2>
      <p style="color:#6B7280;margin-bottom:24px">{len(items)} trend{'s' if len(items)!=1 else ''} from today's batch</p>
      {body}
      <p style="font-size:12px;color:#9CA3AF;margin-top:32px">
        Powered by Groq · LangGraph · Neon Postgres
      </p>
    </body>
    </html>
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

    # Fetch posts for the latest batch only (not a mix of all batches)
    posts_fetch_failed = False
    try:
        latest = session.execute(
            select(BlogPostTable.batch_id)
            .order_by(BlogPostTable.created_at.desc())
            .limit(1)
        ).scalar_one_or_none()
        batch_id = latest or "unknown"

        rows = session.execute(
            select(BlogPostTable)
            .where(BlogPostTable.batch_id == batch_id)
            .order_by(BlogPostTable.created_at.asc())
        ).scalars().all()
        posts = [{"slug": r.slug, "meta": r.meta} for r in rows]
    except Exception as e:
        logger.warning("Could not fetch blog posts: %s", e)
        session.rollback()
        posts = []
        batch_id = "unknown"
        posts_fetch_failed = True

    from_addr = os.getenv("EMAIL_FROM", "")
    to_addr = os.getenv("EMAIL_TO", "")
    provider = os.getenv("EMAIL_PROVIDER", "dry_run").lower()

    if posts_fetch_failed:
        skip_reason = (
            "Blog posts could not be loaded from the database (query failed); "
            "digest email was not sent to avoid a misleading empty digest."
        )
        start = time.time()
        result: dict = {
            "batch_id": batch_id,
            "post_count": 0,
            "provider": provider,
            "status": "skipped",
            "skip_reason": skip_reason,
        }
        result["latency_ms"] = int((time.time() - start) * 1000)
        try:
            log = EmailLogTable(
                batch_id=batch_id,
                status=result["status"],
                model_used=provider,
                skip_reason=skip_reason,
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

    portfolio_url = os.getenv("PORTFOLIO_URL", "").rstrip("/")
    subject = f"AI Trend Intelligence — {len(posts)} new insights"
    html_body = _build_html(posts, portfolio_url)

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
            skip_reason=result.get("skip_reason") or result.get("error", ""),
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

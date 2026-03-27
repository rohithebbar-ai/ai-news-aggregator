"""
AI Trend Intelligence Engine — pipeline runner.

Usage:
  uv run python main.py <stage>

Stages:
  ingest     — scrape RSS + YouTube, deduplicate, store articles
  embed      — embed unembedded articles with MiniLM
  summarize  — Stage 1: summarize each article via Groq
  group      — Stage 2: group articles into themes
  synthesize — Stage 3: synthesize insights per theme (direct)
  agent      — Stage 3 (agentic): ReAct agent loop for richer insights
  blog       — Stage 4: generate blog posts from insights
  email      — Stage 5: send email digest via AWS SES
"""

import sys


def main():
    stage = sys.argv[1] if len(sys.argv) > 1 else ""

    if stage == "ingest":
        from app.ingestion.run import run
        run()

    elif stage == "embed":
        from app.embeddings.embed_service import run
        run()

    elif stage == "summarize":
        from app.llm.summarizer import run
        run()

    elif stage == "group":
        from app.llm.theme_grouper import run
        run()

    elif stage == "synthesize":
        from app.llm.synthesizer import run
        run()

    elif stage == "agent":
        from app.agent.agent_loop import run
        run()

    elif stage == "blog":
        from app.publishing.blog_generator import run
        run()

    elif stage == "email":
        from app.notifications.email_sender import run
        run()

    else:
        print(__doc__)


if __name__ == "__main__":
    main()

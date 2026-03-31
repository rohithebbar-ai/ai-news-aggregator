import os
import json
from dotenv import load_dotenv
import psycopg2
from groq import Groq

load_dotenv()


def _live_setup_enabled() -> tuple[bool, str]:
    """Gate external integration checks to avoid flaky default test runs."""
    enabled = os.getenv("RUN_LIVE_SETUP_TESTS", "").lower() in {"1", "true", "yes"}
    if not enabled:
        return (
            False,
            "Live setup checks are disabled. Set RUN_LIVE_SETUP_TESTS=1 to enable.",
        )
    if not os.getenv("DATABASE_URL"):
        return False, "DATABASE_URL is required for live Neon test."
    if not os.getenv("GROQ_API_KEY"):
        return False, "GROQ_API_KEY is required for live Groq test."
    return True, ""


def _skip_unless_live_enabled() -> None:
    """Skip in pytest by default; no external network calls in normal CI."""
    should_run, reason = _live_setup_enabled()
    if should_run:
        return
    try:
        import pytest

        pytest.skip(reason)
    except Exception:
        # If not running under pytest, keep behavior explicit for script usage.
        raise RuntimeError(reason)

def test_neon():
    _skip_unless_live_enabled()
    print("Testing Neon Connection")
    conn = psycopg2.connect(os.getenv("DATABASE_URL"))
    cur = conn.cursor()

    # Check pgvector is enabled
    cur.execute("SELECT extversion FROM pg_extension WHERE extname = 'vector';")
    version = cur.fetchone()
    assert version is not None, "pgvector extension is not enabled"
    print(f"  pgvector version: {version[0]}")
    
    # Check tables exist
    cur.execute("""
        SELECT table_name FROM information_schema.tables 
        WHERE table_schema = 'public' ORDER BY table_name;
    """)
    tables = [row[0] for row in cur.fetchall()]
    print(f"  Tables: {', '.join(tables)}")
    
    cur.close()
    conn.close()
    print("  Neon: OK\n")

def test_groq():
    _skip_unless_live_enabled()
    print("Testing Groq API...")
    client = Groq(api_key=os.getenv("GROQ_API_KEY"))
    
    response = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[{
            "role": "user",
            "content": "Return a JSON object with key 'status' and value 'connected'. Only return JSON, nothing else."
        }],
        response_format={"type": "json_object"},
        max_tokens=50
    )
    
    result = json.loads(response.choices[0].message.content)
    assert result.get("status") == "connected", f"Unexpected response: {result}"
    print(f"  Model: llama-3.3-70b-versatile")
    print(f"  Response: {result}")
    print(f"  Tokens used: {response.usage.total_tokens}")
    print("  Groq: OK\n")

if __name__ == "__main__":
    print("=" * 40)
    print("AI Trend Engine - Setup Test")
    print("=" * 40 + "\n")

    should_run, reason = _live_setup_enabled()
    if not should_run:
        print(f"Skipping live checks: {reason}")
    else:
        test_neon()
        test_groq()
        print("All systems operational. Ready to build.")
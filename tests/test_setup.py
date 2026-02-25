import os
import json
from dotenv import load_dotenv
import psycopg2
from groq import Groq

load_dotenv()

def test_neon():
    print("Testing Neon Connection")
    conn = psycopg2.connect(os.getenv("DATABASE_URL"))
    cur = conn.cursor()

    # Check pgvector is enabled
    cur.execute("SELECT extversion FROM pg_extension WHERE extname = 'vector';")
    version = cur.fetchone()
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
    print(f"  Model: llama-3.3-70b-versatile")
    print(f"  Response: {result}")
    print(f"  Tokens used: {response.usage.total_tokens}")
    print("  Groq: OK\n")

if __name__ == "__main__":
    print("=" * 40)
    print("AI Trend Engine - Setup Test")
    print("=" * 40 + "\n")
    
    test_neon()
    test_groq()
    
    print("All systems operational. Ready to build.")
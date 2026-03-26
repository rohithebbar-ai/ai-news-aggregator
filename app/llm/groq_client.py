"""
Groq API wrapper with JSON output mode, retry/backoff, and token logging.
"""

import json
import logging
import os
import time

from dotenv import load_dotenv
from groq import Groq, RateLimitError  # type: ignore[import-untyped]

load_dotenv()

logger = logging.getLogger(__name__)

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
DEFAULT_MODEL = "llama-3.3-70b-versatile"
MAX_RETRIES = 3
INITIAL_BACKOFF_SEC = 2.0


def _get_client() -> Groq:
    if not GROQ_API_KEY:
        raise RuntimeError("GROQ_API_KEY environment variable is not set")
    return Groq(api_key=GROQ_API_KEY)


def call_llm(
    system_prompt: str,
    user_prompt: str,
    model: str = DEFAULT_MODEL,
    temperature: float = 0.3,
    max_tokens: int = 4096,
) -> str:
    """
    Call Groq LLM with JSON output mode enabled.
    Returns the raw response text (expected to be valid JSON).
    Retries with exponential backoff on rate-limit errors.
    """
    client = _get_client()
    backoff = INITIAL_BACKOFF_SEC

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=temperature,
                max_tokens=max_tokens,
                response_format={"type": "json_object"},
            )
            content = response.choices[0].message.content or ""

            usage = response.usage
            if usage:
                logger.info(
                    "Groq %s | prompt=%d completion=%d total=%d",
                    model,
                    usage.prompt_tokens,
                    usage.completion_tokens,
                    usage.total_tokens,
                )
            return content

        except RateLimitError:
            if attempt == MAX_RETRIES:
                raise
            logger.warning("Rate limited (attempt %d/%d), backing off %.1fs", attempt, MAX_RETRIES, backoff)
            time.sleep(backoff)
            backoff *= 2

    return ""


def call_llm_json(
    system_prompt: str,
    user_prompt: str,
    model: str = DEFAULT_MODEL,
    temperature: float = 0.3,
    max_tokens: int = 4096,
) -> dict:
    """call_llm but parse the response as JSON dict. Raises ValueError on bad JSON."""
    raw = call_llm(system_prompt, user_prompt, model=model, temperature=temperature, max_tokens=max_tokens)
    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        logger.error("LLM returned invalid JSON: %s", raw[:500])
        raise ValueError(f"Invalid JSON from LLM: {e}") from e

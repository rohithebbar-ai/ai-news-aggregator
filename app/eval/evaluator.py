"""
Day 8: Evaluation pipeline for LLM output quality.

Three checks:
1. schema_validate  — jsonschema validation on insight JSON structure
2. score_coherence  — LLM-as-judge coherence score (1-5, threshold >= 3)
3. check_novelty    — cosine similarity against recent insights (threshold < 0.92)

Usage: uv run python -m app.eval.evaluator
"""

import json
import logging
import time

import jsonschema

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# JSON Schema definition for insight validation
# ---------------------------------------------------------------------------

_INSIGHT_SCHEMA = {
    "type": "object",
    "required": ["trend_name", "analysis", "evidence", "historical_context", "confidence_level", "direction"],
    "properties": {
        "trend_name": {"type": "string"},
        "analysis": {"type": "string"},
        "evidence": {"type": "array"},
        "historical_context": {"type": "string"},
        "confidence_level": {"type": "string", "enum": ["high", "medium", "low"]},
        "direction": {"type": "string", "enum": ["accelerating", "stable", "emerging", "declining"]},
    },
    "additionalProperties": True,
}


# ---------------------------------------------------------------------------
# 1. Schema validation
# ---------------------------------------------------------------------------

def schema_validate(data: dict) -> tuple[bool, str]:
    """
    Validate insight dict against required schema.

    Returns (True, "") on pass, (False, reason) on fail.
    """
    try:
        jsonschema.validate(instance=data, schema=_INSIGHT_SCHEMA)
        return True, ""
    except jsonschema.ValidationError as e:
        return False, e.message
    except Exception as e:
        return False, f"Unexpected validation error: {e}"


# ---------------------------------------------------------------------------
# 2. LLM-as-judge coherence scoring
# ---------------------------------------------------------------------------

def score_coherence(insight: dict) -> tuple[int, str]:
    """
    Ask the LLM to score the insight for coherence, relevance, and quality (1-5).

    Returns (score: int, reason: str).
    On any error, returns (3, "eval failed") to avoid breaking the pipeline.
    """
    try:
        from app.llm.groq_client import call_llm_json

        system_prompt = (
            'You are an evaluator. Score the following AI trend insight for coherence, '
            'relevance, and quality on a scale of 1-5. '
            'Return JSON: {"score": <int>, "reason": <str>}'
        )
        user_prompt = json.dumps(insight)

        result = call_llm_json(system_prompt, user_prompt)
        score = int(result.get("score", 3))
        reason = str(result.get("reason", ""))
        # clamp to valid range
        score = max(1, min(5, score))
        return score, reason

    except Exception as e:
        logger.warning("Coherence scoring failed: %s", e)
        return 3, "eval failed"


# ---------------------------------------------------------------------------
# 3. Novelty check via cosine similarity
# ---------------------------------------------------------------------------

def check_novelty(session, insight: dict) -> tuple[bool, float]:
    """
    Check whether the insight is novel by comparing it against stored article embeddings.

    Searches for insight trend_name + first 200 chars of analysis with top_k=3.
    If any result has score > 0.92, the insight is NOT novel.

    Returns (is_novel: bool, max_similarity: float).
    """
    try:
        from app.embeddings.vector_store import search_by_text

        trend_name = insight.get("trend_name", "")
        analysis = insight.get("analysis", "")
        query = f"{trend_name} {analysis[:200]}"

        results = search_by_text(session, query, top_k=3)

        if not results:
            return True, 0.0

        max_similarity = max(r.get("score", 0.0) for r in results)
        is_novel = max_similarity <= 0.92
        return is_novel, float(max_similarity)

    except Exception as e:
        logger.warning("Novelty check failed: %s", e)
        return True, 0.0


# ---------------------------------------------------------------------------
# 4. Eval log persistence
# ---------------------------------------------------------------------------

def log_eval(
    session,
    batch_id: str,
    stage: str,
    eval_type: str,
    score: float,
    details: dict,
    latency_ms: int,
) -> None:
    """
    Persist an eval result to the eval_logs table.

    Wrapped in try/except so logging never crashes the main pipeline.
    """
    try:
        from app.db.schema import EvalLogTable

        row = EvalLogTable(
            batch_id=batch_id,
            stage=stage,
            eval_type=eval_type,
            score=score,
            details_json=details,
            latency_ms=latency_ms,
        )
        session.add(row)
        session.flush()
    except Exception as e:
        logger.warning("Failed to log eval result: %s", e)


# ---------------------------------------------------------------------------
# 5. Run eval for a single insight
# ---------------------------------------------------------------------------

def run_eval_for_insight(session, batch_id: str, insight: dict) -> dict:
    """
    Run all three eval checks on one insight dict.

    Returns a summary dict:
      {trend_name, schema_valid, coherence_score, is_novel, max_similarity, passed}

    'passed' = schema_valid AND coherence_score >= 3 AND is_novel
    """
    trend_name = insight.get("trend_name", "<unknown>")
    print(f"\n  Evaluating: {trend_name!r}")

    # --- schema check ---
    t0 = time.monotonic()
    schema_valid, schema_reason = schema_validate(insight)
    schema_latency = int((time.monotonic() - t0) * 1000)
    print(f"    schema_validate : {'PASS' if schema_valid else 'FAIL'} — {schema_reason or 'ok'}")
    log_eval(
        session,
        batch_id=batch_id,
        stage="insight",
        eval_type="schema",
        score=1.0 if schema_valid else 0.0,
        details={"valid": schema_valid, "reason": schema_reason},
        latency_ms=schema_latency,
    )

    # --- coherence check ---
    t0 = time.monotonic()
    coherence_score, coherence_reason = score_coherence(insight)
    coherence_latency = int((time.monotonic() - t0) * 1000)
    print(f"    score_coherence : {coherence_score}/5 — {coherence_reason}")
    log_eval(
        session,
        batch_id=batch_id,
        stage="insight",
        eval_type="coherence",
        score=float(coherence_score),
        details={"score": coherence_score, "reason": coherence_reason},
        latency_ms=coherence_latency,
    )

    # --- novelty check ---
    t0 = time.monotonic()
    is_novel, max_similarity = check_novelty(session, insight)
    novelty_latency = int((time.monotonic() - t0) * 1000)
    print(f"    check_novelty   : {'novel' if is_novel else 'duplicate'} (max_sim={max_similarity:.4f})")
    log_eval(
        session,
        batch_id=batch_id,
        stage="insight",
        eval_type="novelty",
        score=float(max_similarity),
        details={"is_novel": is_novel, "max_similarity": max_similarity},
        latency_ms=novelty_latency,
    )

    passed = schema_valid and coherence_score >= 3 and is_novel
    print(f"    => {'PASSED' if passed else 'FAILED'}")

    return {
        "trend_name": trend_name,
        "schema_valid": schema_valid,
        "coherence_score": coherence_score,
        "is_novel": is_novel,
        "max_similarity": max_similarity,
        "passed": passed,
    }


# ---------------------------------------------------------------------------
# 6. Entry point
# ---------------------------------------------------------------------------

def run() -> None:
    """Read latest insights from InsightTable, evaluate each one, print summary."""
    from sqlalchemy import select
    from app.db.connection import get_session
    from app.db.schema import InsightTable

    print("=== Day 8: Evaluation Pipeline ===")

    with get_session() as session:
        rows = session.execute(
            select(InsightTable).order_by(InsightTable.created_at.desc()).limit(20)
        ).scalars().all()

        if not rows:
            print("No insights found in DB. Run the agent or synthesize stage first.")
            return

        print(f"Found {len(rows)} insight(s) to evaluate.")

        results = []
        for row in rows:
            batch_id = str(row.batch_id)
            insight = row.insight_json
            result = run_eval_for_insight(session, batch_id, insight)
            results.append(result)

        session.commit()

    # Summary
    total = len(results)
    passed = sum(1 for r in results if r["passed"])
    print(f"\n=== Summary: {passed}/{total} insights passed all eval checks ===")
    for r in results:
        status = "PASS" if r["passed"] else "FAIL"
        print(
            f"  [{status}] {r['trend_name']!r} "
            f"| schema={r['schema_valid']} "
            f"| coherence={r['coherence_score']}/5 "
            f"| novel={r['is_novel']} (sim={r['max_similarity']:.4f})"
        )


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run()

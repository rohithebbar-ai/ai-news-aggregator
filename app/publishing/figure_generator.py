"""
figure_generator — Groq-powered chart pipeline for blog posts.

Pipeline:
  1. ``_call_chart_spec`` asks the Groq LLM for a structured JSON chart spec
     derived solely from the insight text and article key_facts.
  2. One of three matplotlib renderers turns the spec into PNG bytes.
  3. ``generate_trend_figure`` base64-encodes the PNG and returns a data URI
     safe for direct embedding in markdown (``![](data:image/png;base64,...)``) .
"""

import base64
import logging
from io import BytesIO

from app.llm.groq_client import call_llm_json

logger = logging.getLogger(__name__)

CHART_SPEC_PROMPT = """\
You are a data-visualization assistant for a technical AI blog. Given an insight \
and supporting article facts, output a single JSON object describing a chart to \
accompany the post.

RULES — follow strictly:
• Use ONLY numbers and names that appear verbatim in the insight/articles. Never invent data.
• chart_type selection:
  - "bar"      → insight contains benchmark scores, percentages, latency numbers, \
or cost comparisons.
  - "timeline" → insight describes a sequence of events or model releases over time.
  - "bullet"   → fallback for everything else.
• bar: max 6 items. timeline: max 8 events. bullets: max 5, each under 80 chars.
• title: max 60 chars. caption: one-sentence takeaway, max 100 chars.

Return exactly this JSON (omit inapplicable keys, but always include "bullets" as \
fallback data):
{
  "chart_type": "bar | timeline | bullet",
  "title": "<short chart title, max 60 chars>",
  "caption": "<one sentence takeaway, max 100 chars>",
  "bars": [{"label": "<name>", "value": <number>, "unit": "<%, ms, B, etc>", "highlight": false}],
  "y_label": "<axis label>",
  "events": [{"date": "<YYYY-MM or YYYY>", "label": "<event name, max 40 chars>"}],
  "bullets": ["<fact 1>", "<fact 2>", "<fact 3>"]
}"""


def _call_chart_spec(insight: dict, articles: list[dict]) -> dict:
    facts_lines: list[str] = []
    for art in articles:
        facts = art.get("key_facts")
        if facts:
            if isinstance(facts, list):
                facts_lines.extend(f"- {f}" for f in facts[:5])
            else:
                facts_lines.append(f"- {str(facts)[:200]}")

    prompt = (
        f"Trend: {insight.get('trend_name', '')}\n\n"
        f"Analysis: {str(insight.get('analysis', ''))[:500]}\n\n"
        f"Key facts from articles:\n"
        + ("\n".join(facts_lines) if facts_lines else "(none)")
    )
    return call_llm_json(CHART_SPEC_PROMPT, prompt, temperature=0.1)


def _render_bar(spec: dict) -> bytes:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    bars = spec.get("bars", [])
    labels = [b.get("label", "") for b in bars]
    values = [float(b.get("value", 0)) for b in bars]
    units = [b.get("unit", "") for b in bars]
    highlights = [b.get("highlight", False) for b in bars]

    n = len(bars)
    # Gradient darkest (#3B82F6) → lightest (#60A5FA)
    step = 1 / max(n - 1, 1)
    blues = [
        (0x3B / 255 + i * step * (0x60 - 0x3B) / 255,
         0x82 / 255 + i * step * (0xA5 - 0x82) / 255,
         0xF6 / 255 + i * step * (0xFA - 0xF6) / 255)
        for i in range(n)
    ]
    colors = ["#F59E0B" if h else blues[i] for i, h in enumerate(highlights)]

    fig, ax = plt.subplots(figsize=(8, 4), dpi=100)
    fig.patch.set_facecolor("#FFFFFF")
    ax.set_facecolor("#FFFFFF")

    y_pos = list(range(n))
    bars_plot = ax.barh(y_pos, values, color=colors, height=0.55, zorder=2)

    max_val = max(values) if values else 1
    for bar_patch, val, unit in zip(bars_plot, values, units):
        ax.text(
            bar_patch.get_width() + max_val * 0.01,
            bar_patch.get_y() + bar_patch.get_height() / 2,
            f"{val:g}{unit}",
            va="center", ha="left", fontsize=9, color="#374151",
        )

    ax.set_yticks(y_pos)
    ax.set_yticklabels(labels, fontsize=10)
    ax.set_xlabel(spec.get("caption", ""), color="#6B7280", fontsize=9)
    ax.set_ylabel(spec.get("y_label", ""), fontsize=10)
    ax.set_title(spec.get("title", ""), fontsize=12, fontweight="bold", pad=10, color="#111827")
    ax.set_xlim(0, max_val * 1.2)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.xaxis.grid(True, color="#E5E7EB", linestyle="--", zorder=0)
    ax.set_axisbelow(True)

    buf = BytesIO()
    plt.tight_layout()
    fig.savefig(buf, format="png", bbox_inches="tight")
    plt.close(fig)
    return buf.getvalue()


def _render_timeline(spec: dict) -> bytes:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    events = spec.get("events", [])
    n = len(events)
    x_pos = list(range(n))

    fig, ax = plt.subplots(figsize=(8, 3), dpi=100)
    fig.patch.set_facecolor("#FFFFFF")
    ax.set_facecolor("#FFFFFF")

    ax.axhline(0, color="#3B82F6", linewidth=2, zorder=1)
    ax.scatter(x_pos, [0] * n, color="#3B82F6", s=80, zorder=2)

    for i, ev in enumerate(events):
        above = i % 2 == 0
        y_label = 0.28 if above else -0.28
        y_date = -0.38 if above else 0.38
        va_label = "bottom" if above else "top"
        va_date = "top" if above else "bottom"
        ax.text(i, y_label, ev.get("label", ""), ha="center", va=va_label,
                fontsize=8, color="#1F2937")
        ax.text(i, y_date, ev.get("date", ""), ha="center", va=va_date,
                fontsize=7, color="#6B7280")

    ax.set_title(spec.get("title", ""), fontsize=12, fontweight="bold", color="#111827")
    ax.set_xlim(-0.5, n - 0.5)
    ax.set_ylim(-0.9, 0.9)
    ax.axis("off")

    caption = spec.get("caption", "")
    if caption:
        fig.text(0.5, 0.02, caption, ha="center", fontsize=8, color="#6B7280", style="italic")

    buf = BytesIO()
    plt.tight_layout()
    fig.savefig(buf, format="png", bbox_inches="tight")
    plt.close(fig)
    return buf.getvalue()


def _render_bullet(spec: dict) -> bytes:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import FancyBboxPatch

    bullets = spec.get("bullets", [])
    n = max(len(bullets), 1)
    fig_h = 1.2 * n + 1.2

    fig, ax = plt.subplots(figsize=(8, fig_h), dpi=100)
    fig.patch.set_facecolor("#FFFFFF")
    ax.set_facecolor("#FFFFFF")
    ax.axis("off")

    # Header band spanning full width
    header_height = min(0.18, 0.9 / fig_h)
    header = FancyBboxPatch(
        (0, 1 - header_height), 1, header_height + 0.02,
        transform=ax.transAxes, boxstyle="square,pad=0",
        linewidth=0, facecolor="#EFF6FF", zorder=0,
    )
    ax.add_patch(header)

    ax.text(0.5, 0.97, spec.get("title", ""), transform=ax.transAxes,
            ha="center", va="top", fontsize=13, fontweight="bold", color="#1E3A5F")

    step = 0.78 / n
    for i, bullet in enumerate(bullets):
        y = 0.82 - i * step
        ax.text(0.05, y, f"\u2022  {bullet}", transform=ax.transAxes,
                ha="left", va="top", fontsize=10, color="#374151")

    caption = spec.get("caption", "")
    if caption:
        ax.text(0.5, 0.03, caption, transform=ax.transAxes,
                ha="center", va="bottom", fontsize=9, color="#6B7280", style="italic")

    buf = BytesIO()
    plt.tight_layout()
    fig.savefig(buf, format="png", bbox_inches="tight")
    plt.close(fig)
    return buf.getvalue()


def generate_trend_figure(insight: dict, articles: list[dict]) -> str | None:
    """Generate a trend visualization using Groq LLM spec + matplotlib render.

    Returns a data URI string: 'data:image/png;base64,...'
    or None if generation fails (caller continues without a figure).
    """
    try:
        spec = _call_chart_spec(insight, articles)
    except Exception as exc:
        logger.warning("Chart spec generation failed: %s", exc)
        return None

    # Guard: call_llm_json may return non-dict on certain parse failures
    if not isinstance(spec, dict):
        logger.warning("Chart spec returned non-dict: %r", spec)
        return None

    chart_type = spec.get("chart_type", "bullet")

    if chart_type == "bar" and len(spec.get("bars", [])) >= 2:
        renderer = _render_bar
    elif chart_type == "timeline" and len(spec.get("events", [])) >= 2:
        renderer = _render_timeline
    else:
        renderer = _render_bullet

    try:
        png_bytes = renderer(spec)
    except Exception as exc:
        logger.warning("Primary renderer (%s) failed: %s", chart_type, exc)
        # Only attempt bullet fallback when bullet wasn't already the primary renderer
        if renderer is not _render_bullet:
            try:
                png_bytes = _render_bullet(spec)
            except Exception as exc2:
                logger.warning("Bullet fallback renderer also failed: %s", exc2)
                return None
        else:
            return None

    b64 = base64.b64encode(png_bytes).decode()
    return "data:image/png;base64," + b64

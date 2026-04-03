# Article quality: Vizuara `write-substack` vs `ai-news-aggregator`

## Why Vizuara articles read “better” (root cause)

`Vizuara-AI-Pods/write-substack` is **not** “one prompt → one post.” It encodes an **editorial workflow** (see `SKILL.md` + `scripts/assemble_article.py`):

| Dimension | Vizuara `write-substack` | `ai-news-aggregator` (today) |
|-----------|---------------------------|------------------------------|
| **Voice & style** | Reads a **style profile** + **2–3 reference articles** before writing | No style profile; generic “technical blog writer” system prompt only |
| **Structure** | **Outline first**, user **approval** before draft | No outline; single shot from insight JSON |
| **Draft depth** | Full draft with planned **figures**, **equations**, **code blocks**, placement rules | One JSON call: title, slug, summary, markdown + optional hero/second image |
| **Visuals** | **Specialized** figure pipelines (Excalidraw vs illustration), LaTeX, assembly with QA | **Mermaid only** (fragile in prompts); images mostly og: scrape |
| **Quality gates** | Explicit **Step 6** checklist (captions, figure–text alignment, numerical examples, references) | No automated QA beyond LLM obeying prompt |
| **Human loop** | Stops for outline approval; final read vs style profile | Fully automated |

**Conclusion:** Quality differences are expected: you are comparing **a production content system with review and assets** to a **fully automated news digest generator**. Closing the gap means **adding stages, constraints, and checks**—not only tweaking one prompt.

---

## Improvement suggestions (by layer)

### Upstream (biggest leverage)

1. **Insight quality caps blog quality.** If `synthesizer` / `agent_loop` outputs vague analysis or thin evidence, the blog stage can only rephrase fluff. Invest in stronger synthesis prompts, more evidence URLs, and optional **fact/quote extraction** from `raw_content` or summaries before blogging.

2. **Pass richer context into `_build_prompt`** (`blog_generator.py`). Today the model sees trend fields + up to 5 lines of title/url/image. Consider adding: **short excerpts** from stored summaries, **publish dates**, **source type**, and **explicit quotes** or bullet facts extracted from articles.

3. **Two-pass blog generation:** (a) outline + section thesis; (b) expand to full markdown. Mirrors Vizuara’s outline → draft without requiring a human if you automate both steps.

### Blog stage

4. **Style pack:** Check in a `style-profile.md` (voice, taboo phrases, sentence length, how to cite sources) and **inject a short excerpt** into the system or user prompt every time.

5. **Stronger anti-generic rules:** Ban list for titles/openers; require **at least N named entities** (companies, products, versions) in the intro; require **at least one date or version** when present in sources.

6. **Mermaid / diagrams:** Either simplify rules further, **post-validate** Mermaid syntax, or **drop Mermaid** from auto posts and use a static template diagram only when validation passes.

7. **Temperature & model:** Blog uses `temperature=0.5`. Experiment with **lower** for factual tone or **higher** only for framing paragraphs—not both in one setting without A/B testing.

### Process / ops

8. **Human-in-the-loop export:** Generate drafts to Markdown files + **manual approve** before DB publish (mini Vizuara gate).

9. **Metrics:** Word count, entity count, link-out count, reading level; **reject or regenerate** if below thresholds.

---

## Checklist for implementation

### Critical (do these first — largest impact on perceived quality)

- [ ] **Add a committed style guide** (even 1 page): voice, banned phrases, citation pattern; inject into blog system prompt.
- [ ] **Enrich blog user prompt** with article excerpts or summary bullets from DB—not only title/url/image.
- [ ] **Two-pass or outline step** for blog: outline JSON → then full markdown JSON (or chained calls).
- [ ] **Validate outputs** before save: minimum length, minimum number of concrete proper nouns, evidence URLs preserved in body.
- [ ] **Treat insight quality as prerequisite:** review/tune `synthesizer` + theme grouper prompts if analysis stays generic.

### High (strong ROI; moderate effort)

- [ ] **Quote / fact extraction pass** (LLM or heuristic) from linked articles’ `raw_content` / summaries; feed quotes into blog prompt.
- [ ] **Separate “title + lede” call** from “body” call** to reduce generic titles.
- [ ] **Lower temperature** for factual sections or use structured sections with per-section instructions.
- [ ] **Slug + SEO meta review** rules (length, no stopword-only titles).
- [ ] **Automated Mermaid lint** or remove auto-Mermaid on failure and fall back to text hierarchy only.

### Optional (polish & parity with rich publishing pipelines)

- [ ] **Human approval** UI or script: export → edit → import.
- [ ] **Reference section** auto-generated from evidence URLs with consistent formatting (Vizuara-style reference list).
- [ ] **Optional image pipeline:** curated figures (e.g. Excalidraw/PNG) for flagship posts—not for every automated run.
- [ ] **A/B prompts** logged with batch_id to learn what works.
- [ ] **Reading time, word count, and link density** in `meta` for downstream filtering.

---

## Python version note

**3.11 vs 3.13** does not fix writing quality. Prefer **whatever your `uv.lock` supports**; focus effort on **prompts, data fed to the model, and review steps** above.

---

## Reference paths

- Vizuara workflow: `Vizuara-AI-Pods/write-substack/SKILL.md`
- Assembler (figures/equations): `Vizuara-AI-Pods/write-substack/scripts/assemble_article.py`
- Your blog generator: `app/publishing/blog_generator.py`
- Insight source: `app/llm/synthesizer.py`, `app/agent/agent_loop.py`

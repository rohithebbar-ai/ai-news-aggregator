# AGENTS.md

## Cursor Cloud specific instructions

### Services

| Service | Required | Notes |
|---|---|---|
| Neon Postgres (pgvector) | Yes | Remote DB at `*.neon.tech`; `DATABASE_URL` env var required |
| Groq API | Yes | `GROQ_API_KEY` env var required; model `llama-3.3-70b-versatile` |
| AWS SES / SMTP | No | Email stage falls back to dry-run without credentials |

### Running the pipeline

All stages are run via `uv run python main.py <stage>`. See `CLAUDE.md` for the full stage list and module mapping.

### Environment setup

- The `.env` file must be created from injected environment variables before running any stage (`python-dotenv` loads it at import time in `app/db/connection.py` and other modules).
- `uv` is the only supported package manager. Do **not** use `pip` or `poetry`.
- The project pins `torch>=2.2.0,<2.3.0` and `numpy<2.0.0`; `uv sync` handles this via `uv.lock`.

### Gotchas

- The `tests/test_setup.py` script is an integration connectivity check (DB + Groq), not a unit test suite. There is no `pytest` test suite in this repo.
- `scripts/test_setup.py` referenced in `CLAUDE.md` does not exist; the actual file is `tests/test_setup.py`.
- YouTube scraping may return 0 results depending on transcript availability; this is normal.
- The `embed` stage downloads `all-MiniLM-L6-v2` (~80 MB) on first run; subsequent runs use the HuggingFace cache.
- Database schema initialization (`uv run python -m app.db.schema`) emits a `RuntimeWarning` about `sys.modules` ordering — this is harmless.
- The CI workflow (`.github/workflows/ci.yml`) validates that all pipeline module imports succeed. Run the same check locally with the import validation one-liner in `ci.yml`.

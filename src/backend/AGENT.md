# Backend Agent Guide

## Scope

Applies to `src/backend/`.

## Stack

- FastAPI application entrypoint: `src.backend.app.main:app`
- Settings: `src/backend/app/core/config.py`
- Environment variables are loaded from the repository root `.env`.

## Responsibilities

- File upload and parsing for PDF, Markdown, TXT, and later DOCX/Excel if time allows.
- Chapter detection, page/chapter metadata preservation, and chunking.
- LLM calls for knowledge point and relation extraction.
- Knowledge point extraction must reject table/figure numbers, page headers, broken parenthesis fragments, and generic phrases. Preserve `quality_score`, `extraction_method`, and `warnings` on graph nodes.
- Graph extraction should use cleaned deterministic candidates first, then let LLM validate/define/classify them. Do not let LLM freely persist nodes from raw noisy PDF text without backend validation.
- Knowledge graph merge decisions with confidence and reasons.
- RAG indexing/query APIs with citations.
- Teacher feedback APIs for updating integration decisions.

## API Direction

Keep the API close to the赛题 requirements:

- `GET /api/health`
- `POST /api/textbooks/upload`
- `GET /api/textbooks`
- `POST /api/graphs/build`
- `GET /api/graphs/{textbook_id}`
- `POST /api/integration/run`
- `GET /api/integration/decisions`
- `POST /api/integration/feedback`
- `POST /api/rag/index`
- `POST /api/rag/query`
- `GET /api/rag/status`

## Data Rules

- Never load a full large textbook into memory if page-by-page parsing is available.
- Preserve metadata on every derived object: textbook id, filename/title, chapter, page range, source text span when possible.
- Store generated runtime data under ignored paths such as `data/uploads/`, `data/indexes/`, or `data/cache/`.
- Do not hardcode the seven local textbooks; the app must work from user uploads.

## LLM Rules

- Read model credentials from settings only.
- Do not log API keys.
- Ask LLMs for strict JSON and validate before persisting.
- Keep one chapter or one bounded batch per extraction call to avoid context blowups.
- For single-textbook graph prompts, define relation directions explicitly:
  `prerequisite` = source is required before target, `contains` = source contains target,
  `applies_to` = source applies to target, `parallel` = same-level concepts.
- Cache expensive LLM outputs where possible.

## Verification

- Import/syntax check:
  `.venv/bin/python -m py_compile src/backend/app/main.py src/backend/app/core/config.py`
- RAG regression and benchmark checks:
  `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest -q tests/test_rag.py tests/test_rag_benchmark.py`
- RAG Benchmark optimization:
  `.venv/bin/python scripts/rag_benchmark.py --sample-size 30 --optimize --write-docs`
- Runtime health check:
  `NO_PROXY=127.0.0.1,localhost no_proxy=127.0.0.1,localhost curl -sS http://127.0.0.1:8000/api/health`

## Known Pitfalls

- FastAPI `TestClient` can hang in this command environment when the anyio blocking portal exits. Use real Uvicorn plus HTTP checks for backend verification.
- Keep Uvicorn reload scoped to backend code:
  `.venv/bin/uvicorn src.backend.app.main:app --reload --reload-dir src/backend --host 0.0.0.0 --port 8000`
- Do not watch `.venv/` with reload. It causes reload storms during dependency changes.
- Local HTTP checks may fail through the proxy unless `NO_PROXY` and `no_proxy` include `127.0.0.1,localhost`.
- After temporary checks on alternate ports such as `8001`, verify no process is still listening before starting `npm run dev`.
- When tuning RAG, do not judge from one manual question only. Run the local benchmark, inspect `docs/RAG Benchmark.md`, and keep `src/backend/app/rag_defaults.json` aligned with the measured best config.

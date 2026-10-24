# backend

Second Key authorization kernel. Python 3.12, uv, FastAPI, Pydantic v2, SQLite.

- Install: `uv sync` (downloads Python 3.12 if missing).
- Unit tests: `uv run pytest -q tests/unit`
- Property tests (CI profile, 2000 examples): `HYPOTHESIS_PROFILE=ci uv run pytest -q tests/property`
- Everything: `uv run pytest -q`
- Lint and types: `uv run ruff check . && uv run mypy kernel`
- API: `uv run uvicorn api.main:app --port 8000` then `curl localhost:8000/health`
- Policy rules live in `kernel/policy/v1.yaml`; the kernel library is `kernel/`, HTTP is `api/`.

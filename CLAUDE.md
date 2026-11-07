# CLAUDE.md — Wander

Wander is a travel-idea inbox for two people who travel together: capture first, classify later.
**`PLAN.md` is the source of truth** for goals, design, decisions (§9) and the phased plan (§8).
Read it before starting any phase. When a decision changes, update `PLAN.md` in the same change.

## Layout

- `backend/` — Python 3.13, FastAPI, SQLAlchemy 2, Alembic, SQLite (WAL). Managed with `uv`.
  - `app/main.py` API (`uvicorn --factory app.main:create_app`), `app/worker.py` background worker
    (`python -m app.worker`), `app/jobs.py` the SQLite job queue, `app/auth.py` Cloudflare Access JWT.
  - Migrations: `uv run alembic revision --autogenerate -m "..."` (from `backend/`); the API applies them at startup.
- `frontend/` — Vite + React + TypeScript PWA. In dev, Vite proxies `/api` to `:8000`.
- `Dockerfile` — one image for both roles; `.github/workflows/image.yml` tests and pushes
  `ghcr.io/<owner>/wander:sha-<short>` on `main`.

## Running locally

```bash
cd backend && WANDER_DEV_MODE=true uv run uvicorn --factory app.main:create_app --reload
cd backend && WANDER_DEV_MODE=true uv run python -m app.worker
cd frontend && npm run dev          # http://localhost:5173
cd backend && uv run pytest -q && uv run ruff check . && uv run ruff format --check .
```

(If `uv` isn't on PATH, `python -m uv` works too.)

## Conventions

- **Capture must never fail** because of anything downstream. `POST /api/capture` only stores and enqueues;
  all slow or fallible work (fetching, AI, geocoding) is a worker job that retries and, at worst, parks the
  capture in `needs_review`. Never delete or rewrite `captures.raw_text` / `url`.
- **Auth is Cloudflare Access only.** No passwords in the app. `WANDER_DEV_MODE` is local-only and is refused
  when Access is configured.
- **Dependencies:** `backend/pyproject.toml` has `[tool.uv] exclude-newer` and npm installs use `--before`,
  both set about two weeks back, so nothing brand-new gets pulled in. Bump the date deliberately.
- **Claude API:** default model `claude-opus-5-5` (per PLAN.md §6). Use the official `anthropic` SDK, structured
  outputs, and prompt caching, and log `usage` per call.
- **"Complexity must earn its place"**: no Redis, no Postgres, no Kubernetes unless
  `PLAN.md` is changed first.

## Deployment

The operator's deployment config (compose stack, encrypted secrets, tunnel and Access setup) lives in a
separate **private** ops repo, never here. This repo is **public**: keep it free of secrets, hostnames
beyond those already in `PLAN.md`, internal addresses, and personal details about the users. If a session
has the ops repo available, follow that repo's own `CLAUDE.md` for any deploy work.

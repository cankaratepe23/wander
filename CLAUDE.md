# CLAUDE.md — Wander

Wander is a travel-idea inbox for two people who travel together: capture first, classify later.
**`PLAN.md` is the source of truth** for goals, design, decisions (§9) and the phased plan (§8).
Read it before starting any phase. When a decision changes, update `PLAN.md` in the same change.

## Layout

- `backend/` — Python 3.13, FastAPI, SQLAlchemy 2, Alembic, SQLite (WAL). Managed with `uv`.
  - `app/main.py` API (`uvicorn --factory app.main:create_app`), `app/worker.py` background worker
    (`python -m app.worker`), `app/jobs.py` the SQLite job queue, `app/auth.py` Cloudflare Access JWT.
  - Enrichment: `sources.py` (signals) → `understand.py` (Claude) → `geocode.py` → `enrich.py` (the pipeline);
    `deep.py` video, keyframes and transcripts; `ai.py` the client, prices and usage logging.
  - Routers `ideas_api.py`, `chat_api.py`, `imports_api.py`; `tools.py` is the tool set shared by `chat.py` and
    `mcp_server.py`; `hotspots.py`; `importers.py` + `backfill.py` (Batch API); `nudges.py`; `backup.py`.
  - Migrations: `uv run alembic revision --autogenerate -m "..."` (from `backend/`); the API applies them at startup.
- `frontend/` — Vite + React + TypeScript PWA. In dev, Vite proxies `/api` to `:8000`.
- `Dockerfile` — one image for both roles; `.github/workflows/image.yml` tests and pushes
  `ghcr.io/<owner>/wander:sha-<short>` on `main`.

## Running locally

```bash
cd backend && WANDER_DEV_MODE=true uv run uvicorn --factory app.main:create_app --reload
cd backend && WANDER_DEV_MODE=true uv run python -m app.worker
cd backend && WANDER_DEV_MODE=true uv run python -m app.seed      # demo ideas for the globe (empty DB only)
cd frontend && npm run dev          # http://localhost:5173
cd frontend && npm run build && npm run preview   # http://localhost:4173, the built app (also proxies /api)
cd backend && uv run pytest -q && uv run ruff check . && uv run ruff format --check .
```

(If `uv` isn't on PATH, `python -m uv` works too.)

The globe has been checked on the built app (`npm run preview`). In a hidden or background browser tab, MapLibre's
frame-driven loading stalls (about 10 s or more), so check map changes in a visible tab. The design system is
`docs/design/meridian.md`, and its tokens are `frontend/src/styles/tokens.css`.

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

## How changes ship

- **Straight to `main`.** One maintainer: no pull requests or long-lived branches, unless the owner asks for one.
  `main` is also the only branch CI builds an image from.
- **Build, check, then ask.** Finish a change, run the tests and lint, and try anything visible on the built app.
  Then say what changed and what wasn't verified, and ask in one line whether to commit, push and deploy.
  The owner usually says yes right away, but each change gets its own yes; an earlier one doesn't carry over.
- **"Deploy" is one sequence.** Commit and push here, wait for CI to finish, and only then bump the image tag to
  `sha-<short>` in the ops repo and push that. Confirm the containers are running the new tag and healthy, then
  report it. Don't bump to an image CI hasn't built, and check CI after every push rather than assuming it passed.
- **Secrets never pass through the chat.** The owner puts a value in a local file and an agent moves it into the
  ops repo's encrypted secrets by script, printing only names, lengths and yes/no checks. Windows line endings
  can end up inside a value, so strip them and check the decrypted bytes. Don't delete the owner's files.
- **On Windows, write scripts with the Write tool.** Bash heredocs have mangled backslash escapes and quotes here.

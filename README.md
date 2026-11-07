# Wander

**A travel-idea inbox for two.** Toss in a TikTok, an Instagram reel, a screenshot or a half-remembered
sentence in a few seconds. Wander quietly works out *where* it is, files it on a shared world map, and
shows you where ideas are piling up, which is usually where your next trip should be.

> Status: early. Phase 0 (the plumbing) is done; capture, AI enrichment and the map are next.
> The full research, design and roadmap is in [`PLAN.md`](PLAN.md).

## Why

Travel ideas arrive all day and get lost across saved reels, chat threads and memory. Existing apps either
turn a single reel into map pins, or build itineraries. None treats **quick, messy capture by two people**
as the core loop, with AI doing the filing afterwards (see the survey in [`PLAN.md` §2](PLAN.md#2-does-this-already-exist)).

## How it works

```
 share / paste / type ──► POST /api/capture ──► "Saved ✓"           (instant, never blocks)
                                 │
                                 ▼
                          background worker
         yt-dlp metadata · keyframes · Whisper transcript · screenshot vision
                                 │
                                 ▼
          Claude (structured output) ──► places, category, best months, tags
                                 │
                                 ▼
          OpenStreetMap geocoding ──► dedupe ──► clusters & "hotspots" on a globe
```

- **Capture first, classify later.** Saving only stores the raw input and enqueues a job. If anything
  downstream fails, the idea lands in a *Needs a look* tray instead of disappearing.
- **Share from anywhere.** An installable PWA registers as an Android share target. On iOS, an Apple
  Shortcut posts to the same endpoint.
- **Refine by chatting.** Chat with Claude in the app, or through an MCP connector in the Claude app, about
  your own idea pool ("what do we have around the Aegean coast?").

## Stack

| | |
|---|---|
| Backend | Python 3.13 · FastAPI · SQLAlchemy 2 · Alembic · SQLite (WAL) · a tiny SQLite job queue |
| AI | Claude via the Anthropic SDK (structured outputs, vision, prompt caching) |
| Media | `yt-dlp` · `ffmpeg` · `faster-whisper` (local, CPU) |
| Frontend | React · Vite · TypeScript · PWA · MapLibre GL (globe) on OpenFreeMap tiles |
| Auth | Cloudflare Access: the app verifies the Access JWT and has no passwords of its own |
| Ops | One Docker image (API + worker) · GitHub Actions → GHCR · self-hosted on a low-power mini PC |

## Run it locally

Requires Python 3.13 with [uv](https://docs.astral.sh/uv/), and Node 22.

```bash
# API (dev mode: auth off, everyone is dev@localhost)
cd backend && uv sync && WANDER_DEV_MODE=true uv run uvicorn --factory app.main:create_app --reload

# Worker (second terminal)
cd backend && WANDER_DEV_MODE=true uv run python -m app.worker

# Frontend (third terminal) → http://localhost:5173
cd frontend && npm ci && npm run dev
```

Or run the production image end to end: `docker compose -f docker-compose.dev.yml up --build` → http://localhost:8000.

Tests and lint: `cd backend && uv run pytest -q && uv run ruff check .`

## Configuration

All settings are `WANDER_*` environment variables; see [`backend/app/config.py`](backend/app/config.py).
In production, set `WANDER_ACCESS_TEAM_DOMAIN` and `WANDER_ACCESS_AUD` (and optionally
`WANDER_ALLOWED_EMAILS`), put Cloudflare Access in front, and publish no ports.

## Roadmap

0. ✅ Skeleton: API, worker, job queue, Access auth, image + CI
1. Design language (a real one, see `PLAN.md` §4.7), then the MVP: share targets, AI enrichment, map
2. Deep parsing: video keyframes, transcripts, link-rot archive
3. Hotspots, in-app chat, MCP connector
4. Backfill from WhatsApp / TikTok / Instagram data exports, seasonal nudges
5. Trips and itineraries

## License

[MIT](LICENSE)

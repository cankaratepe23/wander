# Wander: design & implementation plan

*Status (2026-11-07): Phase 0 done and deployed. Next: Phase 1a (design language).*

## 1. The problem

Travel ideas come up all day: a TikTok someone forwards, an Instagram reel, a chat message saying
"we should go here", a sentence at dinner. When they're spread across three apps and two memories, they get lost.
Wander has one job above all: **saving an idea must take seconds, whatever its source**, and it never
asks anyone to organise anything at that moment. Organising happens later, either on its own (AI enrichment and
filing) or on request (chat, map, refining). Over time the map shows where ideas are piling up, and
that pile is the signal for where the next trip should go.

Wander is built for **two people who travel together**. Both save into one shared pool.

## 2. Does this already exist?

**Partly. Several apps turn a reel into map pins, but none does the whole job, and nothing
self-hostable does social capture or AI at all.** Surveyed November 2026:

| App | Saves from TikTok/IG | AI | Map | Shared use | Self-host | Verdict |
|---|---|---|---|---|---|---|
| **Mapstr** | ✅ share sheet; finds the places, you pick | place detection, tags | ✅ | "collaborative map" (vague) | ❌ | Closest for the reel → pin part |
| **Somedays** | ✅ paste a link | extraction | ✅ | friend sharing | ❌ | Free tier: 5 extractions a month |
| **Rhyme** (ex-Roamy), Triply, PlanPin, Go There, TokSpot… | ✅ | vision/transcript claims | ✅ | unclear | ❌ | A wave of 2025–26 iOS-first apps; expect churn |
| **Mindtrip** / **Airial** | paste a link | strong chat and itineraries | ✅ | Mindtrip yes | ❌ | Planners first, not idea inboxes |
| **Google Maps** | ❌ (Gemini reads screenshots) | Gemini | ✅ | shared lists | ❌ | No link parsing |
| **Wanderlog**, Layla, Polarsteps, Stippl, Lambus, Pilot, Tripsy, Wonderplan | ❌ | itinerary AI | ✅ | some | ❌ | Itinerary builders: Wander's *Phase 5*, not its core |
| **AdventureLog**, **TREK** | ❌ | ❌ (TREK has an MCP) | ✅ | ✅ | ✅ | Self-hosted maps with no capture or AI |

**What nobody does** is Wander's core loop:
1. **Free-text jots** ("that place with the cliff pools, Croatia?") classified the same way as saved reels.
2. **One shared pool for two people** with "who saved it" and "do we both want it".
3. **Ideas piling up on a destination** treated as a signal ("Portugal has 9 ideas, time to plan").
4. **Chatting with AI over your own idea pool** rather than over the internet's.
5. **Owning the data.** The reel-to-pin apps are young, VC-shaped and iOS-first. If one shuts down,
   the ideas go with it, which is the original problem all over again.

**Build-vs-buy verdict: build.** One cheap check before Phase 2: share a few real reels into **Mapstr**.
If its place extraction is excellent, that's the quality bar to match; if it misses, that confirms the gap.

*Not verified: pricing for Mapstr Pro, Rhyme, Airial and Wanderlog Pro, and how shared use actually works in the reel apps.*

## 3. Design principles

1. **Capture first, classify later.** The capture call stores the raw input and returns at once with a
   "Saved ✓". Everything slow (fetching the post, transcription, AI, geocoding) runs afterwards in
   a background worker. If AI is down, the network is down, or a post can't be parsed, the idea is still saved.
2. **One input box takes everything.** Free text, a link, a screenshot, a voice note, or a share from
   another app all go through the same capture path. The app works out what it received.
3. **Keep the original.** The raw text and link are stored unchanged, beside whatever the AI made of
   them, so a bad AI result can always be redone (a "re-enrich" button) without losing anything.
4. **Archive against link rot.** TikToks and reels get deleted. The caption, transcript, thumbnail,
   a few keyframes and a capped copy of the video are stored locally, so the idea outlives the post.
5. **Ask only when unsure.** When the AI's confidence is low ("is 'the blue city' Chefchaouen or
   Jodhpur?"), the item goes to a small *Needs a look* tray to settle with one tap. Everything else is
   filed silently.
6. **Two people, one shared pool.** Every idea records who saved it, and each person can heart it.
   An idea both people hearted counts for more on the map.
7. **Complexity must earn its place.** One container image, SQLite, no Redis, no Kubernetes, and no
   self-hosted map tiles.

## 4. Features

### 4.1 Capture (the most important part)

| Path | How it works | Platform |
|---|---|---|
| **Quick box** | The home screen opens on an autofocused text box with *Save* underneath. Type or paste a link and that's it. | Any |
| **Android share target** | The installed PWA registers as a share target (Web Share Target API), so TikTok, Instagram, WhatsApp, Chrome and Gallery all get "Share → Wander". A service worker receives the share, queues it in IndexedDB and shows "Saved ✓" right away. This also works offline and survives an expired login. | Android |
| **iOS Shortcut** | iOS Safari doesn't support web share targets ([WebKit bug 194593](https://bugs.webkit.org/show_bug.cgi?id=194593)), so an Apple Shortcut ("Save to Wander") shows up in the iOS share sheet and POSTs the URL or text, or an image, to `/api/capture`. It authenticates with a Cloudflare Access *service token* scoped to that one endpoint. | iOS |
| **Screenshot** | Share or upload a screenshot (an Instagram post, a Google Maps pin, a hotel listing), and Claude reads it with vision. This is also the fallback whenever a link can't be parsed. | Any |
| **Voice note** | A mic button uses the browser's speech-to-text: "Somewhere in the Dolomites with those hut-to-hut hikes, maybe September". | Any |
| **Forward from a chat** | Long-press a message, then Share → Wander (Android), or use the Shortcut (iOS). | Any |

### 4.2 Enrichment pipeline (behind the scenes)

```
capture ──► queue ──► [1] resolve source ──► [2] extract media signals ──► [3] Claude: understand
                          (text / URL type)     caption · hashtags · location    structured JSON:
                                                tag · thumbnail · keyframes ·    ideas[], places[],
                                                audio transcript                 category, season…
                                                                                         │
            [6] cluster & score ◄── [5] dedupe / merge ◄── [4] geocode places ◄──────────┘
                (hotspots)            (same place → stack)    (Nominatim/Photon)
```

1. **Resolve.** Plain text goes straight to step 3. For a URL, detect the platform: TikTok,
   Instagram, YouTube Shorts, Google Maps, a blog, Booking/Airbnb, or anything else.
2. **Extract signals.** For video posts: the caption and hashtags, the author, the platform's
   location tag where there is one, and the thumbnail, all from **`yt-dlp` metadata**
   (with `curl_cffi` installed for TikTok impersonation, and the cookies of a dedicated, throwaway account for
   Instagram, which gates most posts behind a login). oEmbed is *not* a reliable caption source: a live test in
   Nov 2026 showed TikTok's oEmbed returning only the iframe HTML, and Meta's tokenless oEmbed (since June 2026)
   returns embed HTML only. It's still used to render an embedded player on the idea card.
   Deep mode adds 4–6 keyframes from `ffmpeg` (travel videos usually have "📍 place name" text overlays, which
   Claude reads with vision) and an audio transcript from `faster-whisper`, running locally on CPU. The `small`
   int8 model takes roughly 20–40 s for a 60 s clip on a low-power Intel N150, and it's asynchronous, so nobody waits.
   For web pages: `og:` tags plus the readable text.
3. **Understand.** One Claude call with **structured outputs** (a JSON schema) returns:
   `is_travel_related`, a short title, a 1–2 sentence summary, one or more **places** (name,
   type `country|region|city|poi|restaurant|hotel|activity`, country, a geocoder-friendly query string
   such as `"Kaş, Antalya, Türkiye"`, and a confidence), plus `category` (beach, city break, food, hiking,
   nature, culture, festival, road trip, ski, wellness, experience, accommodation…), `tags`,
   `best_months`, `budget_level`, `trip_length_hint` and `language`. A single post such as "10 hidden gems in
   Portugal" becomes one idea linked to 10 places. Captions and voice-overs in any language are understood;
   summaries are written in English.
4. **Geocode.** Claude names places but doesn't supply coordinates, because LLM coordinates aren't
   reliable. The query string goes to a real geocoder, public **Nominatim** or **Photon**
   (OpenStreetMap, free, about 1 req/s, plenty at this volume). The OSM id and the
   country/region/city hierarchy are stored for grouping.
5. **Dedupe and merge.** A new place that matches an existing one by OSM id, or by name within a few
   km, attaches to it. That's how ideas stack up on a destination.
6. **Score.** Each region and city gets a "heat" score: the number of ideas, weighted by recency,
   by how many people hearted them, and by how varied they are (food + hike + beach counts for more than three beaches).

Anything with low confidence, or flagged as not travel-related, lands in *Needs a look* rather than being dropped.

### 4.3 Browse: the world view

- **Globe / map** (MapLibre GL JS v5, which has globe projection, on free **OpenFreeMap** vector tiles,
  with no API key and no self-hosted tiles). Pins cluster as you zoom out; a **heatmap** toggle shows where ideas
  pile up, and pin colour shows category.
- **Hotspots panel.** A ranked list such as "🔥 Portugal — 9 ideas (4 food, 3 coast, 2 city), both
  ❤️ on 5, best Apr–Jun". This is the "time to plan a trip here" signal.
- **Inbox / list.** Newest first, filterable by category, country, month, who saved it and status
  (`someday → shortlist → planned → done`, or `dismissed`).
- **Idea card.** Archived thumbnail, original link, summary, places on a mini-map, notes, hearts
  and a *Chat about this* button.

### 4.4 Refine: chat

Two complementary surfaces:

- **In-app chat**, per idea or per destination. Claude gets tools: `search_ideas`, `get_idea`,
  `update_idea`, `add_place`, `merge_places`, `set_status`, plus Anthropic's server-side **web search** for
  "when's the best time for X / is it doable in 5 days". Use it for quick refinements: "add the
  restaurants from this list", "what else is near Kaş?".
- **An MCP connector for the Claude app.** The same tools are exposed as a remote MCP server behind
  Cloudflare Access managed OAuth. Long "plan our spring" brainstorms then run in the Claude app on a
  Claude subscription and write their results back into Wander, without spending API credit.

### 4.5 Nice touches (cheap and delightful)

- **Seasonal nudges** via push notification (ntfy). A monthly push might read: "4 of your ideas are best in
  March–April: Cappadocia balloons, Japan sakura, Sevilla Feria, Lycian Way. Plan one?"
- **"Both ❤️" filter.** It narrows the pool to what both people want, which is where shared trips actually come from.
- **Re-enrich.** The prompt or model will improve, so any item (or all of them) can be reprocessed
  from its archived raw input.

### 4.6 Backfill: rescue ideas that are already scattered

| Source | How |
|---|---|
| **WhatsApp chat** | Chat → *Export chat* (without media) gives a `.txt`. Every link is pulled out, and Claude keeps the travel-related text messages ("let's go to Georgia next year"). |
| **TikTok** | *Settings → Download your data* (JSON) includes **Favorites** and **Liked** video links. |
| **Instagram** | *Accounts Centre → Download your information* (JSON) includes **saved posts and collections**. |

Imports run through the **Message Batches API at 50% off**, are rate-limited so Instagram doesn't
flag the parsing account, and all land in a review tray at first.

### 4.7 Look and feel: a real design language, not a basic UI

Wander should have **wow factor**: an aesthetic, distinctive interface with a **well-defined design
language** (type scale, colour and theme tokens, spacing, motion, iconography, map styling, and how
cards, pins and the globe all feel like one product). A plain utility UI isn't the goal. The Phase 0
shell is deliberately throwaway plumbing, not the design.

This gets its own research step, **Phase 1a**, before any Phase 1 screen is built:
- explore visual directions (moodboards of travel and map products, editorial vs. playful vs. "atlas" styles);
- choose the UI tech stack to suit (component library or headless primitives, a motion library,
  MapLibre style authoring for a custom map look, fonts);
- look for Claude skills and tooling for UI design work;
- end with a short design-system doc (tokens + key screens), approved before building.

### 4.8 Out of scope for now (the obvious next step)

**Trips.** Promote a hotspot to a *Trip*, pull its ideas in, and have Claude draft a day-by-day
itinerary with dates, a budget and bookings. The data model already allows for it, but nothing gets built
until v1 has been lived with for a while.

## 5. Architecture

### 5.1 Stack

| Layer | Choice | Why |
|---|---|---|
| Backend | **Python 3.13 + FastAPI** | `yt-dlp`, `faster-whisper` and the Anthropic SDK are native Python, and FastAPI is small and typed |
| Worker | Same image, second process (`python -m app.worker`) polling a jobs table | No Redis or broker. One worker is plenty for two people |
| DB | **SQLite (WAL)** on a data volume | One file, trivially backed up, more than enough for two users. Places carry lat/lng columns, and spatial work happens in Python or on the client. Postgres + PostGIS only if this ever hurts |
| Frontend | **React + Vite + TypeScript** PWA (`vite-plugin-pwa`) with MapLibre; UI system chosen in Phase 1a | Large ecosystem, and served as static files by FastAPI, so it's still one container |
| AI | Anthropic Python SDK, structured outputs, prompt caching | See §6 |
| Media | `yt-dlp`, `ffmpeg`, `faster-whisper` (`small`, int8, CPU) | All local and free |
| Geocoding | Nominatim / Photon (public) | Free at this volume, with Google Places as a later swap if quality disappoints |
| Map tiles | OpenFreeMap | Free, no key. Self-hosted PMTiles would cost about 100 GB, so no |

### 5.2 Data model (v1)

```
users(id, email, display_name)                      -- keyed by the Access login email
captures(id, user_id, kind[text|url|image|voice|import], raw_text, url,
         file_path, source_app, status[queued|processing|done|needs_review|failed],
         error, created_at)
media(id, capture_id, platform, author, caption, transcript, location_tag,
      thumbnail_path, keyframe_paths[], video_path, fetched_at)
ideas(id, capture_id, title, summary, category, tags[], best_months[],
      budget_level, trip_length_hint, status[someday|shortlist|planned|done|dismissed],
      notes, created_by, created_at, ai_model, ai_confidence)
places(id, name, type, lat, lng, country_code, region, city, osm_id, geocoder, created_at)
idea_places(idea_id, place_id, role[primary|mentioned])
hearts(idea_id, user_id)
conversations(id, scope[idea|place|region|global], scope_id, created_by)
messages(id, conversation_id, role, content_json, created_at)
jobs(id, kind, payload_json, status, attempts, run_after, last_error)
-- later: trips(id, name, region, start, end), trip_items(...)
```

### 5.3 Deployment

Wander is designed to self-host on a small, always-on Docker box (a low-power mini PC is plenty):

- **One image, two containers**: `wander-api` (the default command) and `wander-worker`
  (`python -m app.worker`), sharing one data volume (`/data`: the SQLite file plus media), owned by UID 1000.
  Memory caps of about 512 MB (API) and 1.5 GB (worker, because Whisper is the expensive part) are ample.
- **The image** is built and pushed by GitHub Actions to `ghcr.io/cankaratepe23/wander:sha-<short>`. Deployments
  pin a tag and bump it on purpose.
- **Configuration** is `WANDER_*` environment variables (see `backend/app/config.py`). The secret ones (the
  Anthropic key, Instagram cookies) belong in an encrypted store on the host side, never in this repo.
- **Backups.** The app writes a nightly `sqlite3 .backup` copy beside the live DB, so a filesystem snapshot
  always holds a consistent file. Archived videos are capped (`VIDEO_ARCHIVE_MAX_GB`, default 5).
- **No ports are published.** A Cloudflare Tunnel connector reaches the API over a private Docker network.

### 5.4 Access: public behind Cloudflare Access

**Decided 2026-11-07: public behind Cloudflare Tunnel + Access, not VPN-only.** Three facts decide it:

1. **Capture must never fail quietly.** A share made on mobile data while a VPN client happens to have
   dropped is exactly the idea that gets lost. Mobile OSes suspend VPN apps in the background now and then,
   and not every user wants one installed.
2. **The iOS Shortcut and the MCP connector both need a public HTTPS endpoint.** The MCP is called
   from Anthropic's cloud, and Access's managed OAuth handles its sign-in.
3. **No auth code in the app.** Access does the login (a one-time PIN to an allowed email, with 30-day sessions),
   and the app only validates the `Cf-Access-Jwt-Assertion` JWT against the team's public keys, checks the
   audience, and reads the email. An app-side email allow-list backs up the Access policy.

| Hostname | Access policy | Purpose |
|---|---|---|
| `wander.comaristan.com` | Allow: the two users' emails (OTP, 30-day session), plus a **Service Auth** policy for the iOS Shortcut's service token | PWA + API |
| `wander-mcp.comaristan.com` | Managed OAuth (Claude's callback only), the two users' emails | MCP connector (Phase 3) |

Each Access application is created *before* its DNS record, so the hostname is never reachable unprotected.

## 6. AI usage and cost

Prices are current Anthropic list prices per million tokens (input / output): **Opus 5.5 $4 / $20**,
**Sonnet 5.5 $2 / $10**, **Haiku 5.5 $0.10 / $0.50**. Web search costs about $10 per 1,000 searches.

| Task | Tokens (rough) | Opus 5.5 | Sonnet 5.5 | Haiku 5.5 |
|---|---|---|---|---|
| Enrich one capture (prompt + caption/transcript + 4 keyframes ≈ 8k in, ~2k out incl. thinking) | 10k | ~$0.07 | ~$0.04 | ~$0.002 |
| One chat turn (~10k context in, ~1k out) | 11k | ~$0.06 | ~$0.03 | ~$0.0015 |
| **Typical month**: 100 captures + 150 chat turns | | **~$16** | ~$8 | ~$0.40 |
| **One-off backfill**: 1,500 imported items, Batch API (−50%) | | ~$50 | ~$27 | ~$1.50 |

**Default: Opus 5.5 everywhere**, at `low` effort for enrichment and `medium` for chat. The model is a single
config value per task (`ENRICH_MODEL`, `CHAT_MODEL`), so it can be changed in one line. The backfill is the
only budget-sensitive job: run it on Sonnet 5.5 or spread it over two months. Heavy brainstorming goes
through the MCP connector, which costs no API credit.

Guard rails:
- A **dedicated Console workspace and API key** with its own **monthly spend limit**.
- The app logs `usage` per call and shows "this month: $x.xx" in settings.
- Prompt caching on the fixed system prompt and schema, and structured outputs instead of "please return JSON".

## 7. Risks and mitigations

| Risk | Likelihood | Mitigation |
|---|---|---|
| **Instagram blocks anonymous fetching.** `yt-dlp` usually needs logged-in cookies | High | Cookies from a **dedicated throwaway account**, rate limiting, and fallback to `og:` tags, then a screenshot or "paste the caption". The capture itself never fails |
| TikTok or `yt-dlp` breakage after platform changes | Medium | Pin `yt-dlp` but bump it often, and if extraction fails the item still lands in *Needs a look* with its link |
| Platform action against the cookie account | Low–medium | It's a throwaway account, never a personal one |
| Wrong place picked ("Georgia", the country or the US state?) | Medium | Confidence threshold → *Needs a look*, plus a one-tap "wrong place" fix and re-geocode |
| Public endpoint exposure | Low | Access in front, no published ports, JWT verified in the app, service token scoped to `/api/capture` |
| Whisper too slow on low-power hardware | Low | It's asynchronous anyway. Use `base` instead of `small`, or skip audio when caption + keyframes already gave a confident place |
| API credit exhaustion | Low | Workspace spend limit, and capture keeps working without AI (items queue until the next cycle) |

## 8. Implementation plan

Each phase ends with something both users use, and nothing after Phase 1 blocks capture.

### Phase 0 — Skeleton & plumbing ✅ done 2026-11-07
- Repo layout: `backend/` (FastAPI, worker, Alembic migrations), `frontend/` (Vite React PWA shell),
  a multi-stage `Dockerfile`, `docker-compose.dev.yml`, CI to GHCR.
- Access JWT middleware (`Cf-Access-Jwt-Assertion` → user), with a dev mode that is refused when Access is configured.
- Jobs table and worker loop with retries, backoff and stale-job recovery.
- Deployment: tunnel route, Access app (created *before* the DNS record), pinned image, encrypted secrets.
- **Done when:** the deployed page greets its user after an Access login, from a phone on mobile data.

### Phase 1a — Design language (before any Phase 1 UI, see §4.7)
- Research visual directions, the UI stack and Claude design skills, then write a design-system doc.
- **Done when:** one direction, its tokens and mockups of the capture, map and idea-card screens are approved.

### Phase 1 — Never lose an idea (MVP)
- Quick box (text / link / image), with `POST /api/capture` returning in under 300 ms.
- PWA manifest, service worker, offline capture queue, **Android share target**.
- **iOS Shortcut** plus the Access service-token policy on `/api/capture`, with a short setup guide.
- Enrichment v1: text + link metadata (`yt-dlp --dump-json` for TikTok/Shorts captions, `og:` tags
  for web pages) + screenshot vision → Claude structured output → Nominatim geocoding → dedupe.
  Instagram links that can't be read without cookies go to *Needs a look* until Phase 2.
- List view, idea card, edit, *Needs a look* tray, hearts, statuses.
- Map view: clustered pins with category colours (globe projection comes in Phase 3).
- **Done when:** at least 10 real posts from TikTok, Instagram and WhatsApp have been shared in, and
  every one is either filed on the map or waiting in *Needs a look*.

### Phase 2 — Deep parsing
- `yt-dlp` metadata and media download (TikTok, Instagram with the throwaway account's cookies, YouTube Shorts).
  Before writing the Instagram path, check `instaloader` as a fallback. It is Instagram-specific and
  exposes a post's **location tag with coordinates**, which `yt-dlp` doesn't always surface. Use it for
  that field only if it is still maintained.
- `ffmpeg` keyframes → vision, and `faster-whisper` transcripts.
- Local archive: thumbnail, keyframes, caption, transcript, plus the original video (≤ 720p,
  `yt-dlp -f "best[height<=720]"`) under a total size cap that deletes the oldest videos first.
- *Re-enrich* button and "re-enrich all".
- **Done when:** a voice-over-only TikTok, with no place in the caption, gets the right place.

### Phase 3 — Hotspots & chat
- Region/city aggregation, heat score, Hotspots panel, heatmap layer, globe view.
- In-app chat (per idea or destination) with tools and web search, streamed, with usage logging.
- **MCP server** (`/mcp`, streamable HTTP, same tool set) behind `wander-mcp.comaristan.com`.
- **Done when:** "what do we have around the Aegean coast?" works both in the app and in the Claude app.

### Phase 4 — Backfill & nudges
- Importers for the WhatsApp `.txt`, the TikTok data JSON and the Instagram data JSON → Batch API → review tray.
- Monthly seasonal nudge via ntfy.
- **Done when:** an old chat history's travel links are all on the map.

### Phase 5 — Trips (later, separate plan)
Promote a hotspot to a trip, then itinerary drafting, dates and budget.

## 9. Decisions (2026-11-07)

1. **Name: Wander**, at `wander.comaristan.com`, with the MCP at `wander-mcp.comaristan.com`.
2. **UI language: English only.** Captions and transcripts in any language are still read; summaries come out in English.
3. **Public behind Cloudflare Access** (§5.4), reached through a shared tunnel connector.
4. **Instagram: a dedicated throwaway account** supplies the cookies for `yt-dlp`.
5. **Video archiving: keep originals, capped** (`VIDEO_ARCHIVE_MAX_GB`, default 5, oldest first; ≤ 720p).
   Thumbnails, keyframes, caption and transcript are always kept.
6. **The repository is public** (a portfolio project). It holds no secrets and no deployment-specific
   internals; those live in the operator's private ops repo.
7. **The UI gets a real design language** (§4.7), researched in Phase 1a before Phase 1 screens are built.

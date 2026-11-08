"""The enrichment pipeline (PLAN.md §4.2): signals → Claude → geocode → dedupe → an idea on the map.

``run`` is what the worker's ``enrich_capture`` job calls. Collaborators are passed in, so tests can
swap the network-facing parts for fakes. Anything uncertain lands in *Needs a look* with a note;
nothing is dropped, and the capture's raw input is never changed.
"""

import logging
import shutil
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import geocode, sources, understand
from app.config import Settings
from app.models import Capture, Idea, IdeaPlace, Media
from app.sources import Signals
from app.understand import Understanding

log = logging.getLogger("wander.enrich")

PLACE_CONFIDENCE = 0.5
IDEA_CONFIDENCE = 0.4


@dataclass
class Deps:
    gather: Callable[[str | None, Settings, Path], Signals] = sources.gather
    deepen: Callable[[Signals, Settings, Path], None] | None = (
        None  # Phase 2: keyframes, transcript
    )
    understand: Callable[..., Understanding] = understand.understand
    geocoder: Callable[[str, Settings], geocode.Hit | None] = geocode.nominatim
    notes: list[str] = field(default_factory=list)


def media_dir(settings: Settings, capture_id: int) -> Path:
    return settings.media_dir / str(capture_id)


def rel(settings: Settings, path: Path | None) -> str | None:
    return path.relative_to(settings.data_dir).as_posix() if path else None


@dataclass
class Prepared:
    signals: Signals
    images: list[Path]


def run(db: Session, capture: Capture, settings: Settings, deps: Deps | None = None) -> Idea | None:
    """The whole pipeline for one capture: read the source, ask Claude, file the idea."""
    deps = deps or Deps()
    prepared = prepare(db, capture, settings, deps)
    if prepared is None:
        return None
    u = deps.understand(db, settings, capture.raw_text, prepared.signals, prepared.images)
    db.commit()  # keep the usage row even if a later step fails
    return apply(db, capture, settings, u, prepared.signals.notes, deps)


def prepare(
    db: Session, capture: Capture, settings: Settings, deps: Deps | None = None
) -> Prepared | None:
    """Steps 1-2: gather signals (and deep-parse videos). Returns None if the capture was parked."""
    deps = deps or Deps()
    capture.status = "processing"
    capture.error = None
    db.commit()

    workdir = media_dir(settings, capture.id)
    workdir.mkdir(parents=True, exist_ok=True)
    signals = deps.gather(capture.url, settings, workdir)
    if deps.deepen and signals.platform in sources.VIDEO_PLATFORMS:
        try:
            deps.deepen(signals, settings, workdir)
        except Exception as exc:  # noqa: BLE001 - deep parsing is a bonus, never a blocker
            signals.notes.append(f"Deep parsing failed ({type(exc).__name__}).")
            log.exception("deep parsing failed for capture %s", capture.id)
    save_media(db, capture, signals, settings)

    images = images_for(capture, settings, signals)
    if not (capture.raw_text or signals.as_prompt().keys() - {"platform", "url"} or images):
        park(db, capture, "Couldn't read anything from this link. " + " ".join(signals.notes))
        return None
    return Prepared(signals, images)


def images_for(capture: Capture, settings: Settings, signals: Signals) -> list[Path]:
    images: list[Path] = []
    if capture.file_path:
        images.append(settings.data_dir / capture.file_path)
    if signals.thumbnail_path:
        images.append(signals.thumbnail_path)
    images.extend(signals.keyframe_paths)
    return images


def signals_from_media(capture: Capture, media: Media | None, settings: Settings) -> Signals:
    """Rebuild a capture's signals from what prepare() stored (used when a batch result arrives)."""
    if media is None:
        return Signals()

    def path(p: str | None) -> Path | None:
        return settings.data_dir / p if p else None

    return Signals(
        platform=media.platform or "text",
        url=capture.url,
        title=media.title,
        caption=media.caption,
        author=media.author,
        location_tag=media.location_tag,
        transcript=media.transcript,
        thumbnail_path=path(media.thumbnail_path),
        keyframe_paths=[p for p in (path(k) for k in media.keyframe_paths or []) if p],
        notes=list(media.notes or []),
    )


def apply(
    db: Session,
    capture: Capture,
    settings: Settings,
    u: Understanding,
    notes: list[str],
    deps: Deps | None = None,
    *,
    imported: bool = False,
) -> Idea | None:
    """Steps 4-5: geocode, dedupe and file the idea; decide whether it needs a look."""
    deps = deps or Deps()
    if not u.is_travel_related:
        if imported:
            # Most of a chat export isn't travel; drop those quietly (the raw input is kept).
            capture.status = "dismissed"
            capture.error = "Not travel-related (from an import)."
            db.commit()
            return None
        return park(
            db, capture, "This doesn't look like a travel idea. Keep it, edit it, or dismiss it."
        )

    notes = list(notes)
    idea = db.scalar(
        select(Idea).where(Idea.capture_id == capture.id)
    )  # re-enrich updates in place
    if idea is None:
        idea = Idea(capture_id=capture.id, created_by=capture.user_id, reviewed=not imported)
        db.add(idea)
    idea.title = u.title
    idea.summary = u.summary
    idea.category = u.category
    idea.tags = u.tags
    idea.best_months = u.best_months
    idea.good_months = u.good_months
    idea.budget_level = u.budget_level
    idea.trip_length_hint = u.trip_length_hint
    idea.ai_model = settings.enrich_model
    idea.ai_confidence = u.confidence
    idea.links.clear()
    db.flush()

    seen: set[int] = set()
    place_problems = False
    for i, guess in enumerate(u.places):
        if guess.confidence < PLACE_CONFIDENCE:
            notes.append(f"Not sure about “{guess.name}”, so it wasn't placed.")
            place_problems = True
            continue
        hit = deps.geocoder(guess.query, settings)
        if hit is None and guess.query != f"{guess.name}, {guess.country}":
            hit = deps.geocoder(f"{guess.name}, {guess.country}", settings)
        if hit is None:
            notes.append(f"Couldn't find “{guess.name}” on the map.")
            place_problems = True
            continue
        place = geocode.find_or_create(db, hit, guess.name, guess.type)
        if place.id in seen:
            continue
        seen.add(place.id)
        idea.links.append(IdeaPlace(place=place, role="primary" if i == 0 else "mentioned"))

    if not idea.links and u.places:
        notes.append("No place could be put on the map.")
    elif not u.places:
        notes.append("No place was named, so it isn't on the map yet.")
    if u.confidence < IDEA_CONFIDENCE:
        notes.append("Claude wasn't confident about this one.")

    needs_look = not idea.links or u.confidence < IDEA_CONFIDENCE or place_problems
    capture.status = "needs_review" if needs_look else "done"
    capture.error = " ".join(dict.fromkeys(notes)) or None
    db.commit()
    log.info(
        "capture %s → idea %s (%s, %d places)", capture.id, idea.id, capture.status, len(idea.links)
    )
    return idea


def park(db: Session, capture: Capture, note: str) -> None:
    capture.status = "needs_review"
    capture.error = note.strip()
    db.commit()
    return None


def save_media(db: Session, capture: Capture, s: Signals, settings: Settings) -> None:
    if s.platform == "text":
        return
    media = db.scalar(select(Media).where(Media.capture_id == capture.id)) or Media(
        capture_id=capture.id
    )
    media.platform = s.platform
    media.author = s.author
    media.title = s.title
    media.caption = s.caption or s.description
    media.transcript = s.transcript or media.transcript
    media.location_tag = s.location_tag
    media.thumbnail_path = rel(settings, s.thumbnail_path) or media.thumbnail_path
    media.keyframe_paths = (
        [rel(settings, p) for p in s.keyframe_paths] or media.keyframe_paths or []
    )
    media.notes = s.notes
    if s.video_path and s.video_path.is_file():
        media.video_path = rel(settings, s.video_path)
        media.video_bytes = s.video_path.stat().st_size
    db.add(media)
    db.flush()
    if s.video_path:
        from app import deep

        for gone in deep.prune_videos(settings):
            for row in db.scalars(select(Media).where(Media.video_path == gone)):
                row.video_path = None
                row.video_bytes = None


def forget_media(settings: Settings, capture_id: int) -> None:
    shutil.rmtree(media_dir(settings, capture_id), ignore_errors=True)

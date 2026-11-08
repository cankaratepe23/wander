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

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app import geocode, sources, understand
from app.config import Settings
from app.models import Capture, Heart, Idea, IdeaPlace, Media
from app.sources import Signals
from app.understand import IdeaDraft, Understanding

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
    """Steps 1-2: gather signals (and deep-parse videos). Returns None if the capture needs no Claude call
    (parked, or the same link was already filed)."""
    deps = deps or Deps()
    capture.post_key = capture.post_key or sources.post_key(capture.url)
    if heart_if_filed(db, capture):
        return None
    capture.status = "processing"
    capture.error = None
    db.commit()

    workdir = media_dir(settings, capture.id)
    workdir.mkdir(parents=True, exist_ok=True)
    signals = deps.gather(capture.url, settings, workdir)
    if capture.post_key is None and (key := sources.post_key(signals.final_url)):
        capture.post_key = key  # a short link only shows which post it is once it's resolved
        if heart_if_filed(db, capture):
            forget_media(settings, capture.id)
            return None
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


def already_filed(db: Session, capture: Capture) -> list[Idea]:
    """The ideas already filed from another capture of the same link or the same post."""
    if not capture.url:
        return []
    same = Capture.url == capture.url
    if capture.post_key:
        same = or_(same, Capture.post_key == capture.post_key)
    return list(
        db.scalars(
            select(Idea)
            .join(Capture, Idea.capture_id == Capture.id)
            .where(same, Capture.id != capture.id, Idea.status != "dismissed")
            .order_by(Idea.id)
        )
    )


def heart_if_filed(db: Session, capture: Capture) -> Idea | None:
    """Saved twice (often once by each person): count it as interest in the existing ideas, not a duplicate."""
    same = already_filed(db, capture)
    if not same:
        return None
    for idea in same:
        if db.get(Heart, (idea.id, capture.user_id)) is None:
            db.add(Heart(idea_id=idea.id, user_id=capture.user_id))
    more = f" and {len(same) - 1} more" if len(same) > 1 else ""
    capture.status = "done"
    capture.error = f"Already saved as “{same[0].title}”{more}, so it was hearted for you instead."
    db.commit()
    return same[0]


def images_for(capture: Capture, settings: Settings, signals: Signals) -> list[Path]:
    images: list[Path] = []
    if capture.file_path:
        images.append(settings.data_dir / capture.file_path)
    if signals.thumbnail_path:
        images.append(signals.thumbnail_path)
    images.extend(signals.keyframe_paths)
    return list(dict.fromkeys(images))


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
    """Steps 4-5: geocode, dedupe and file the capture's ideas, and decide whether it needs a look.

    Returns the first idea. A capture filed again updates its ideas in place, in order.
    """
    deps = deps or Deps()
    if not u.is_travel_related or not u.ideas:
        if imported:
            # Most of a chat export isn't travel; drop those quietly (the raw input is kept).
            capture.status = "dismissed"
            capture.error = "Not travel-related (from an import)."
            db.commit()
            return None
        return park(
            db, capture, "This doesn't look like a travel idea. Keep it, edit it, or dismiss it."
        )

    existing = list(db.scalars(select(Idea).where(Idea.capture_id == capture.id).order_by(Idea.id)))
    # Another copy may have been filed while this one waited, as happens within a batch.
    if not existing and (same := heart_if_filed(db, capture)):
        return same

    notes = list(notes)
    filed: list[Idea] = []
    needs_look = False
    for n, draft in enumerate(u.ideas):
        if n < len(existing):
            idea = existing[n]
        else:
            idea = Idea(capture_id=capture.id, created_by=capture.user_id, reviewed=not imported)
            db.add(idea)
        label = f"“{draft.title}”: " if len(u.ideas) > 1 else ""
        needs_look |= file_idea(db, idea, draft, settings, deps, notes, label)
        filed.append(idea)
    for stale in existing[len(u.ideas) :]:  # a re-read found fewer; keep any someone has acted on
        if stale.status == "someday" and not stale.hearts and not stale.notes:
            db.delete(stale)

    capture.status = "needs_review" if needs_look else "done"
    capture.error = " ".join(dict.fromkeys(notes)) or None
    db.commit()
    log.info("capture %s → %d ideas (%s)", capture.id, len(filed), capture.status)
    return filed[0]


def file_idea(
    db: Session,
    idea: Idea,
    draft: IdeaDraft,
    settings: Settings,
    deps: Deps,
    notes: list[str],
    label: str,
) -> bool:
    """Fill one idea from Claude's draft and place it on the map. True if it needs a look."""
    idea.title = draft.title
    idea.summary = draft.summary
    idea.category = draft.category
    idea.tags = draft.tags
    idea.best_months = draft.best_months
    idea.good_months = draft.good_months
    idea.budget_level = draft.budget_level
    idea.trip_length_hint = draft.trip_length_hint
    idea.ai_model = settings.enrich_model
    idea.ai_confidence = draft.confidence
    idea.links.clear()
    db.flush()

    seen: set[int] = set()
    place_problems = False
    for i, guess in enumerate(draft.places):
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

    if not idea.links and draft.places:
        notes.append(f"{label}No place could be put on the map.")
    elif not draft.places:
        notes.append(f"{label}No place was named, so it isn't on the map yet.")
    if draft.confidence < IDEA_CONFIDENCE:
        notes.append(f"{label}Claude wasn't confident about this one.")
    return not idea.links or draft.confidence < IDEA_CONFIDENCE or place_problems


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

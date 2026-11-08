"""Ideas, places, hearts, the map, re-enrichment and usage: the API behind Inbox, Globe and the idea card."""

from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app import ai, geocode, jobs
from app.auth import current_user, get_db
from app.config import Settings
from app.models import Capture, Heart, Idea, IdeaPlace, Media, User
from app.schemas import IdeaOut, PlaceOut
from app.taxonomy import CATEGORIES, family_of

router = APIRouter(prefix="/api")

STATUSES = ("someday", "shortlist", "planned", "done", "dismissed")


def settings_of(request: Request) -> Settings:
    return request.app.state.settings


MAX_IDEAS = 5000


def load_ideas(db: Session, limit: int = MAX_IDEAS, idea_id: int | None = None) -> list[Idea]:
    query = (
        select(Idea)
        .options(
            joinedload(Idea.creator),
            joinedload(Idea.links).joinedload(IdeaPlace.place),
            joinedload(Idea.hearts),
        )
        .order_by(Idea.created_at.desc(), Idea.id.desc())
    )
    if idea_id is not None:
        query = query.where(Idea.id == idea_id)
    return list(db.scalars(query.limit(max(1, min(limit, MAX_IDEAS)))).unique())


def names_of(db: Session) -> dict[int, str]:
    return {u.id: u.display_name for u in db.scalars(select(User))}


def idea_out(db: Session, idea: Idea, me: User, names: dict[int, str]) -> IdeaOut:
    capture = db.get(Capture, idea.capture_id) if idea.capture_id else None
    media = (
        db.scalar(select(Media).where(Media.capture_id == idea.capture_id))
        if idea.capture_id
        else None
    )
    return IdeaOut(
        id=idea.id,
        capture_id=idea.capture_id,
        title=idea.title,
        summary=idea.summary,
        category=idea.category,
        family=family_of(idea.category),
        tags=idea.tags or [],
        best_months=idea.best_months or [],
        good_months=idea.good_months or [],
        budget_level=idea.budget_level,
        trip_length_hint=idea.trip_length_hint,
        status=idea.status,
        notes=idea.notes,
        created_by=idea.creator.display_name,
        created_at=idea.created_at,
        places=[PlaceOut.model_validate(link.place) for link in idea.links],
        hearted_by=sorted(names.get(h.user_id, "?") for h in idea.hearts),
        hearted_by_me=any(h.user_id == me.id for h in idea.hearts),
        source_url=capture.url if capture else None,
        source_platform=media.platform if media else None,
        thumbnail=f"/api/media/{idea.capture_id}/thumb" if media and media.thumbnail_path else None,
        has_video=bool(media and media.video_path),
        reviewed=idea.reviewed,
    )


def one(db: Session, idea_id: int, me: User) -> IdeaOut:
    db.expire_all()
    found = load_ideas(db, 1, idea_id)
    if not found:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no such idea")
    return idea_out(db, found[0], me, names_of(db))


@router.get("/ideas", response_model=list[IdeaOut])
def list_ideas(
    limit: int = MAX_IDEAS, user: User = Depends(current_user), db: Session = Depends(get_db)
) -> list[IdeaOut]:
    names = names_of(db)
    return [idea_out(db, i, user, names) for i in load_ideas(db, limit)]


@router.get("/ideas/{idea_id}", response_model=IdeaOut)
def get_idea(
    idea_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)
) -> IdeaOut:
    return one(db, idea_id, user)


class IdeaPatch(BaseModel):
    title: str | None = None
    summary: str | None = None
    category: str | None = None
    status: Literal["someday", "shortlist", "planned", "done", "dismissed"] | None = None
    notes: str | None = None
    best_months: list[int] | None = None
    good_months: list[int] | None = None
    budget_level: int | None = None
    trip_length_hint: str | None = None
    reviewed: bool | None = None


def apply_patch(idea: Idea, patch: IdeaPatch) -> None:
    data = patch.model_dump(exclude_unset=True)
    if "category" in data and data["category"] not in CATEGORIES:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "unknown category")
    if (
        "budget_level" in data
        and data["budget_level"] is not None
        and not 1 <= data["budget_level"] <= 4
    ):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "budget_level is 1-4")
    for key in ("best_months", "good_months"):
        if key in data:
            data[key] = sorted({m for m in data[key] if 1 <= m <= 12})
    if "title" in data and not (data["title"] or "").strip():
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "title can't be empty")
    for key, value in data.items():
        setattr(idea, key, value.strip() if isinstance(value, str) else value)


@router.patch("/ideas/{idea_id}", response_model=IdeaOut)
def patch_idea(
    idea_id: int,
    patch: IdeaPatch,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> IdeaOut:
    idea = db.get(Idea, idea_id)
    if idea is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no such idea")
    apply_patch(idea, patch)
    db.commit()
    return one(db, idea_id, user)


@router.post("/ideas/{idea_id}/heart", response_model=IdeaOut)
def toggle_heart(
    idea_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)
) -> IdeaOut:
    if db.get(Idea, idea_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no such idea")
    existing = db.get(Heart, (idea_id, user.id))
    if existing:
        db.delete(existing)
    else:
        db.add(Heart(idea_id=idea_id, user_id=user.id))
    db.commit()
    return one(db, idea_id, user)


class PlaceIn(BaseModel):
    query: str
    name: str | None = None


@router.post("/ideas/{idea_id}/places", response_model=IdeaOut)
def add_place(
    idea_id: int,
    body: PlaceIn,
    request: Request,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> IdeaOut:
    """The one-tap "wrong place" fix: geocode a new query and attach it."""
    idea = db.get(Idea, idea_id)
    if idea is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no such idea")
    try:
        hit = geocode.nominatim(body.query, settings_of(request))
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, "the geocoder didn't answer, try again"
        ) from exc
    if hit is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"couldn't find “{body.query}”")
    place = geocode.find_or_create(db, hit, body.name or hit.name, "poi")
    if not any(link.place_id == place.id for link in idea.links):
        idea.links.append(IdeaPlace(place=place, role="primary" if not idea.links else "mentioned"))
    db.commit()
    return one(db, idea_id, user)


@router.delete("/ideas/{idea_id}/places/{place_id}", response_model=IdeaOut)
def remove_place(
    idea_id: int, place_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)
) -> IdeaOut:
    link = db.get(IdeaPlace, (idea_id, place_id))
    if link is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "that place isn't on this idea")
    db.delete(link)
    db.commit()
    return one(db, idea_id, user)


@router.get("/map")
def map_points(_user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    """One GeoJSON point per (idea, place). The client clusters them into piles per zoom."""
    features = []
    for idea in load_ideas(db):
        if idea.status == "dismissed" or not idea.reviewed:
            continue
        both = len(idea.hearts) >= 2
        for link in idea.links:
            p = link.place
            features.append(
                {
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": [p.lng, p.lat]},
                    "properties": {
                        "idea_id": idea.id,
                        "place_id": p.id,
                        "name": p.name,
                        "city": p.city or "",
                        "region": p.region or "",
                        "country": p.country or "",
                        "family": family_of(idea.category),
                        "both": 1 if both else 0,
                    },
                }
            )
    return {"type": "FeatureCollection", "features": features}


def requeue(db: Session, capture: Capture) -> None:
    capture.status = "queued"
    capture.error = None
    jobs.enqueue(db, "enrich_capture", {"capture_id": capture.id})


@router.post("/captures/{capture_id}/reenrich", status_code=status.HTTP_202_ACCEPTED)
def reenrich(
    capture_id: int, _user: User = Depends(current_user), db: Session = Depends(get_db)
) -> dict:
    capture = db.get(Capture, capture_id)
    if capture is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no such capture")
    requeue(db, capture)
    db.commit()
    return {"queued": 1}


@router.post("/captures/reenrich-all", status_code=status.HTTP_202_ACCEPTED)
def reenrich_all(_user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    """Re-run enrichment on every capture, e.g. after a better prompt or model (PLAN.md §4.5)."""
    captures = list(db.scalars(select(Capture).where(Capture.status != "dismissed")))
    for capture in captures:
        requeue(db, capture)
    db.commit()
    return {"queued": len(captures)}


@router.post("/captures/{capture_id}/dismiss", status_code=status.HTTP_204_NO_CONTENT)
def dismiss_capture(
    capture_id: int, _user: User = Depends(current_user), db: Session = Depends(get_db)
) -> None:
    """Take a capture out of *Needs a look*. The raw input is kept; it can be re-enriched later."""
    capture = db.get(Capture, capture_id)
    if capture is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no such capture")
    capture.status = "dismissed"
    db.commit()


@router.get("/media/{capture_id}/thumb")
def thumbnail(
    capture_id: int,
    request: Request,
    _user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> FileResponse:
    media = db.scalar(select(Media).where(Media.capture_id == capture_id))
    settings = settings_of(request)
    if media is None or not media.thumbnail_path:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    path = (settings.data_dir / media.thumbnail_path).resolve()
    if not path.is_file() or not path.is_relative_to(Path(settings.data_dir).resolve()):
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    return FileResponse(path, headers={"Cache-Control": "private, max-age=86400"})


@router.get("/usage")
def usage(
    request: Request, _user: User = Depends(current_user), db: Session = Depends(get_db)
) -> dict:
    out = ai.month_to_date(db)
    out["ai_configured"] = settings_of(request).ai_configured
    return out

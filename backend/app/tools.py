"""The tools Claude gets for refining ideas (PLAN.md §4.4), shared by in-app chat and the MCP server.

Each tool has a Pydantic input model (the chat validates every input with it, since streamed tool
inputs aren't validated by the API) and a function that runs it as a given person.
"""

import json
from collections.abc import Callable
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app import geocode, hotspots
from app.config import Settings
from app.models import Idea, IdeaPlace, Place, User
from app.taxonomy import CATEGORIES, family_of

Status = Literal["someday", "shortlist", "planned", "done", "dismissed"]
Category = Literal[tuple(CATEGORIES)]  # type: ignore[valid-type]


def brief(idea: Idea) -> dict[str, Any]:
    return {
        "id": idea.id,
        "title": idea.title,
        "category": idea.category,
        "status": idea.status,
        "places": [
            {
                "place_id": link.place.id,
                "name": link.place.name,
                "region": link.place.region,
                "country": link.place.country,
            }
            for link in idea.links
        ],
        "best_months": idea.best_months,
        "hearts": len(idea.hearts),
    }


def full(idea: Idea, db: Session) -> dict[str, Any]:
    names = {u.id: u.display_name for u in db.scalars(select(User))}
    out = brief(idea)
    out.update(
        summary=idea.summary,
        tags=idea.tags,
        good_months=idea.good_months,
        budget_level=idea.budget_level,
        trip_length_hint=idea.trip_length_hint,
        notes=idea.notes,
        saved_by=idea.creator.display_name,
        hearted_by=sorted(names.get(h.user_id, "?") for h in idea.hearts),
        created_at=idea.created_at.date().isoformat(),
    )
    out["places"] = [
        {"place_id": p.id, "name": p.name, "type": p.type, "city": p.city, "region": p.region,
         "country": p.country, "lat": round(p.lat, 4), "lng": round(p.lng, 4)}
        for p in (link.place for link in idea.links)
    ]  # fmt: skip
    return out


class ToolError(Exception):
    """A problem to report back to Claude as a tool error (not a crash)."""


def _idea(db: Session, idea_id: int) -> Idea:
    idea = db.get(Idea, idea_id)
    if idea is None:
        raise ToolError(f"there is no idea with id {idea_id}")
    return idea


# --- inputs -----------------------------------------------------------------------------------


class SearchIdeas(BaseModel):
    """Search the saved travel ideas. All filters are optional and combine with AND."""

    query: str | None = Field(
        None, description="words to match in titles, summaries, tags, notes and place names"
    )
    country: str | None = Field(None, description="country name in English, e.g. 'Portugal'")
    region: str | None = Field(None, description="region or city name, e.g. 'Antalya' or 'Kyoto'")
    category: str | None = Field(None, description=f"one of: {', '.join(CATEGORIES)}")
    status: Status | None = None
    month: int | None = Field(
        None, description="only ideas that are best or good in this month (1-12)"
    )
    hearted_by_both: bool | None = Field(None, description="only ideas both people have hearted")
    limit: int = Field(25, description="maximum results, up to 60")


class GetIdea(BaseModel):
    """Get everything about one idea."""

    idea_id: int


class UpdateIdea(BaseModel):
    """Change an idea's fields. Only the fields given are changed."""

    idea_id: int
    title: str | None = None
    summary: str | None = None
    notes: str | None = None
    category: str | None = Field(None, description=f"one of: {', '.join(CATEGORIES)}")
    best_months: list[int] | None = None
    good_months: list[int] | None = None
    budget_level: int | None = Field(None, description="1 (cheap) to 4 (luxury)")
    trip_length_hint: str | None = None


class SetStatus(BaseModel):
    """Move an idea along: someday → shortlist → planned → done, or dismissed."""

    idea_id: int
    status: Status


class AddPlace(BaseModel):
    """Find a real place with the geocoder and attach it to an idea."""

    idea_id: int
    query: str = Field(
        description="geocoder query from specific to general, e.g. 'Kaputaş Beach, Kaş, Türkiye'"
    )
    name: str | None = Field(
        None, description="display name, if different from what the geocoder returns"
    )


class RemovePlace(BaseModel):
    """Detach a place from an idea (the place itself stays for other ideas)."""

    idea_id: int
    place_id: int


class MergePlaces(BaseModel):
    """Merge a duplicate place into another: every idea on merge_place_id moves to keep_place_id."""

    keep_place_id: int
    merge_place_id: int


class CreateIdea(BaseModel):
    """Save a new idea, e.g. each restaurant from a list. Places are geocoded."""

    title: str
    summary: str | None = None
    category: str = Field("other", description=f"one of: {', '.join(CATEGORIES)}")
    place_queries: list[str] = Field(
        default_factory=list, description="geocoder queries, e.g. ['Nishiki Market, Kyoto, Japan']"
    )
    best_months: list[int] = Field(default_factory=list)
    notes: str | None = None


class ListHotspots(BaseModel):
    """Where ideas are piling up, ranked by a heat score (ideas, recency, hearts, variety)."""

    level: Literal["country", "region", "city"] = "country"
    limit: int = 10


# --- implementations --------------------------------------------------------------------------


def search_ideas(db: Session, user: User, settings: Settings, a: SearchIdeas) -> Any:
    q = select(Idea).where(Idea.status != "dismissed") if a.status != "dismissed" else select(Idea)
    if a.status:
        q = q.where(Idea.status == a.status)
    if a.category:
        q = q.where(Idea.category == a.category)
    if a.query:
        like = f"%{a.query.lower()}%"
        place_match = select(IdeaPlace.idea_id).join(Place).where(func.lower(Place.name).like(like))
        q = q.where(
            or_(
                func.lower(Idea.title).like(like),
                func.lower(Idea.summary).like(like),
                func.lower(Idea.notes).like(like),
                func.lower(Idea.tags).like(like),
                Idea.id.in_(place_match),
            )
        )
    if a.country or a.region:
        p = select(IdeaPlace.idea_id).join(Place)
        if a.country:
            p = p.where(func.lower(Place.country) == a.country.lower())
        if a.region:
            r = a.region.lower()
            p = p.where(
                or_(
                    func.lower(Place.region) == r,
                    func.lower(Place.city) == r,
                    func.lower(Place.name) == r,
                )
            )
        q = q.where(Idea.id.in_(p))
    ideas = list(db.scalars(q.order_by(Idea.created_at.desc())))
    if a.month:
        ideas = [
            i for i in ideas if a.month in (i.best_months or []) or a.month in (i.good_months or [])
        ]
    if a.hearted_by_both:
        ideas = [i for i in ideas if len(i.hearts) >= 2]
    return {"count": len(ideas), "ideas": [brief(i) for i in ideas[: max(1, min(a.limit, 60))]]}


def get_idea(db: Session, user: User, settings: Settings, a: GetIdea) -> Any:
    return full(_idea(db, a.idea_id), db)


def update_idea(db: Session, user: User, settings: Settings, a: UpdateIdea) -> Any:
    idea = _idea(db, a.idea_id)
    data = a.model_dump(exclude_unset=True, exclude={"idea_id"})
    if "category" in data and data["category"] not in CATEGORIES:
        raise ToolError(f"category must be one of {', '.join(CATEGORIES)}")
    if data.get("budget_level") is not None and not 1 <= data["budget_level"] <= 4:
        raise ToolError("budget_level must be 1-4")
    for key in ("best_months", "good_months"):
        if key in data:
            data[key] = sorted({m for m in data[key] if 1 <= m <= 12})
    for key, value in data.items():
        setattr(idea, key, value)
    db.commit()
    return full(idea, db)


def set_status(db: Session, user: User, settings: Settings, a: SetStatus) -> Any:
    idea = _idea(db, a.idea_id)
    idea.status = a.status
    db.commit()
    return brief(idea)


def _attach(db: Session, idea: Idea, query: str, name: str | None, settings: Settings) -> Place:
    hit = geocode.nominatim(query, settings)
    if hit is None:
        raise ToolError(f"the geocoder found nothing for “{query}”; try a fuller query")
    place = geocode.find_or_create(db, hit, name or hit.name, "poi")
    if not any(link.place_id == place.id for link in idea.links):
        idea.links.append(IdeaPlace(place=place, role="primary" if not idea.links else "mentioned"))
    return place


def add_place(db: Session, user: User, settings: Settings, a: AddPlace) -> Any:
    idea = _idea(db, a.idea_id)
    _attach(db, idea, a.query, a.name, settings)
    db.commit()
    return full(idea, db)


def remove_place(db: Session, user: User, settings: Settings, a: RemovePlace) -> Any:
    link = db.get(IdeaPlace, (a.idea_id, a.place_id))
    if link is None:
        raise ToolError("that place isn't on that idea")
    db.delete(link)
    db.commit()
    return full(_idea(db, a.idea_id), db)


def merge_places(db: Session, user: User, settings: Settings, a: MergePlaces) -> Any:
    keep, gone = db.get(Place, a.keep_place_id), db.get(Place, a.merge_place_id)
    if keep is None or gone is None or keep.id == gone.id:
        raise ToolError("give two different existing place ids")
    moved = 0
    for link in list(db.scalars(select(IdeaPlace).where(IdeaPlace.place_id == gone.id))):
        if db.get(IdeaPlace, (link.idea_id, keep.id)) is None:
            db.add(IdeaPlace(idea_id=link.idea_id, place_id=keep.id, role=link.role))
            moved += 1
        db.delete(link)
    db.flush()
    db.delete(gone)
    db.commit()
    return {"kept": keep.name, "ideas_moved": moved}


def create_idea(db: Session, user: User, settings: Settings, a: CreateIdea) -> Any:
    if a.category not in CATEGORIES:
        raise ToolError(f"category must be one of {', '.join(CATEGORIES)}")
    idea = Idea(
        title=a.title.strip()[:200],
        summary=a.summary,
        category=a.category,
        best_months=sorted({m for m in a.best_months if 1 <= m <= 12}),
        notes=a.notes,
        created_by=user.id,
        ai_model="chat",
    )
    db.add(idea)
    db.flush()
    missing = []
    for query in a.place_queries[:12]:
        try:
            _attach(db, idea, query, None, settings)
        except ToolError:
            missing.append(query)
    db.commit()
    out = full(idea, db)
    if missing:
        out["not_found"] = missing
    return out


def list_hotspots(db: Session, user: User, settings: Settings, a: ListHotspots) -> Any:
    rows = hotspots.load_and_rank(db, a.level, limit=max(1, min(a.limit, 30)))
    for r in rows:
        r.pop("idea_ids", None)
        r.pop("lat", None)
        r.pop("lng", None)
    return rows


Impl = Callable[[Session, User, Settings, Any], Any]
TOOLS: dict[str, tuple[type[BaseModel], Impl, str]] = {
    "search_ideas": (SearchIdeas, search_ideas, "Searching your ideas"),
    "get_idea": (GetIdea, get_idea, "Reading an idea"),
    "update_idea": (UpdateIdea, update_idea, "Updating an idea"),
    "set_status": (SetStatus, set_status, "Changing a status"),
    "add_place": (AddPlace, add_place, "Adding a place"),
    "remove_place": (RemovePlace, remove_place, "Removing a place"),
    "merge_places": (MergePlaces, merge_places, "Merging places"),
    "create_idea": (CreateIdea, create_idea, "Saving a new idea"),
    "list_hotspots": (ListHotspots, list_hotspots, "Ranking hotspots"),
}
WRITES = {"update_idea", "set_status", "add_place", "remove_place", "merge_places", "create_idea"}


def schemas(*, eager: bool) -> list[dict[str, Any]]:
    """Tool definitions for the Messages API, in a fixed order (stable for prompt caching)."""
    out = []
    for name, (model, _fn, _label) in TOOLS.items():
        schema = model.model_json_schema()
        schema.pop("title", None)
        schema.pop("description", None)
        tool = {"name": name, "description": (model.__doc__ or "").strip(), "input_schema": schema}
        if eager:
            tool["eager_input_streaming"] = True
        out.append(tool)
    return out


def run(db: Session, user: User, settings: Settings, name: str, raw: Any) -> tuple[str, bool]:
    """Validate and run one tool call. Returns (JSON result, is_error)."""
    if name not in TOOLS:
        return json.dumps({"error": f"unknown tool {name}"}), True
    model, fn, _label = TOOLS[name]
    try:
        args = model.model_validate(raw if isinstance(raw, dict) else {})
    except ValidationError as exc:
        return json.dumps(
            {
                "INVALID_INPUT": json.dumps(raw, default=str),
                "errors": exc.errors(include_url=False),
            },
            default=str,
        ), True
    try:
        return json.dumps(fn(db, user, settings, args), ensure_ascii=False, default=str), False
    except ToolError as exc:
        db.rollback()
        return json.dumps({"error": str(exc)}), True


def family_note() -> str:
    return "Categories group into colour families: " + "; ".join(
        f"{f}: {', '.join(c for c in CATEGORIES if family_of(c) == f)}"
        for f in ("food", "nature", "stays", "culture")
    )

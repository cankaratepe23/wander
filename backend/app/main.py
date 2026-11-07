"""The Wander API: ``uvicorn --factory app.main:create_app``.

The capture endpoint is the heart of the app: it stores the raw input, enqueues enrichment and
answers immediately. Everything slow happens in the worker (app/worker.py).
"""

import logging
import re
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload
from starlette.datastructures import UploadFile  # what request.form() returns

from app import jobs
from app.auth import AccessVerifier, current_user, get_db
from app.config import Settings, get_settings
from app.db import make_engine, make_sessionmaker
from app.migrate import upgrade_to_head
from app.models import Capture, Heart, Idea, IdeaPlace, User
from app.schemas import CaptureIn, CaptureOut, IdeaOut, Me, PlaceOut
from app.taxonomy import family_of

log = logging.getLogger("wander.api")

URL_RE = re.compile(r"https?://[^\s<>\"']+", re.IGNORECASE)
IMAGE_TYPES = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/gif": ".gif",
    "image/heic": ".heic",
    "image/heif": ".heif",
}


def first_url(text: str | None) -> str | None:
    if not text:
        return None
    match = URL_RE.search(text)
    return match.group(0).rstrip(").,!?;:") if match else None


def to_out(capture: Capture) -> CaptureOut:
    return CaptureOut(
        id=capture.id,
        kind=capture.kind,
        raw_text=capture.raw_text,
        url=capture.url,
        has_file=capture.file_path is not None,
        status=capture.status,
        error=capture.error,
        created_by=capture.user.display_name,
        created_at=capture.created_at,
    )


async def _save_upload(upload: UploadFile, settings: Settings) -> str:
    suffix = IMAGE_TYPES.get((upload.content_type or "").lower())
    if suffix is None:
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "only images are accepted")
    limit = settings.max_upload_mb * 1024 * 1024
    settings.uploads_dir.mkdir(parents=True, exist_ok=True)
    name = f"{uuid.uuid4().hex}{suffix}"
    dest = settings.uploads_dir / name
    size = 0
    try:
        with dest.open("wb") as out:
            while chunk := await upload.read(1024 * 1024):
                size += len(chunk)
                if size > limit:
                    raise HTTPException(
                        status.HTTP_413_CONTENT_TOO_LARGE, f"image over {settings.max_upload_mb} MB"
                    )
                out.write(chunk)
    except BaseException:
        dest.unlink(missing_ok=True)
        raise
    return f"uploads/{name}"


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        upgrade_to_head(settings.db_path)
        if settings.dev_mode:
            log.warning(
                "DEV MODE: authentication is OFF; every request is %s", settings.dev_user_email
            )
        elif not settings.access_configured:
            log.error("Cloudflare Access is not configured; every request will be refused")
        yield

    app = FastAPI(
        title="Wander", lifespan=lifespan, docs_url="/api/docs", openapi_url="/api/openapi.json"
    )
    app.state.settings = settings
    app.state.sessionmaker = make_sessionmaker(make_engine(settings.db_path))
    app.state.access_verifier = (
        AccessVerifier(settings.access_team_domain, settings.access_aud)
        if settings.access_configured
        else None
    )

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/me", response_model=Me)
    def me(user: User = Depends(current_user)) -> Me:
        return Me(email=user.email, display_name=user.display_name)

    @app.post("/api/capture", status_code=status.HTTP_202_ACCEPTED, response_model=CaptureOut)
    async def capture(
        request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)
    ) -> CaptureOut:
        content_type = request.headers.get("content-type", "")
        upload: UploadFile | None = None
        try:
            if content_type.startswith("multipart/form-data"):
                form = await request.form()
                file_field = form.get("file")
                upload = file_field if isinstance(file_field, UploadFile) else None
                data = CaptureIn(
                    text=form.get("text") or None,  # type: ignore[arg-type]
                    url=form.get("url") or None,  # type: ignore[arg-type]
                    source_app=form.get("source_app") or None,  # type: ignore[arg-type]
                )
            else:
                data = CaptureIn.model_validate(await request.json())
        except (ValidationError, ValueError) as exc:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT, "invalid capture body"
            ) from exc

        text = (data.text or "").strip() or None
        url = (data.url or "").strip() or first_url(text)
        if upload is not None and not upload.filename:
            upload = None
        if not (text or url or upload):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "nothing to save")

        file_path = await _save_upload(upload, settings) if upload else None
        kind = "image" if file_path else "url" if url else "text"
        row = Capture(
            user_id=user.id,
            kind=kind,
            raw_text=text,
            url=url,
            file_path=file_path,
            source_app=data.source_app,
        )
        row.user = user
        db.add(row)
        db.flush()
        jobs.enqueue(db, "enrich_capture", {"capture_id": row.id})
        db.commit()
        return to_out(row)

    @app.get("/api/captures", response_model=list[CaptureOut])
    def list_captures(
        limit: int = 50, _user: User = Depends(current_user), db: Session = Depends(get_db)
    ) -> list[CaptureOut]:
        rows = db.scalars(
            select(Capture)
            .options(joinedload(Capture.user))
            .order_by(Capture.created_at.desc(), Capture.id.desc())
            .limit(max(1, min(limit, 200)))
        )
        return [to_out(c) for c in rows]

    def load_ideas(db: Session, limit: int, idea_id: int | None = None) -> list[Idea]:
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
        return list(db.scalars(query.limit(max(1, min(limit, 1000)))).unique())

    @app.get("/api/ideas", response_model=list[IdeaOut])
    def list_ideas(
        limit: int = 200, user: User = Depends(current_user), db: Session = Depends(get_db)
    ) -> list[IdeaOut]:
        names = {u.id: u.display_name for u in db.scalars(select(User))}
        return [idea_out(i, user, names) for i in load_ideas(db, limit)]

    @app.post("/api/ideas/{idea_id}/heart", response_model=IdeaOut)
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
        db.expire_all()
        names = {u.id: u.display_name for u in db.scalars(select(User))}
        return idea_out(load_ideas(db, 1, idea_id)[0], user, names)

    @app.get("/api/map")
    def map_points(_user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
        """One GeoJSON point per (idea, place). The client clusters them into piles per zoom."""
        features = []
        for idea in load_ideas(db, 1000):
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

    if settings.static_dir and Path(settings.static_dir).is_dir():
        _mount_spa(app, Path(settings.static_dir))

    return app


def _mount_spa(app: FastAPI, static_dir: Path) -> None:
    """Serve the built frontend, falling back to index.html for client-side routes."""
    index = static_dir / "index.html"
    if (static_dir / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=static_dir / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str) -> FileResponse:
        if path.startswith("api/"):
            raise HTTPException(status.HTTP_404_NOT_FOUND)
        candidate = (static_dir / path).resolve()
        if path and candidate.is_file() and candidate.is_relative_to(static_dir.resolve()):
            return FileResponse(candidate)
        return FileResponse(index)


def idea_out(idea: Idea, me: User, names: dict[int, str]) -> IdeaOut:
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
        created_by=idea.creator.display_name,
        created_at=idea.created_at,
        places=[PlaceOut.model_validate(link.place) for link in idea.links],
        hearted_by=sorted(names.get(h.user_id, "?") for h in idea.hearts),
        hearted_by_me=any(h.user_id == me.id for h in idea.hearts),
    )

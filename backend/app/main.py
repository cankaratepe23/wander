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

from app import ideas_api, jobs
from app.auth import AccessVerifier, current_user, get_db
from app.config import Settings, get_settings
from app.db import make_engine, make_sessionmaker
from app.migrate import upgrade_to_head
from app.models import Capture, User
from app.schemas import CaptureIn, CaptureOut, Me

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

    app.include_router(ideas_api.router)

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

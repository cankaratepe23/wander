"""Backfill uploads and the monthly nudge preview (PLAN.md §4.5, §4.6)."""

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import backfill, importers, nudges
from app.auth import current_user, get_db
from app.models import Import, User

router = APIRouter(prefix="/api")
MAX_IMPORT_MB = 100


@router.post("/imports", status_code=status.HTTP_202_ACCEPTED)
async def upload_import(
    file: UploadFile, user: User = Depends(current_user), db: Session = Depends(get_db)
) -> dict:
    raw = await file.read(MAX_IMPORT_MB * 1024 * 1024 + 1)
    if len(raw) > MAX_IMPORT_MB * 1024 * 1024:
        raise HTTPException(
            status.HTTP_413_CONTENT_TOO_LARGE, f"exports over {MAX_IMPORT_MB} MB aren't supported"
        )
    try:
        source, items = importers.detect(file.filename or "", raw)
    except importers.UnknownFormat as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    if not items:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, f"no travel links found in that {source} export"
        )
    imp = backfill.create(db, user, source, file.filename, items)
    return backfill.progress(db, imp)


@router.get("/imports")
def list_imports(_u: User = Depends(current_user), db: Session = Depends(get_db)) -> list[dict]:
    return [
        backfill.progress(db, i)
        for i in db.scalars(select(Import).order_by(Import.id.desc()).limit(20))
    ]


@router.post("/nudges/preview")
def nudge_preview(
    request: Request,
    send: bool = False,
    _u: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    settings = request.app.state.settings
    ideas, months = nudges.in_season(db, datetime.now(UTC))
    msg = nudges.message(ideas, months)
    sent = bool(msg and send and nudges.send(settings, *msg))
    return {
        "title": msg[0] if msg else None,
        "body": msg[1] if msg else None,
        "sent": sent,
        "configured": bool(settings.ntfy_url),
    }

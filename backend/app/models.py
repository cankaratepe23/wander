"""Tables: users, captures and jobs (Phase 0); ideas, places, idea_places and hearts (Phase 1)."""

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def utcnow() -> datetime:
    return datetime.now(UTC)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(320), unique=True)
    display_name: Mapped[str] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Capture(Base):
    """The raw input, kept unchanged forever so enrichment can always be redone."""

    __tablename__ = "captures"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    kind: Mapped[str] = mapped_column(String(16))  # text | url | image | voice | import
    raw_text: Mapped[str | None] = mapped_column(Text)
    url: Mapped[str | None] = mapped_column(Text)
    file_path: Mapped[str | None] = mapped_column(Text)  # relative to data_dir
    source_app: Mapped[str | None] = mapped_column(String(32))  # share-target, shortcut, web...
    # queued | processing | done | needs_review | failed
    status: Mapped[str] = mapped_column(String(16), default="queued")
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    user: Mapped[User] = relationship()

    __table_args__ = (Index("ix_captures_created_at", "created_at"),)


class Job(Base):
    """A minimal durable job queue: no Redis, one worker, SQLite serialises the writes."""

    __tablename__ = "jobs"

    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(64))
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    # queued | running | done | failed
    status: Mapped[str] = mapped_column(String(16), default="queued")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=5)
    run_after: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (Index("ix_jobs_claim", "status", "run_after"),)


class Idea(Base):
    """One travel idea, usually understood from a capture by the enrichment pipeline."""

    __tablename__ = "ideas"

    id: Mapped[int] = mapped_column(primary_key=True)
    capture_id: Mapped[int | None] = mapped_column(ForeignKey("captures.id"))
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    title: Mapped[str] = mapped_column(String(200))
    summary: Mapped[str | None] = mapped_column(Text)
    category: Mapped[str] = mapped_column(String(32), default="other")
    tags: Mapped[list[str]] = mapped_column(JSON, default=list)
    best_months: Mapped[list[int]] = mapped_column(JSON, default=list)  # 1-12
    good_months: Mapped[list[int]] = mapped_column(JSON, default=list)
    budget_level: Mapped[int | None] = mapped_column(Integer)  # 1-4 (€ to €€€€)
    trip_length_hint: Mapped[str | None] = mapped_column(String(64))
    # someday | shortlist | planned | done | dismissed
    status: Mapped[str] = mapped_column(String(16), default="someday")
    notes: Mapped[str | None] = mapped_column(Text)
    ai_model: Mapped[str | None] = mapped_column(String(64))
    ai_confidence: Mapped[float | None] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    creator: Mapped[User] = relationship()
    links: Mapped[list["IdeaPlace"]] = relationship(
        back_populates="idea", cascade="all, delete-orphan"
    )
    hearts: Mapped[list["Heart"]] = relationship(cascade="all, delete-orphan")

    __table_args__ = (Index("ix_ideas_created_at", "created_at"),)


class Place(Base):
    """A geocoded place. Coordinates always come from a geocoder, never from the model."""

    __tablename__ = "places"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    # country | region | city | poi | restaurant | hotel | activity
    type: Mapped[str] = mapped_column(String(16), default="poi")
    lat: Mapped[float] = mapped_column(Float)
    lng: Mapped[float] = mapped_column(Float)
    country_code: Mapped[str | None] = mapped_column(String(2))
    country: Mapped[str | None] = mapped_column(String(100))
    region: Mapped[str | None] = mapped_column(String(100))
    city: Mapped[str | None] = mapped_column(String(100))
    osm_id: Mapped[str | None] = mapped_column(String(32), unique=True)
    geocoder: Mapped[str | None] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class IdeaPlace(Base):
    __tablename__ = "idea_places"

    idea_id: Mapped[int] = mapped_column(ForeignKey("ideas.id"), primary_key=True)
    place_id: Mapped[int] = mapped_column(ForeignKey("places.id"), primary_key=True)
    role: Mapped[str] = mapped_column(String(16), default="primary")  # primary | mentioned

    idea: Mapped[Idea] = relationship(back_populates="links")
    place: Mapped[Place] = relationship()


class Heart(Base):
    __tablename__ = "hearts"

    idea_id: Mapped[int] = mapped_column(ForeignKey("ideas.id"), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), primary_key=True)

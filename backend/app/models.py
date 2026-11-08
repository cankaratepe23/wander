"""Tables: users, captures and jobs (Phase 0); ideas, places, idea_places, hearts, media and ai_usage
(Phase 1-2); conversations and messages (Phase 3)."""

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
    # One post's identity across its link forms ("tiktok:<id>"), so repeat saves can be spotted.
    post_key: Mapped[str | None] = mapped_column(String(64))
    file_path: Mapped[str | None] = mapped_column(Text)  # relative to data_dir
    source_app: Mapped[str | None] = mapped_column(String(32))  # share-target, shortcut, web...
    # queued | processing | done | needs_review | failed
    status: Mapped[str] = mapped_column(String(16), default="queued")
    error: Mapped[str | None] = mapped_column(Text)
    # Backfill (PLAN.md §4.6): imported captures are read cheaply first, then sent in a batch.
    import_id: Mapped[int | None] = mapped_column(ForeignKey("imports.id"))
    prepared_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    batch_id: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    user: Mapped[User] = relationship()

    __table_args__ = (
        Index("ix_captures_created_at", "created_at"),
        Index("ix_captures_post_key", "post_key"),
    )


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
    # False for ideas from an import until someone keeps them (the review tray).
    reviewed: Mapped[bool] = mapped_column(default=True, server_default="1")
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


class Import(Base):
    """One uploaded export (a WhatsApp chat, TikTok or Instagram data) being backfilled."""

    __tablename__ = "imports"

    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(16))  # whatsapp | tiktok | instagram
    filename: Mapped[str | None] = mapped_column(String(255))
    total: Mapped[int] = mapped_column(Integer, default=0)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Media(Base):
    """What was extracted from a capture's link: caption, transcript and archived files."""

    __tablename__ = "media"

    id: Mapped[int] = mapped_column(primary_key=True)
    capture_id: Mapped[int] = mapped_column(ForeignKey("captures.id"), unique=True)
    platform: Mapped[str | None] = mapped_column(String(32))
    author: Mapped[str | None] = mapped_column(String(200))
    title: Mapped[str | None] = mapped_column(Text)
    caption: Mapped[str | None] = mapped_column(Text)
    transcript: Mapped[str | None] = mapped_column(Text)
    location_tag: Mapped[str | None] = mapped_column(String(200))
    thumbnail_path: Mapped[str | None] = mapped_column(Text)  # relative to data_dir
    keyframe_paths: Mapped[list[str]] = mapped_column(JSON, default=list)
    video_path: Mapped[str | None] = mapped_column(Text)
    video_bytes: Mapped[int | None] = mapped_column(Integer)
    notes: Mapped[list[str]] = mapped_column(JSON, default=list)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AiUsage(Base):
    """One row per Claude call, so the app can show what this month has cost."""

    __tablename__ = "ai_usage"

    id: Mapped[int] = mapped_column(primary_key=True)
    task: Mapped[str] = mapped_column(String(32))  # enrich | chat | import
    model: Mapped[str] = mapped_column(String(64))
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cache_read_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cache_write_tokens: Mapped[int] = mapped_column(Integer, default=0)
    web_searches: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    batch: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (Index("ix_ai_usage_created_at", "created_at"),)


class Conversation(Base):
    """A chat thread, scoped to an idea, a place, a region or everything."""

    __tablename__ = "conversations"

    id: Mapped[int] = mapped_column(primary_key=True)
    scope: Mapped[str] = mapped_column(
        String(16), default="global"
    )  # idea | place | region | global
    scope_id: Mapped[str | None] = mapped_column(String(100))
    title: Mapped[str | None] = mapped_column(String(200))
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    messages: Mapped[list["Message"]] = relationship(
        back_populates="conversation", cascade="all, delete-orphan", order_by="Message.id"
    )


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    conversation_id: Mapped[int] = mapped_column(ForeignKey("conversations.id"))
    role: Mapped[str] = mapped_column(String(16))  # user | assistant
    # The API's content blocks, stored as-is so the conversation can be replayed exactly.
    content: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    conversation: Mapped[Conversation] = relationship(back_populates="messages")

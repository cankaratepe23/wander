"""API request/response shapes."""

from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict, field_serializer


class Me(BaseModel):
    email: str
    display_name: str


class CaptureIn(BaseModel):
    text: str | None = None
    url: str | None = None
    source_app: str | None = None


class CaptureOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    kind: str
    raw_text: str | None
    url: str | None
    has_file: bool
    status: str
    error: str | None
    created_by: str
    created_at: datetime

    @field_serializer("created_at")
    def _utc(self, value: datetime) -> str:
        # SQLite hands datetimes back naive; they are always stored in UTC.
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return value.isoformat()


class PlaceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    type: str
    lat: float
    lng: float
    country_code: str | None
    country: str | None
    region: str | None
    city: str | None


class IdeaOut(BaseModel):
    id: int
    capture_id: int | None
    title: str
    summary: str | None
    category: str
    family: str
    tags: list[str]
    best_months: list[int]
    good_months: list[int]
    budget_level: int | None
    trip_length_hint: str | None
    status: str
    notes: str | None = None
    created_by: str
    created_at: datetime
    places: list[PlaceOut]
    hearted_by: list[str]
    hearted_by_me: bool
    source_url: str | None = None
    source_platform: str | None = None
    thumbnail: str | None = None
    has_video: bool = False
    reviewed: bool = True

    @field_serializer("created_at")
    def _utc(self, value: datetime) -> str:
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return value.isoformat()

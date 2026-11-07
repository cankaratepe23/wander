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

"""Runtime settings, read from WANDER_* environment variables (or a local .env file)."""

from functools import lru_cache
from pathlib import Path

from pydantic import AliasChoices, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # str_strip_whitespace: values written on Windows often carry a trailing "\r", which would
    # otherwise end up inside URLs (e.g. the Access certs URL) and fail in confusing ways.
    model_config = SettingsConfigDict(
        env_prefix="WANDER_", env_file=".env", extra="ignore", str_strip_whitespace=True
    )

    # Where the SQLite database and uploaded/archived media live (/data in the container).
    data_dir: Path = Path("./data")

    # Cloudflare Access. Both must be set in production; requests are then authenticated by
    # validating the Cf-Access-Jwt-Assertion JWT against the team's public keys.
    access_team_domain: str = ""  # e.g. "yourteam.cloudflareaccess.com"
    access_aud: str = ""  # the Access application's AUD tag; comma-separate several (app, MCP)

    # Comma-separated emails allowed in. Access already enforces this; the app checks again so a
    # misconfigured Access policy can't silently open it up. Empty = trust Access alone.
    allowed_emails: str = ""

    # Access service tokens allowed to save captures (the iOS Shortcut), each mapped to the person it
    # saves for: "<client id>=<email>,<client id>=<email>". Service tokens can do nothing else.
    service_tokens: str = ""

    # Local development only: skip Access and treat every request as dev_user_email.
    # Refused at startup when Access is configured, so it can't be left on in production.
    dev_mode: bool = False
    dev_user_email: str = "dev@localhost"

    # Built SPA to serve at "/". Unset in development (Vite serves the frontend instead).
    static_dir: Path | None = None

    max_upload_mb: int = 20
    worker_poll_seconds: float = 2.0

    # Claude (PLAN.md §6). Without a key, captures wait in the queue until one is configured.
    anthropic_api_key: str = Field(
        default="", validation_alias=AliasChoices("WANDER_ANTHROPIC_API_KEY", "ANTHROPIC_API_KEY")
    )
    enrich_model: str = "claude-opus-5-5"
    enrich_effort: str = "low"
    chat_model: str = "claude-opus-5-5"
    chat_effort: str = "medium"

    # Geocoding: public Nominatim by default (about 1 request per second, which is plenty here).
    geocoder_url: str = "https://nominatim.openstreetmap.org"
    user_agent: str = "Wander/0.1 (+https://github.com/cankaratepe23/wander)"

    # yt-dlp: a Netscape cookies.txt from a throwaway Instagram account (PLAN.md §4.2).
    ytdlp_cookies_file: Path | None = None
    # Phase 2 deep parsing: keyframes and transcripts, and the video archive cap.
    deep_parse: bool = True
    whisper_model: str = "small"
    video_archive_max_gb: float = 5.0

    # Local time zone, for when the monthly nudge goes out (the container's TZ).
    tz: str = Field(default="UTC", validation_alias=AliasChoices("WANDER_TZ", "TZ"))

    # Push notifications for seasonal nudges (PLAN.md §4.5), e.g. https://ntfy.sh/your-topic
    ntfy_url: str = ""

    @model_validator(mode="after")
    def _check_auth_mode(self) -> "Settings":
        access_configured = bool(self.access_team_domain and self.access_aud)
        if self.dev_mode and access_configured:
            raise ValueError(
                "WANDER_DEV_MODE must not be enabled when Cloudflare Access is configured"
            )
        if bool(self.access_team_domain) != bool(self.access_aud):
            raise ValueError("Set both WANDER_ACCESS_TEAM_DOMAIN and WANDER_ACCESS_AUD, or neither")
        return self

    @property
    def access_configured(self) -> bool:
        return bool(self.access_team_domain and self.access_aud)

    @property
    def allowed_email_set(self) -> set[str]:
        return {e.strip().lower() for e in self.allowed_emails.split(",") if e.strip()}

    @property
    def service_token_map(self) -> dict[str, str]:
        pairs = (p.split("=", 1) for p in self.service_tokens.split(",") if "=" in p)
        return {k.strip(): v.strip().lower() for k, v in pairs if k.strip() and v.strip()}

    @property
    def db_path(self) -> Path:
        return self.data_dir / "wander.db"

    @property
    def uploads_dir(self) -> Path:
        return self.data_dir / "uploads"

    @property
    def media_dir(self) -> Path:
        return self.data_dir / "media"

    @property
    def ai_configured(self) -> bool:
        return bool(self.anthropic_api_key)


@lru_cache
def get_settings() -> Settings:
    return Settings()

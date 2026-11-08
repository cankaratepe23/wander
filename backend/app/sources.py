"""Step 1-2 of enrichment (PLAN.md §4.2): work out what a capture's link is and pull out its signals.

Everything here is best effort. A failure is recorded as a note and the pipeline carries on with
whatever it has, so a capture never fails because a site was unreachable.
"""

import contextlib
import ipaddress
import logging
import re
import socket
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

import httpx

from app.config import Settings

log = logging.getLogger("wander.sources")

MAX_PAGE_BYTES = 2_000_000
MAX_IMAGE_BYTES = 4_500_000  # the API's per-image limit is 5 MB
PAGE_TEXT_CHARS = 6000
BROWSER_UA = "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130 Mobile Safari/537.36"


@dataclass
class Signals:
    """Everything known about a capture before Claude reads it."""

    platform: str = "text"
    url: str | None = None
    final_url: str | None = None
    title: str | None = None
    description: str | None = None
    caption: str | None = None
    author: str | None = None
    location_tag: str | None = None
    hashtags: list[str] = field(default_factory=list)
    page_text: str | None = None
    map_hint: str | None = None  # e.g. a Google Maps place name and coordinates
    transcript: str | None = None
    thumbnail_url: str | None = None
    thumbnail_path: Path | None = None
    keyframe_paths: list[Path] = field(default_factory=list)
    video_path: Path | None = None
    duration_s: float | None = None
    notes: list[str] = field(default_factory=list)

    def as_prompt(self) -> dict[str, Any]:
        keys = [
            "platform", "url", "final_url", "title", "author", "location_tag", "caption",
            "description", "hashtags", "map_hint", "transcript", "page_text",
        ]  # fmt: skip
        return {k: getattr(self, k) for k in keys if getattr(self, k)}


PLATFORMS = [
    ("tiktok", re.compile(r"(^|\.)tiktok\.com$")),
    ("instagram", re.compile(r"(^|\.)instagram\.com$")),
    ("youtube", re.compile(r"(^|\.)(youtube\.com|youtu\.be)$")),
    (
        "google_maps",
        re.compile(r"^(maps\.google\.[a-z.]+|maps\.app\.goo\.gl|goo\.gl|www\.google\.[a-z.]+)$"),
    ),
    ("booking", re.compile(r"(^|\.)booking\.com$")),
    ("airbnb", re.compile(r"(^|\.)airbnb\.[a-z.]+$")),
]
VIDEO_PLATFORMS = {"tiktok", "instagram", "youtube"}


def detect_platform(url: str) -> str:
    host = (urlparse(url).hostname or "").lower()
    for name, pattern in PLATFORMS:
        if pattern.search(host):
            if name == "google_maps" and host.startswith("www.google.") and "/maps" not in url:
                return "web"
            return name
    return "web"


class UnsafeURL(ValueError):
    pass


def check_public(url: str) -> None:
    """Refuse URLs that point inside the network the worker runs in (SSRF guard)."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise UnsafeURL(f"not a web URL: {url}")
    try:
        infos = socket.getaddrinfo(parsed.hostname, None)
    except socket.gaierror as exc:
        raise UnsafeURL(f"can't resolve {parsed.hostname}") from exc
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if not ip.is_global:
            raise UnsafeURL(f"{parsed.hostname} resolves to a non-public address")


def http_client(settings: Settings, *, browser: bool = False) -> httpx.Client:
    # Social platforms only serve their pages to browsers; everywhere else, say honestly who we are
    # (Wikipedia and many blogs refuse anonymous or fake-browser clients).
    return httpx.Client(
        headers={
            "User-Agent": BROWSER_UA if browser else settings.user_agent,
            "Accept-Language": "en;q=0.9,*;q=0.5",
        },
        timeout=15,
        follow_redirects=True,
    )


def _guarded_get(client: httpx.Client, url: str, limit: int) -> httpx.Response:
    """GET with the SSRF check applied to every redirect hop, and a size cap."""
    for _ in range(6):
        check_public(url)
        with client.stream("GET", url, follow_redirects=False) as r:
            if r.is_redirect and r.headers.get("location"):
                url = str(r.url.join(r.headers["location"]))
                continue
            body = b""
            for chunk in r.iter_bytes():
                body += chunk
                if len(body) > limit:
                    break
            # iter_bytes() already decoded gzip/br, so don't let the copy decode it again.
            headers = {
                k: v
                for k, v in r.headers.items()
                if k.lower() not in ("content-encoding", "content-length")
            }
            return httpx.Response(
                r.status_code, headers=headers, content=body[:limit], request=r.request
            )
    raise UnsafeURL("too many redirects")


class _PageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.meta: dict[str, str] = {}
        self.title = ""
        self.text: list[str] = []
        self._skip = 0
        self._in_title = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = {k: (v or "") for k, v in attrs}
        if tag == "meta":
            key = (a.get("property") or a.get("name") or "").lower()
            if key and a.get("content"):
                self.meta.setdefault(key, a["content"])
        elif tag in ("script", "style", "noscript", "svg"):
            self._skip += 1
        elif tag == "title":
            self._in_title = True

    def handle_endtag(self, tag: str) -> None:
        if tag in ("script", "style", "noscript", "svg") and self._skip:
            self._skip -= 1
        elif tag == "title":
            self._in_title = False

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.title += data
        elif not self._skip and data.strip():
            self.text.append(data.strip())


def parse_page(html: str) -> dict[str, str]:
    p = _PageParser()
    with contextlib.suppress(Exception):  # malformed HTML still yields what was parsed
        p.feed(html)
    text = re.sub(r"\s+", " ", " ".join(p.text))
    return {
        "title": (p.meta.get("og:title") or p.title or "").strip(),
        "description": (p.meta.get("og:description") or p.meta.get("description") or "").strip(),
        "image": (p.meta.get("og:image") or "").strip(),
        "text": text[:PAGE_TEXT_CHARS],
    }


GMAPS_PLACE = re.compile(r"/maps/place/([^/@]+)")
GMAPS_AT = re.compile(r"@(-?\d+\.\d+),(-?\d+\.\d+)")
GMAPS_Q = re.compile(r"[?&](?:q|query)=([^&]+)")


def google_maps_hint(url: str) -> str | None:
    name = GMAPS_PLACE.search(url) or GMAPS_Q.search(url)
    at = GMAPS_AT.search(url)
    parts = []
    if name:
        parts.append("place: " + unquote(name.group(1)).replace("+", " "))
    if at:
        parts.append(f"map pin at {at.group(1)}, {at.group(2)}")
    return "; ".join(parts) or None


def ytdlp_options(settings: Settings) -> dict[str, Any]:
    opts: dict[str, Any] = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "noplaylist": True,
    }
    if settings.ytdlp_cookies_file and Path(settings.ytdlp_cookies_file).is_file():
        opts["cookiefile"] = str(settings.ytdlp_cookies_file)
    return opts


def ytdlp_info(url: str, settings: Settings) -> dict[str, Any]:
    import yt_dlp  # heavy import, only when needed

    with yt_dlp.YoutubeDL(ytdlp_options(settings)) as ydl:
        return ydl.extract_info(url, download=False) or {}


HASHTAG = re.compile(r"#(\w+)", re.UNICODE)
IG_SHORTCODE = re.compile(r"instagram\.com/(?:[^/]+/)?(?:p|reel|reels|tv)/([A-Za-z0-9_-]+)")


def instagram_location(
    url: str, settings: Settings
) -> tuple[str, float | None, float | None] | None:
    """An Instagram post's location tag, which yt-dlp doesn't expose (PLAN.md Phase 2).

    Uses instaloader with the same throwaway account's cookies. Best effort: None on any failure.
    """
    match = IG_SHORTCODE.search(url)
    if not match or not (
        settings.ytdlp_cookies_file and Path(settings.ytdlp_cookies_file).is_file()
    ):
        return None
    try:
        from http.cookiejar import MozillaCookieJar

        import instaloader

        jar = MozillaCookieJar(str(settings.ytdlp_cookies_file))
        jar.load(ignore_discard=True, ignore_expires=True)
        loader = instaloader.Instaloader(
            quiet=True, max_connection_attempts=1, download_pictures=False
        )
        loader.context._session.cookies.update(jar)  # noqa: SLF001 - instaloader has no public cookie API
        loc = instaloader.Post.from_shortcode(loader.context, match.group(1)).location
    except Exception as exc:  # noqa: BLE001
        log.info("instaloader couldn't read %s: %s", url, exc)
        return None
    if loc is None or not loc.name:
        return None
    return loc.name, loc.lat, loc.lng


def gather(url: str | None, settings: Settings, workdir: Path) -> Signals:
    """Collect signals for a URL (or nothing, for plain text)."""
    if not url:
        return Signals()
    s = Signals(platform=detect_platform(url), url=url)
    with http_client(settings, browser=s.platform not in ("web", "google_maps")) as client:
        if s.platform in VIDEO_PLATFORMS:
            try:
                info = ytdlp_info(url, settings)
                s.title = info.get("title") or None
                s.caption = info.get("description") or None
                s.author = info.get("uploader") or info.get("channel") or None
                s.location_tag = info.get("location") or None
                s.duration_s = info.get("duration")
                s.thumbnail_url = info.get("thumbnail") or None
                s.final_url = info.get("webpage_url") or None
                tags = list(info.get("tags") or [])
                s.hashtags = sorted(set(tags + HASHTAG.findall(s.caption or "")))[:30]
            except Exception as exc:  # noqa: BLE001 - extractors fail in many ways
                s.notes.append(f"Couldn't read the post with yt-dlp ({type(exc).__name__}).")
                log.warning("yt-dlp failed for %s: %s", url, exc)
        if not s.caption:
            try:
                r = _guarded_get(client, url, MAX_PAGE_BYTES)
                s.final_url = str(r.request.url) if r.request else url
                if r.status_code < 400 and "html" in r.headers.get("content-type", "html"):
                    page = parse_page(r.text)
                    s.title = s.title or page["title"] or None
                    s.description = page["description"] or None
                    s.page_text = page["text"] or None if s.platform == "web" else None
                    s.thumbnail_url = s.thumbnail_url or page["image"] or None
                else:
                    s.notes.append(f"The page answered {r.status_code}.")
            except (httpx.HTTPError, UnsafeURL) as exc:
                s.notes.append(f"Couldn't open the link ({exc}).")
        loc = (
            instagram_location(url, settings)
            if s.platform == "instagram" and not s.location_tag
            else None
        )
        if loc:
            s.location_tag = loc[0]
            if loc[1] is not None and loc[2] is not None:
                s.map_hint = f"post's location tag: {loc[0]} at {loc[1]:.5f}, {loc[2]:.5f}"
        if s.platform == "google_maps":
            s.map_hint = google_maps_hint(s.final_url or url) or google_maps_hint(url)
        if s.thumbnail_url:
            s.thumbnail_path = download_image(client, s.thumbnail_url, workdir / "thumb")
    if s.platform == "instagram" and not s.caption and not s.description:
        s.notes.append("Instagram needs a logged-in session to read this post.")
    return s


IMAGE_EXT = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp", "image/gif": ".gif"}


def download_image(client: httpx.Client, url: str, stem: Path) -> Path | None:
    try:
        r = _guarded_get(client, url, MAX_IMAGE_BYTES + 1)
    except (httpx.HTTPError, UnsafeURL):
        return None
    ctype = r.headers.get("content-type", "").split(";")[0].strip()
    if r.status_code >= 400 or ctype not in IMAGE_EXT or len(r.content) > MAX_IMAGE_BYTES:
        return None
    stem.parent.mkdir(parents=True, exist_ok=True)
    path = stem.with_suffix(IMAGE_EXT[ctype])
    path.write_bytes(r.content)
    return path

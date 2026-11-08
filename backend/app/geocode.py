"""Step 4-5 of enrichment (PLAN.md §4.2): coordinates from a real geocoder, then dedupe into existing places.

Claude names places; it never supplies coordinates. Public Nominatim allows about one request per
second and asks for an identifying User-Agent, both of which this module respects.
"""

import logging
import math
import re
import threading
import time
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass

import httpx
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import Settings
from app.models import Place

log = logging.getLogger("wander.geocode")

_lock = threading.Lock()
_last_call = 0.0
MIN_INTERVAL = 1.1  # seconds between Nominatim requests
SAME_PLACE_KM = 3.0


@dataclass
class Hit:
    name: str
    lat: float
    lng: float
    osm_id: str | None
    country: str | None
    country_code: str | None
    region: str | None
    city: str | None


def _throttle() -> None:
    global _last_call
    with _lock:
        wait = MIN_INTERVAL - (time.monotonic() - _last_call)
        if wait > 0:
            time.sleep(wait)
        _last_call = time.monotonic()


def nominatim(query: str, settings: Settings) -> Hit | None:
    """Look a place up. Returns None when nothing matches; raises on network errors (the job retries)."""
    _throttle()
    r = httpx.get(
        settings.geocoder_url.rstrip("/") + "/search",
        params={
            "q": query,
            "format": "jsonv2",
            "addressdetails": 1,
            "limit": 1,
            "accept-language": "en",
        },
        headers={"User-Agent": settings.user_agent},
        timeout=20,
    )
    r.raise_for_status()
    results = r.json()
    if not results:
        return None
    return hit_from(results[0])


def photon(query: str, settings: Settings) -> Hit | None:
    """A fuzzier second opinion, for names Nominatim wants spelled exactly. Best effort: None on any failure."""
    _throttle()
    try:
        r = httpx.get(
            settings.photon_url.rstrip("/") + "/api/",
            params={"q": query, "limit": 1, "lang": "en"},
            headers={"User-Agent": settings.user_agent},
            timeout=20,
        )
        r.raise_for_status()
        features = r.json().get("features") or []
    except (httpx.HTTPError, ValueError) as exc:
        log.info("photon failed for %r: %s", query, exc)
        return None
    if not features:
        return None
    p = features[0]["properties"]
    lng, lat = features[0]["geometry"]["coordinates"]
    osm_type, osm_id = p.get("osm_type"), p.get("osm_id")
    return Hit(
        name=p.get("name") or query.split(",")[0],
        lat=float(lat),
        lng=float(lng),
        osm_id=f"{osm_type.lower()}{osm_id}" if osm_type and osm_id else None,
        country=p.get("country"),
        country_code=(p.get("countrycode") or "").upper() or None,
        region=p.get("state"),
        city=p.get("city") or p.get("county"),
    )


def _words(text: str) -> list[str]:
    plain = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()
    return re.findall(r"[a-z0-9]+", plain)


def names_match(found: str, name: str, query: str) -> bool:
    """Is a fuzzy result really the place asked for? Photon always answers with something close-sounding."""
    specific = query.split(",")[0]
    wanted = set(_words(name)) | set(_words(specific))
    got = _words(found)
    if not got:
        return False
    shared = [w for w in got if w in wanted]
    if len(shared) / len(got) < 0.6:
        return False
    return len(shared) >= 2 or got[0] in (_words(name)[:1] + _words(specific)[:1])


def locate(
    name: str,
    country: str,
    query: str,
    settings: Settings,
    primary: Callable[[str, Settings], Hit | None],
    fuzzy: Callable[[str, Settings], Hit | None],
) -> tuple[Hit | None, bool]:
    """Find a place. Returns the hit and whether it's the place itself rather than the area around it."""
    searches = list(dict.fromkeys([query, f"{name}, {country}"]))
    for search in searches:
        if hit := primary(search, settings):
            return hit, True
    for search in searches:
        hit = fuzzy(search, settings)
        if hit and names_match(hit.name, name, query):
            return hit, True
    # Still nothing, so try the area, keeping at least "city, country": "Togoshiya, Shibuya, Tokyo, Japan" → Shibuya.
    parts = [p.strip() for p in query.split(",")]
    for start in range(1, len(parts) - 1):
        if hit := primary(", ".join(parts[start:]), settings):
            return hit, False
    return None, False


def hit_from(result: dict) -> Hit:
    a = result.get("address") or {}
    osm_type, osm_id = result.get("osm_type"), result.get("osm_id")
    return Hit(
        name=result.get("name") or (result.get("display_name") or "").split(",")[0],
        lat=float(result["lat"]),
        lng=float(result["lon"]),
        osm_id=f"{osm_type[0]}{osm_id}" if osm_type and osm_id else None,
        country=a.get("country"),
        country_code=(a.get("country_code") or "").upper() or None,
        region=region_of(a),
        city=a.get("city")
        or a.get("town")
        or a.get("village")
        or a.get("municipality")
        or a.get("hamlet"),
    )


def region_of(a: dict) -> str | None:
    # The first-level division, except where OSM's "state" is a statistical region (Türkiye's
    # "Mediterranean Region"); there the province (Antalya) is what people mean.
    state = a.get("state")
    if state and state.endswith(" Region") and a.get("province"):
        return a["province"]
    return state or a.get("province") or a.get("region") or a.get("county")


def km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    r = math.radians
    dlat, dlng = r(lat2 - lat1), r(lng2 - lng1)
    h = math.sin(dlat / 2) ** 2 + math.cos(r(lat1)) * math.cos(r(lat2)) * math.sin(dlng / 2) ** 2
    return 6371 * 2 * math.asin(math.sqrt(h))


def find_or_create(db: Session, hit: Hit, name: str, type_: str) -> Place:
    """Attach to an existing place with the same OSM id, or the same name within a few km."""
    if hit.osm_id:
        existing = db.scalar(select(Place).where(Place.osm_id == hit.osm_id))
        if existing:
            return existing
    for candidate in db.scalars(select(Place).where(func.lower(Place.name) == name.lower())):
        if km(candidate.lat, candidate.lng, hit.lat, hit.lng) <= SAME_PLACE_KM:
            return candidate
    place = Place(
        name=name,
        type=type_,
        lat=hit.lat,
        lng=hit.lng,
        osm_id=hit.osm_id,
        country=hit.country,
        country_code=hit.country_code,
        region=hit.region,
        city=hit.city,
        geocoder="nominatim",
    )
    db.add(place)
    db.flush()
    return place

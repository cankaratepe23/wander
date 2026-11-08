"""Backfill (PLAN.md §4.6): turn data exports into capture items.

- WhatsApp: "Export chat" (without media) gives a .txt. Every link becomes an item, plus text messages that
  look travel-related (Claude makes the final call, and drops what isn't).
- TikTok: "Download your data" (JSON) lists Favorites with video links. Likes are in the file but are skipped.
- Instagram: "Download your information" (JSON) has saved posts and collections.

Each parser is defensive about format drift: it walks the JSON and keeps any post link it finds under
keys that mean "saved" or "favorite", rather than relying on one exact layout.
"""

import io
import json
import re
import zipfile
from dataclasses import dataclass
from typing import Any

URL = re.compile(r"https?://[^\s<>\"']+", re.IGNORECASE)
# "[03/11/2026, 21:14:05] Sam: text" (iOS) or "03/11/2026, 21:14 - Sam: text" (Android), any date order.
WA_LINE = re.compile(
    r"^‎?\[?(\d{1,4}[./-]\d{1,2}[./-]\d{1,4}),? (\d{1,2}[:.]\d{2}(?:[:.]\d{2})?(?:\s?[APap][Mm])?)\]?(?: -)? ([^:]{1,60}): (.*)$"
)
TRAVEL_WORDS = re.compile(
    r"\b(trip|travel|holiday|vacation|visit|flight|fly to|hotel|airbnb|hostel|beach|hike|hiking|trek|island|"
    r"road ?trip|weekend in|week in|go to|let'?s go|should go|we could go|restaurant|museum|festival|"
    r"tatil|gidelim|gezi|seyahat|otel|plaj)\b",
    re.IGNORECASE,
)
MAX_ITEMS = 5000


@dataclass
class Item:
    text: str | None
    url: str | None


def _clean_url(url: str) -> str:
    return url.rstrip(".,;:!?)]}>'\"")


def whatsapp(text: str) -> list[Item]:
    messages: list[str] = []
    for line in text.splitlines():
        m = WA_LINE.match(line.strip())
        if m:
            messages.append(m.group(4))
        elif messages and line.strip():
            messages[-1] += "\n" + line.strip()  # a continuation of a multi-line message
    items: list[Item] = []
    seen: set[str] = set()
    for msg in messages:
        if "<Media omitted>" in msg or msg.strip() in ("<attached:", "This message was deleted"):
            continue
        urls = [_clean_url(u) for u in URL.findall(msg)]
        if urls:
            for u in urls:
                if u not in seen:
                    seen.add(u)
                    items.append(Item(text=msg.strip()[:2000], url=u))
        elif len(msg) >= 25 and TRAVEL_WORDS.search(msg):
            key = msg.strip().lower()
            if key not in seen:
                seen.add(key)
                items.append(Item(text=msg.strip()[:2000], url=None))
    return items[:MAX_ITEMS]


def _walk(node: Any, path: str, out: list[tuple[str, str]]) -> None:
    if isinstance(node, dict):
        for k, v in node.items():
            _walk(v, f"{path}/{k}".lower(), out)
    elif isinstance(node, list):
        for v in node:
            _walk(v, path, out)
    elif isinstance(node, str) and node.startswith("http"):
        out.append((path, node))


def _links(data: Any, host: str, path_words: tuple[str, ...]) -> list[Item]:
    found: list[tuple[str, str]] = []
    _walk(data, "", found)
    seen: set[str] = set()
    items: list[Item] = []
    for path, url in found:
        if host not in url or not any(w in path for w in path_words):
            continue
        url = _clean_url(url)
        if url not in seen:
            seen.add(url)
            items.append(Item(text=None, url=url))
    return items[:MAX_ITEMS]


def tiktok(data: Any) -> list[Item]:
    # Only saved videos. Likes are no signal of travel intent, and TikTok files them under
    # "Like List/ItemFavoriteList", so a bare "favorite" would match them (and sounds and effects) too.
    return _links(data, "tiktok", ("favorite videos", "favoritevideo"))


def instagram(data: Any) -> list[Item]:
    items = _links(data, "instagram.com", ("saved", "collection"))
    return [
        i
        for i in items
        if re.search(r"instagram\.com/(?:[^/]+/)?(?:p|reel|reels|tv)/", i.url or "")
    ]


class UnknownFormat(ValueError):
    pass


def detect(filename: str, raw: bytes) -> tuple[str, list[Item]]:
    """Work out what kind of export this is and parse it. Zips are searched for the right file."""
    name = (filename or "").lower()
    if name.endswith(".zip") or raw[:2] == b"PK":
        return _from_zip(raw)
    text = raw.decode("utf-8-sig", errors="replace")
    if name.endswith(".json") or text.lstrip().startswith(("{", "[")):
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise UnknownFormat("that JSON file couldn't be read") from exc
        blob = text[:200_000].lower()
        if "tiktok" in blob:
            return "tiktok", tiktok(data)
        if "instagram" in blob:
            return "instagram", instagram(data)
        raise UnknownFormat("this JSON isn't a TikTok or Instagram export")
    return "whatsapp", whatsapp(text)


def _from_zip(raw: bytes) -> tuple[str, list[Item]]:
    try:
        z = zipfile.ZipFile(io.BytesIO(raw))
    except zipfile.BadZipFile as exc:
        raise UnknownFormat("that zip file couldn't be opened") from exc
    names = [n for n in z.namelist() if not n.endswith("/")]
    chats = [n for n in names if n.lower().endswith(".txt") and "chat" in n.lower()]
    if chats:
        return "whatsapp", whatsapp(z.read(chats[0]).decode("utf-8-sig", errors="replace"))
    tik = [n for n in names if n.lower().endswith(".json") and "user_data" in n.lower()]
    if tik:
        return "tiktok", tiktok(json.loads(z.read(tik[0])))
    insta = [
        n
        for n in names
        if n.lower().endswith(".json")
        and ("saved_posts" in n.lower() or "saved_collections" in n.lower())
    ]
    if insta:
        items: list[Item] = []
        for n in insta:
            items += instagram(json.loads(z.read(n)))
        seen: set[str] = set()
        return "instagram", [i for i in items if not (i.url in seen or seen.add(i.url))]
    raise UnknownFormat("no WhatsApp chat, TikTok user_data or Instagram saved posts in that zip")

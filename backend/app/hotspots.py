"""Hotspots (PLAN.md §4.3, §4.2 step 6): where ideas are piling up, ranked by a heat score.

heat = Σ over ideas of recency × (1 + 0.5 per heart), × a variety bonus for mixed kinds of ideas
(food + hike + beach counts for more than three beaches). An idea counts once per area even when it
names several places there.
"""

import math
from collections import defaultdict
from datetime import UTC, datetime
from typing import Literal

from sqlalchemy.orm import Session

from app.models import Idea
from app.taxonomy import FAMILIES, family_of

Level = Literal["country", "region", "city"]
HALF_LIFE_DAYS = 180


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def hotspots(
    ideas: list[Idea], level: Level = "country", now: datetime | None = None, limit: int = 20
) -> list[dict]:
    now = now or datetime.now(UTC)
    areas: dict[tuple[str, str], dict] = {}
    for idea in ideas:
        if idea.status in ("dismissed", "done"):
            continue
        keys: dict[tuple[str, str], list] = defaultdict(list)
        for link in idea.links:
            p = link.place
            name = {"country": p.country, "region": p.region, "city": p.city or p.name}[level]
            if not name:
                continue
            within = p.country or "" if level != "country" else ""
            keys[(name, within)].append(p)
        age_days = max(0.0, (now - _aware(idea.created_at)).total_seconds() / 86400)
        weight = math.pow(0.5, age_days / HALF_LIFE_DAYS) * (1 + 0.5 * len(idea.hearts))
        for key, places in keys.items():
            a = areas.setdefault(
                key,
                {
                    "name": key[0],
                    "within": key[1] or None,
                    "level": level,
                    "ideas": 0,
                    "both": 0,
                    "mix": dict.fromkeys(FAMILIES, 0),
                    "categories": set(),
                    "best_months": defaultdict(int),
                    "idea_ids": [],
                    "lat": 0.0,
                    "lng": 0.0,
                    "_n": 0,
                    "heat": 0.0,
                },
            )
            a["ideas"] += 1
            a["both"] += 1 if len(idea.hearts) >= 2 else 0
            a["mix"][family_of(idea.category)] += 1
            a["categories"].add(idea.category)
            for m in idea.best_months or []:
                a["best_months"][m] += 1
            a["idea_ids"].append(idea.id)
            a["heat"] += weight
            for p in places:
                a["lat"] += p.lat
                a["lng"] += p.lng
                a["_n"] += 1
    out = []
    for a in areas.values():
        variety = 1 + 0.15 * (len(a["categories"]) - 1)
        months = sorted(a["best_months"].items(), key=lambda kv: (-kv[1], kv[0]))
        out.append(
            {
                "name": a["name"],
                "within": a["within"],
                "level": level,
                "ideas": a["ideas"],
                "both": a["both"],
                "mix": a["mix"],
                "best_months": sorted(m for m, n in months if n >= max(1, months[0][1] // 2))
                if months
                else [],
                "idea_ids": a["idea_ids"],
                "lat": a["lat"] / a["_n"],
                "lng": a["lng"] / a["_n"],
                "heat": round(a["heat"] * variety, 3),
            }
        )
    out.sort(key=lambda h: (-h["heat"], -h["ideas"], h["name"]))
    return out[:limit]


def load_and_rank(db: Session, level: Level = "country", limit: int = 20) -> list[dict]:
    from app.ideas_api import load_ideas

    return hotspots(load_ideas(db), level, limit=limit)

"""Idea categories and the four colour families the UI groups them into (docs/design/meridian.md §2)."""

FAMILIES = ("food", "nature", "stays", "culture")

CATEGORY_FAMILY: dict[str, str] = {
    "food": "food",
    "restaurant": "food",
    "market": "food",
    "wine": "food",
    "beach": "nature",
    "hiking": "nature",
    "nature": "nature",
    "ski": "nature",
    "road trip": "nature",
    "accommodation": "stays",
    "wellness": "stays",
    "experience": "stays",
    "culture": "culture",
    "city break": "culture",
    "festival": "culture",
    "other": "culture",
}

CATEGORIES = tuple(CATEGORY_FAMILY)


def family_of(category: str | None) -> str:
    return CATEGORY_FAMILY.get((category or "other").lower(), "culture")

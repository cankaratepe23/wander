import pytest
from sqlalchemy import select

from app import enrich, geocode
from app.geocode import Hit, names_match
from app.models import Capture, Idea, User
from app.understand import PlaceGuess
from tests.test_enrich import draft, fake_deps, understanding


def hit(name: str) -> Hit:
    return Hit(name, 35.0, 139.0, f"n{name}", "Japan", "JP", "Tokyo", "Tokyo")


@pytest.mark.parametrize(
    ("found", "name", "query"),
    [  # real Photon answers for places Nominatim missed
        ("Aqua Park Shinagawa", "Maxell Aqua Park Shinagawa", "Maxell Aqua Park Shinagawa, Tokyo, Japan"),
        ("ANA Hangar", "ANA Blue Hangar", "ANA Blue Hangar, Haneda Airport, Tokyo, Japan"),
        ("Tokyo Metropolitan Government Main Building 1", "Tokyo Metropolitan Government Building", "x, Tokyo"),
        ("Nippon Television Tower", "NTV Ohdokei (Miyazaki Clock)", "Nippon Television Tower, Shiodome, Tokyo"),
        ("KITTE", "KITTE Garden", "KITTE Marunouchi, Chiyoda, Tokyo, Japan"),
    ],
)  # fmt: skip
def test_fuzzy_results_that_are_the_place(found, name, query):
    assert names_match(found, name, query)


@pytest.mark.parametrize(
    ("found", "name", "query"),
    [  # real Photon answers that would have put a pin in the wrong place
        ("Better Home Cooking School", "Babaramen Cooking School", "Babaramen Cooking School, Tokyo, Japan"),
        ("Workshop", "Plus Y Workshop", "Plus Y Workshop, Tokyo, Japan"),
        ("Youth Job Workshop", "Plus Y Workshop", "Plus Y Workshop, Tokyo, Japan"),
        ("Shibuya", "Togoshiya", "Togoshiya, Shibuya, Tokyo, Japan"),
        ("Togoshi-ginza", "Togoshiya", "Togoshiya, Shibuya, Tokyo, Japan"),
        ("Kitte Hakata", "KITTE Garden", "KITTE Marunouchi, Chiyoda, Tokyo, Japan"),
        ("東京都庁", "Tokyo Metropolitan Government Building", "Tokyo Metropolitan Government Building, Tokyo"),
    ],
)  # fmt: skip
def test_fuzzy_results_that_are_something_else(found, name, query):
    assert not names_match(found, name, query)


def locate(name, query, primary=None, fuzzy=None):
    primary = primary or {}
    fuzzy = fuzzy or {}
    return geocode.locate(
        name, "Japan", query, None, lambda q, s: primary.get(q), lambda q, s: fuzzy.get(q)
    )


def test_the_exact_search_wins():
    found = hit("Toyosu Market")
    assert locate("Toyosu", "Toyosu, Tokyo, Japan", {"Toyosu, Tokyo, Japan": found}) == (
        found,
        True,
    )


def test_a_checked_fuzzy_result_counts_as_the_place():
    found = hit("ANA Hangar")
    query = "ANA Blue Hangar, Haneda, Tokyo, Japan"
    assert locate("ANA Blue Hangar", query, fuzzy={query: found}) == (found, True)


def test_a_wrong_fuzzy_result_falls_back_to_the_area():
    area = hit("Shibuya")
    query = "Togoshiya, Shibuya, Tokyo, Japan"
    result = locate(
        "Togoshiya", query, {"Shibuya, Tokyo, Japan": area}, {query: hit("Togoshi-ginza")}
    )
    assert result == (area, False)


def test_a_country_alone_is_too_vague_to_pin():
    assert locate("Somewhere", "Somewhere, Japan", {"Japan": hit("Japan")}) == (None, False)


def test_an_area_pin_files_the_idea_with_a_note(client, settings):
    client.get("/api/me")
    place = PlaceGuess(
        name="Togoshiya",
        type="restaurant",
        country="Japan",
        query="Togoshiya, Shibuya, Tokyo, Japan",
        confidence=0.9,
    )
    area = hit("Shibuya")
    deps, _ = fake_deps(
        understanding(),
        hits={
            "Togoshiya, Shibuya, Tokyo, Japan": None,
            "Togoshiya, Japan": None,
            "Shibuya, Tokyo, Japan": area,
        },
    )
    with client.app.state.sessionmaker() as db:
        capture = Capture(user_id=db.query(User).one().id, kind="text", raw_text="x")
        db.add(capture)
        db.commit()
        u = understanding(ideas=[draft(title="Onigiri at Togoshiya", places=[place])])
        enrich.apply(db, capture, settings, u, [], deps)
        idea = db.scalar(select(Idea))
        assert capture.status == "done" and "pinned to Shibuya" in capture.error
        assert [link.place.name for link in idea.links] == ["Shibuya"]

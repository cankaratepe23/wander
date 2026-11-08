from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from app import backfill, deep, enrich, sources
from app.geocode import Hit
from app.models import Capture, Heart, Idea, User
from app.sources import Signals
from app.understand import IdeaDraft, PlaceGuess, build_content
from tests.test_enrich import draft, fake_deps, understanding
from tests.test_phase4 import FakeBatches

EXPORT_LINK = "https://www.tiktokv.com/share/video/7400000000000000000/"
BROWSER_LINK = "https://www.tiktok.com/@someone/video/7400000000000000000?lang=en"
PHOTO_LINK = "https://www.tiktok.com/@someone/photo/7400000000000000000"
SHORT_LINK = "https://vm.tiktok.com/ZM1abc/"
KEY = "tiktok:7400000000000000000"

CAROUSEL = {
    "desc": "Kyoto in 5 stops #kyoto",
    "author": {"nickname": "Someone", "uniqueId": "someone"},
    "poi": {"name": "Fushimi Inari", "city": "Kyoto", "province": "Kyoto", "country": "Japan"},
    "stickersOnItem": [{"stickerText": ["Go at sunrise"]}],
    "imagePost": {
        "images": [
            {"imageURL": {"urlList": ["https://cdn.example/a.heic", "https://cdn.example/a.jpg"]}},
            {"imageURL": {"urlList": ["https://cdn.example/b.jpg"]}},
        ]
    },
}


@pytest.fixture
def db(client):
    client.get("/api/me")
    with client.app.state.sessionmaker() as session:
        yield session


def add_capture(db, url, user=None) -> Capture:
    user = user or db.query(User).one()
    capture = Capture(user_id=user.id, kind="url", raw_text="Look at this", url=url)
    db.add(capture)
    db.commit()
    return capture


def test_export_links_are_tiktok_and_every_form_of_a_post_has_one_key():
    assert sources.detect_platform(EXPORT_LINK) == "tiktok"
    assert {sources.post_key(u) for u in (EXPORT_LINK, BROWSER_LINK, PHOTO_LINK)} == {KEY}
    assert sources.post_key(SHORT_LINK) is None and sources.post_key(None) is None
    assert sources.post_key("https://example.com/video/1") is None


def test_the_same_post_from_another_link_is_hearted_not_duplicated(db, settings):
    deps, calls = fake_deps(understanding())
    first = add_capture(db, BROWSER_LINK)
    idea = enrich.run(db, first, settings, deps)

    second = add_capture(db, EXPORT_LINK)
    assert enrich.run(db, second, settings, deps) is None
    assert calls["understand"] == 1 and second.status == "done" and second.post_key == KEY
    assert db.query(Idea).count() == 1
    assert db.get(Heart, (idea.id, second.user_id)) is not None


def test_a_short_link_is_recognised_once_resolved(db, settings):
    deps, calls = fake_deps(understanding())
    enrich.run(db, add_capture(db, EXPORT_LINK), settings, deps)

    short = add_capture(db, SHORT_LINK)
    deps.gather = lambda url, s, w: Signals(platform="tiktok", url=url, final_url=BROWSER_LINK)
    assert enrich.run(db, short, settings, deps) is None
    assert calls["understand"] == 1 and short.post_key == KEY and db.query(Idea).count() == 1


def test_copies_waiting_in_one_batch_file_a_single_idea(db, settings):
    deps, _ = fake_deps(understanding())
    first, second = add_capture(db, BROWSER_LINK), add_capture(db, EXPORT_LINK)
    first.post_key = second.post_key = KEY
    idea = enrich.apply(db, first, settings, understanding(), [], deps, imported=True)
    assert enrich.apply(db, second, settings, understanding(), [], deps, imported=True) is idea
    assert second.status == "done" and db.query(Idea).count() == 1


def test_re_enriching_keeps_a_capture_on_its_own_idea(db, settings):
    deps, _ = fake_deps(understanding())
    capture = add_capture(db, BROWSER_LINK)
    idea = enrich.run(db, capture, settings, deps)
    again = enrich.apply(db, capture, settings, understanding(title="New title"), [], deps)
    assert again.id == idea.id and again.title == "New title"


def spot(name: str) -> IdeaDraft:
    return draft(
        title=name,
        places=[
            PlaceGuess(
                name=name, type="poi", country="Japan", query=f"{name}, Tokyo", confidence=0.9
            )
        ],
    )


def test_a_list_post_becomes_one_idea_per_thing(db, settings, client):
    deps, _ = fake_deps(understanding())
    capture = add_capture(db, BROWSER_LINK)
    u = understanding(ideas=[spot("Sumo stable"), spot("Toyosu Market"), spot("Imperial Palace")])
    first = enrich.apply(db, capture, settings, u, [], deps, imported=True)

    ideas = db.query(Idea).filter_by(capture_id=capture.id).order_by(Idea.id).all()
    assert [i.title for i in ideas] == ["Sumo stable", "Toyosu Market", "Imperial Palace"]
    assert first is ideas[0] and all(not i.reviewed and len(i.links) == 1 for i in ideas)
    title = next(c for c in client.get("/api/captures").json() if c["id"] == capture.id)
    assert title["title"] == "Sumo stable and 2 more"


def test_a_route_stays_one_idea_with_every_stop(db, settings):
    stops = [
        PlaceGuess(name=n, type="city", country="T", query=n, confidence=0.9)
        for n in ("A", "B", "C")
    ]
    hits = {n: Hit(n, 1.0, float(i), f"r{i}", "T", "TR", "R", n) for i, n in enumerate("ABC")}
    deps, _ = fake_deps(understanding(), hits=hits)
    capture = add_capture(db, BROWSER_LINK)
    idea = enrich.apply(db, capture, settings, understanding(title="Route", places=stops), [], deps)
    assert db.query(Idea).count() == 1 and len(idea.links) == 3
    assert [link.role for link in idea.links] == ["primary", "mentioned", "mentioned"]


def test_a_second_save_of_a_list_post_hearts_every_idea(db, settings):
    deps, _ = fake_deps(understanding())
    first = add_capture(db, BROWSER_LINK)
    first.post_key = KEY
    enrich.apply(db, first, settings, understanding(ideas=[spot("A"), spot("B")]), [], deps)
    second = add_capture(db, EXPORT_LINK)
    assert enrich.run(db, second, settings, deps) is None and second.status == "done"
    assert db.query(Heart).count() == 2 and db.query(Idea).count() == 2
    assert "and 1 more" in second.error


def test_reading_again_updates_in_place_and_keeps_what_someone_acted_on(db, settings):
    deps, _ = fake_deps(understanding())
    capture = add_capture(db, BROWSER_LINK)
    enrich.apply(
        db, capture, settings, understanding(ideas=[spot("A"), spot("B"), spot("C")]), [], deps
    )
    a, b, c = db.query(Idea).order_by(Idea.id).all()
    c.status = "shortlist"
    b_id = b.id
    db.commit()

    enrich.apply(db, capture, settings, understanding(ideas=[spot("A2")]), [], deps)
    assert a.title == "A2"
    assert db.get(Idea, b_id) is None and db.get(Idea, c.id).status == "shortlist"


def test_carousel_gets_its_slides_location_tag_and_stickers(monkeypatch, settings, tmp_path):
    monkeypatch.setattr(
        sources,
        "ytdlp_info",
        lambda url, s: {
            "description": "Kyoto in 5 stops #kyoto",
            "thumbnail": "https://cdn.example/t.jpg",
        },
    )
    monkeypatch.setattr(sources, "tiktok_record", lambda post_id, s: CAROUSEL)
    tried = []

    def fake_image(client, url, stem):
        tried.append(url)
        return None if url.endswith(".heic") else stem.with_suffix(".jpg")

    monkeypatch.setattr(sources, "download_image", fake_image)
    s = sources.gather(EXPORT_LINK, settings, tmp_path)

    assert s.platform == "tiktok" and s.carousel
    assert [p.name for p in s.keyframe_paths] == ["slide01.jpg", "slide02.jpg"]
    assert "https://cdn.example/a.jpg" in tried  # the next URL when a format can't be used
    assert s.location_tag == "Fushimi Inari, Kyoto, Japan"
    assert s.caption.endswith("Text stickers on the post: Go at sunrise")

    monkeypatch.setattr(deep, "download_video", lambda *a: pytest.fail("a carousel has no video"))
    deep.deepen(s, settings, tmp_path)


def test_a_failed_record_changes_nothing(monkeypatch, settings, tmp_path):
    monkeypatch.setattr(sources, "ytdlp_info", lambda url, s: {"description": "A video"})
    monkeypatch.setattr(sources, "tiktok_record", lambda post_id, s: None)
    s = sources.gather(BROWSER_LINK, settings, tmp_path)
    assert s.caption == "A video" and not s.carousel and s.location_tag is None


def test_the_record_rescues_a_link_yt_dlp_cannot_read(monkeypatch, settings, tmp_path):
    def broken(url, s):
        raise ValueError("unsupported URL")

    monkeypatch.setattr(sources, "ytdlp_info", broken)
    monkeypatch.setattr(sources, "tiktok_record", lambda post_id, s: {"desc": "Hello"})
    monkeypatch.setattr(sources, "_guarded_get", broken_page)
    s = sources.gather(PHOTO_LINK, settings, tmp_path)
    assert s.caption == "Hello" and not any("yt-dlp" in n for n in s.notes)


def broken_page(client, url, limit):
    raise sources.UnsafeURL("no network in tests")


def test_every_slide_reaches_claude(tmp_path):
    paths = []
    for n in range(20):
        path = tmp_path / f"slide{n}.jpg"
        path.write_bytes(b"x")
        paths.append(path)
    blocks = build_content(None, Signals(), paths)
    assert sum(b["type"] == "image" for b in blocks) == 20


def test_a_batch_stops_short_of_the_size_limit(db, settings, monkeypatch):
    user = db.query(User).one()
    captures = [
        Capture(
            user_id=user.id,
            kind="import",
            raw_text="Kaş",
            status="queued",
            prepared_at=datetime.now(UTC),
        )
        for _ in range(2)
    ]
    db.add_all(captures)
    db.commit()
    monkeypatch.setattr(backfill, "MAX_BATCH_BYTES", 1)
    fake = FakeBatches()
    backfill.submit_batch(
        db, settings, client=SimpleNamespace(messages=SimpleNamespace(batches=fake))
    )
    assert len(fake.created[0]) == 1
    assert captures[0].batch_id and captures[1].batch_id is None

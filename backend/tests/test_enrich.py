from types import SimpleNamespace

import anthropic
import httpx
import pytest

from app import ai, enrich, jobs, sources
from app.config import get_settings
from app.geocode import Hit, hit_from
from app.models import AiUsage, Capture, Idea, Job, Place, User
from app.sources import Signals
from app.understand import IdeaDraft, PlaceGuess, Understanding, build_content, clean
from app.worker import run_one


def understanding(**kw) -> Understanding:
    """One idea by default; keyword arguments set its fields, or the top-level ones."""
    top = {k: kw.pop(k) for k in ("is_travel_related", "language", "ideas") if k in kw}
    return Understanding(
        **{"is_travel_related": True, "language": "en", "ideas": [draft(**kw)], **top}
    )


def draft(**kw) -> IdeaDraft:
    base = dict(
        title="Lycian Way: Kaş to Kalkan", summary="Cliff paths and coves.",
        category="hiking", tags=["hiking", "coast"], confidence=0.9,
        places=[PlaceGuess(name="Kaş", type="city", country="Türkiye", query="Kaş, Antalya, Türkiye", confidence=0.95)],
        best_months=[9, 10], good_months=[4, 5], budget_level=2, trip_length_hint="2-3 days",
    )  # fmt: skip
    base.update(kw)
    return IdeaDraft(**base)


KAS = Hit("Kaş", 36.2, 29.64, "r123", "Türkiye", "TR", "Antalya", "Kaş")


def fake_deps(u: Understanding, hits=None, signals: Signals | None = None):
    calls = {"understand": 0, "geocode": []}

    def _understand(db, settings, raw_text, sig, images):
        calls["understand"] += 1
        db.add(
            AiUsage(
                task="enrich",
                model="claude-opus-5-5",
                input_tokens=100,
                output_tokens=50,
                cost_usd=0.001,
            )
        )
        return u

    def _geocode(query, settings):
        calls["geocode"].append(query)
        return (hits or {}).get(query, KAS)

    deps = enrich.Deps(
        gather=lambda url, s, w: signals or Signals(),
        understand=_understand,
        geocoder=_geocode,
        fuzzy_geocoder=lambda query, settings: None,
    )
    return deps, calls


@pytest.fixture
def db(client):
    client.get("/api/me")
    factory = client.app.state.sessionmaker
    with factory() as session:
        yield session


def make_capture(db, text="Lycian Way hike, Kaş to Kalkan", url=None) -> Capture:
    user = db.query(User).one()
    c = Capture(user_id=user.id, kind="url" if url else "text", raw_text=text, url=url)
    db.add(c)
    db.commit()
    return c


def test_capture_becomes_an_idea_on_the_map(db, settings):
    c = make_capture(db)
    deps, calls = fake_deps(understanding())
    idea = enrich.run(db, c, settings, deps)
    assert c.status == "done" and c.error is None
    assert idea.title == "Lycian Way: Kaş to Kalkan" and idea.category == "hiking"
    assert [link.place.name for link in idea.links] == ["Kaş"]
    assert idea.links[0].place.country_code == "TR"
    assert calls["geocode"] == ["Kaş, Antalya, Türkiye"]
    assert db.query(AiUsage).count() == 1
    assert c.raw_text == "Lycian Way hike, Kaş to Kalkan"  # raw input untouched


def test_same_place_is_reused_so_ideas_pile_up(db, settings):
    for _ in range(2):
        enrich.run(db, make_capture(db), settings, fake_deps(understanding())[0])
    assert db.query(Place).count() == 1
    assert db.query(Idea).count() == 2


def test_not_travel_goes_to_needs_a_look(db, settings):
    c = make_capture(db, "buy milk")
    assert enrich.run(db, c, settings, fake_deps(understanding(is_travel_related=False))[0]) is None
    assert c.status == "needs_review" and "travel" in c.error
    assert db.query(Idea).count() == 0


def test_unsure_or_unfound_places_need_a_look_but_keep_the_idea(db, settings):
    u = understanding(
        places=[
            PlaceGuess(
                name="Georgia", type="country", country="?", query="Georgia", confidence=0.3
            ),
            PlaceGuess(
                name="Nowhere", type="city", country="X", query="Nowhere, X", confidence=0.9
            ),
        ]
    )
    c = make_capture(db)
    idea = enrich.run(db, c, settings, fake_deps(u, hits={"Nowhere, X": None})[0])
    assert idea is not None and idea.links == []
    assert c.status == "needs_review"
    assert "Georgia" in c.error and "Nowhere" in c.error


def test_reenrich_updates_the_same_idea(db, settings):
    c = make_capture(db)
    first = enrich.run(db, c, settings, fake_deps(understanding())[0])
    second = enrich.run(db, c, settings, fake_deps(understanding(title="Better title"))[0])
    assert first.id == second.id and second.title == "Better title"
    assert db.query(Idea).count() == 1


def test_link_with_nothing_readable_is_parked_without_calling_claude(db, settings):
    c = make_capture(db, text=None, url="https://www.instagram.com/p/abc/")
    deps, calls = fake_deps(
        understanding(),
        signals=Signals(platform="instagram", url=c.url, notes=["Instagram needs a login."]),
    )
    assert enrich.run(db, c, settings, deps) is None
    assert calls["understand"] == 0
    assert c.status == "needs_review" and "Instagram" in c.error


def test_worker_defers_until_an_api_key_exists(client, settings):
    r = client.post("/api/capture", json={"text": "Cappadocia balloons"})
    factory = client.app.state.sessionmaker
    assert run_one(factory)
    with factory() as db:
        job = db.query(Job).one()
        assert job.status == "queued" and job.attempts == 0
        cap = db.get(Capture, r.json()["id"])
        assert cap.status == "queued" and "Claude" in cap.error


def api_error(status: int, message: str) -> anthropic.APIStatusError:
    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    return anthropic.APIStatusError(
        message, response=httpx.Response(status, request=request), body=None
    )


@pytest.mark.parametrize(
    ("status", "message", "expected"),
    [
        (402, "Payment required", True),
        (400, "Your credit balance is too low to access the Anthropic API.", True),
        (400, "You have reached your specified API usage limits.", True),
        (429, "You have reached your workspace spend limit.", True),
        (400, "messages: at least one message is required", False),
        (429, "This request would exceed your rate limit.", False),
    ],
)
def test_out_of_credit_is_told_apart_from_other_errors(status, message, expected):
    assert ai.out_of_credit(api_error(status, message)) is expected


def test_out_of_credit_waits_without_using_up_attempts(client, monkeypatch):
    monkeypatch.setattr(ai, "_credit_paused_until", 0.0)
    monkeypatch.setenv("WANDER_ANTHROPIC_API_KEY", "test-key")
    get_settings.cache_clear()
    calls = []

    def refuse(db, capture, settings, deps):
        calls.append(capture.id)
        capture.status = "processing"
        db.commit()
        raise api_error(400, "Your credit balance is too low.")

    monkeypatch.setattr(enrich, "run", refuse)
    first = client.post("/api/capture", json={"text": "Cappadocia balloons"}).json()["id"]
    second = client.post("/api/capture", json={"text": "Lycian Way"}).json()["id"]
    factory = client.app.state.sessionmaker
    assert run_one(factory) and run_one(factory)
    assert not run_one(factory)  # both are waiting, not due yet

    assert calls == [first]  # the second one wasn't fetched just to be refused
    with factory() as db:
        for job in db.query(Job):
            assert job.status == "queued" and job.attempts == 0
        for capture_id in (first, second):
            cap = db.get(Capture, capture_id)
            assert cap.status == "queued" and "credit" in cap.error


def test_clean_clamps_values():
    u = clean(
        understanding(
            best_months=[0, 9, 13, 9],
            good_months=[9, 4],
            budget_level=7,
            category="nope",
            title="  x  ",
        )
    ).ideas[0]
    assert u.best_months == [9] and u.good_months == [4]
    assert u.budget_level is None and u.category == "other" and u.title == "x"


def test_prompt_content_puts_images_first_and_marks_source_as_data(tmp_path):
    img = tmp_path / "shot.png"
    img.write_bytes(b"\x89PNG fake")
    content = build_content("note", Signals(platform="tiktok", caption="📍 Kaş"), [img])
    assert content[0]["type"] == "image"
    assert "<source>" in content[-1]["text"] and "Kaş" in content[-1]["text"]


def test_cost_uses_list_prices():
    usage = SimpleNamespace(
        input_tokens=1_000_000,
        output_tokens=100_000,
        cache_read_input_tokens=0,
        cache_creation_input_tokens=0,
        server_tool_use=None,
    )
    assert ai.cost("claude-opus-5-5", usage) == pytest.approx(4.0 + 2.0)
    assert ai.cost("claude-opus-5-5", usage, batch=True) == pytest.approx(3.0)


def test_platform_detection_and_maps_hint():
    assert sources.detect_platform("https://vm.tiktok.com/ZM123/") == "tiktok"
    assert sources.detect_platform("https://www.instagram.com/reel/x/") == "instagram"
    assert sources.detect_platform("https://youtu.be/abc") == "youtube"
    assert sources.detect_platform("https://maps.app.goo.gl/abc") == "google_maps"
    assert sources.detect_platform("https://example.com/blog") == "web"
    hint = sources.google_maps_hint(
        "https://www.google.com/maps/place/Pena+Palace/@38.78,-9.39,17z"
    )
    assert "Pena Palace" in hint and "38.78" in hint


def test_page_parser_reads_og_tags_and_text():
    page = sources.parse_page(
        "<html><head><title>T</title><meta property='og:title' content='Hidden coves'>"
        "<meta name='description' content='Ten coves'></head><body><script>x()</script><p>Kalkan &amp; Kaş</p></body></html>"
    )
    assert page["title"] == "Hidden coves" and page["description"] == "Ten coves"
    assert page["text"] == "Kalkan & Kaş"


def test_private_addresses_are_refused():
    with pytest.raises(sources.UnsafeURL):
        sources.check_public("http://127.0.0.1:8000/api")
    with pytest.raises(sources.UnsafeURL):
        sources.check_public("file:///etc/passwd")


def test_nominatim_result_mapping():
    hit = hit_from({
        "lat": "36.2", "lon": "29.64", "osm_type": "relation", "osm_id": 123, "name": "Kaş",
        "address": {"town": "Kaş", "state": "Antalya", "country": "Türkiye", "country_code": "tr"},
    })  # fmt: skip
    assert (
        hit.osm_id == "r123"
        and hit.city == "Kaş"
        and hit.region == "Antalya"
        and hit.country_code == "TR"
    )


def test_defer_does_not_use_up_attempts(db):
    job = jobs.enqueue(db, "x", {})
    db.commit()
    claimed = jobs.claim_next(db)
    from datetime import timedelta

    jobs.defer(db, claimed.id, timedelta(minutes=5), "later")
    db.refresh(job)
    assert job.status == "queued" and job.attempts == 0 and job.last_error == "later"


def test_same_link_twice_hearts_the_existing_idea(db, settings):
    url = "https://vm.tiktok.com/ZM1abc/"
    first = make_capture(db, text=None, url=url)
    deps, calls = fake_deps(
        understanding(), signals=Signals(platform="tiktok", url=url, caption="📍 Kaş")
    )
    idea = enrich.run(db, first, settings, deps)
    second = make_capture(db, text="look!", url=url)
    assert enrich.run(db, second, settings, deps) is None
    assert calls["understand"] == 1  # no second Claude call
    assert second.status == "done" and "Already saved" in second.error
    db.refresh(idea)
    assert len(idea.hearts) == 1 and db.query(Idea).count() == 1

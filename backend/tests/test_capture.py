from app.main import first_url
from app.models import Idea
from app.worker import run_one


def test_health_needs_no_auth(client):
    assert client.get("/api/health").json() == {"status": "ok"}


def test_me_creates_user_on_first_sight(client):
    body = client.get("/api/me").json()
    assert body == {"email": "alex@example.com", "display_name": "Alex"}


def test_text_capture_is_accepted_and_queued(client):
    r = client.post("/api/capture", json={"text": "Cappadocia balloons, maybe April"})
    assert r.status_code == 202
    body = r.json()
    assert body["kind"] == "text"
    assert body["status"] == "queued"
    assert body["created_by"] == "Alex"


def test_link_inside_shared_text_is_extracted(client):
    shared = "Look at this! https://www.tiktok.com/@someone/video/7400000000000000000?lang=en."
    body = client.post("/api/capture", json={"text": shared, "source_app": "share-target"}).json()
    assert body["kind"] == "url"
    assert body["url"] == "https://www.tiktok.com/@someone/video/7400000000000000000?lang=en"
    assert body["raw_text"] == shared  # the original is kept unchanged


def test_empty_capture_is_rejected(client):
    assert client.post("/api/capture", json={"text": "   "}).status_code == 422


def test_image_capture_via_multipart(client, settings):
    r = client.post(
        "/api/capture",
        data={"text": "hotel from IG"},
        files={"file": ("shot.png", b"\x89PNG fake", "image/png")},
    )
    assert r.status_code == 202
    assert r.json()["kind"] == "image"
    assert len(list(settings.uploads_dir.iterdir())) == 1


def test_non_image_upload_is_rejected(client):
    r = client.post("/api/capture", files={"file": ("x.exe", b"MZ", "application/octet-stream")})
    assert r.status_code == 415


def test_worker_keeps_capture_waiting_without_an_api_key(client):
    client.post("/api/capture", json={"text": "Lycian Way"})
    assert run_one(client.app.state.sessionmaker) is True
    assert run_one(client.app.state.sessionmaker) is False  # deferred, not due yet
    [item] = client.get("/api/captures").json()
    assert item["status"] == "queued"


def test_first_url_strips_trailing_punctuation():
    assert first_url("see (https://example.com/a).") == "https://example.com/a"
    assert first_url("no link here") is None


def test_share_target_fallback_saves_and_redirects(client):
    r = client.post(
        "/share-target",
        data={
            "title": "Hidden coves",
            "text": "https://vm.tiktok.com/ZM1/",
            "url": "https://vm.tiktok.com/ZM1/",
        },
        files={"media": ("cove.jpg", b"\xff\xd8 fake", "image/jpeg")},
        follow_redirects=False,
    )
    assert r.status_code == 303 and r.headers["location"] == "/#/capture?shared=1"
    [item] = client.get("/api/captures").json()
    assert item["kind"] == "image"
    assert item["raw_text"] == "Hidden coves\nhttps://vm.tiktok.com/ZM1/"


def test_captures_list_shows_the_source_and_the_filed_title(client):
    link = client.post(
        "/api/capture", json={"text": "https://www.tiktok.com/@someone/video/123"}
    ).json()
    note = client.post("/api/capture", json={"text": "Lycian Way"}).json()
    assert link["source"] == "tiktok" and link["title"] is None

    with client.app.state.sessionmaker() as db:
        db.add(Idea(capture_id=link["id"], created_by=1, title="Espresso Chalet"))
        db.commit()

    rows = {c["id"]: c for c in client.get("/api/captures").json()}
    assert rows[link["id"]]["title"] == "Espresso Chalet"
    assert (
        rows[link["id"]]["url"] == "https://www.tiktok.com/@someone/video/123"
    )  # the original stays
    assert rows[note["id"]]["source"] == "text" and rows[note["id"]]["title"] is None

from app.main import first_url
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

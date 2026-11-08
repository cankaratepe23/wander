import io
import json
import zipfile
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from app import backfill, enrich, importers, nudges
from app.models import Capture, Idea, Job, User
from app.sources import Signals
from tests.test_enrich import KAS, understanding

WA_IOS = """[03/11/2026, 21:14:05] Sam: look https://vm.tiktok.com/ZM1abc/ 😍
[03/11/2026, 21:15:10] Alex: we should go to Georgia next year, the Kazbegi hikes look unreal
[03/11/2026, 21:16:00] Alex: ok
[04/11/2026, 08:01:00] Sam: also this one https://www.instagram.com/reel/C9xyz/?igsh=1.
and a second line
[04/11/2026, 08:02:00] Alex: ‎<Media omitted>
[04/11/2026, 08:03:00] Sam: https://vm.tiktok.com/ZM1abc/"""

WA_ANDROID = """03/11/2026, 21:14 - Sam: https://maps.app.goo.gl/xyz
03/11/2026, 21:15 - Alex: Let's go to Lofoten in winter for the northern lights"""


def test_whatsapp_links_and_travel_talk():
    items = importers.whatsapp(WA_IOS)
    assert [i.url for i in items if i.url] == [
        "https://vm.tiktok.com/ZM1abc/",
        "https://www.instagram.com/reel/C9xyz/?igsh=1",
    ]
    texts = [i.text for i in items if not i.url]
    assert texts == ["we should go to Georgia next year, the Kazbegi hikes look unreal"]
    assert "second line" in next(i.text for i in items if i.url and "instagram" in i.url)
    android = importers.whatsapp(WA_ANDROID)
    assert android[0].url == "https://maps.app.goo.gl/xyz" and "Lofoten" in android[1].text


def test_tiktok_and_instagram_exports():
    tik = {"Activity": {"Favorite Videos": {"FavoriteVideoList": [{"Date": "2026-01-01", "Link": "https://www.tiktokv.com/share/video/1/"}]},
                        "Like List": {"ItemFavoriteList": [{"date": "x", "link": "https://www.tiktokv.com/share/video/2/"}]},
                        "Favorite Sounds": {"FavoriteSoundList": [{"Date": "x", "Link": "https://m.tiktok.com/music/4"}]},
                        "Video Browsing History": {"VideoList": [{"Link": "https://www.tiktokv.com/share/video/3/"}]}}}  # fmt: skip
    assert [i.url for i in importers.tiktok(tik)] == ["https://www.tiktokv.com/share/video/1/"]
    ig = {"saved_saved_media": [{"title": "someone", "string_map_data": {"Saved on": {"href": "https://www.instagram.com/p/ABC/", "timestamp": 1}}},
                                 {"title": "x", "string_map_data": {"Saved on": {"href": "https://www.instagram.com/someone/"}}}]}  # fmt: skip
    assert [i.url for i in importers.instagram(ig)] == ["https://www.instagram.com/p/ABC/"]


def test_detect_reads_zips_and_rejects_unknown():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("WhatsApp Chat - Trip/_chat.txt", WA_IOS)
    source, items = importers.detect("export.zip", buf.getvalue())
    assert source == "whatsapp" and len(items) == 3
    with pytest.raises(importers.UnknownFormat):
        importers.detect("x.json", json.dumps({"hello": "world"}).encode())


@pytest.fixture
def db(client):
    client.get("/api/me")
    with client.app.state.sessionmaker() as session:
        yield session


class FakeBatches:
    def __init__(self):
        self.created = []

    def create(self, requests):
        self.created.append(requests)
        return SimpleNamespace(id="batch_1")

    def retrieve(self, batch_id):
        return SimpleNamespace(processing_status="ended")

    def results(self, batch_id):
        out = []
        for r in self.created[-1]:
            cid = r["custom_id"]
            if cid.endswith(str(self.fail_id)):
                out.append(SimpleNamespace(custom_id=cid, result=SimpleNamespace(type="errored")))
                continue
            u = understanding(is_travel_related=not cid.endswith(str(self.not_travel_id)))
            msg = SimpleNamespace(stop_reason="end_turn", usage=SimpleNamespace(input_tokens=100, output_tokens=40),
                                  content=[SimpleNamespace(type="text", text=u.model_dump_json())])  # fmt: skip
            out.append(
                SimpleNamespace(
                    custom_id=cid, result=SimpleNamespace(type="succeeded", message=msg)
                )
            )
        return out


def test_backfill_flow_lands_in_the_review_tray(db, settings, client):
    user = db.query(User).one()
    items = [
        importers.Item(text="Kaş hike", url=None),
        importers.Item(text="buy milk", url=None),
        importers.Item(text="x", url="https://example.com/a"),
    ]
    imp = backfill.create(db, user, "whatsapp", "chat.txt", items)
    caps = db.query(Capture).filter_by(import_id=imp.id).order_by(Capture.id).all()
    assert len(caps) == 3 and db.query(Job).filter_by(kind="prepare_import").count() == 3

    deps = enrich.Deps(gather=lambda url, s, w: Signals(platform="web", url=url, title="A page") if url else Signals(),
                       geocoder=lambda q, s: KAS)  # fmt: skip
    for c in caps:
        backfill.prepare_import(db, {"capture_id": c.id}, settings, deps)
    assert all(c.prepared_at for c in caps)
    assert db.query(Job).filter_by(kind="submit_batch").count() == 1

    fake = FakeBatches()
    fake.not_travel_id, fake.fail_id = caps[1].id, caps[2].id
    client_ = SimpleNamespace(messages=SimpleNamespace(batches=fake))
    assert backfill.submit_batch(db, settings, client=client_) == "batch_1"
    req = fake.created[0][0]
    assert (
        req["custom_id"] == f"capture-{caps[0].id}"
        and req["params"]["output_config"]["format"]["type"] == "json_schema"
    )

    backfill.poll_batch(db, {"batch_id": "batch_1"}, settings, client=client_, deps=deps)
    for c in caps:
        db.refresh(c)
    assert caps[0].status == "done"
    idea = db.query(Idea).filter_by(capture_id=caps[0].id).one()
    assert idea.reviewed is False  # waits in the review tray
    assert caps[1].status == "dismissed"  # not travel: dropped quietly
    assert (
        caps[2].batch_id is None and db.query(Job).filter_by(kind="enrich_capture").count() == 1
    )  # errored: retried alone

    assert client.get("/api/map").json()["features"] == []  # unreviewed ideas stay off the map
    client.patch(f"/api/ideas/{idea.id}", json={"reviewed": True})
    assert len(client.get("/api/map").json()["features"]) == 1
    prog = client.get("/api/imports").json()[0]
    assert prog["total"] == 3 and prog["counts"]["done"] == 1


def test_upload_endpoint(client):
    r = client.post("/api/imports", files={"file": ("chat.txt", WA_ANDROID.encode(), "text/plain")})
    assert r.status_code == 202 and r.json()["source"] == "whatsapp" and r.json()["total"] == 2
    r = client.post("/api/imports", files={"file": ("x.json", b'{"a": 1}', "application/json")})
    assert r.status_code == 422


def test_nudge_message_and_schedule(db, client):
    user = db.query(User).one()
    for t, months in [
        ("Cappadocia balloons", [4, 5]),
        ("Sakura in Kyoto", [3, 4]),
        ("Lofoten aurora", [1, 2]),
    ]:
        db.add(Idea(title=t, category="nature", creator=user, best_months=months))
    db.commit()
    ideas, months = nudges.in_season(db, datetime(2026, 3, 1, tzinfo=UTC))
    title, body = nudges.message(ideas, months)
    assert title == "In season: March–April"
    assert body.startswith("2 of your ideas are best in March–April") and "Lofoten" not in body
    nxt = nudges.next_send_time(datetime(2026, 12, 15, tzinfo=UTC), "Europe/Istanbul")
    assert (nxt.year, nxt.month, nxt.day, nxt.hour) == (2027, 1, 1, 6)  # 09:07 in Istanbul (UTC+3)
    r = client.post("/api/nudges/preview").json()
    assert r["sent"] is False and r["configured"] is False

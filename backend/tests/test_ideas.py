from app.models import Idea, IdeaPlace, Place, User


def add_idea(client, title="Lycian Way", category="hiking", place=None):
    factory = client.app.state.sessionmaker
    with factory() as db:
        user = db.query(User).filter_by(email="alex@example.com").one()
        idea = Idea(title=title, category=category, creator=user, best_months=[9, 10])
        p = place or Place(
            name="Kaş", lat=36.2, lng=29.64, city="Kaş", region="Antalya", country="Türkiye"
        )
        idea.links.append(IdeaPlace(place=p))
        db.add(idea)
        db.commit()
        return idea.id


def test_ideas_list_includes_places_and_family(client):
    client.get("/api/me")
    add_idea(client)
    body = client.get("/api/ideas").json()
    assert len(body) == 1
    idea = body[0]
    assert idea["title"] == "Lycian Way"
    assert idea["family"] == "nature"
    assert idea["places"][0]["country"] == "Türkiye"
    assert idea["created_by"] == "Alex"
    assert idea["hearted_by_me"] is False


def test_heart_toggles(client):
    client.get("/api/me")
    idea_id = add_idea(client)
    on = client.post(f"/api/ideas/{idea_id}/heart").json()
    assert on["hearted_by"] == ["Alex"] and on["hearted_by_me"] is True
    off = client.post(f"/api/ideas/{idea_id}/heart").json()
    assert off["hearted_by"] == [] and off["hearted_by_me"] is False
    assert client.post("/api/ideas/999/heart").status_code == 404


def test_map_is_geojson_with_one_point_per_idea_place(client):
    client.get("/api/me")
    add_idea(client, "Mole", "food", Place(name="Oaxaca", lat=17.07, lng=-96.73, country="Mexico"))
    add_idea(
        client, "Tacos", "food", Place(name="Roma Norte", lat=19.42, lng=-99.16, country="Mexico")
    )
    fc = client.get("/api/map").json()
    assert fc["type"] == "FeatureCollection"
    assert len(fc["features"]) == 2
    props = fc["features"][0]["properties"]
    assert props["family"] == "food" and props["country"] == "Mexico"
    assert fc["features"][0]["geometry"]["coordinates"][0] < -90  # [lng, lat]


def test_patch_idea_validates_and_saves(client):
    client.get("/api/me")
    idea_id = add_idea(client)
    r = client.patch(
        f"/api/ideas/{idea_id}",
        json={"status": "shortlist", "best_months": [10, 13, 9], "notes": " go in Oct "},
    )
    body = r.json()
    assert (
        body["status"] == "shortlist"
        and body["best_months"] == [9, 10]
        and body["notes"] == "go in Oct"
    )
    assert client.patch(f"/api/ideas/{idea_id}", json={"category": "nope"}).status_code == 422
    assert client.patch(f"/api/ideas/{idea_id}", json={"status": "nope"}).status_code == 422


def test_wrong_place_fix(client, monkeypatch):
    from app import geocode

    client.get("/api/me")
    idea_id = add_idea(client)
    monkeypatch.setattr(
        geocode,
        "nominatim",
        lambda q, s: geocode.Hit("Kalkan", 36.26, 29.41, "n9", "Türkiye", "TR", "Antalya", "Kaş"),
    )
    body = client.post(f"/api/ideas/{idea_id}/places", json={"query": "Kalkan, Türkiye"}).json()
    assert [p["name"] for p in body["places"]] == ["Kaş", "Kalkan"]
    kas = body["places"][0]["id"]
    body = client.delete(f"/api/ideas/{idea_id}/places/{kas}").json()
    assert [p["name"] for p in body["places"]] == ["Kalkan"]
    monkeypatch.setattr(geocode, "nominatim", lambda q, s: None)
    assert (
        client.post(f"/api/ideas/{idea_id}/places", json={"query": "Atlantis"}).status_code == 404
    )


def test_dismissed_ideas_leave_the_map(client):
    client.get("/api/me")
    idea_id = add_idea(client)
    client.patch(f"/api/ideas/{idea_id}", json={"status": "dismissed"})
    assert client.get("/api/map").json()["features"] == []


def test_reenrich_and_dismiss_captures(client):
    cap = client.post("/api/capture", json={"text": "Kaş"}).json()
    assert client.post(f"/api/captures/{cap['id']}/reenrich").json() == {"queued": 1}
    assert client.post("/api/captures/reenrich-all").json() == {"queued": 1}
    assert client.post(f"/api/captures/{cap['id']}/dismiss").status_code == 204
    assert client.get("/api/captures").json()[0]["status"] == "dismissed"


def test_usage_reports_this_month(client):
    body = client.get("/api/usage").json()
    assert body["usd"] == 0 and body["ai_configured"] is False and "month" in body

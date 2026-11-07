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

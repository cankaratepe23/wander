import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from app import chat, geocode, tools
from app.hotspots import hotspots
from app.models import Conversation, Heart, Idea, IdeaPlace, Message, Place, User


@pytest.fixture
def db(client):
    client.get("/api/me")
    with client.app.state.sessionmaker() as session:
        yield session


def seed(db):
    alex = db.query(User).one()
    sam = User(email="sam@example.com", display_name="Sam")
    db.add(sam)
    lisbon = Place(
        name="Lisbon", lat=38.72, lng=-9.14, city="Lisbon", region="Lisbon", country="Portugal"
    )
    porto = Place(
        name="Porto", lat=41.15, lng=-8.61, city="Porto", region="Porto", country="Portugal"
    )
    kas = Place(name="Kaş", lat=36.2, lng=29.64, city="Kaş", region="Antalya", country="Türkiye")
    ideas = []
    for title, cat, place, hearts in [
        ("Pastéis de nata", "food", lisbon, 2),
        ("Alfama tascas", "food", lisbon, 1),
        ("Francesinha", "food", porto, 0),
        ("Douro by train", "nature", porto, 2),
        ("Lycian Way", "hiking", kas, 1),
    ]:
        idea = Idea(
            title=title, category=cat, creator=alex, best_months=[5] if place is not kas else [10]
        )
        idea.links.append(IdeaPlace(place=place))
        db.add(idea)
        db.flush()
        for u in [alex, sam][:hearts]:
            db.add(Heart(idea_id=idea.id, user_id=u.id))
        ideas.append(idea)
    db.commit()
    return alex, ideas


def test_hotspots_rank_by_heat_and_count_ideas_once(db):
    seed(db)
    ideas = db.query(Idea).all()
    countries = hotspots(ideas, "country")
    assert [h["name"] for h in countries] == ["Portugal", "Türkiye"]
    pt = countries[0]
    assert (
        pt["ideas"] == 4 and pt["both"] == 2 and pt["mix"]["food"] == 3 and pt["best_months"] == [5]
    )
    cities = hotspots(ideas, "city")
    assert {h["name"] for h in cities} == {"Lisbon", "Porto", "Kaş"}
    assert cities[0]["within"] == "Portugal"


def test_recency_decays_heat():
    place = Place(name="X", lat=0, lng=0, country="A")
    old = SimpleNamespace(status="someday", links=[SimpleNamespace(place=place)], hearts=[], category="food",
                          best_months=[], id=1, created_at=datetime.now(UTC) - timedelta(days=360))  # fmt: skip
    new = SimpleNamespace(**{**old.__dict__, "id": 2, "created_at": datetime.now(UTC)})
    assert hotspots([old])[0]["heat"] == pytest.approx(0.25, abs=0.01)
    assert hotspots([new])[0]["heat"] == pytest.approx(1.0, abs=0.01)


def test_tools_search_update_and_create(db, settings, monkeypatch):
    alex, ideas = seed(db)
    out, err = tools.run(
        db, alex, settings, "search_ideas", {"country": "Portugal", "hearted_by_both": True}
    )
    assert not err and {i["title"] for i in json.loads(out)["ideas"]} == {
        "Pastéis de nata",
        "Douro by train",
    }
    out, err = tools.run(db, alex, settings, "search_ideas", {"query": "kaş"})
    assert [i["title"] for i in json.loads(out)["ideas"]] == ["Lycian Way"]
    out, err = tools.run(
        db, alex, settings, "set_status", {"idea_id": ideas[0].id, "status": "shortlist"}
    )
    assert not err and json.loads(out)["status"] == "shortlist"
    out, err = tools.run(
        db, alex, settings, "update_idea", {"idea_id": ideas[0].id, "category": "nope"}
    )
    assert err and "category" in json.loads(out)["error"]
    out, err = tools.run(db, alex, settings, "set_status", {"idea_id": "x"})
    assert err and "INVALID_INPUT" in json.loads(out)

    monkeypatch.setattr(
        geocode,
        "nominatim",
        lambda q, s: (
            None
            if "Atlantis" in q
            else geocode.Hit("Nishiki Market", 35.0, 135.76, "w1", "Japan", "JP", "Kyoto", "Kyoto")
        ),
    )
    out, err = tools.run(
        db,
        alex,
        settings,
        "create_idea",
        {
            "title": "Nishiki lunch",
            "category": "food",
            "place_queries": ["Nishiki Market, Kyoto", "Atlantis"],
        },
    )
    body = json.loads(out)
    assert (
        not err
        and body["places"][0]["name"] == "Nishiki Market"
        and body["not_found"] == ["Atlantis"]
    )


def test_merge_places_moves_ideas(db, settings):
    alex, ideas = seed(db)
    dup = Place(name="Lisboa", lat=38.71, lng=-9.13, country="Portugal")
    ideas[4].links.append(IdeaPlace(place=dup))
    db.commit()
    lisbon_id = ideas[0].links[0].place_id
    out, err = tools.run(
        db, alex, settings, "merge_places", {"keep_place_id": lisbon_id, "merge_place_id": dup.id}
    )
    assert not err and json.loads(out)["ideas_moved"] == 1
    assert db.get(Place, dup.id) is None


def test_tool_schemas_are_stable_and_eager_when_streaming():
    eager = tools.schemas(eager=True)
    assert [t["name"] for t in eager] == list(tools.TOOLS)
    assert all(t["eager_input_streaming"] for t in eager)
    assert "eager_input_streaming" not in tools.schemas(eager=False)[0]
    assert eager[0]["input_schema"]["type"] == "object"


def test_chat_render_hides_context_and_merges_tool_rounds(db):
    alex, _ = seed(db)
    c = Conversation(scope="global", created_by=alex.id)
    db.add(c)
    db.flush()
    db.add_all([
        Message(conversation_id=c.id, role="user", content=[{"type": "text", "text": "<context>\nx\n</context>"}, {"type": "text", "text": "What's in Portugal?"}]),
        Message(conversation_id=c.id, role="assistant", content=[{"type": "tool_use", "id": "t1", "name": "search_ideas", "input": {}}]),
        Message(conversation_id=c.id, role="user", content=[{"type": "tool_result", "tool_use_id": "t1", "content": "{}"}]),
        Message(conversation_id=c.id, role="assistant", content=[{"type": "text", "text": "Four ideas."}]),
    ])  # fmt: skip
    db.commit()
    db.refresh(c)
    rendered = chat.render(c)
    assert rendered[0] == {"role": "user", "text": "What's in Portugal?", "id": rendered[0]["id"]}
    assert rendered[1]["steps"] == ["Searching your ideas"] and rendered[1]["text"] == "Four ideas."
    assert len(rendered) == 2


def test_chat_endpoints_without_a_key(client):
    cid = client.post("/api/conversations", json={"scope": "idea", "scope_id": "1"}).json()["id"]
    assert client.get(f"/api/conversations/{cid}").json()["messages"] == []
    assert client.post(f"/api/conversations/{cid}/messages", json={"text": "hi"}).status_code == 503
    assert client.get("/api/conversations?scope=idea&scope_id=1").json()[0]["id"] == cid


def test_hotspots_endpoint(client, db):
    seed(db)
    body = client.get("/api/hotspots?level=country").json()
    assert body[0]["name"] == "Portugal"


def mcp_call(client, method, params=None, id_=1):
    r = client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": id_, "method": method, "params": params or {}},
        headers={
            "Accept": "application/json, text/event-stream",
            "MCP-Protocol-Version": "2025-06-18",
        },
    )
    assert r.status_code == 200, r.text
    return r.json()


def test_mcp_lists_and_runs_tools(client, db):
    seed(db)
    init = mcp_call(
        client,
        "initialize",
        {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {"name": "t", "version": "1"},
        },
    )
    assert init["result"]["serverInfo"]["name"] == "Wander"
    names = [t["name"] for t in mcp_call(client, "tools/list")["result"]["tools"]]
    assert names == list(tools.TOOLS)
    res = mcp_call(
        client, "tools/call", {"name": "search_ideas", "arguments": {"country": "Türkiye"}}
    )
    text = res["result"]["content"][0]["text"]
    assert "Lycian Way" in text


class FakeStream:
    def __init__(self, message, events):
        self.message, self.events = message, events

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def __iter__(self):
        return iter(self.events)

    def get_final_message(self):
        return self.message


def test_chat_loop_runs_tools_and_persists_blocks(db, settings, monkeypatch):
    from anthropic.types import Message as ApiMessage
    from anthropic.types import TextBlock, ToolUseBlock, Usage

    from app import ai

    alex, ideas = seed(db)
    usage = Usage(input_tokens=10, output_tokens=5)
    turns = [
        ApiMessage(id="m1", type="message", role="assistant", model="claude-opus-5-5", stop_reason="tool_use", usage=usage,
                   content=[ToolUseBlock(type="tool_use", id="t1", name="set_status", input={"idea_id": ideas[4].id, "status": "shortlist"})]),
        ApiMessage(id="m2", type="message", role="assistant", model="claude-opus-5-5", stop_reason="end_turn", usage=usage,
                   content=[TextBlock(type="text", text="Shortlisted the Lycian Way.")]),
    ]  # fmt: skip
    sent = []

    class FakeClient:
        class messages:  # noqa: N801
            @staticmethod
            def stream(**kw):
                sent.append(kw)
                msg = turns[len(sent) - 1]
                events = [
                    SimpleNamespace(type="text", text=b.text)
                    for b in msg.content
                    if b.type == "text"
                ]
                events += [
                    SimpleNamespace(type="content_block_start", content_block=b)
                    for b in msg.content
                    if b.type == "tool_use"
                ]
                return FakeStream(msg, events)

    monkeypatch.setattr(ai, "client", lambda s: FakeClient)
    c = Conversation(scope="idea", scope_id=str(ideas[4].id), created_by=alex.id)
    db.add(c)
    db.commit()
    events = list(chat.respond(db, settings, c, alex, "Shortlist this one"))
    kinds = [e["type"] for e in events]
    assert kinds == ["tool", "changed", "text", "done"]
    assert db.get(Idea, ideas[4].id).status == "shortlist"
    # The second request replays the whole conversation, including the tool result.
    replay = sent[1]["messages"]
    assert [m["role"] for m in replay] == ["user", "assistant", "user"]
    assert replay[0]["content"][0]["text"].startswith("<context>")
    assert (
        replay[2]["content"][0]["type"] == "tool_result"
        and replay[2]["content"][0]["is_error"] is False
    )
    assert sent[0]["tools"][-1]["type"] == "web_search_20260209"
    assert c.title == "Shortlist this one"
    assert db.query(Message).filter_by(conversation_id=c.id).count() == 4

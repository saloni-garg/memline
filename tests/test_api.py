import io
import json
import os
import sys
import zipfile

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ["MEMLINE_DB"] = "/tmp/memline_test.db"

if os.path.exists("/tmp/memline_test.db"):
    os.remove("/tmp/memline_test.db")

import app.main as main_module  # noqa: E402
from app.main import app  # noqa: E402
from app.understanding import UnderstandingUnavailable, merge, top_insights  # noqa: E402


def _fake_extract(conversations, source):
    """Deterministic stand-in for the LLM extractors, used by the API tests.
    The real engine is exercised separately against a live model."""
    text = " ".join(m for c in conversations for m in c["messages"])
    out = []

    def add(kind, title, body):
        out.append({"kind": kind, "title": title, "body": body, "source": source,
                    "source_quote": body, "confidence": 0.9, "surprise": 3})

    if "Austin" in text:
        add("identity", "Location", "You live in Austin, Texas.")
    if "Denver" in text:
        add("identity", "Location", "You live in Denver, Colorado.")
    if "Fridays" in text:
        add("preference", "Reporting cadence", "You prefer weekly reports on Fridays.")
    if "garden" in text:
        add("project", "Community garden app", "You are working on a community garden app.")
    if "Jamie Lee" in text:
        add("identity", "Name", "Your name is Jamie Lee.")
    return out


main_module.extract_understandings = _fake_extract

client = TestClient(app)
EMAIL = {"email": "test@example.com", "password": "password123"}


@pytest.fixture(scope="module", autouse=True)
def account():
    r = client.post("/api/register", json=EMAIL)
    assert r.status_code == 200


def test_me_and_plans():
    me = client.get("/api/me").json()
    assert me["plan"] == "free"
    assert me["usage"]["active_memories"] == 0
    plans = client.get("/api/plans").json()["plans"]
    assert plans["pro"]["price_usd"] == 19


def test_manual_memory_and_pack():
    r = client.post("/api/memories", json={
        "kind": "preference", "title": "Writing style",
        "body": "I prefer short, direct drafts."})
    assert r.status_code == 200
    pack = client.post("/api/packs", json={"target": "chatgpt"})
    assert pack.status_code == 200
    assert "short, direct drafts" in pack.json()["pack"]["body"]
    assert "ChatGPT" in pack.json()["pack"]["body"] or "first message" in pack.json()["pack"]["body"]


def test_extraction_goes_to_inbox_not_memory():
    text = ("I live in Denver, Colorado. I prefer weekly reports on Fridays. "
            "I am working on a community garden app.")
    r = client.post("/api/extract", json={"text": text})
    assert r.status_code == 200 and r.json()["added"] >= 2
    pending = client.get("/api/memories?status=pending").json()["memories"]
    assert pending, "extracted candidates must wait in the inbox"
    active = client.get("/api/memories?status=active").json()["memories"]
    assert all("Denver" not in m["body"] for m in active), "unapproved facts must not be active"


def test_approval_and_superseding():
    client.post("/api/memories", json={
        "kind": "identity", "title": "Location", "body": "I live in Denver, Colorado."})
    client.post("/api/extract", json={"text": "I live in Austin, Texas now."})
    pending = client.get("/api/memories?status=pending").json()["memories"]
    austin = [m for m in pending if "Austin" in m["body"]]
    assert austin and austin[0].get("replaces"), "new location must visibly replace the old one"
    r = client.post(f"/api/memories/{austin[0]['id']}/approve")
    assert r.status_code == 200
    active = client.get("/api/memories?status=active").json()["memories"]
    assert any("Austin" in m["body"] for m in active)
    assert not any("Denver" in m["body"] for m in active), "replaced fact must leave the active memory"


def test_free_plan_memory_limit_and_upgrade():
    for i in range(30):
        client.post("/api/memories", json={"kind": "fact", "title": f"F{i}", "body": f"Fact number {i}."})
    me = client.get("/api/me").json()
    assert me["usage"]["active_memories"] == 25
    r = client.post("/api/memories", json={"kind": "fact", "title": "overflow", "body": "One too many."})
    assert r.status_code == 402
    up = client.post("/api/upgrade")
    assert up.json()["plan"] == "pro"
    r = client.post("/api/memories", json={"kind": "fact", "title": "overflow", "body": "Now it fits."})
    assert r.status_code == 200


def test_chatgpt_import_zip():
    conv = [{
        "mapping": {
            "n1": {"message": {"author": {"role": "user"},
                               "content": {"parts": ["My name is Jamie Lee and I prefer bullet points."]}}},
            "n2": {"message": {"author": {"role": "assistant"},
                               "content": {"parts": ["I prefer to ignore assistant text."]}}},
        }
    }]
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("conversations.json", json.dumps(conv))
    buf.seek(0)
    r = client.post("/api/import", files={"file": ("export.zip", buf, "application/zip")})
    assert r.status_code == 200
    assert r.json()["messages_scanned"] == 1, "only the user's side is scanned"
    pending = client.get("/api/memories?status=pending").json()["memories"]
    assert any("Jamie Lee" in m["body"] for m in pending)


def test_import_fails_honestly_when_engine_unavailable():
    def boom(conversations, source):
        raise UnderstandingUnavailable("no model configured")
    original = main_module.extract_understandings
    main_module.extract_understandings = boom
    try:
        conv = [{"mapping": {"n1": {"message": {"author": {"role": "user"},
                              "content": {"parts": ["hello"]}}}}}]
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("conversations.json", json.dumps(conv))
        buf.seek(0)
        r = client.post("/api/import", files={"file": ("export.zip", buf, "application/zip")})
        assert r.status_code == 503
        assert "not configured" in r.json()["detail"]
    finally:
        main_module.extract_understandings = original


def test_merge_dedupes_and_top_insights_rank_surprise():
    cands = [
        {"kind": "fact", "title": "Job", "body": "You work at a company.", "surprise": 1},
        {"kind": "principle", "title": "Tradeoffs first", "surprise": 5,
         "body": "You prefer tradeoff analyses over single recommendations."},
        {"kind": "preference", "title": "Tradeoffs first", "surprise": 4,
         "body": "You prefer tradeoff analyses over single recommendations, always."},
        {"kind": "goal", "title": "Staff role", "body": "You are working toward a Staff role.", "surprise": 4},
    ]
    merged = merge(cands)
    assert len(merged) == 3, "near-duplicate principle claims must merge"
    tradeoff = [m for m in merged if m["title"] == "Tradeoffs first"][0]
    assert tradeoff["support"] == 2, "two extractor kinds independently found it"
    top = top_insights(merged)
    assert top[0]["title"] == "Tradeoffs first", "highest surprise leads the review"
    assert any(t["title"] == "Staff role" for t in top)


def test_surprise_rating_and_coverage():
    r = client.post("/api/memories", json={
        "kind": "principle", "title": "Tradeoffs first",
        "body": "You prefer tradeoff analyses over recommendations."})
    mid = r.json()["memory"]["id"]
    ok = client.post(f"/api/memories/{mid}/surprise", json={"level": 2})
    assert ok.status_code == 200
    bad = client.post(f"/api/memories/{mid}/surprise", json={"level": 5})
    assert bad.status_code == 400
    me = client.get("/api/me").json()
    assert len(me["coverage"]) == 8
    principles = [c for c in me["coverage"] if c["key"] == "principles"][0]
    assert principles["covered"], "an active principle must light up coverage"


def test_pack_includes_principles_and_unknowns():
    from app.packs import build_pack
    mems = [
        {"kind": "principle", "title": "Tradeoffs", "body": "Show tradeoffs, not recommendations.", "project": ""},
        {"kind": "goal", "title": "Staff", "body": "Working toward a Staff role.", "project": ""},
        {"kind": "unknown", "title": "Startup business", "body": "You mention your startup often, but I don't understand its business yet.", "project": ""},
    ]
    pack = build_pack(mems, target="claude")
    assert "How I decide" in pack and "Tradeoffs" in pack
    assert "My current goals" in pack
    assert "not understood about me yet" in pack and "Startup business" in pack


def test_api_key_and_hosted_mcp():
    r = client.post("/api/keys", json={"name": "test key"})
    assert r.status_code == 200
    key = r.json()["key"]
    assert key.startswith("ml_")
    listed = client.get("/api/keys").json()["keys"]
    assert listed and "key" not in listed[0], "full key must never be listed again"
    anon = TestClient(app)
    bad = anon.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    assert bad.status_code == 401
    ok = anon.post("/mcp", headers={"Authorization": f"Bearer {key}"},
                   json={"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                         "params": {"name": "propose_memory",
                                    "arguments": {"kind": "fact", "title": "Via MCP",
                                                  "body": "Proposed over hosted MCP."}}})
    assert ok.status_code == 200
    pending = client.get("/api/memories?status=pending").json()["memories"]
    assert any(m["body"] == "Proposed over hosted MCP." for m in pending), \
        "hosted MCP proposals must land in the inbox"


def test_export_and_delete_account():
    c = TestClient(app)
    c.post("/api/register", json={"email": "gone@example.com", "password": "password123"})
    c.post("/api/memories", json={"kind": "fact", "title": "T", "body": "Export me."})
    exp = c.get("/api/export")
    assert exp.status_code == 200
    assert "Export me." in exp.text
    assert "attachment" in exp.headers.get("content-disposition", "")
    wrong = c.request("DELETE", "/api/account", json={"password": "wrongpassword"})
    assert wrong.status_code == 401
    gone = c.request("DELETE", "/api/account", json={"password": "password123"})
    assert gone.status_code == 200
    relogin = TestClient(app).post("/api/login", json={"email": "gone@example.com", "password": "password123"})
    assert relogin.status_code == 401, "deleted account must be gone"


def test_demo_account():
    c2 = TestClient(app)
    r = c2.post("/api/demo")
    assert r.status_code == 200
    me = c2.get("/api/me").json()
    assert me["usage"]["active_memories"] >= 8
    assert me["usage"]["pending"] >= 2

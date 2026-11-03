"""Developer platform (/v1) tests: Mem0-parity surface plus the parts
Mem0 does not have (temporal validity, history, profile, graph)."""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("MEMLINE_DB", "/tmp/memline_test.db")

from fastapi.testclient import TestClient  # noqa: E402

import app.devapi as devapi_module  # noqa: E402
from app.main import app  # noqa: E402


def _fake_extract(conversations, source):
    """Local copy of the deterministic extractor used by the API tests.
    (Importing it from tests.test_api would re-execute that module and
    delete the shared test DB mid-run.)"""
    text = " ".join(m for c in conversations for m in c["messages"])
    out = []

    def add(kind, title, body):
        out.append({"kind": kind, "title": title, "body": body, "source": source,
                    "source_quote": body, "confidence": 0.9, "surprise": 3})

    if "Austin" in text:
        add("identity", "Location", "You live in Austin, Texas.")
    if "Denver" in text:
        add("identity", "Location", "You live in Denver, Colorado.")
    return out


def _account(email: str) -> dict:
    c = TestClient(app)
    r = c.post("/api/register", json={"email": email, "password": "password123"})
    assert r.status_code == 200
    key = c.post("/api/keys", json={"name": "test"}).json()["key"]
    return {"Authorization": f"Bearer {key}"}


def test_v1_requires_key():
    c = TestClient(app)
    r = c.post("/v1/memories/search", json={"query": "anything"})
    assert r.status_code == 401


def test_v1_add_search_and_profile():
    h = _account("dev1@example.com")
    c = TestClient(app)
    r = c.post("/v1/memories", headers=h, json={
        "text": "I live in Austin, Texas.", "user_id": "u1", "infer": False})
    assert r.status_code == 200 and len(r.json()["results"]) == 1
    found = c.post("/v1/memories/search", headers=h, json={
        "query": "where do I live", "user_id": "u1", "threshold": 0.05}).json()["results"]
    assert found and "Austin" in found[0]["memory"]
    assert "score_components" in found[0] and "evidence" in found[0]
    prof = c.get("/v1/profile", headers=h, params={"user_id": "u1"}).json()
    assert prof["total"] == 1 and "fact" in prof["profile"]
    other = c.post("/v1/memories/search", headers=h, json={
        "query": "where do I live", "user_id": "u2", "threshold": 0.05}).json()["results"]
    assert other == [], "scope isolation: another end user must see nothing"


def test_v1_temporal_invalidate_and_history():
    h = _account("dev2@example.com")
    c = TestClient(app)
    mid = c.post("/v1/memories", headers=h, json={
        "text": "My manager is Ruth.", "user_id": "u1", "infer": False}).json()["results"][0]["id"]
    valid_from = c.get(f"/v1/memories/{mid}", headers=h).json()["valid_from"]
    c.post(f"/v1/memories/{mid}/invalidate", headers=h)
    present = c.post("/v1/memories/search", headers=h, json={
        "query": "who is my manager", "user_id": "u1", "threshold": 0.05}).json()["results"]
    assert all(r["id"] != mid for r in present), "invalidated memory must leave present search"
    past = c.post("/v1/memories/search", headers=h, json={
        "query": "who is my manager", "user_id": "u1", "as_of": valid_from,
        "threshold": 0.05}).json()["results"]
    assert any(r["id"] == mid for r in past), "as-of search must still see it in its window"
    events = [e["event"] for e in c.get(f"/v1/memories/{mid}/history", headers=h).json()["history"]]
    assert events == ["ADD", "INVALIDATE"]


def test_v1_extraction_supersede_keeps_temporal_history():
    devapi_module.extract_understandings = _fake_extract
    h = _account("dev3@example.com")
    c = TestClient(app)
    c.post("/v1/memories", headers=h, json={"text": "I live in Austin.", "user_id": "u1"})
    r = c.post("/v1/memories", headers=h, json={"text": "I live in Denver.", "user_id": "u1"})
    assert any(res["event"] == "UPDATE" for res in r.json()["results"])
    now_res = c.post("/v1/memories/search", headers=h, json={
        "query": "where do I live", "user_id": "u1", "threshold": 0.05}).json()["results"]
    assert now_res and "Denver" in now_res[0]["memory"]
    past = c.post("/v1/memories/search", headers=h, json={
        "query": "where do I live", "user_id": "u1",
        "as_of": "2020-01-01T00:00:00+00:00", "threshold": 0.05}).json()["results"]
    assert past == [], "nothing was true in 2020; the window must be respected both ways"


def test_v1_update_delete_and_tenant_isolation():
    h = _account("dev4@example.com")
    h2 = _account("dev5@example.com")
    c = TestClient(app)
    mid = c.post("/v1/memories", headers=h, json={
        "text": "Draft note.", "user_id": "u1", "infer": False}).json()["results"][0]["id"]
    assert c.get(f"/v1/memories/{mid}", headers=h2).status_code == 404, \
        "another tenant's key must not read this memory"
    upd = c.put(f"/v1/memories/{mid}", headers=h, json={"text": "Final note."})
    assert upd.status_code == 200 and upd.json()["memory"] == "Final note."
    assert c.delete(f"/v1/memories/{mid}", headers=h).status_code == 200
    assert c.get(f"/v1/memories/{mid}", headers=h).status_code == 404
    events = [e["event"] for e in c.get(f"/v1/memories/{mid}/history", headers=h).json()["history"]]
    assert events == ["ADD", "UPDATE", "DELETE"], "history must survive the memory itself"


def test_v1_assemble_context_and_understanding_alias():
    h = _account("dev7@example.com")
    c = TestClient(app)
    c.post("/v1/memories", headers=h, json={
        "text": "I prefer tradeoff analyses over single recommendations.",
        "user_id": "u1", "infer": False})
    out = c.post("/v1/assemble_context", headers=h, json={
        "query": "help me decide between two vendors", "user_id": "u1",
        "max_tokens": 800}).json()
    assert "tradeoff" in out["context"]
    assert out["supporting_understandings"], "included set must be returned"
    assert out["omitted_understandings"] == []
    assert out["confidence"]["based_on"] >= 1
    assert out["tokens_estimated"] <= out["max_tokens"]
    c.post("/v1/memories", headers=h, json={
        "text": "I also like extremely detailed written status reports with full background.",
        "user_id": "u1", "infer": False})
    tiny = c.post("/v1/assemble_context", headers=h, json={
        "query": "help me decide between two vendors", "user_id": "u1",
        "max_tokens": 100}).json()
    assert tiny["omitted_understandings"], "a tiny budget must report what it dropped"
    assert tiny["omitted_understandings"][0]["reason"] == "token_budget"
    und = c.get("/v1/understanding", headers=h, params={"user_id": "u1"}).json()
    prof = c.get("/v1/profile", headers=h, params={"user_id": "u1"}).json()
    assert und == prof and und["total"] >= 1, "/understanding is primary, /profile the alias"


def test_v1_graph_part_of_relation():
    c = TestClient(app)
    r = c.post("/api/register", json={"email": "dev8@example.com", "password": "password123"})
    assert r.status_code == 200
    c.post("/api/memories", json={"kind": "project", "title": "Firefly",
                                  "body": "Firefly is the main platform."})
    c.post("/api/memories", json={"kind": "project", "title": "Pluto",
                                  "body": "Pluto is part of Firefly and ships next quarter."})
    key = c.post("/api/keys", json={"name": "g2"}).json()["key"]
    g = c.get("/v1/graph", headers={"Authorization": f"Bearer {key}"}).json()
    assert any(e["relation"] == "part_of" and e["src_name"] == "Pluto"
               and e["dst_name"] == "Firefly" for e in g["edges"]), \
        "a stated part-of relation must be derived so queries can reason over it"


def _extract_returning(kind, title, body, quote):
    def _extract(conversations, source):
        return [{"kind": kind, "title": title, "body": body, "source": source,
                 "source_quote": quote, "confidence": 0.9, "surprise": 3,
                 "support": 1}]
    return _extract


def test_v1_write_gate_rejects_ungrounded():
    devapi_module.extract_understandings = _extract_returning(
        "preference", "Editor", "User prefers Vim for all editing tasks.",
        "User prefers Vim for all editing tasks")
    h = _account("dev9@example.com")
    c = TestClient(app)
    r = c.post("/v1/remember", headers=h, json={
        "text": "I write Python in VS Code every day.", "user_id": "u1"})
    body = r.json()
    assert body["results"] == [], "ungrounded extraction must not be stored"
    assert len(body["rejected"]) == 1 and body["rejected"][0]["verdict"] == "rejected"
    assert "evidence not found" in body["rejected"][0]["reason"]
    assert body["gate"] == {"checked": 1, "stored": 0, "rejected": 1, "skipped": 0}
    rej = c.get("/v1/rejections", headers=h, params={"user_id": "u1"}).json()["rejections"]
    assert rej and "Vim" in rej[0]["body"], "rejections must be inspectable"
    health = c.get("/v1/memory_health", headers=h, params={"user_id": "u1"}).json()
    assert health["rejected_writes"] >= 1 and health["gate_pass_rate"] == 0.0


def test_v1_remember_grounded_verdicts_and_explained_search():
    devapi_module.extract_understandings = _extract_returning(
        "identity", "Location", "You live in Austin, Texas.", "I live in Austin.")
    h = _account("dev10@example.com")
    c = TestClient(app)
    r = c.post("/v1/remember", headers=h, json={
        "text": "I live in Austin.", "user_id": "u1"}).json()
    assert r["results"][0]["verdict"] == "stored"
    assert r["results"][0]["grounding"] == "verified"
    found = c.post("/v1/memories/search", headers=h, json={
        "query": "where do I live", "user_id": "u1", "threshold": 0.05}).json()["results"]
    assert found and any("evidence verified" in w for w in found[0]["why"]), \
        "every retrieval must explain itself"


def test_v1_revision_detection_supersedes_and_closes_window():
    h = _account("dev11@example.com")
    c = TestClient(app)
    devapi_module.extract_understandings = _extract_returning(
        "identity", "Location", "You live in Austin, Texas.", "I live in Austin.")
    c.post("/v1/remember", headers=h, json={"text": "I live in Austin.", "user_id": "u1"})
    devapi_module.extract_understandings = _extract_returning(
        "identity", "Current location", "You live in Denver, Colorado.",
        "I live in Denver now.")
    r = c.post("/v1/remember", headers=h, json={
        "text": "I live in Denver now.", "user_id": "u1"}).json()
    assert r["results"][0]["event"] == "REVISION", \
        "a restated slot with a new value is a revision, not a contradiction"
    present = c.post("/v1/memories/search", headers=h, json={
        "query": "where do I live", "user_id": "u1", "threshold": 0.05}).json()["results"]
    assert present and "Denver" in present[0]["memory"]
    assert all("Austin" not in x["memory"] for x in present)
    health = c.get("/v1/memory_health", headers=h, params={"user_id": "u1"}).json()
    assert health["superseded"] >= 1 and health["contradictions"] == 0
    assert health["grounded_pct"] == 1.0


def test_v1_duplicate_never_restored():
    devapi_module.extract_understandings = _extract_returning(
        "identity", "Location", "You live in Austin, Texas.", "I live in Austin.")
    h = _account("dev12@example.com")
    c = TestClient(app)
    c.post("/v1/remember", headers=h, json={"text": "I live in Austin.", "user_id": "u1"})
    r = c.post("/v1/remember", headers=h, json={
        "text": "I live in Austin.", "user_id": "u1"}).json()
    assert r["results"] == [] and len(r["skipped_duplicates"]) == 1, \
        "recalled memories re-fed as input must not multiply in storage"
    lst = c.get("/v1/memories", headers=h, params={"user_id": "u1"}).json()["results"]
    assert len(lst) == 1


def test_v1_unknowns_are_questions_not_claims():
    devapi_module.extract_understandings = _extract_returning(
        "unknown", "Ledgerly's business model",
        "You mention Ledgerly often, but what the company does is not understood yet.",
        "no quote could ground an absence")
    h = _account("dev14@example.com")
    c = TestClient(app)
    r = c.post("/v1/remember", headers=h, json={
        "text": " standup at Ledgerly moved to nine thirty.", "user_id": "u1"}).json()
    assert r["results"] and r["results"][0]["grounding"] == "question", \
        "an unknown asserts ignorance; the gate guards claims, not questions"
    assert r["rejected"] == []


def test_v1_memory_health_shape():
    h = _account("dev13@example.com")
    c = TestClient(app)
    c.post("/v1/memories", headers=h, json={
        "text": "My manager is Ruth.", "user_id": "u1", "infer": False})
    health = c.get("/v1/memory_health", headers=h, params={"user_id": "u1"}).json()
    for key in ("active_memories", "grounded_pct", "stale", "contradictions",
                "superseded", "unknowns", "rejected_writes", "gate_pass_rate",
                "orphaned_graph_edges", "coverage", "recent_rejections"):
        assert key in health, f"memory health must report {key}"
    assert health["coverage"]["of"] == 10
    assert health["active_memories"] == 1


def test_v1_graph_from_people_and_projects():
    c = TestClient(app)
    r = c.post("/api/register", json={"email": "dev6@example.com", "password": "password123"})
    assert r.status_code == 200
    c.post("/api/memories", json={"kind": "person", "title": "Dana",
                                  "body": "Dana is my co-founder."})
    key = c.post("/api/keys", json={"name": "g"}).json()["key"]
    g = c.get("/v1/graph", headers={"Authorization": f"Bearer {key}"}).json()
    assert any(n["name"] == "Dana" and n["kind"] == "person" for n in g["nodes"])
    assert any(e["dst_name"] == "Dana" and e["relation"] == "works_with" for e in g["edges"])


def test_v1_migration_import_keeps_superseded_as_of_history():
    """--push must import closed validity windows, not drop superseded rows."""
    h = _account("migrate-push@example.com")
    c = TestClient(app)
    portland = c.post("/v1/memories", headers=h, json={
        "text": "User lives in Portland.", "user_id": "user-42", "infer": False,
        "valid_from": "2025-03-04T12:00:00Z", "valid_to": "2025-11-18T12:00:00Z",
        "metadata": {"migration_status": "superseded"},
    })
    assert portland.status_code == 200
    austin = c.post("/v1/memories", headers=h, json={
        "text": "User moved to Austin.", "user_id": "user-42", "infer": False,
        "valid_from": "2025-11-18T12:00:00Z", "valid_to": "2026-06-22T12:00:00Z",
        "metadata": {"migration_status": "superseded"},
    })
    assert austin.status_code == 200
    denver = c.post("/v1/memories", headers=h, json={
        "text": "User lives in Denver.", "user_id": "user-42", "infer": False,
        "valid_from": "2026-06-22T12:00:00Z",
        "metadata": {"migration_status": "current"},
    })
    assert denver.status_code == 200
    present = c.post("/v1/memories/search", headers=h, json={
        "query": "where does the user live", "user_id": "user-42",
        "threshold": 0.05}).json()["results"]
    assert present and any("Denver" in r["memory"] for r in present)
    assert all("Portland" not in r["memory"] and "Austin" not in r["memory"] for r in present)
    in_portland = c.post("/v1/memories/search", headers=h, json={
        "query": "where does the user live", "user_id": "user-42",
        "as_of": "2025-06-01T00:00:00Z", "threshold": 0.05}).json()["results"]
    assert any("Portland" in r["memory"] for r in in_portland)
    in_austin = c.post("/v1/memories/search", headers=h, json={
        "query": "where does the user live", "user_id": "user-42",
        "as_of": "2026-01-15T00:00:00Z", "threshold": 0.05}).json()["results"]
    assert any("Austin" in r["memory"] for r in in_austin)
    pid = portland.json()["results"][0]["id"]
    events = [e["event"] for e in c.get(f"/v1/memories/{pid}/history", headers=h).json()["history"]]
    assert events == ["ADD", "INVALIDATE"]


def test_migrate_push_sends_superseded_rows(monkeypatch):
    import importlib.util
    import urllib.request

    migrate_path = os.path.join(os.path.dirname(__file__), "..", "scripts", "migrate.py")
    spec = importlib.util.spec_from_file_location("migrate_script", migrate_path)
    migrate = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(migrate)

    sent = []

    class FakeResp:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake_urlopen(req):
        sent.append(json.loads(req.data.decode()))
        return FakeResp()

    monkeypatch.setenv("MEMLINE_API_KEY", "ml_test")
    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    cleaned = [
        {"user_id": "u", "body": "User lives in Denver.", "valid_from": "2026-06-22T12:00:00Z",
         "valid_to": None, "migration": "current"},
        {"user_id": "u", "body": "User lives in Portland.", "valid_from": "2025-03-04T12:00:00Z",
         "valid_to": "2025-11-18T12:00:00Z", "migration": "superseded"},
    ]
    n = migrate.push(cleaned, "http://example.test")
    assert n == 2
    assert len(sent) == 2
    assert sent[0]["text"] == "User lives in Portland."
    assert sent[0]["valid_to"] == "2025-11-18T12:00:00Z"
    assert "valid_to" not in sent[1]
    assert sent[1]["text"] == "User lives in Denver."

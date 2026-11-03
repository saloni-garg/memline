"""Memline API. Fresh build, product-first (see PRODUCT.md)."""
import io
import json
import os
import zipfile
from datetime import datetime, timezone

from fastapi import Depends, FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .db import db, init_db, now, row_dict
from .understanding import (UnderstandingUnavailable, extract_understandings,
                            starter_memories, top_insights)
from .packs import build_pack
from .security import check_password, hash_password, new_token

PLANS = {
    "free": {"label": "Free", "price_usd": 0, "active_memories": 25, "packs_per_month": 5, "mcp": "read"},
    "pro": {"label": "Pro", "price_usd": 19, "active_memories": 100000, "packs_per_month": 100000, "mcp": "read+write"},
}

STATIC = os.path.join(os.path.dirname(__file__), "static")
app = FastAPI(title="Memline")
init_db()


# ---------- auth ----------

class Credentials(BaseModel):
    email: str
    password: str


def current_user(request: Request) -> dict:
    token = request.cookies.get("ml_session", "")
    with db() as conn:
        row = conn.execute(
            "SELECT u.* FROM sessions s JOIN users u ON u.id = s.user_id WHERE s.token = ?",
            (token,),
        ).fetchone()
    if not row:
        raise HTTPException(401, "Please sign in.")
    return dict(row)


def _start_session(user_id: int) -> JSONResponse:
    token = new_token()
    with db() as conn:
        conn.execute("INSERT INTO sessions(token, user_id, created_at) VALUES (?,?,?)",
                     (token, user_id, now()))
    resp = JSONResponse({"ok": True})
    resp.set_cookie("ml_session", token, httponly=True, samesite="lax", max_age=60 * 60 * 24 * 30)
    return resp


@app.post("/api/register")
def register(creds: Credentials):
    email = creds.email.strip().lower()
    if "@" not in email or len(creds.password) < 8:
        raise HTTPException(400, "Use a valid email and a password of 8 or more characters.")
    with db() as conn:
        if conn.execute("SELECT 1 FROM users WHERE email = ?", (email,)).fetchone():
            raise HTTPException(400, "That email already has an account. Try signing in.")
        cur = conn.execute("INSERT INTO users(email, pw_hash, plan, created_at) VALUES (?,?, 'free', ?)",
                           (email, hash_password(creds.password), now()))
    return _start_session(cur.lastrowid)


@app.post("/api/login")
def login(creds: Credentials):
    with db() as conn:
        row = conn.execute("SELECT * FROM users WHERE email = ?",
                           (creds.email.strip().lower(),)).fetchone()
    if not row or not check_password(creds.password, row["pw_hash"]):
        raise HTTPException(401, "Email or password did not match.")
    return _start_session(row["id"])


@app.post("/api/logout")
def logout(request: Request):
    with db() as conn:
        conn.execute("DELETE FROM sessions WHERE token = ?", (request.cookies.get("ml_session", ""),))
    resp = JSONResponse({"ok": True})
    resp.delete_cookie("ml_session")
    return resp


COVERAGE_DIMENSIONS = [
    ("identity", "Identity", ["identity"]),
    ("goals", "Current goals", ["goal"]),
    ("writing_style", "Writing style", ["style"]),
    ("preferences", "Preferences", ["preference"]),
    ("principles", "Principles", ["principle"]),
    ("projects", "Active projects", ["project"]),
    ("relationships", "Relationships", ["person"]),
    ("unknowns", "Unknowns identified", ["unknown"]),
]


def _coverage(user: dict) -> list[dict]:
    """Understanding Coverage: which dimensions of the person the model
    actually covers. Breadth across dimensions predicts perceived
    continuity better than raw counts, so this is a headline metric."""
    with db() as conn:
        rows = conn.execute(
            "SELECT kind, COUNT(*) c FROM memories WHERE user_id = ? AND status = 'active' GROUP BY kind",
            (user["id"],)).fetchall()
    counts = {row["kind"]: row["c"] for row in rows}
    return [{"key": key, "label": label,
             "covered": any(counts.get(k, 0) > 0 for k in kinds),
             "count": sum(counts.get(k, 0) for k in kinds)}
            for key, label, kinds in COVERAGE_DIMENSIONS]


@app.get("/api/me")
def me(user: dict = Depends(current_user)):
    return {"email": user["email"], "plan": user["plan"], "usage": _usage(user),
            "coverage": _coverage(user)}


@app.get("/api/memory-health")
def memory_health(user: dict = Depends(current_user)):
    """Memory Integrity for the signed-in user: how grounded, stale and
    contradictory their own store is. Quality you can see, not trust."""
    from .integrity import memory_health as _health
    with db() as conn:
        return _health(conn, user["id"], "")


@app.post("/api/demo")
def demo():
    """One-click live demo: a seeded account so anyone can feel the product
    in under a minute, no signup form first."""
    email = "demo@memline.app"
    with db() as conn:
        row = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
        if not row:
            cur = conn.execute(
                "INSERT INTO users(email, pw_hash, plan, created_at) VALUES (?, ?, 'pro', ?)",
                (email, hash_password(new_token()), now()))
            user_id = cur.lastrowid
            needs_seed = True
        else:
            user_id = row["id"]
            has_goal = conn.execute(
                "SELECT 1 FROM memories WHERE user_id = ? AND kind = 'goal' AND status = 'active'",
                (user_id,)).fetchone()
            needs_seed = not has_goal
            if needs_seed:
                conn.execute("DELETE FROM memories WHERE user_id = ?", (user_id,))
        if needs_seed:
            seed = [
                ("identity", "Who she is", "You are a freelance brand consultant working with early-stage startups, increasingly positioning as a small studio rather than a solo freelancer.", "", 1),
                ("identity", "Location", "You live in Austin, Texas and work US Central hours.", "", 0),
                ("goal", "Studio, not solo", "You are working toward six retainer clients by March so you can hire a part-time designer and stop trading hours for every dollar.", "", 1),
                ("principle", "Scope, not discounts", "When a client pushes on price, you never discount your rate. You reduce the scope instead, and you say so plainly.", "", 1),
                ("style", "Writing voice", "You write short, direct drafts with no corporate filler. Headline first, then the detail. If a sentence sounds like marketing, you cut it.", "", 1),
                ("preference", "Invoice rhythm", "You prefer invoices to be sent on the first Monday of the month.", "", 0),
                ("project", "Pricing workshop", "You are building a pricing workshop for SaaS founders with 10 to 50 employees who sell subscriptions, launching in December.", "Pricing workshop", 0),
                ("person", "Dana", "Dana is your co-founder. She handles operations and scheduling.", "", 0),
                ("unknown", "The waitlist", "You mention a workshop waitlist often, but I don't understand how people join it or how long it is yet.", "", 0),
            ]
            for kind, title, body, project, pinned in seed:
                conn.execute(
                    "INSERT INTO memories(user_id, kind, title, body, project, source, status, pinned, created_at, updated_at)"
                    " VALUES (?,?,?,?,?, 'ChatGPT import', 'active', ?, ?, ?)",
                    (user_id, kind, title, body, project, pinned, now(), now()))
            pending = [
                ("principle", "Teaches while delivering", "You turn client work into teaching as you go: every deliverable comes with the reasoning, because you believe clients who understand the why renew. Three separate engagements show this pattern.", 3,
                 "Across 3 conversations: 'I always walk them through why we chose it, not just what we chose.'"),
                ("unknown", "Why clients churn", "You mention losing two clients in the spring, but I don't understand what actually caused it yet.", 1,
                 "Mentioned in 2 conversations, never explained."),
            ]
            for kind, title, body, support, quote in pending:
                conn.execute(
                    "INSERT INTO memories(user_id, kind, title, body, source, source_quote, status, support_count, created_at, updated_at)"
                    " VALUES (?,?,?,?, 'ChatGPT import', ?, 'pending', ?, ?, ?)",
                    (user_id, kind, title, body, quote, support, now(), now()))
    return _start_session(user_id)


# ---------- helpers ----------

def _usage(user: dict) -> dict:
    month = datetime.now(timezone.utc).strftime("%Y-%m")
    with db() as conn:
        active = conn.execute("SELECT COUNT(*) c FROM memories WHERE user_id = ? AND status = 'active'",
                              (user["id"],)).fetchone()["c"]
        pending = conn.execute("SELECT COUNT(*) c FROM memories WHERE user_id = ? AND status = 'pending'",
                               (user["id"],)).fetchone()["c"]
        packs = conn.execute("SELECT COUNT(*) c FROM packs WHERE user_id = ? AND created_at LIKE ?",
                             (user["id"], month + "%")).fetchone()["c"]
    plan = PLANS[user["plan"]]
    return {"active_memories": active, "pending": pending, "packs_this_month": packs,
            "active_limit": plan["active_memories"], "packs_limit": plan["packs_per_month"]}


def _add_candidates(user_id: int, candidates: list[dict]) -> int:
    """Insert candidates as pending. If an active memory of the same kind and
    title exists with a different body, link it as superseded: replacing old
    facts visibly is a core product promise."""
    added = 0
    with db() as conn:
        for cand in candidates:
            dupe = conn.execute(
                "SELECT 1 FROM memories WHERE user_id = ? AND status IN ('pending','active') AND lower(body) = lower(?)",
                (user_id, cand["body"])).fetchone()
            if dupe:
                continue
            old = conn.execute(
                "SELECT id FROM memories WHERE user_id = ? AND status = 'active' AND kind = ? AND title = ?",
                (user_id, cand["kind"], cand["title"])).fetchone()
            conn.execute(
                "INSERT INTO memories(user_id, kind, title, body, project, source, source_quote, status,"
                " confidence, support_count, created_at, updated_at, supersedes_id) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (user_id, cand["kind"], cand["title"], cand["body"], cand.get("project", ""),
                 cand["source"], cand.get("source_quote", ""), "pending", cand.get("confidence", 1.0),
                 int(cand.get("support", 1)), now(), now(), old["id"] if old else None))
            added += 1
    return added


# ---------- memories ----------

class MemoryIn(BaseModel):
    kind: str = "fact"
    title: str = ""
    body: str
    project: str = ""
    pinned: bool = False


@app.get("/api/memories")
def list_memories(status: str = "active", q: str = "", user: dict = Depends(current_user)):
    sql = "SELECT * FROM memories WHERE user_id = ? AND status = ?"
    args = [user["id"], status]
    if q:
        sql += " AND (body LIKE ? OR title LIKE ? OR project LIKE ?)"
        args += [f"%{q}%"] * 3
    sql += " ORDER BY pinned DESC, updated_at DESC"
    with db() as conn:
        rows = conn.execute(sql, args).fetchall()
        out = []
        for row in rows:
            d = row_dict(row)
            if d.get("supersedes_id"):
                old = conn.execute("SELECT body FROM memories WHERE id = ?", (d["supersedes_id"],)).fetchone()
                d["replaces"] = old["body"] if old else None
            out.append(d)
    return {"memories": out}


@app.post("/api/memories")
def create_memory(mem: MemoryIn, user: dict = Depends(current_user)):
    usage = _usage(user)
    if usage["active_memories"] >= usage["active_limit"]:
        raise HTTPException(402, "Your Free plan holds 25 understandings. Pro removes the limit.")
    with db() as conn:
        cur = conn.execute(
            "INSERT INTO memories(user_id, kind, title, body, project, source, status, pinned, created_at, updated_at)"
            " VALUES (?,?,?,?,?, 'typed by you', 'active', ?, ?, ?)",
            (user["id"], mem.kind, mem.title or "Memory", mem.body, mem.project, int(mem.pinned), now(), now()))
        row = conn.execute("SELECT * FROM memories WHERE id = ?", (cur.lastrowid,)).fetchone()
        from .retrieval import index_memory
        from .graph import index_graph
        index_memory(conn, row)
        index_graph(conn, row)
    return {"memory": row_dict(row)}


@app.post("/api/memories/{memory_id}/approve")
def approve(memory_id: int, user: dict = Depends(current_user)):
    with db() as conn:
        row = conn.execute("SELECT * FROM memories WHERE id = ? AND user_id = ?",
                           (memory_id, user["id"])).fetchone()
        if not row:
            raise HTTPException(404, "Memory not found.")
        usage = _usage(user)
        if usage["active_memories"] >= usage["active_limit"]:
            raise HTTPException(402, "Your Free plan holds 25 understandings. Pro removes the limit.")
        if row["supersedes_id"]:
            conn.execute("UPDATE memories SET status = 'archived', replaced_by = ?, updated_at = ? WHERE id = ?",
                         (memory_id, now(), row["supersedes_id"]))
        project_expires = None
        if row["kind"] == "project":
            from datetime import timedelta
            project_expires = (datetime.now(timezone.utc) + timedelta(days=90)).date().isoformat()
        conn.execute("UPDATE memories SET status = 'active', expires_at = COALESCE(expires_at, ?), updated_at = ? WHERE id = ?",
                     (project_expires, now(), memory_id))
        row = conn.execute("SELECT * FROM memories WHERE id = ?", (memory_id,)).fetchone()
        from .retrieval import index_memory
        from .graph import index_graph
        index_memory(conn, row)
        index_graph(conn, row)
    return {"ok": True}


class SurpriseIn(BaseModel):
    level: int  # 0 = not surprised, 1 = a little surprised, 2 = very surprised


@app.post("/api/memories/{memory_id}/surprise")
def surprise(memory_id: int, payload: SurpriseIn, user: dict = Depends(current_user)):
    """Ground truth for the metric that matters: after approving an
    understanding, the user rates how surprised they were that the system
    figured it out. This label, not the model's own estimate, is what the
    importer learns to maximize."""
    if payload.level not in (0, 1, 2):
        raise HTTPException(400, "level must be 0, 1, or 2")
    with db() as conn:
        cur = conn.execute("UPDATE memories SET surprise_actual = ? WHERE id = ? AND user_id = ?",
                           (payload.level, memory_id, user["id"]))
        if cur.rowcount == 0:
            raise HTTPException(404, "Memory not found.")
    return {"ok": True}


@app.post("/api/memories/{memory_id}/reject")
def reject(memory_id: int, user: dict = Depends(current_user)):
    with db() as conn:
        conn.execute("UPDATE memories SET status = 'rejected', updated_at = ? WHERE id = ? AND user_id = ?",
                     (now(), memory_id, user["id"]))
    return {"ok": True}


@app.post("/api/memories/{memory_id}/archive")
def archive(memory_id: int, user: dict = Depends(current_user)):
    with db() as conn:
        conn.execute("UPDATE memories SET status = 'archived', updated_at = ? WHERE id = ? AND user_id = ?",
                     (now(), memory_id, user["id"]))
    return {"ok": True}


class MemoryPatch(BaseModel):
    body: str | None = None
    title: str | None = None
    pinned: bool | None = None


@app.patch("/api/memories/{memory_id}")
def patch_memory(memory_id: int, patch: MemoryPatch, user: dict = Depends(current_user)):
    with db() as conn:
        row = conn.execute("SELECT * FROM memories WHERE id = ? AND user_id = ?",
                           (memory_id, user["id"])).fetchone()
        if not row:
            raise HTTPException(404, "Memory not found.")
        conn.execute("UPDATE memories SET body = ?, title = ?, pinned = ?, updated_at = ? WHERE id = ?",
                     (patch.body if patch.body is not None else row["body"],
                      patch.title if patch.title is not None else row["title"],
                      int(patch.pinned) if patch.pinned is not None else row["pinned"],
                      now(), memory_id))
        row = conn.execute("SELECT * FROM memories WHERE id = ?", (memory_id,)).fetchone()
    return {"memory": row_dict(row)}


# ---------- capture: paste, starter, import ----------

class ExtractIn(BaseModel):
    text: str
    source: str = "paste"


@app.post("/api/extract")
def extract(payload: ExtractIn, user: dict = Depends(current_user)):
    conversations = [{"title": "Pasted text", "messages": [payload.text]}]
    try:
        candidates = extract_understandings(conversations, source=payload.source)
    except UnderstandingUnavailable:
        raise HTTPException(503, "The understanding engine is not configured on this server yet, so nothing was extracted. Your text was not stored.")
    added = _add_candidates(user["id"], candidates)
    return {"found": len(candidates), "added": added,
            "top_insights": top_insights(candidates) if added else []}


class StarterIn(BaseModel):
    answers: dict


@app.post("/api/starter")
def starter(payload: StarterIn, user: dict = Depends(current_user)):
    added = _add_candidates(user["id"], starter_memories(payload.answers))
    return {"added": added}


def _conversations_from_chatgpt_export(data) -> list[dict]:
    """Structured conversations: title plus the user's own messages, in
    order. Only the user's side is ever read."""
    conversations = []
    convs = data if isinstance(data, list) else [data]
    for conv in convs:
        if not isinstance(conv, dict):
            continue
        messages = []
        mapping = conv.get("mapping", {}) or {}
        for node in mapping.values():
            msg = (node or {}).get("message") or {}
            if (msg.get("author") or {}).get("role") != "user":
                continue
            parts = ((msg.get("content") or {}).get("parts") or [])
            messages += [p for p in parts if isinstance(p, str) and p.strip()]
        if messages:
            conversations.append({"title": conv.get("title") or "ChatGPT conversation",
                                  "messages": messages})
    return conversations


def _conversations_from_claude_export(data) -> list[dict]:
    conversations = []
    convs = data if isinstance(data, list) else [data]
    for conv in convs:
        if not isinstance(conv, dict):
            continue
        messages = [msg.get("text", "") for msg in conv.get("chat_messages", [])
                    if msg.get("sender") == "human" and msg.get("text", "").strip()]
        if messages:
            conversations.append({"title": conv.get("name") or "Claude conversation",
                                  "messages": messages})
    return conversations


@app.post("/api/import")
async def import_file(file: UploadFile = File(...), user: dict = Depends(current_user)):
    raw = await file.read()
    conversations: list[dict] = []
    label = "import"
    try:
        if file.filename.endswith(".zip"):
            with zipfile.ZipFile(io.BytesIO(raw)) as zf:
                for name in zf.namelist():
                    if name.endswith("conversations.json"):
                        conversations += _conversations_from_chatgpt_export(json.loads(zf.read(name)))
                        label = "ChatGPT import"
        elif file.filename.endswith(".json"):
            data = json.loads(raw)
            conversations = _conversations_from_chatgpt_export(data)
            label = "ChatGPT import"
            if not conversations:
                conversations = _conversations_from_claude_export(data)
                label = "Claude import"
        else:
            text = raw.decode("utf-8", errors="ignore")
            conversations = [{"title": file.filename or "Imported text", "messages": [text]}]
    except (zipfile.BadZipFile, json.JSONDecodeError, UnicodeDecodeError):
        raise HTTPException(400, "That file could not be read. Use a ChatGPT or Claude export, or a text file.")
    messages_scanned = sum(len(c["messages"]) for c in conversations)
    if not conversations:
        raise HTTPException(400, "No conversations from you were found in that file. Memline only reads your side of an export.")
    try:
        candidates = extract_understandings(conversations, source=label)
    except UnderstandingUnavailable:
        raise HTTPException(503, "The understanding engine is not configured on this server yet, so nothing was extracted. Your file was not stored.")
    added = _add_candidates(user["id"], candidates)
    by_kind: dict[str, int] = {}
    for cand in candidates:
        by_kind[cand["kind"]] = by_kind.get(cand["kind"], 0) + 1
    return {"messages_scanned": messages_scanned,
            "conversations_scanned": len(conversations),
            "found": len(candidates), "added": added, "by_kind": by_kind,
            "top_insights": top_insights(candidates) if added else [],
            "engine": "understanding-v2"}


# ---------- context packs ----------

class PackIn(BaseModel):
    target: str = "plain"
    project: str = ""


@app.post("/api/packs")
def make_pack(payload: PackIn, user: dict = Depends(current_user)):
    usage = _usage(user)
    if usage["packs_this_month"] >= usage["packs_limit"]:
        raise HTTPException(402, "Your Free plan includes 5 assembled contexts a month. Pro makes them unlimited.")
    with db() as conn:
        rows = conn.execute(
            "SELECT * FROM memories WHERE user_id = ? AND status = 'active'"
            " AND (expires_at IS NULL OR expires_at >= date('now'))"
            " AND (project = '' OR project = ?) ORDER BY pinned DESC, kind, id",
            (user["id"], payload.project)).fetchall()
        if not rows:
            raise HTTPException(400, "No active memories yet. Approve a few in your inbox first.")
        body = build_pack([row_dict(r) for r in rows], payload.target, payload.project)
        cur = conn.execute("INSERT INTO packs(user_id, target, project, body, created_at) VALUES (?,?,?,?,?)",
                           (user["id"], payload.target, payload.project, body, now()))
        pack = conn.execute("SELECT * FROM packs WHERE id = ?", (cur.lastrowid,)).fetchone()
    return {"pack": dict(pack)}


@app.get("/api/packs")
def list_packs(user: dict = Depends(current_user)):
    with db() as conn:
        rows = conn.execute("SELECT id, target, project, created_at FROM packs WHERE user_id = ? ORDER BY id DESC LIMIT 20",
                            (user["id"],)).fetchall()
    return {"packs": [dict(r) for r in rows]}


# ---------- plans ----------

@app.get("/api/plans")
def plans():
    return {"plans": PLANS}


@app.post("/api/upgrade")
def upgrade(user: dict = Depends(current_user)):
    """Pro trial activation. At launch this is replaced by Stripe Checkout;
    plan limits and entitlements are already real in the code."""
    with db() as conn:
        conn.execute("UPDATE users SET plan = 'pro' WHERE id = ?", (user["id"],))
    return {"ok": True, "plan": "pro", "note": "Pro trial active. Paid checkout opens at launch via Stripe."}


# ---------- API keys and hosted MCP ----------

from .apiauth import hash_key as _hash_key, user_for_api_key as _user_for_api_key  # noqa: E402


class KeyIn(BaseModel):
    name: str = "My assistants"


@app.post("/api/keys")
def create_key(payload: KeyIn, user: dict = Depends(current_user)):
    key = "ml_" + new_token()
    with db() as conn:
        cur = conn.execute(
            "INSERT INTO api_keys(user_id, name, prefix, key_hash, created_at) VALUES (?,?,?,?,?)",
            (user["id"], payload.name, key[:10], _hash_key(key), now()))
        row = conn.execute("SELECT id, name, prefix, created_at FROM api_keys WHERE id = ?",
                           (cur.lastrowid,)).fetchone()
    return {"key": key, "record": dict(row),
            "note": "Copy this key now. For safety we only store a hash, so it cannot be shown again."}


@app.get("/api/keys")
def list_keys(user: dict = Depends(current_user)):
    with db() as conn:
        rows = conn.execute(
            "SELECT id, name, prefix, created_at, last_used_at FROM api_keys WHERE user_id = ? ORDER BY id DESC",
            (user["id"],)).fetchall()
    return {"keys": [dict(r) for r in rows]}


@app.delete("/api/keys/{key_id}")
def delete_key(key_id: int, user: dict = Depends(current_user)):
    with db() as conn:
        conn.execute("DELETE FROM api_keys WHERE id = ? AND user_id = ?", (key_id, user["id"]))
    return {"ok": True}


@app.post("/mcp")
async def mcp_http(request: Request):
    """Hosted MCP endpoint (streamable-HTTP style JSON-RPC over POST).
    Assistants connect with the user's API key; propose_memory still lands
    in the approval inbox, never straight into the memory."""
    user = _user_for_api_key(request)
    from .mcp_server import TOOLS, call_tool
    body = await request.json()
    method, req_id = body.get("method", ""), body.get("id")
    if method == "initialize":
        result = {"protocolVersion": "2024-11-05", "capabilities": {"tools": {}},
                  "serverInfo": {"name": "memline", "version": "0.1.0"}}
    elif method == "tools/list":
        result = {"tools": TOOLS}
    elif method == "tools/call":
        params = body.get("params", {})
        try:
            text = call_tool(params.get("name", ""), params.get("arguments", {}), user["id"])
            result = {"content": [{"type": "text", "text": text}]}
        except Exception as exc:
            result = {"content": [{"type": "text", "text": f"Error: {exc}"}], "isError": True}
    elif req_id is None:
        return JSONResponse({}, status_code=202)
    else:
        result = {}
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


# ---------- export and account deletion ----------

@app.get("/api/export")
def export_data(user: dict = Depends(current_user)):
    with db() as conn:
        memories = [row_dict(r) for r in conn.execute(
            "SELECT * FROM memories WHERE user_id = ? ORDER BY id", (user["id"],)).fetchall()]
        packs = [dict(r) for r in conn.execute(
            "SELECT id, target, project, body, created_at FROM packs WHERE user_id = ? ORDER BY id",
            (user["id"],)).fetchall()]
    payload = {"exported_at": now(), "account": {"email": user["email"], "plan": user["plan"]},
               "memories": memories, "context_packs": packs}
    return JSONResponse(payload, headers={
        "Content-Disposition": "attachment; filename=memline-export.json"})


class DeleteAccountIn(BaseModel):
    password: str


@app.delete("/api/account")
def delete_account(payload: DeleteAccountIn, request: Request, user: dict = Depends(current_user)):
    if not check_password(payload.password, user["pw_hash"]):
        raise HTTPException(401, "Password did not match. Account not deleted.")
    with db() as conn:
        for table in ("memories", "packs", "api_keys", "sessions", "memory_events", "entities", "edges", "write_rejections"):
            conn.execute(f"DELETE FROM {table} WHERE user_id = ?", (user["id"],))
        conn.execute("DELETE FROM users WHERE id = ?", (user["id"],))
    resp = JSONResponse({"ok": True, "note": "Your account and all of its data are deleted."})
    resp.delete_cookie("ml_session")
    return resp


# ---------- pages ----------

@app.get("/")
def landing():
    return FileResponse(os.path.join(STATIC, "index.html"))


@app.get("/app")
def app_page():
    return FileResponse(os.path.join(STATIC, "app.html"))


@app.get("/api-docs")
def api_docs_page():
    return FileResponse(os.path.join(STATIC, "api.html"))


@app.get("/terms")
def terms_page():
    return FileResponse(os.path.join(STATIC, "terms.html"))


@app.get("/privacy")
def privacy_page():
    return FileResponse(os.path.join(STATIC, "privacy.html"))


from .devapi import router as dev_router  # noqa: E402

app.include_router(dev_router)

app.mount("/static", StaticFiles(directory=STATIC), name="static")

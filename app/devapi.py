"""Developer REST API (/v1): the Mem0-parity platform layer.

Same shape as Mem0's API (add, search, get, update, delete, history,
scoped by user_id / agent_id / app_id / run_id) so an app built on Mem0
can switch by changing its base URL and key. The differences are the
product: memories here are typed understandings with evidence,
confidence, support counts and temporal validity windows, search is a
transparent hybrid (semantic + lexical + graph) whose score components
are returned, and /v1/profile returns the whole understanding profile,
not just facts.

Auth: the account's Memline API key (Bearer ml_...). The key's account
is the tenant; user_id and friends scope end users inside it.
"""
import json

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from .apiauth import user_for_api_key
from .db import db, now
from .graph import fetch_graph, index_graph
from .retrieval import index_memory, record_event, run_decay, search as hybrid_search
from .understanding import UnderstandingUnavailable, extract_understandings

router = APIRouter(prefix="/v1")


class AddIn(BaseModel):
    messages: list[dict] | None = None
    text: str | None = None
    user_id: str = ""
    agent_id: str = ""
    app_id: str = ""
    run_id: str = ""
    metadata: dict = {}
    infer: bool = True


class SearchIn(BaseModel):
    query: str
    user_id: str = ""
    agent_id: str = ""
    app_id: str = ""
    run_id: str = ""
    limit: int = 10
    as_of: str | None = None
    threshold: float = 0.0


class UpdateIn(BaseModel):
    text: str
    metadata: dict | None = None


def _serialize(row) -> dict:
    return {
        "id": row["id"], "memory": row["body"], "title": row["title"],
        "kind": row["kind"],
        "user_id": row["ext_user_id"] or None,
        "agent_id": row["agent_id"] or None,
        "app_id": row["app_id"] or None,
        "run_id": row["run_id"] or None,
        "evidence": row["source_quote"] or None,
        "grounding": (row["grounding"] or None) if "grounding" in row.keys() else None,
        "confidence": row["confidence"], "support_count": row["support_count"],
        "valid_from": row["valid_from"], "valid_to": row["valid_to"],
        "created_at": row["created_at"], "updated_at": row["updated_at"],
        "metadata": json.loads(row["metadata"] or "{}"),
    }


def _scope_args(payload) -> tuple[str, str, str, str]:
    return (payload.user_id or "", payload.agent_id or "",
            payload.app_id or "", payload.run_id or "")


@router.post("/memories")
@router.post("/remember")
def add_memories(payload: AddIn, user: dict = Depends(user_for_api_key)):
    """Add with the write gate. Machine-extracted candidates are checked
    before storage: evidence must be grounded in this call's source text
    (ungrounded candidates are rejected with a reason, never stored),
    duplicates of active memories are skipped (stored memories cannot
    multiply by being recalled and re-fed), and candidates that restate
    an existing slot supersede it as a REVISION, closing its validity
    window instead of coexisting as a contradiction. /remember is the
    same operation under the name that says what it guarantees."""
    ext_user, agent_id, app_id, run_id = _scope_args(payload)
    texts: list[str] = []
    if payload.messages:
        for msg in payload.messages:
            content = (msg or {}).get("content", "")
            if isinstance(content, str) and content.strip():
                texts.append(content)
    if payload.text:
        texts.append(payload.text)
    if not texts:
        raise HTTPException(400, "Provide messages or text.")
    source_text = "\n".join(texts)

    candidates: list[dict] = []
    engine = "understanding-v2"
    extracted = False
    if payload.infer:
        conversations = [{"title": "API conversation", "messages": texts}]
        try:
            candidates = extract_understandings(conversations, source="api")
            extracted = bool(candidates)
        except UnderstandingUnavailable:
            candidates = []
            engine = "verbatim-fallback (understanding engine not configured)"
    if not candidates:
        joined = " ".join(texts)
        candidates = [{"kind": "fact", "title": "Memory", "body": joined,
                       "source": "api", "source_quote": joined[:300],
                       "confidence": 1.0, "support": 1}]
        engine = "verbatim" if not payload.infer else engine

    from .gate import find_duplicate, find_revision, grounding_check, record_rejection
    scope = (ext_user, agent_id, app_id)
    results, rejected, skipped = [], [], []
    with db() as conn:
        for cand in candidates:
            if extracted and cand["kind"] == "unknown":
                # An unknown is not a claim; it asserts ignorance, not a
                # fact. The gate guards assertions, so unknowns pass
                # labeled as questions (caught live: the gate rejected
                # "Ledgerly's business model" for lacking evidence,
                # which is precisely what an unknown is).
                grounding = "question"
            elif extracted:
                label, gscore = grounding_check(cand.get("source_quote", ""), source_text)
                if label == "unverified":
                    reason = ("evidence not found in the source conversation "
                              f"(grounding score {gscore:.2f}); refused rather than stored unverified")
                    record_rejection(conn, user["id"], ext_user, cand, reason, gscore)
                    rejected.append({"memory": cand["body"], "title": cand["title"],
                                     "kind": cand["kind"], "verdict": "rejected",
                                     "reason": reason})
                    continue
                grounding = label
            else:
                grounding = "asserted"
            dup = find_duplicate(conn, user["id"], scope, cand)
            if dup:
                skipped.append({"memory": cand["body"], "title": cand["title"],
                                "kind": cand["kind"], "verdict": "skipped",
                                "reason": "already stored; duplicates never re-enter storage",
                                "existing_id": dup["id"]})
                continue
            event = "ADD"
            supersedes = None
            old = conn.execute(
                "SELECT * FROM memories WHERE user_id = ? AND status = 'active'"
                " AND kind = ? AND title = ? AND ext_user_id = ? AND agent_id = ? AND app_id = ?",
                (user["id"], cand["kind"], cand["title"], ext_user, agent_id, app_id)).fetchone()
            # Supersede only for genuinely titled understandings. Generic
            # verbatim adds all share the fallback title "Memory", and
            # treating them as replacements would archive the previous
            # fact on every add (found in smoke testing, 2026-11-02).
            if old and old["body"] != cand["body"] and cand["title"] not in ("", "Memory"):
                event = "UPDATE"
            else:
                old = find_revision(conn, user["id"], scope, cand)
                if old:
                    event = "REVISION"
            if old:
                conn.execute(
                    "UPDATE memories SET status = 'archived', valid_to = ?, updated_at = ? WHERE id = ?",
                    (now(), now(), old["id"]))
                record_event(conn, old["id"], user["id"],
                             "SUPERSEDE" if event == "UPDATE" else "REVISION",
                             old["body"], cand["body"])
                supersedes = old["id"]
            cur = conn.execute(
                "INSERT INTO memories(user_id, kind, title, body, project, source, source_quote,"
                " status, confidence, support_count, ext_user_id, agent_id, app_id, run_id,"
                " metadata, valid_from, supersedes_id, grounding, created_at, updated_at)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (user["id"], cand["kind"], cand["title"], cand["body"], cand.get("project", ""),
                 "api", cand.get("source_quote", ""), "active", cand.get("confidence", 1.0),
                 int(cand.get("support", 1)), ext_user, agent_id, app_id, run_id,
                 json.dumps(payload.metadata or {}), now(), supersedes, grounding, now(), now()))
            if supersedes:
                conn.execute("UPDATE memories SET replaced_by = ? WHERE id = ?",
                             (cur.lastrowid, supersedes))
            row = conn.execute("SELECT * FROM memories WHERE id = ?", (cur.lastrowid,)).fetchone()
            index_memory(conn, row)
            index_graph(conn, row)
            record_event(conn, row["id"], user["id"], event, "", row["body"])
            result = _serialize(row)
            result["event"] = event
            result["verdict"] = "stored"
            result["grounding"] = grounding
            results.append(result)
    return {"results": results, "rejected": rejected,
            "skipped_duplicates": skipped,
            "gate": {"checked": len(candidates), "stored": len(results),
                     "rejected": len(rejected), "skipped": len(skipped)},
            "engine": engine}


@router.get("/memory_health")
def memory_health(user_id: str = "", user: dict = Depends(user_for_api_key)):
    """Memory Integrity: grounded share, stale count, contradictions,
    superseded count, unknowns, gate pass rate, coverage. The numbers
    no other memory layer publishes about its own store."""
    from .integrity import memory_health as _health
    with db() as conn:
        run_decay(conn, user["id"])
        return _health(conn, user["id"], user_id)


@router.get("/rejections")
def rejections(user_id: str = "", limit: int = 20,
               user: dict = Depends(user_for_api_key)):
    """What the write gate refused, and why. Hallucinations a memory
    layer declined to store are a feature; here is the receipt."""
    with db() as conn:
        rows = conn.execute(
            "SELECT * FROM write_rejections WHERE user_id = ? AND ext_user_id = ?"
            " ORDER BY id DESC LIMIT ?",
            (user["id"], user_id, max(1, min(limit, 100)))).fetchall()
    return {"rejections": [dict(r) for r in rows]}


@router.post("/memories/search")
def search_memories(payload: SearchIn, user: dict = Depends(user_for_api_key)):
    ext_user, agent_id, app_id, run_id = _scope_args(payload)
    with db() as conn:
        run_decay(conn, user["id"])
        results = hybrid_search(conn, user["id"], payload.query, ext_user, agent_id,
                                app_id, run_id, limit=max(1, min(payload.limit, 100)),
                                as_of=payload.as_of)
    if payload.threshold > 0:
        results = [r for r in results if r["score"] >= payload.threshold]
    return {"results": results}


@router.get("/memories")
def list_memories(user_id: str = "", agent_id: str = "", app_id: str = "",
                  limit: int = 100, offset: int = 0,
                  user: dict = Depends(user_for_api_key)):
    sql = "SELECT * FROM memories WHERE user_id = ? AND status = 'active'"
    args: list = [user["id"]]
    for col, val in (("ext_user_id", user_id), ("agent_id", agent_id), ("app_id", app_id)):
        if val:
            sql += f" AND {col} = ?"
            args.append(val)
    sql += " ORDER BY id DESC LIMIT ? OFFSET ?"
    args += [max(1, min(limit, 500)), max(0, offset)]
    with db() as conn:
        run_decay(conn, user["id"])
        rows = conn.execute(sql, args).fetchall()
    return {"results": [_serialize(r) for r in rows]}


def _owned_memory(conn, memory_id: int, account_id: int):
    row = conn.execute("SELECT * FROM memories WHERE id = ? AND user_id = ?",
                       (memory_id, account_id)).fetchone()
    if not row:
        raise HTTPException(404, "Memory not found.")
    return row


@router.get("/memories/{memory_id}")
def get_memory(memory_id: int, user: dict = Depends(user_for_api_key)):
    with db() as conn:
        return _serialize(_owned_memory(conn, memory_id, user["id"]))


@router.put("/memories/{memory_id}")
def update_memory(memory_id: int, payload: UpdateIn, user: dict = Depends(user_for_api_key)):
    with db() as conn:
        row = _owned_memory(conn, memory_id, user["id"])
        meta = payload.metadata if payload.metadata is not None else json.loads(row["metadata"] or "{}")
        conn.execute("UPDATE memories SET body = ?, metadata = ?, updated_at = ? WHERE id = ?",
                     (payload.text, json.dumps(meta), now(), memory_id))
        record_event(conn, memory_id, user["id"], "UPDATE", row["body"], payload.text)
        row = conn.execute("SELECT * FROM memories WHERE id = ?", (memory_id,)).fetchone()
        index_memory(conn, row)
        index_graph(conn, row)
        return _serialize(row)


@router.delete("/memories/{memory_id}")
def delete_memory(memory_id: int, user: dict = Depends(user_for_api_key)):
    with db() as conn:
        row = _owned_memory(conn, memory_id, user["id"])
        record_event(conn, memory_id, user["id"], "DELETE", row["body"], "")
        conn.execute("DELETE FROM edges WHERE memory_id = ?", (memory_id,))
        conn.execute("DELETE FROM memories WHERE id = ?", (memory_id,))
    return {"message": "Memory deleted successfully!"}


@router.delete("/memories")
def delete_all_memories(user_id: str = "", agent_id: str = "", app_id: str = "",
                        user: dict = Depends(user_for_api_key)):
    sql = "SELECT * FROM memories WHERE user_id = ? AND status = 'active'"
    args: list = [user["id"]]
    for col, val in (("ext_user_id", user_id), ("agent_id", agent_id), ("app_id", app_id)):
        if val:
            sql += f" AND {col} = ?"
            args.append(val)
    with db() as conn:
        rows = conn.execute(sql, args).fetchall()
        for row in rows:
            record_event(conn, row["id"], user["id"], "DELETE", row["body"], "")
            conn.execute("DELETE FROM edges WHERE memory_id = ?", (row["id"],))
            conn.execute("DELETE FROM memories WHERE id = ?", (row["id"],))
    return {"message": f"{len(rows)} memories deleted."}


@router.get("/memories/{memory_id}/history")
def memory_history(memory_id: int, user: dict = Depends(user_for_api_key)):
    with db() as conn:
        _owned_or_event = conn.execute(
            "SELECT 1 FROM memories WHERE id = ? AND user_id = ?", (memory_id, user["id"])).fetchone()
        events = conn.execute(
            "SELECT * FROM memory_events WHERE memory_id = ? AND user_id = ? ORDER BY id",
            (memory_id, user["id"])).fetchall()
        if not events and not _owned_or_event:
            raise HTTPException(404, "Memory not found.")
    return {"history": [{"id": e["id"], "event": e["event"], "old_memory": e["old_body"] or None,
                         "new_memory": e["new_body"] or None, "created_at": e["created_at"]}
                        for e in events]}


@router.post("/memories/{memory_id}/invalidate")
def invalidate_memory(memory_id: int, user: dict = Depends(user_for_api_key)):
    """Temporal correction: the memory stops being true now, without
    being deleted. Present-day searches stop returning it; as-of searches
    into the past still do. Mem0 has no equivalent short of deletion."""
    with db() as conn:
        row = _owned_memory(conn, memory_id, user["id"])
        conn.execute("UPDATE memories SET valid_to = ?, updated_at = ? WHERE id = ?",
                     (now(), now(), memory_id))
        record_event(conn, memory_id, user["id"], "INVALIDATE", row["body"], "")
        row = conn.execute("SELECT * FROM memories WHERE id = ?", (memory_id,)).fetchone()
        return _serialize(row)


@router.get("/graph")
def graph(user_id: str = "", user: dict = Depends(user_for_api_key)):
    with db() as conn:
        return fetch_graph(conn, user["id"], user_id)


class AssembleIn(BaseModel):
    query: str
    user_id: str = ""
    agent_id: str = ""
    app_id: str = ""
    run_id: str = ""
    max_tokens: int = 1500


def _est_tokens(text: str) -> int:
    return max(1, len(text) // 4)


@router.post("/assemble_context")
def assemble_context(payload: AssembleIn, user: dict = Depends(user_for_api_key)):
    """The one-call endpoint: give a task, get back context that is ready
    to paste into a prompt. Developers should not have to rebuild the
    planner: retrieval, ranking, kind-grouped assembly, token budgeting,
    and the honesty layer (what was omitted, what is not understood, how
    confident the included set is) all happen here."""
    from .packs import KIND_HEADINGS
    ext_user, agent_id, app_id, run_id = _scope_args(payload)
    budget = max(100, min(payload.max_tokens, 20000))
    with db() as conn:
        run_decay(conn, user["id"])
        candidates = hybrid_search(conn, user["id"], payload.query, ext_user, agent_id,
                                   app_id, run_id, limit=25)
        moment = now()
        unknown_rows = conn.execute(
            "SELECT * FROM memories WHERE user_id = ? AND status = 'active' AND kind = 'unknown'"
            " AND ext_user_id = ? AND (valid_from IS NULL OR valid_from <= ?)"
            " AND (valid_to IS NULL OR valid_to > ?) ORDER BY id",
            (user["id"], ext_user, moment, moment)).fetchall()

    intro = (f"Context about the user, assembled for this task: {payload.query}\n"
             "Treat it as standing background. Where it is silent, ask rather than guess.")
    included: list[dict] = []
    omitted: list[dict] = []
    used = _est_tokens(intro) + 40  # headings and unknowns header allowance
    for cand in candidates:
        cost = _est_tokens(f"{cand['title']}: {cand['memory']}") + 6
        if used + cost <= budget:
            included.append(cand)
            used += cost
        else:
            omitted.append({"id": cand["id"], "memory": cand["memory"],
                            "kind": cand["kind"], "score": cand["score"],
                            "reason": "token_budget"})

    by_kind: dict[str, list[dict]] = {}
    for cand in included:
        by_kind.setdefault(cand["kind"], []).append(cand)
    lines = [intro, ""]
    for kind, heading in KIND_HEADINGS:
        items = by_kind.get(kind)
        if not items:
            continue
        lines.append(f"## {heading}")
        for item in items:
            label = f"**{item['title']}:** " if item["title"] else ""
            lines.append(f"- {label}{item['memory']}")
        lines.append("")
    unknowns = [_serialize(r) for r in unknown_rows]
    if unknowns:
        lines.append("## What is not understood about this user yet (do not guess these)")
        for unk in unknowns:
            lines.append(f"- **{unk['title']}:** {unk['memory']}")
        lines.append("")
    context_text = "\n".join(lines).strip()
    mean_conf = (sum(c["confidence"] for c in included) / len(included)) if included else 0.0
    mean_support = (sum(c["support_count"] for c in included) / len(included)) if included else 0.0
    return {
        "query": payload.query,
        "context": context_text,
        "supporting_understandings": included,
        "omitted_understandings": omitted,
        "unknowns": unknowns,
        "confidence": {"mean_confidence": round(mean_conf, 3),
                       "mean_support": round(mean_support, 2),
                       "based_on": len(included)},
        "tokens_estimated": _est_tokens(context_text),
        "max_tokens": budget,
    }


@router.get("/understanding")
@router.get("/profile")
def profile(user_id: str = "", user: dict = Depends(user_for_api_key)):
    """The understanding for one end user: every active memory grouped by
    kind, plus unknowns. Primary name is /understanding (that is what it
    is); /profile remains as an alias. This is the endpoint Mem0 does not
    have: not what the user said, but who the system understands them
    to be, with the gaps stated."""
    with db() as conn:
        run_decay(conn, user["id"])
        rows = conn.execute(
            "SELECT * FROM memories WHERE user_id = ? AND status = 'active' AND ext_user_id = ?"
            " ORDER BY kind, id",
            (user["id"], user_id)).fetchall()
    grouped: dict[str, list] = {}
    for row in rows:
        grouped.setdefault(row["kind"], []).append(_serialize(row))
    return {"user_id": user_id or None, "profile": grouped,
            "kinds_covered": sorted(grouped.keys()),
            "total": len(rows)}

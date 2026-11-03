"""Hybrid retrieval for the developer platform.

Every memory gets an embedding at write time. Search combines:
- semantic similarity (cosine over embeddings),
- lexical overlap (token F1 between query and memory text),
- a graph boost when the query names an entity the memory is linked to,
- validity filtering: a memory is only returned when the search moment
  (as_of, default now) falls inside its [valid_from, valid_to) window.
  Superseded and expired memories therefore stop answering questions
  about the present while remaining answerable about the past, which is
  the temporal behavior Mem0's store does not offer.

Embeddings: if EMBEDDING_API_KEY is set, an OpenAI-compatible embeddings
endpoint is used (EMBEDDING_BASE_URL, EMBEDDING_MODEL configurable).
Otherwise a deterministic local hashing embedder runs, so the platform
works with zero external dependencies. The local embedder is lexical,
not a neural model; scores say so via the "embedder" field in results.
"""
import hashlib
import json
from datetime import datetime, timezone
import math
import os
import re
import urllib.request

from .db import now

DIM = 256
_TOKEN = re.compile(r"[a-z0-9]+")
STOPWORDS = {"what", "who", "where", "when", "how", "does", "do", "did", "is",
             "are", "was", "were", "she", "he", "her", "his", "the", "a", "an",
             "of", "to", "in", "on", "for", "and", "or", "it", "its", "i", "you"}


def _stem(token: str) -> str:
    if len(token) > 3 and token.endswith("s") and not token.endswith("ss"):
        return token[:-1]
    return token


def tokens(text: str) -> list[str]:
    return [_stem(t) for t in _TOKEN.findall((text or "").lower())]


def content_tokens(text: str) -> set[str]:
    return {t for t in tokens(text) if t not in STOPWORDS}


def coverage(query: str, text: str) -> float:
    """Share of the query's content words present in the memory. The
    strongest single signal when the embedder is the local lexical one."""
    q = content_tokens(query)
    if not q:
        return 0.0
    return len(q & set(tokens(text))) / len(q)


def _local_embed(text: str) -> list[float]:
    vec = [0.0] * DIM
    toks = tokens(text)
    grams = toks + [a + "_" + b for a, b in zip(toks, toks[1:])]
    for gram in grams:
        h = int(hashlib.md5(gram.encode()).hexdigest()[:8], 16)
        vec[h % DIM] += 1.0
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


def embedder_name() -> str:
    return "remote" if os.environ.get("EMBEDDING_API_KEY") else "local-hash-v1"


def embed(text: str) -> list[float]:
    key = os.environ.get("EMBEDDING_API_KEY")
    if not key:
        return _local_embed(text)
    base = os.environ.get("EMBEDDING_BASE_URL", "https://api.openai.com/v1")
    model = os.environ.get("EMBEDDING_MODEL", "text-embedding-3-small")
    req = urllib.request.Request(
        base.rstrip("/") + "/embeddings",
        data=json.dumps({"model": model, "input": text[:8000]}).encode(),
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read())
    return data["data"][0]["embedding"]


def cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    return sum(x * y for x, y in zip(a, b))


def lexical_f1(query: str, text: str) -> float:
    q, t = set(tokens(query)), set(tokens(text))
    if not q or not t:
        return 0.0
    overlap = len(q & t)
    if not overlap:
        return 0.0
    precision = overlap / len(t)
    recall = overlap / len(q)
    return 2 * precision * recall / (precision + recall)


def memory_text(row) -> str:
    return f"{row['title']}. {row['body']}"


def index_memory(conn, row) -> None:
    """(Re)compute and store the embedding for one memory row."""
    vec = embed(memory_text(row))
    conn.execute("UPDATE memories SET embedding = ? WHERE id = ?",
                 (json.dumps(vec), row["id"]))


def record_event(conn, memory_id: int, user_id: int, event: str,
                 old_body: str = "", new_body: str = "") -> None:
    conn.execute(
        "INSERT INTO memory_events(memory_id, user_id, event, old_body, new_body, created_at)"
        " VALUES (?,?,?,?,?,?)",
        (memory_id, user_id, event, old_body, new_body, now()))


def run_decay(conn, account_id: int) -> int:
    """Archive active memories whose expiry has passed, with an EXPIRE
    event. Runs opportunistically on reads, so no cron is needed."""
    cur = conn.execute(
        "UPDATE memories SET status = 'archived', updated_at = ?"
        " WHERE user_id = ? AND status = 'active' AND expires_at IS NOT NULL AND expires_at < date('now')",
        (now(), account_id))
    return cur.rowcount


def search(conn, account_id: int, query: str, ext_user_id: str = "",
           agent_id: str = "", app_id: str = "", run_id: str = "",
           limit: int = 10, as_of: str | None = None) -> list[dict]:
    """Hybrid search over active memories in one scope. Returns Mem0-shaped
    results with transparent score components."""
    moment = as_of or now()
    sql = ("SELECT * FROM memories WHERE user_id = ? AND status = 'active'"
           " AND (valid_from IS NULL OR valid_from <= ?)"
           " AND (valid_to IS NULL OR valid_to > ?)")
    args: list = [account_id, moment, moment]
    for col, val in (("ext_user_id", ext_user_id), ("agent_id", agent_id),
                     ("app_id", app_id), ("run_id", run_id)):
        if val:
            sql += f" AND {col} = ?"
            args.append(val)
    rows = conn.execute(sql, args).fetchall()

    entity_names = {r["name"].lower() for r in conn.execute(
        "SELECT name FROM entities WHERE user_id = ?", (account_id,)).fetchall()}
    query_entities = {t for t in entity_names if t and t in query.lower()}

    # Weights depend on the embedder: a neural embedding earns the lead
    # weight; the local hashing embedder is lexical noise by comparison,
    # so exact coverage leads instead. (Ranking fix from the benchmark:
    # hash noise was outranking exact matches, 2026-11-02.)
    if embedder_name() == "remote":
        w_sem, w_lex, w_cov = 0.55, 0.25, 0.20
    else:
        w_sem, w_lex, w_cov = 0.20, 0.35, 0.45
    q_lower = query.lower()
    qvec = embed(query)
    scored = []
    for row in rows:
        stored = row["embedding"]
        if stored:
            vec = json.loads(stored)
            if len(vec) != len(qvec):
                vec = embed(memory_text(row))
        else:
            vec = embed(memory_text(row))
            conn.execute("UPDATE memories SET embedding = ? WHERE id = ?",
                         (json.dumps(vec), row["id"]))
        sem = cosine(qvec, vec)
        lex = lexical_f1(query, memory_text(row))
        cov = coverage(query, memory_text(row))
        graph_boost = 0.0
        matched_entities: list[str] = []
        if query_entities:
            linked = {r["dst_name"].lower() for r in conn.execute(
                "SELECT dst_name FROM edges WHERE user_id = ? AND memory_id = ?",
                (account_id, row["id"])).fetchall()}
            matched_entities = sorted(query_entities & linked)
            if matched_entities:
                graph_boost = 0.15
        kind_boost = 0.0
        if "project" in q_lower and row["kind"] == "project":
            kind_boost = 0.15
        elif ("manager" in q_lower or q_lower.startswith("who")) and row["kind"] == "person":
            kind_boost = 0.10
        elif ("goal" in q_lower or "working toward" in q_lower) and row["kind"] == "goal":
            kind_boost = 0.10
        score = (w_sem * sem + w_lex * lex + w_cov * cov + graph_boost
                 + kind_boost + (0.05 if row["pinned"] else 0.0))
        scored.append((score, sem, lex, cov, graph_boost, matched_entities, row))
    scored.sort(key=lambda item: item[0], reverse=True)
    out = []
    for score, sem, lex, cov, graph_boost, matched_entities, row in scored[:limit]:
        out.append({
            "id": row["id"],
            "memory": row["body"],
            "title": row["title"],
            "kind": row["kind"],
            "user_id": row["ext_user_id"] or None,
            "agent_id": row["agent_id"] or None,
            "app_id": row["app_id"] or None,
            "run_id": row["run_id"] or None,
            "score": round(score, 4),
            "score_components": {"semantic": round(sem, 4), "lexical": round(lex, 4),
                                 "coverage": round(cov, 4), "graph_boost": graph_boost},
            "evidence": row["source_quote"] or None,
            "confidence": row["confidence"],
            "support_count": row["support_count"],
            "valid_from": row["valid_from"],
            "valid_to": row["valid_to"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "metadata": json.loads(row["metadata"] or "{}"),
            "embedder": embedder_name(),
            "why": explain(row, matched_entities),
        })
    return out


def explain(row, matched_entities: list[str] | None = None) -> list[str]:
    """Why this memory exists in the results, in plain language.
    Developers should never have to guess what the ranking saw."""
    why: list[str] = []
    support = row["support_count"] or 1
    if support >= 2:
        why.append(f"noticed independently by {support} extractors")
    if row["source_quote"]:
        why.append("carries source evidence")
    grounding = row["grounding"] if "grounding" in row.keys() else ""
    if grounding == "verified":
        why.append("evidence verified against the source conversation")
    elif grounding == "pattern":
        why.append("grounded in a repeated behavioral pattern")
    elif grounding == "asserted":
        why.append("asserted directly by the developer")
    try:
        created = datetime.fromisoformat(row["created_at"])
        age = (datetime.now(timezone.utc) - created).days
        why.append("learned today" if age <= 0 else f"learned {age} day{'s' if age != 1 else ''} ago")
    except (TypeError, ValueError):
        pass
    if row["valid_to"]:
        why.append(f"was true until {row['valid_to'][:10]}")
    else:
        why.append("currently valid, not superseded")
    for name in (matched_entities or []):
        why.append(f"connected to {name} in the relationship graph")
    return why

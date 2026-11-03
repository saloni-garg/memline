"""The write gate: nothing enters storage unverified.

The category's best-documented production failure is extraction junk
accumulating unchecked (a Mem0 user audited 10,134 stored entries and
found 97.8% junk, including hundreds of copies of one hallucination
re-extracted from recalled memories). The gate is the countermeasure,
applied to every machine-extracted candidate before storage:

1. Grounding: the candidate's evidence quote must actually be supported
   by the source conversation in this call. Token-overlap verification;
   behavioral-pattern evidence is accepted but labeled as such.
2. Feedback-loop prevention: a candidate whose body duplicates an
   active memory in the same scope is skipped, never re-stored. Stored
   memories can never multiply by being recalled and re-fed.
3. Revision detection: a candidate that restates the same slot as an
   existing active understanding (same kind, similar title or a shared
   slot word) with a different body supersedes it, closing its validity
   window, instead of coexisting as a contradiction.

Verbatim developer writes (infer=false) skip grounding by design: the
developer is the authority, and those writes are labeled "asserted".
"""
from .retrieval import content_tokens, tokens

GROUND_THRESHOLD = 0.5
SLOT_WORDS = {"location", "employer", "company", "manager", "role", "job",
              "address", "city", "school", "title", "name", "team"}


def grounding_check(quote: str, source_text: str) -> tuple[str, float]:
    """Returns (label, score): 'verified', 'pattern', or 'unverified'."""
    q = (quote or "").strip()
    if not q:
        return "unverified", 0.0
    low = q.lower()
    if low.startswith("pattern") or "(seen" in low or "observed" in low[:40]:
        return "pattern", 1.0
    qt = content_tokens(q)
    if not qt:
        return "unverified", 0.0
    overlap = len(qt & set(tokens(source_text))) / len(qt)
    return ("verified", overlap) if overlap >= GROUND_THRESHOLD else ("unverified", overlap)


def _norm_body(body: str) -> str:
    return " ".join(sorted(content_tokens(body or "")))


def find_duplicate(conn, account_id: int, scope: tuple, cand: dict):
    ext_user, agent_id, app_id = scope
    rows = conn.execute(
        "SELECT * FROM memories WHERE user_id = ? AND status = 'active'"
        " AND ext_user_id = ? AND agent_id = ? AND app_id = ?",
        (account_id, ext_user, agent_id, app_id)).fetchall()
    target = _norm_body(cand["body"])
    for row in rows:
        if _norm_body(row["body"]) == target:
            return row
    return None


def _title_f1(a: str, b: str) -> float:
    ta, tb = content_tokens(a or ""), content_tokens(b or "")
    if not ta or not tb:
        return 0.0
    inter = len(ta & tb)
    return 2 * inter / (len(ta) + len(tb)) if inter else 0.0


def find_revision(conn, account_id: int, scope: tuple, cand: dict):
    """An active memory this candidate revises: same kind, and either a
    similar title (F1 >= 0.5) or a shared slot word with some overlap,
    and a genuinely different body. Returns the row or None."""
    ext_user, agent_id, app_id = scope
    if cand.get("title") in ("", "Memory", None):
        return None
    rows = conn.execute(
        "SELECT * FROM memories WHERE user_id = ? AND status = 'active'"
        " AND kind = ? AND ext_user_id = ? AND agent_id = ? AND app_id = ?",
        (account_id, cand["kind"], ext_user, agent_id, app_id)).fetchall()
    cand_slots = content_tokens(cand["title"]) & SLOT_WORDS
    best, best_score = None, 0.0
    for row in rows:
        if _norm_body(row["body"]) == _norm_body(cand["body"]):
            continue
        sim = _title_f1(cand["title"], row["title"])
        shared_slot = bool(cand_slots & content_tokens(row["title"]))
        score = sim + (0.25 if shared_slot else 0.0)
        if (sim >= 0.5 or (shared_slot and sim >= 0.3)) and score > best_score:
            best, best_score = row, score
    return best


def record_rejection(conn, account_id: int, ext_user_id: str, cand: dict,
                     reason: str, score: float) -> None:
    from .db import now
    conn.execute(
        "INSERT INTO write_rejections(user_id, ext_user_id, kind, title, body,"
        " reason, grounding_score, created_at) VALUES (?,?,?,?,?,?,?,?)",
        (account_id, ext_user_id, cand.get("kind", ""), cand.get("title", ""),
         cand.get("body", ""), reason, round(score, 3), now()))

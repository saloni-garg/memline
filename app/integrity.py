"""Memory Integrity: the health of a memory store, as numbers.

Memory quality is invisible in every other system in this category: no
one can say how grounded, how stale, or how contradictory their store
is. This module computes exactly that, from the same tables the product
runs on, with definitions simple enough to state in one line each:

- grounded: active memories whose evidence was verified against the
  source conversation, is a labeled behavioral pattern, was asserted
  directly by the developer, or (legacy rows) carries a source quote.
- stale: active memories not updated in 180+ days.
- contradictions: groups of active memories sharing kind and title
  with different bodies, which should have been revisions.
- superseded: memories archived because a newer understanding replaced
  them (their validity windows are closed, history intact).
- unknowns: active open questions, stated rather than guessed.
- rejections: candidates the write gate refused, with the pass rate.
- orphaned edges: relationship edges pointing at deleted memories.
- coverage: which understanding kinds are present at all.
"""
from datetime import datetime, timedelta, timezone

from .gate import _norm_body

KINDS = ["identity", "goal", "principle", "preference", "style",
         "project", "person", "fact", "narrative", "unknown"]
STALE_DAYS = 180


def memory_health(conn, account_id: int, ext_user_id: str = "") -> dict:
    scope = " AND ext_user_id = ?"
    active = conn.execute(
        "SELECT * FROM memories WHERE user_id = ? AND status = 'active'" + scope,
        (account_id, ext_user_id)).fetchall()
    archived = conn.execute(
        "SELECT COUNT(*) AS n FROM memories WHERE user_id = ?"
        " AND status = 'archived' AND replaced_by IS NOT NULL" + scope,
        (account_id, ext_user_id)).fetchone()["n"]

    def grounded(row) -> bool:
        label = row["grounding"] if "grounding" in row.keys() else ""
        return label in ("verified", "pattern", "asserted") or bool(row["source_quote"])

    claim_rows = [r for r in active
                  if not (r["kind"] == "unknown" and r["grounding"] == "question")]
    grounded_n = sum(1 for r in claim_rows if grounded(r))
    cutoff = (datetime.now(timezone.utc) - timedelta(days=STALE_DAYS)).isoformat()
    stale_n = sum(1 for r in active if (r["updated_at"] or "") < cutoff)

    groups: dict[tuple, set] = {}
    for r in active:
        key = (r["kind"], " ".join((r["title"] or "").lower().split()))
        groups.setdefault(key, set()).add(_norm_body(r["body"]))
    contradictions = sum(1 for bodies in groups.values() if len(bodies) > 1)

    unknowns = sum(1 for r in active if r["kind"] == "unknown")
    covered = sorted({r["kind"] for r in active} & set(KINDS))

    rejected = conn.execute(
        "SELECT COUNT(*) AS n FROM write_rejections WHERE user_id = ?" + scope,
        (account_id, ext_user_id)).fetchone()["n"]
    gated_stored = sum(1 for r in conn.execute(
        "SELECT grounding FROM memories WHERE user_id = ?" + scope,
        (account_id, ext_user_id)).fetchall()
        if r["grounding"] in ("verified", "pattern"))
    denom = gated_stored + rejected
    gate_pass_rate = round(gated_stored / denom, 3) if denom else None

    orphaned = conn.execute(
        "SELECT COUNT(*) AS n FROM edges e WHERE e.user_id = ? AND e.memory_id > 0"
        " AND NOT EXISTS (SELECT 1 FROM memories m WHERE m.id = e.memory_id)",
        (account_id,)).fetchone()["n"]
    recent_sql = ("SELECT kind, title, body, reason, grounding_score, created_at"
                  " FROM write_rejections WHERE user_id = ?" + scope
                  + " ORDER BY id DESC LIMIT 5")
    recent_rejections = conn.execute(recent_sql, (account_id, ext_user_id)).fetchall()

    total = len(active)
    return {
        "user_id": ext_user_id or None,
        "active_memories": total,
        "grounded": grounded_n,
        "grounded_pct": round(grounded_n / len(claim_rows), 3) if claim_rows else None,
        "stale": stale_n,
        "stale_definition": f"not updated in {STALE_DAYS}+ days",
        "contradictions": contradictions,
        "superseded": archived,
        "unknowns": unknowns,
        "rejected_writes": rejected,
        "gate_pass_rate": gate_pass_rate,
        "orphaned_graph_edges": orphaned,
        "coverage": {"covered": covered, "of": len(KINDS),
                     "missing": [k for k in KINDS if k not in covered]},
        "recent_rejections": [dict(r) for r in recent_rejections],
    }

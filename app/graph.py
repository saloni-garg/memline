"""A derived graph layer over the flat memory store.

Entities come from the structure the understanding engine already
produces: person memories are people, project fields and project
memories are projects. Edges tie each memory to its entities, which is
what powers the graph boost in retrieval and the /v1/graph view.
Deterministic on purpose: the graph is an index over approved
understanding, never a second source of truth.
"""
from .db import now


def _upsert_entity(conn, account_id: int, ext_user_id: str, name: str, kind: str) -> None:
    name = (name or "").strip()
    if not name:
        return
    conn.execute(
        "INSERT OR IGNORE INTO entities(user_id, ext_user_id, name, kind, created_at)"
        " VALUES (?,?,?,?,?)",
        (account_id, ext_user_id, name, kind, now()))


def _link(conn, account_id: int, ext_user_id: str, entity: str, relation: str, memory_id: int) -> None:
    conn.execute(
        "INSERT OR IGNORE INTO edges(user_id, ext_user_id, src_name, dst_name, relation, memory_id, created_at)"
        " VALUES (?,?,?,?,?,?,?)",
        (account_id, ext_user_id, "user", entity, relation, memory_id, now()))


def index_graph(conn, row) -> None:
    """Extract entities for one memory row and link them."""
    account_id, ext_user_id, mid = row["user_id"], row["ext_user_id"], row["id"]
    if row["kind"] == "person" and row["title"]:
        _upsert_entity(conn, account_id, ext_user_id, row["title"], "person")
        _link(conn, account_id, ext_user_id, row["title"], "works_with", mid)
    if row["project"]:
        _upsert_entity(conn, account_id, ext_user_id, row["project"], "project")
        _link(conn, account_id, ext_user_id, row["project"], "works_on", mid)
    if row["kind"] == "project" and row["title"]:
        _upsert_entity(conn, account_id, ext_user_id, row["title"], "project")
        _link(conn, account_id, ext_user_id, row["title"], "works_on", mid)
    # Mention links: a memory whose body names a known person or project
    # is linked to it, so entity queries retrieve it too.
    known = conn.execute(
        "SELECT name, kind FROM entities WHERE user_id = ? AND ext_user_id = ?",
        (account_id, ext_user_id)).fetchall()
    body = (row["body"] or "").lower()
    for ent in known:
        if ent["name"].lower() in body:
            _link(conn, account_id, ext_user_id, ent["name"], "mentioned_in", mid)
        # Part-of relations are what make the graph reason rather than
        # merely index: "Project Pluto is part of Firefly" lets a query
        # about Firefly retrieve Pluto's context. The edge runs from
        # this memory's own subject to the parent it names, so it is
        # inserted directly rather than through the user-centric _link.
        if (ent["kind"] == "project" and row["title"]
                and ent["name"].lower() != row["title"].lower()
                and f"part of {ent['name'].lower()}" in body):
            conn.execute(
                "INSERT OR IGNORE INTO edges(user_id, ext_user_id, src_name,"
                " dst_name, relation, memory_id, created_at) VALUES (?,?,?,?,?,?,?)",
                (account_id, ext_user_id, row["title"], ent["name"], "part_of",
                 mid, now()))


def fetch_graph(conn, account_id: int, ext_user_id: str = "") -> dict:
    ents = conn.execute(
        "SELECT name, kind FROM entities WHERE user_id = ? AND (ext_user_id = ? OR ? = '')"
        " ORDER BY kind, name",
        (account_id, ext_user_id, ext_user_id)).fetchall()
    edges = conn.execute(
        "SELECT DISTINCT src_name, dst_name, relation FROM edges"
        " WHERE user_id = ? AND (ext_user_id = ? OR ? = '')",
        (account_id, ext_user_id, ext_user_id)).fetchall()
    return {"nodes": [{"name": e["name"], "kind": e["kind"]} for e in ents],
            "edges": [dict(e) for e in edges]}

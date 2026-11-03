"""Memline MCP server (stdio).

Lets MCP clients (Claude, Cursor, and others) use the user's Memline
memory directly:
- recall_memory: read active memories, optionally filtered by a query
- propose_memory: suggest a new memory. It lands in the user's inbox for
  approval, never straight into the memory. That rule is the product.
- forget_memory: archive a memory by id

The user is identified by the MEMLINE_USER environment variable (their
account email) in this local-first MVP. Hosted launch swaps this for an
API key per user, with the same tool surface.
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.db import db, init_db, now, row_dict  # noqa: E402

TOOLS = [
    {
        "name": "recall_memory",
        "description": "Recall what Memline knows about this user: identity, preferences, instructions, projects, people and facts. Call this before asking the user to repeat themselves.",
        "inputSchema": {"type": "object", "properties": {"query": {"type": "string"}}, "required": []},
    },
    {
        "name": "propose_memory",
        "description": "Propose a lasting fact about the user for their Memline memory. It goes to their approval inbox; it is not stored silently.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "kind": {"type": "string", "enum": ["identity", "preference", "instruction", "project", "person", "fact"]},
                "title": {"type": "string"},
                "body": {"type": "string"},
            },
            "required": ["body"],
        },
    },
    {
        "name": "forget_memory",
        "description": "Archive a memory by its id (from recall_memory results) when the user says it is no longer true.",
        "inputSchema": {"type": "object", "properties": {"id": {"type": "integer"}}, "required": ["id"]},
    },
]


def _user_id() -> int:
    init_db()
    email = os.environ.get("MEMLINE_USER", "demo@memline.app")
    with db() as conn:
        row = conn.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()
    if not row:
        raise RuntimeError(f"No Memline account for {email}")
    return row["id"]


def call_tool(name: str, args: dict, user_id: int) -> str:
    if name == "recall_memory":
        query = (args.get("query") or "").strip()
        sql = "SELECT * FROM memories WHERE user_id = ? AND status = 'active'"
        params = [user_id]
        if query:
            sql += " AND (body LIKE ? OR title LIKE ? OR project LIKE ?)"
            params += [f"%{query}%"] * 3
        sql += " ORDER BY pinned DESC, kind, id"
        with db() as conn:
            rows = [row_dict(r) for r in conn.execute(sql, params).fetchall()]
        if not rows:
            return "No memories found."
        return "\n".join(f"[{m['id']}] ({m['kind']}) {m['title']}: {m['body']}" for m in rows)
    if name == "propose_memory":
        with db() as conn:
            cur = conn.execute(
                "INSERT INTO memories(user_id, kind, title, body, source, status, created_at, updated_at)"
                " VALUES (?,?,?,?, 'an assistant, via MCP', 'pending', ?, ?)",
                (user_id, args.get("kind", "fact"), args.get("title", "Memory"), args["body"], now(), now()))
        return f"Proposed as memory #{cur.lastrowid}. It will appear in the user's Memline inbox for approval."
    if name == "forget_memory":
        with db() as conn:
            conn.execute("UPDATE memories SET status = 'archived', updated_at = ? WHERE id = ? AND user_id = ?",
                         (now(), args["id"], user_id))
        return f"Memory #{args['id']} archived."
    raise ValueError(f"Unknown tool {name}")


def main() -> None:
    user_id = _user_id()
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError:
            continue
        method, req_id = req.get("method", ""), req.get("id")
        if method == "initialize":
            result = {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "memline", "version": "0.1.0"},
            }
        elif method == "tools/list":
            result = {"tools": TOOLS}
        elif method == "tools/call":
            params = req.get("params", {})
            try:
                text = call_tool(params.get("name", ""), params.get("arguments", {}), user_id)
                result = {"content": [{"type": "text", "text": text}]}
            except Exception as exc:  # surface tool errors in-band, keep serving
                result = {"content": [{"type": "text", "text": f"Error: {exc}"}], "isError": True}
        elif req_id is None:
            continue  # notification
        else:
            result = {}
        if req_id is not None:
            sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": req_id, "result": result}) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()

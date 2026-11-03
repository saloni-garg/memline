"""API-key authentication shared by the hosted MCP endpoint and the
developer REST API (/v1). Keys are stored hashed; the full key is shown
to the user exactly once, at creation."""
import hashlib

from fastapi import HTTPException, Request

from .db import db, now


def hash_key(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


def user_for_api_key(request: Request) -> dict:
    auth = request.headers.get("authorization", "")
    if not auth.startswith("Bearer ml_"):
        raise HTTPException(401, "Missing Memline API key.")
    key = auth.removeprefix("Bearer ").strip()
    with db() as conn:
        row = conn.execute(
            "SELECT u.* FROM api_keys k JOIN users u ON u.id = k.user_id WHERE k.key_hash = ?",
            (hash_key(key),)).fetchone()
        if row:
            conn.execute("UPDATE api_keys SET last_used_at = ? WHERE key_hash = ?",
                         (now(), hash_key(key)))
    if not row:
        raise HTTPException(401, "That API key is not valid.")
    return dict(row)

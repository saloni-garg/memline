"""Memline storage. Fresh schema designed for the product in PRODUCT.md.

One SQLite file, stdlib sqlite3 only. Concepts:
- users / sessions: accounts and login sessions
- memories: the user's memory. status flows pending -> active -> archived,
  or pending -> rejected. An active memory that gets replaced is archived
  and points at its replacement (replaced_by), so history is never lost
  and never silently overwritten.
- packs: every generated context pack, used for plan limits and history.
"""
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone

DB_PATH = os.environ.get("MEMLINE_DB", os.path.join(os.path.dirname(__file__), "..", "memline.db"))


def now() -> str:
    # Millisecond resolution: temporal validity windows need to order
    # events that happen inside the same second (an add and an
    # invalidate in one API flow, found by the /v1 temporal tests).
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


@contextmanager
def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY,
    email TEXT UNIQUE NOT NULL,
    pw_hash TEXT NOT NULL,
    plan TEXT NOT NULL DEFAULT 'free',
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sessions (
    token TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id),
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS memories (
    id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id),
    kind TEXT NOT NULL,
    title TEXT NOT NULL,
    body TEXT NOT NULL,
    project TEXT NOT NULL DEFAULT '',
    source TEXT NOT NULL DEFAULT 'manual',
    source_quote TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'pending',
    pinned INTEGER NOT NULL DEFAULT 0,
    confidence REAL NOT NULL DEFAULT 1.0,
    support_count INTEGER NOT NULL DEFAULT 1,
    surprise_actual INTEGER,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    expires_at TEXT,
    supersedes_id INTEGER REFERENCES memories(id),
    replaced_by INTEGER REFERENCES memories(id)
);
CREATE TABLE IF NOT EXISTS api_keys (
    id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id),
    name TEXT NOT NULL DEFAULT 'default',
    prefix TEXT NOT NULL,
    key_hash TEXT NOT NULL,
    created_at TEXT NOT NULL,
    last_used_at TEXT
);
CREATE TABLE IF NOT EXISTS packs (
    id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id),
    target TEXT NOT NULL,
    project TEXT NOT NULL DEFAULT '',
    body TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS memory_events (
    id INTEGER PRIMARY KEY,
    memory_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL REFERENCES users(id),
    event TEXT NOT NULL,
    old_body TEXT NOT NULL DEFAULT '',
    new_body TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS write_rejections (
    id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id),
    ext_user_id TEXT NOT NULL DEFAULT '',
    kind TEXT NOT NULL DEFAULT '',
    title TEXT NOT NULL DEFAULT '',
    body TEXT NOT NULL DEFAULT '',
    reason TEXT NOT NULL DEFAULT '',
    grounding_score REAL NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS entities (
    id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id),
    ext_user_id TEXT NOT NULL DEFAULT '',
    name TEXT NOT NULL,
    kind TEXT NOT NULL DEFAULT 'topic',
    created_at TEXT NOT NULL,
    UNIQUE(user_id, ext_user_id, name, kind)
);
CREATE TABLE IF NOT EXISTS edges (
    id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id),
    ext_user_id TEXT NOT NULL DEFAULT '',
    src_name TEXT NOT NULL,
    dst_name TEXT NOT NULL,
    relation TEXT NOT NULL,
    memory_id INTEGER,
    created_at TEXT NOT NULL,
    UNIQUE(user_id, ext_user_id, src_name, dst_name, relation, memory_id)
);
CREATE INDEX IF NOT EXISTS idx_mem_user_status ON memories(user_id, status);
CREATE INDEX IF NOT EXISTS idx_packs_user ON packs(user_id, created_at);
CREATE INDEX IF NOT EXISTS idx_events_memory ON memory_events(memory_id, id);
CREATE INDEX IF NOT EXISTS idx_entities_user ON entities(user_id, ext_user_id);
"""


def init_db() -> None:
    with db() as conn:
        conn.executescript(SCHEMA)
        cols = {row["name"] for row in conn.execute("PRAGMA table_info(memories)")}
        if "support_count" not in cols:
            conn.execute("ALTER TABLE memories ADD COLUMN support_count INTEGER NOT NULL DEFAULT 1")
        if "surprise_actual" not in cols:
            conn.execute("ALTER TABLE memories ADD COLUMN surprise_actual INTEGER")
        # Developer-platform columns (Mem0 parity layer): external end-user
        # scoping, agent/app/run scoping, metadata, temporal validity
        # windows, and a stored embedding for hybrid retrieval.
        for col, ddl in (
            ("grounding", "TEXT NOT NULL DEFAULT ''"),
            ("ext_user_id", "TEXT NOT NULL DEFAULT ''"),
            ("agent_id", "TEXT NOT NULL DEFAULT ''"),
            ("app_id", "TEXT NOT NULL DEFAULT ''"),
            ("run_id", "TEXT NOT NULL DEFAULT ''"),
            ("metadata", "TEXT NOT NULL DEFAULT '{}'"),
            ("valid_from", "TEXT"),
            ("valid_to", "TEXT"),
            ("embedding", "TEXT"),
        ):
            if col not in cols:
                conn.execute(f"ALTER TABLE memories ADD COLUMN {col} {ddl}")


def row_dict(row) -> dict:
    d = dict(row)
    d["pinned"] = bool(d.get("pinned"))
    return d

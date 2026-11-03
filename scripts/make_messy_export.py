"""Generate a synthetic Mem0-format export with the failure patterns the
category research documents in real production stores: duplicate
accumulation from re-extraction, value chains that were never resolved
(moves, employer changes), contradictory managers, and stale project
facts that were never reconfirmed. Deterministic; for demonstrating
scripts/migrate.py. Not real user data."""
import json
import os
import random

random.seed(42)
OUT = os.path.join(os.path.dirname(__file__), "..", "eval", "migration_demo",
                   "messy_mem0_export.json")

items = []
_n = [0]


def add(user, body, created, updated=None):
    _n[0] += 1
    items.append({"id": f"mem-{_n[0]:04d}", "memory": body, "user_id": user,
                  "created_at": created, "updated_at": updated or created,
                  "metadata": {}})


# user-42: a support-engineering persona with a messy store
for i in range(46):
    add("user-42", f"User discussed ticket topic number {i} about billing exports.",
        f"2026-0{1 + i % 9}-1{(i % 27) + 1:02d}T10:00:00Z")
for k in range(14):  # the hallucination that would not die
    add("user-42", "User prefers Vim for editing code" + ("." if k % 2 else ""),
        f"202{5 + (k % 2)}-{(k % 12) + 1:02d}-05T09:00:00Z")
for k in range(5):
    add("user-42", "User's favorite coffee is an oat milk latte.",
        f"2025-{(k % 12) + 1:02d}-11T08:30:00Z")
add("user-42", "User lives in Portland.", "2025-03-04T12:00:00Z")
add("user-42", "User moved to Austin.", "2025-11-18T12:00:00Z")
add("user-42", "User lives in Denver.", "2026-06-22T12:00:00Z")
add("user-42", "User works at Northwind Traders.", "2025-02-10T09:00:00Z")
add("user-42", "User works at Globex.", "2026-01-15T09:00:00Z")
add("user-42", "User's manager is Priya.", "2026-02-01T09:00:00Z")
add("user-42", "User's manager is Tom.", "2026-03-01T09:00:00Z")
add("user-42", "User is a support engineer.", "2025-02-10T09:00:00Z")
for i in range(12):  # stale project facts, never touched again
    add("user-42", f"User is working on Project Falcon milestone {i}.",
        f"2025-0{1 + i % 3}-0{(i % 27) + 1:02d}T14:00:00Z")

# user-7: smaller, cleaner, one move
for i in range(18):
    add("user-7", f"User asked about recipe variation {i} with chickpeas.",
        f"2026-05-{(i % 27) + 1:02d}T19:00:00Z")
add("user-7", "User lives in Chicago.", "2025-08-01T10:00:00Z")
add("user-7", "User moved to Seattle.", "2026-04-01T10:00:00Z")
add("user-7", "User is a product designer.", "2025-08-01T10:00:00Z")

os.makedirs(os.path.dirname(OUT), exist_ok=True)
with open(OUT, "w") as fh:
    json.dump({"results": items}, fh, indent=1)
print(f"wrote {len(items)} memories to {OUT}")

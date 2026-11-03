"""Head-to-head quality harness: Mem0-style fact memory vs Memline
understanding, on the same history, through the same production
retrieval stack.

The variable being isolated is WHAT GETS STORED. Mem0's pipeline stores
atomic facts extracted from conversations. Memline stores typed
understandings (identity, goals, principles, style, preferences,
projects, people, unknowns). Both sets are loaded into the real store
under two scopes and queried through the production hybrid search; a
question counts as answerable when the expected content appears in the
top-3 retrieved memories. Deterministic, no LLM judge, no API key
needed for the default run.

With --live and ANTHROPIC_API_KEY set, the understanding set is produced
by the real specialist extractors on the fixture export, and the fact
set by one generic Mem0-style extraction prompt. That is the run whose
numbers can be quoted externally; the default run validates the harness
and the storage-model difference on recorded extraction outputs.

Usage: .venv/bin/python eval/run_benchmark.py [--live]
"""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ["MEMLINE_DB"] = os.path.join(tempfile.mkdtemp(), "bench.db")

from app.db import db, init_db, now  # noqa: E402
from app.retrieval import index_memory, search  # noqa: E402

HERE = os.path.dirname(__file__)


def load_fixture_qa() -> dict:
    with open(os.path.join(HERE, "fixture_qa.json")) as fh:
        return json.load(fh)


def build_systems(live: bool) -> dict[str, list[dict]]:
    qa = load_fixture_qa()
    from app.main import _conversations_from_chatgpt_export
    with open(os.path.join(HERE, "..", "tests", "fixture_export.json")) as fh:
        data = json.load(fh)
    conversations = _conversations_from_chatgpt_export(data)
    # Raw RAG: the conversation itself, chunked per user message, no
    # extraction at all. This is the honest third baseline: maybe the
    # raw history already answers everything and extraction is overhead.
    chunks = [{"kind": "chunk", "title": c["title"], "body": message}
              for c in conversations for message in c["messages"]]
    systems = {
        "rag (raw chunks)": chunks,
        "facts (Mem0-style)": [{"kind": "fact", "title": "Fact", "body": body}
                               for body in qa["facts_system"]],
        "understanding (Memline)": qa["understanding_system"],
    }
    if live:
        from app.understanding import _call_model, extract_understandings
        digest = "\n".join(m for c in conversations for m in c["messages"])
        raw = _call_model(
            "You extract atomic facts from conversations, the way a memory "
            "API does. Return one fact per line, no numbering, no commentary. "
            "Facts only: who, what, where, when. No goals, principles, or style "
            "inferences beyond what is stated verbatim.",
            digest, max_tokens=1200)
        systems["facts (Mem0-style)"] = [
            {"kind": "fact", "title": "Fact", "body": line.strip("- ").strip()}
            for line in raw.splitlines() if line.strip()]
        systems["understanding (Memline)"] = extract_understandings(
            conversations, source="benchmark")
    return systems


def seed(account_id: int, scope: str, memories: list[dict]) -> None:
    with db() as conn:
        for mem in memories:
            cur = conn.execute(
                "INSERT INTO memories(user_id, kind, title, body, source, status,"
                " ext_user_id, valid_from, created_at, updated_at)"
                " VALUES (?,?,?,?,'benchmark','active',?,?,?,?)",
                (account_id, mem["kind"], mem["title"], mem["body"], scope, now(), now(), now()))
            row = conn.execute("SELECT * FROM memories WHERE id = ?", (cur.lastrowid,)).fetchone()
            index_memory(conn, row)


def answerable(retrieved: list[dict], expect: list[list[str]]) -> bool:
    text = " ".join(r["memory"] for r in retrieved).lower()
    return all(any(syn in text for syn in group) for group in expect)


def main() -> None:
    live = "--live" in sys.argv
    init_db()
    with db() as conn:
        cur = conn.execute(
            "INSERT INTO users(email, pw_hash, plan, created_at) VALUES ('bench@x','x','pro',?)",
            (now(),))
        account_id = cur.lastrowid
    systems = build_systems(live)
    scopes = {}
    for i, (name, memories) in enumerate(systems.items()):
        scope = f"sys{i}"
        scopes[name] = scope
        seed(account_id, scope, memories)

    qa = load_fixture_qa()
    print(f"Mode: {'live extraction' if live else 'recorded extraction outputs'}")
    print(f"Questions: {len(qa['questions'])}  |  retrieval: production hybrid search, top 3\n")
    summary = {}
    with db() as conn:
        for name, scope in scopes.items():
            per_cat: dict[str, list[int]] = {}
            for q in qa["questions"]:
                got = search(conn, account_id, q["q"], ext_user_id=scope, limit=3)
                ok = answerable(got, q["expect"])
                per_cat.setdefault(q["category"], []).append(1 if ok else 0)
            total = sum(sum(v) for v in per_cat.values())
            summary[name] = (total, len(qa["questions"]))
            print(f"{name}: {total}/{len(qa['questions'])} answerable")
            for cat, scores in sorted(per_cat.items()):
                print(f"  {cat:<11} {sum(scores)}/{len(scores)}")
            print()
    rag_ok, _ = summary["rag (raw chunks)"]
    fact_ok, total = summary["facts (Mem0-style)"]
    und_ok, _ = summary["understanding (Memline)"]
    print(f"Delta: understanding {und_ok}/{total}, facts {fact_ok}/{total}, "
          f"raw RAG {rag_ok}/{total}, same history, same retrieval.")


if __name__ == "__main__":
    main()

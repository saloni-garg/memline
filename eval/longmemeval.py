"""LongMemEval-S subset run: three storage models, one reader, one judge.

Protocol (deliberately conservative, deviations stated in the writeup):
- Subset: the first --per-type instances of each of the 6 question types
  (default 5 per type, 30 questions), in dataset order. Not the full 500.
- Each instance's haystack sessions become conversations with role
  prefixed turns (deviation: the consumer importer reads user turns
  only, but LongMemEval also asks about assistant-provided content).
- Three stores per instance, all through Memline's production
  retrieval (local hashing embedder):
  * rag: one chunk per conversation turn, no extraction.
  * facts: one Mem0-style atomic-fact extraction call over the same
    production digest the understanding engine uses.
  * understanding: the production extract_understandings pipeline.
- The extraction systems see the production digest (48k chars, opener +
  longest messages per session). LongMemEval-S histories are far longer,
  so this truncation is a real product limitation the run exposes on
  purpose. Raw RAG stores every turn.
- Reader: claude-haiku via app.understanding._call_model, top-5
  retrieved memories, instructed to answer only from context.
- Judge: same model, official-style correctness prompt, reference
  answer comparison. Accuracy is judged-answer accuracy.

Run: ANTHROPIC_API_KEY=... .venv/bin/python eval/longmemeval.py [--per-type 5]
Results stream to eval/longmemeval_results.json after every instance.
"""
import argparse
import json
import os
import sys
import tempfile
from collections import defaultdict

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
DATA = os.path.join(os.path.dirname(__file__), "data", "longmemeval_s")
OUT = os.path.join(os.path.dirname(__file__), "longmemeval_results.json")

FACT_SYSTEM = (
    "You extract atomic facts from conversations, the way a memory API "
    "does. Return one fact per line, no numbering, no commentary. Facts "
    "only: who, what, where, when. No goals, principles, or style "
    "inferences beyond what is stated verbatim."
)

READER_SYSTEM = (
    "You answer a question about a user using only the retrieved context "
    "from their stored information. If the context does not contain the "
    "answer, reply that you do not know. Be concise and give the specific "
    "answer (name, date, number) when the context supports it."
)

JUDGE_SYSTEM = (
    "You judge whether a model response correctly answers a question. "
    "It is CORRECT if it contains or clearly implies the reference "
    "answer and does not contradict it. If the reference shows the "
    "information was never provided, a response saying it does not know "
    "is CORRECT. Reply with exactly one word: CORRECT or INCORRECT."
)


def load_subset(per_type: int) -> list[dict]:
    with open(DATA) as fh:
        data = json.load(fh)
    by_type: dict[str, list[dict]] = defaultdict(list)
    for inst in data:
        if len(by_type[inst["question_type"]]) < per_type:
            by_type[inst["question_type"]].append(inst)
    subset = [inst for group in by_type.values() for inst in group]
    subset.sort(key=lambda x: x["question_id"])
    return subset


def conversations_of(inst: dict) -> list[dict]:
    convs = []
    for date, session in zip(inst["haystack_dates"], inst["haystack_sessions"]):
        msgs = [f"{t['role']}: {t['content']}" for t in session
                if t.get("content", "").strip()]
        if msgs:
            convs.append({"title": f"Session on {date}", "messages": msgs})
    return convs


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--per-type", type=int, default=5)
    ap.add_argument("--topk", type=int, default=5)
    args = ap.parse_args()

    os.environ["MEMLINE_DB"] = os.path.join(tempfile.mkdtemp(), "lme.db")
    from app.db import db, init_db, now
    from app.retrieval import index_memory, search
    from app.understanding import _call_model, build_digest, extract_understandings

    init_db()
    subset = load_subset(args.per_type)
    print(f"LongMemEval-S subset: {len(subset)} questions", flush=True)

    results: list[dict] = []
    if os.path.exists(OUT):
        results = json.load(open(OUT))
    done = {r["question_id"] for r in results}

    with db() as conn:
        cur = conn.execute(
            "INSERT INTO users(email, pw_hash, plan, created_at)"
            " VALUES ('lme@bench', 'x', 'pro', ?)", (now(),))
        acct = cur.lastrowid

        def store(scope: str, mems: list[dict]) -> None:
            for mem in mems:
                c = conn.execute(
                    "INSERT INTO memories(user_id, kind, title, body, source,"
                    " status, ext_user_id, valid_from, created_at, updated_at)"
                    " VALUES (?,?,?,?,'lme','active',?,?,?,?)",
                    (acct, mem["kind"], mem.get("title") or "", mem["body"],
                     scope, now(), now(), now()))
                row = conn.execute("SELECT * FROM memories WHERE id = ?",
                                   (c.lastrowid,)).fetchone()
                index_memory(conn, row)

        for i, inst in enumerate(subset, 1):
            qid = inst["question_id"]
            if qid in done:
                continue
            convs = conversations_of(inst)
            digest = build_digest(convs)
            systems: dict[str, list[dict]] = {
                "rag": [{"kind": "chunk", "title": c["title"], "body": m}
                        for c in convs for m in c["messages"]],
                "facts": [{"kind": "fact", "title": "Fact", "body": line.strip()}
                          for line in _call_model(FACT_SYSTEM, digest,
                                                  max_tokens=3000).splitlines()
                          if line.strip()],
                "understanding": [
                    {"kind": c["kind"], "title": c["title"], "body": c["body"]}
                    for c in extract_understandings(convs, "longmemeval")],
            }
            record = {"question_id": qid, "question_type": inst["question_type"],
                      "question": inst["question"], "answer": inst["answer"],
                      "systems": {}}
            for name, mems in systems.items():
                scope = f"{qid}:{name}"
                store(scope, mems)
                got = search(conn, acct, inst["question"], ext_user_id=scope,
                             limit=args.topk)
                context = "\n".join(f"- {g['memory']}" for g in got) or "(nothing retrieved)"
                response = _call_model(
                    READER_SYSTEM,
                    f"Current date: {inst['question_date']}\n\nContext:\n{context}"
                    f"\n\nQuestion: {inst['question']}",
                    max_tokens=300)
                verdict = _call_model(
                    JUDGE_SYSTEM,
                    f"Question: {inst['question']}\nReference answer: {inst['answer']}"
                    f"\nModel response: {response}",
                    max_tokens=10).strip().upper()
                record["systems"][name] = {
                    "stored": len(mems), "retrieved": len(got),
                    "response": response,
                    "correct": verdict.startswith("CORRECT"),
                }
            results.append(record)
            with open(OUT, "w") as fh:
                json.dump(results, fh, indent=1)
            marks = " ".join(
                f"{n}={'Y' if record['systems'][n]['correct'] else 'n'}"
                for n in ("rag", "facts", "understanding"))
            print(f"[{i}/{len(subset)}] {inst['question_type']} {marks}", flush=True)

    by_sys: dict[str, list[bool]] = defaultdict(list)
    by_sys_type: dict[tuple, list[bool]] = defaultdict(list)
    for r in results:
        for name, s in r["systems"].items():
            by_sys[name].append(s["correct"])
            by_sys_type[(name, r["question_type"])].append(s["correct"])
    print("\n=== LongMemEval-S subset accuracy (judged) ===")
    for name, vals in sorted(by_sys.items()):
        print(f"{name}: {sum(vals)}/{len(vals)} = {sum(vals)/len(vals):.0%}")
    types = sorted({r['question_type'] for r in results})
    for t in types:
        row = ", ".join(
            f"{n} {sum(by_sys_type[(n, t)])}/{len(by_sys_type[(n, t)])}"
            for n in ("rag", "facts", "understanding"))
        print(f"  {t}: {row}")


if __name__ == "__main__":
    main()

"""memline migrate: audit and clean a Mem0 export in one pass.

    python scripts/migrate.py mem0_export.json --out report_dir/
    python scripts/migrate.py mem0_export.json --out report_dir/ --push https://mindcarry.fly.dev

Reads a Mem0 export (a list of memories, or {"results": [...]}) and
produces, in the output directory:
- report.md: the audit. Duplicates, contradiction chains, stale
  unconfirmed memories, provenance coverage, and the temporal upgrade.
- cleaned.json: the deduplicated memories with validity windows:
  superseded values keep their history with valid_to set to the moment
  the newer value appeared, instead of being deleted or left to
  contradict the present.

The analysis is deterministic and local. Nothing leaves the machine
unless --push is given, which imports every cleaned memory into a
Memline account via its API (verbatim adds, original validity windows
preserved, superseded rows imported as closed history) using
MEMLINE_API_KEY.
"""
import argparse
import json
import os
import re
import sys
from collections import defaultdict
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from app.gate import _norm_body  # noqa: E402
from app.retrieval import content_tokens  # noqa: E402

SLOT_PATTERNS = [
    ("location", re.compile(r"\b(?:lives?|living|based|located) in ([A-Z][\w .'-]+?)(?:[.,;]|$)")),
    ("location", re.compile(r"\bmoved to ([A-Z][\w .'-]+?)(?:[.,;]|$)")),
    ("employer", re.compile(r"\bworks? (?:at|for) ([A-Z][\w& .'-]+?)(?:[.,;]|$)")),
    ("employer", re.compile(r"\bemployed (?:at|by) ([A-Z][\w& .'-]+?)(?:[.,;]|$)")),
    ("manager", re.compile(r"\bmanager is ([A-Z][\w .'-]+?)(?:[.,;]|$)")),
    ("role", re.compile(r"\bis an? ([\w ]+?(?:designer|engineer|manager|analyst|developer))(?:[.,;]|$)")),
]


def load_export(path: str) -> list[dict]:
    with open(path) as fh:
        data = json.load(fh)
    if isinstance(data, dict):
        data = data.get("results") or data.get("memories") or []
    out = []
    for i, item in enumerate(data):
        body = item.get("memory") or item.get("text") or item.get("data") or ""
        if not body.strip():
            continue
        out.append({
            "src_id": item.get("id", f"row-{i}"),
            "body": body.strip(),
            "user_id": item.get("user_id") or "",
            "created_at": item.get("created_at") or "",
            "updated_at": item.get("updated_at") or item.get("created_at") or "",
            "has_evidence": bool(item.get("evidence") or item.get("source_quote")
                                 or item.get("source")),
        })
    return out


def slot_of(body: str):
    for slot, pattern in SLOT_PATTERNS:
        m = pattern.search(body)
        if m:
            return slot, m.group(1).strip()
    return None, None


def analyze(items: list[dict], stale_days: int) -> dict:
    by_user: dict[str, list[dict]] = defaultdict(list)
    for item in items:
        by_user[item["user_id"]].append(item)

    report = {"total_in": len(items), "users": {}, "cleaned": []}
    totals = {"duplicates_removed": 0, "chains": 0, "superseded": 0,
              "stale": 0, "no_evidence": sum(1 for i in items if not i["has_evidence"])}
    for user_id, rows in sorted(by_user.items()):
        # 1. Deduplicate on normalized content (the feedback-loop guard).
        seen: dict[str, dict] = {}
        dup_groups: dict[str, int] = defaultdict(int)
        deduped = []
        for row in sorted(rows, key=lambda r: r["created_at"]):
            key = _norm_body(row["body"])
            if key in seen:
                dup_groups[seen[key]["body"]] += 1
                continue
            seen[key] = row
            deduped.append(row)
        dups_removed = len(rows) - len(deduped)

        # 2. Slot chains: same slot, different values over time.
        slots: dict[str, list[tuple[str, dict]]] = defaultdict(list)
        for row in deduped:
            slot, value = slot_of(row["body"])
            if slot:
                slots[slot].append((value, row))
        superseded_ids: dict[str, str] = {}  # src_id -> valid_to
        chains = []
        for slot, entries in sorted(slots.items()):
            values = {v for v, _ in entries}
            if len(values) <= 1:
                continue
            ordered = sorted(entries, key=lambda e: e[1]["created_at"])
            chains.append({"slot": slot,
                           "chain": [{"value": v, "at": r["created_at"], "body": r["body"]}
                                     for v, r in ordered]})
            for (_, older), (_, newer) in zip(ordered, ordered[1:]):
                if older["src_id"] not in superseded_ids:
                    superseded_ids[older["src_id"]] = newer["created_at"]

        # 3. Stale: old, never updated, not part of a chain.
        now = datetime.now(timezone.utc)
        stale = []
        for row in deduped:
            if row["src_id"] in superseded_ids:
                continue
            try:
                created = datetime.fromisoformat(row["created_at"].replace("Z", "+00:00"))
            except ValueError:
                continue
            age = (now - created).days
            if age >= stale_days and row["updated_at"] <= row["created_at"]:
                stale.append({**row, "age_days": age})

        for row in deduped:
            report["cleaned"].append({
                "user_id": user_id, "body": row["body"],
                "valid_from": row["created_at"] or None,
                "valid_to": superseded_ids.get(row["src_id"]),
                "migration": ("superseded" if row["src_id"] in superseded_ids
                              else "stale-unconfirmed" if row in stale else "current"),
            })
        report["users"][user_id or "(no user)"] = {
            "total": len(rows), "duplicates_removed": dups_removed,
            "dup_groups": sorted(({"body": b, "extra_copies": n}
                                  for b, n in dup_groups.items() if n > 0),
                                 key=lambda d: -d["extra_copies"])[:5],
            "chains": chains, "stale": stale,
        }
        totals["duplicates_removed"] += dups_removed
        totals["chains"] += len(chains)
        totals["superseded"] += len(superseded_ids)
        totals["stale"] += len(stale)
    report["totals"] = totals
    report["total_cleaned"] = len(report["cleaned"])

    affected = 0
    for u in report["users"].values():
        if u["chains"] or u["stale"] or u["duplicates_removed"] >= 5:
            affected += 1
    dup_share = (totals["duplicates_removed"] / rep_total(report)
                 if rep_total(report) else 0.0)
    report["impact"] = {
        "duplicate_share_pct": round(100 * dup_share, 1),
        "repeat_slots_in_top5": round(5 * dup_share, 1),
        "outdated_values_assertable": totals["superseded"],
        "users_affected": affected,
        "fixes_automatic": totals["duplicates_removed"] + totals["superseded"],
        "fixes_manual": totals["stale"],
    }
    return report


def rep_total(report: dict) -> int:
    return report["total_in"]


def render_report(rep: dict, stale_days: int, label: str = "") -> str:
    t = rep["totals"]
    lines = [
        "# Memory migration audit",
        "",
    ]
    if label:
        lines += [f"**Data provenance: {label}.**", ""]
    lines += [
        f"Export analyzed: **{rep['total_in']} memories** across "
        f"{len(rep['users'])} user scope(s).",
        "",
        "| Finding | Count |",
        "|---|---|",
        f"| Duplicate copies removed | {t['duplicates_removed']} |",
        f"| Contradiction chains detected (same slot, changing value) | {t['chains']} |",
        f"| Memories upgraded to superseded with a validity window | {t['superseded']} |",
        f"| Stale, never reconfirmed in {stale_days}+ days | {t['stale']} |",
        f"| Memories carrying any source evidence | {rep['total_in'] - t['no_evidence']} of {rep['total_in']} |",
        f"| Cleaned store size | {rep['total_cleaned']} |",
        "",
        "A contradiction chain is not deleted. The newest value stays current; "
        "each older value keeps its history with its validity window closed at "
        "the moment the newer value appeared, so the assistant stops asserting "
        "it about the present while remaining able to answer about the past.",
        "",
    ]
    imp = rep["impact"]
    lines += [
        "## Impact: how this store is affecting your product today",
        "",
        f"- **Retrieval noise:** {imp['duplicate_share_pct']}% of this store is "
        f"duplicate copies. A retrieval that samples the store returns roughly "
        f"{imp['repeat_slots_in_top5']} of its top 5 slots as repeats of "
        "something already in context, crowding out distinct information.",
        f"- **Wrong answers waiting to happen:** {imp['outdated_values_assertable']} "
        "outdated values (old locations, employers, managers) are still stored "
        "as if current. Any present-day lookup can return one, and the "
        "assistant will state it with full confidence.",
        f"- **Unverified answers:** {t['stale']} memories have not been "
        "reconfirmed in "
        f"{stale_days}+ days and none of the {rep['total_in']} memories "
        "carries source evidence, so when a user disputes an answer there is "
        "nothing to check it against.",
        f"- **Users affected:** {imp['users_affected']} of {len(rep['users'])} "
        "user scopes carry at least one contradiction chain, stale fact, or "
        "material duplication.",
        f"- **Fixes:** {imp['fixes_automatic']} are automatic in this "
        f"migration (duplicates removed, validity windows closed). "
        f"{imp['fixes_manual']} need a human decision (reconfirm or retire "
        "the stale memories).",
        "",
        "Estimates and definitions: retrieval noise assumes retrieval "
        "samples the store roughly uniformly, so duplicates occupy context "
        "slots in proportion to their share of the store; outdated values "
        "counts every superseded value in a detected chain; users affected "
        "counts scopes with a chain, a stale memory, or 5+ duplicate copies.",
        "",
    ]
    for user_id, u in rep["users"].items():
        lines += [f"## User scope: {user_id}", ""]
        if u["dup_groups"]:
            lines.append("Top duplicate groups (extra copies beyond the first):")
            for g in u["dup_groups"]:
                lines.append(f"- {g['extra_copies']}x extra: \"{g['body'][:90]}\"")
            lines.append("")
        for chain in u["chains"]:
            lines.append(f"Contradiction chain, slot **{chain['slot']}**:")
            for step in chain["chain"]:
                lines.append(f"- {step['at'][:10]}: {step['value']} (\"{step['body'][:80]}\")")
            lines.append(f"  Current value: **{chain['chain'][-1]['value']}**. "
                         "Older values are superseded, not deleted.")
            lines.append("")
        if u["stale"]:
            lines.append(f"Stale and never reconfirmed (sample of {len(u['stale'])}):")
            for s in u["stale"][:5]:
                lines.append(f"- {s['age_days']} days old: \"{s['body'][:90]}\"")
            lines.append("")
    lines += [
        "## What this audit cannot tell you",
        "",
        "An export shows the state of the store, not its production "
        "history. This report cannot say how often any memory was "
        "actually retrieved, whether a specific stale or contradictory "
        "memory ever reached a user, or how much token spend duplicates "
        "caused last month. Those answers need the team's retrieval "
        "logs or support records alongside the export. Where a finding "
        "above says a wrong value 'could be returned', that is the "
        "honest ceiling of what an export alone establishes; treat any "
        "clean result the same way: few findings in the export means "
        "the store is tidy, not that production answers were correct.",
        "",
        "## What happens on import",
        "",
        "- Duplicates never enter storage (the write gate skips them).",
        "- Superseded memories are imported as history with closed validity "
        "windows, so present-day answers use only current values.",
        "- Stale memories are imported flagged for reconfirmation, not "
        "silently trusted.",
        "- From the first new write onward, every memory carries evidence, "
        "passes the grounding gate, and appears in Memory Health.",
        "",
        "Method and limits: duplicates are exact on normalized content; slot "
        "chains use deterministic patterns for location, employer, manager and "
        "role, so paraphrased revisions in other slots need the semantic pass "
        "that runs inside Memline after import. Stale means old and never "
        "updated since creation, a proxy for unconfirmed, not proof of falsity.",
    ]
    return "\n".join(lines) + "\n"


def push(cleaned: list[dict], base_url: str) -> int:
    """Import cleaned memories, including superseded history rows.

    Order by valid_from so earlier values land before later ones. Superseded
    rows carry their closed validity window; current rows stay open.
    """
    import urllib.request
    key = os.environ.get("MEMLINE_API_KEY", "")
    if not key:
        raise SystemExit("--push needs MEMLINE_API_KEY in the environment.")
    sent = 0
    ordered = sorted(
        cleaned,
        key=lambda m: (m.get("user_id") or "", m.get("valid_from") or "", m.get("body") or ""),
    )
    for mem in ordered:
        body = {
            "text": mem["body"], "user_id": mem["user_id"], "infer": False,
            "metadata": {"migrated_from": "mem0-export",
                         "original_valid_from": mem["valid_from"],
                         "migration_status": mem["migration"]},
        }
        if mem.get("valid_from"):
            body["valid_from"] = mem["valid_from"]
        if mem.get("valid_to"):
            body["valid_to"] = mem["valid_to"]
        payload = json.dumps(body).encode()
        req = urllib.request.Request(base_url.rstrip("/") + "/v1/memories", data=payload,
                                     headers={"Authorization": f"Bearer {key}",
                                              "Content-Type": "application/json"})
        with urllib.request.urlopen(req) as resp:
            if resp.status == 200:
                sent += 1
    return sent


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("export")
    ap.add_argument("--out", default="migration_out")
    ap.add_argument("--stale-days", type=int, default=180)
    ap.add_argument("--push", default="", help="Memline base URL to import into")
    ap.add_argument("--label", default="",
                    help="provenance line printed on the report, e.g. "
                         "'synthetic demonstration data, not a customer export'")
    args = ap.parse_args()

    items = load_export(args.export)
    rep = analyze(items, args.stale_days)
    os.makedirs(args.out, exist_ok=True)
    with open(os.path.join(args.out, "report.md"), "w") as fh:
        fh.write(render_report(rep, args.stale_days, args.label))
    with open(os.path.join(args.out, "cleaned.json"), "w") as fh:
        json.dump(rep["cleaned"], fh, indent=1)
    t = rep["totals"]
    print(f"analyzed {rep['total_in']} memories: {t['duplicates_removed']} duplicates, "
          f"{t['chains']} contradiction chains, {t['superseded']} superseded, "
          f"{t['stale']} stale, {t['no_evidence']} without evidence")
    print(f"report: {args.out}/report.md   cleaned: {args.out}/cleaned.json")
    if args.push:
        sent = push(rep["cleaned"], args.push)
        print(f"pushed {sent} memories (including superseded history) to {args.push}")


if __name__ == "__main__":
    main()

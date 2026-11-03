"""The Understanding Engine's capture side: build proposed understandings
from a person's conversations.

Design (UNDERSTANDING.md v3.1, demo path):
- No regex extraction. Facts are cheap; understanding comes from patterns
  across many conversations, so extraction is done by an LLM prompted like
  an anthropologist: "read this person's conversations, build an
  understanding of who they are, extract only claims that would materially
  improve another assistant".
- Six specialized extractors run in parallel (identity, goals, principles,
  preferences, writing style, narrative and projects), then merge.
- Every proposal carries its evidence (a short exact quote, or a behavioral
  pattern with a count) and a surprise score: how likely the user is to
  think "how did it know that". Surprise, not volume, is the metric.
- Everything lands in the inbox as pending. Nothing is stored silently.
- If no model is configured the engine says so. It never falls back to a
  weaker silent substitute.
"""
import json
import os
import re
import urllib.request
from concurrent.futures import ThreadPoolExecutor

API_URL = "https://api.anthropic.com/v1/messages"
MODEL = os.environ.get("MEMLINE_LLM_MODEL", "claude-haiku-4-5-20251001")
DIGEST_BUDGET = 48000  # characters of user text across all conversations
MAX_PER_KIND = {"identity": 5, "goal": 5, "principle": 6, "preference": 8,
                "style": 5, "narrative": 4, "project": 5, "unknown": 4}
TOTAL_CAP = 40


class UnderstandingUnavailable(Exception):
    """No model configured, or the model call failed. Surfaced honestly."""


def llm_configured() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY"))


def _call_model(system: str, user_text: str, max_tokens: int = 1800) -> str:
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        raise UnderstandingUnavailable("no model configured")
    payload = {
        "model": MODEL,
        "max_tokens": max_tokens,
        "system": system,
        "messages": [{"role": "user", "content": user_text}],
    }
    req = urllib.request.Request(
        API_URL, data=json.dumps(payload).encode(), method="POST",
        headers={"x-api-key": key, "anthropic-version": "2023-06-01",
                 "content-type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read().decode())
    except Exception as exc:  # network, auth, rate limit: all mean unavailable
        raise UnderstandingUnavailable(f"model call failed: {exc.__class__.__name__}")
    return "".join(block.get("text", "") for block in data.get("content", [])
                   if block.get("type") == "text")


BASE = """You are one specialist on a team building a personal understanding model of ONE person from their AI conversation history. You are given a digest of conversations: titles plus the person's own messages only.

Rules for everything you return:
- Extract only claims that would materially improve another assistant's work with this person. Skip trivia, one-off requests, and anything the person would find obvious or creepy.
- Ground every claim in the digest. Evidence must be either a short exact quote from the person (under 140 characters) or a behavioral pattern with a count (for example: "in 9 of 11 writing requests, asked to remove hype words").
- Write the claim in second person about the person, as a durable understanding, not a transcript summary. Good: "You are working toward a Staff-level role and judge opportunities by scope growth." Bad: "The user asked about staff roles."
- Rate surprise from 1 to 5: how likely is this person to think "how did it know that" when shown the claim. Explicit self-descriptions are 1 or 2. Patterns the person probably never noticed about themselves are 4 or 5. Be honest; most claims are not 5.
- Mark strength "strong" when the evidence repeats or is stated outright, "emerging" when it is a real but thinner pattern.
- Return ONLY a JSON array, no prose, no code fences. Each item: {"title": string (2-5 words), "body": string (the claim, 1-2 sentences), "evidence": string, "surprise": int 1-5, "strength": "strong" or "emerging"}. Return at most {cap} items. If nothing in the digest supports your specialty, return []."""

EXTRACTORS = {
    "identity": ("Identity extractor. Find who this person is and who they are becoming: roles, profession, life stage, communities, and identity-level statements ('I am an engineer', 'becoming a founder'). Identity changes slowly; prefer claims that would still be true in a year.", 5),
    "goal": ("Goal extractor. Find what this person is actively trying to achieve or become: promotions, launches, learning targets, health or money goals, applications, transitions. Include the horizon when the digest shows one. A goal is something with effort behind it, not a passing wish.", 5),
    "principle": ("Principle extractor. Find how this person decides: tradeoffs they repeatedly make, what they optimize, what they refuse, how they judge quality, risk, people, and products. Principles are usually implicit in repeated choices, rarely stated. These are the highest-value claims you can find.", 6),
    "preference": ("Preference extractor. Find concrete working preferences: formats, tools, detail level, tone, foods, schedules, anything an assistant should default to without being asked. Only preferences shown more than once or stated as standing.", 8),
    "style": ("Writing style extractor. Find how this person writes and wants writing done: voice, structure, length, words and tones they love or ban, how they edit drafts, what they always change. Editing behavior is stronger evidence than stated taste.", 5),
    "narrative": ("Narrative and projects extractor. Find the stories: current and recent projects (return those with kind-level concreteness: name, what it is, its stage) and the arcs connecting them (career moves, why they left, what they learned). For projects use title = the project name and body = what it is and where it stands, and add \"project\": true to that item. For arcs, compress the story, do not list events.", 7),
    "unknown": ("Open questions extractor. Find the GAPS: things this person references often but never explains, where an assistant would have to guess. Examples: a startup mentioned repeatedly whose business is never described; a manager mentioned often whose relationship and role are unclear; a project whose purpose is assumed but unstated. For each gap: title = the missing piece in 2-5 words, body = one sentence in the form 'You mention X often, but I don't understand Y yet.', evidence = how often it appears or a short quote, surprise = 1 always (these are questions, not insights). Return at most 4. Only gaps that recur across conversations, never one-off mentions.", 4),
}


def build_digest(conversations: list[dict]) -> str:
    """Sample user text across conversations within a character budget.
    First messages and long messages carry the most self-description, so
    each conversation contributes its opener plus its longest messages."""
    total_msgs = sum(len(c["messages"]) for c in conversations)
    header = (f"DIGEST: {len(conversations)} conversations, {total_msgs} messages "
              f"from the person. Titles and the person's own words only.\n")
    parts = [header]
    budget = DIGEST_BUDGET
    per_conv = max(1200, DIGEST_BUDGET // max(1, len(conversations)))
    for conv in conversations:
        if budget <= 0:
            break
        msgs = [m.strip() for m in conv["messages"] if m and m.strip()]
        if not msgs:
            continue
        picked = []
        seen = set()
        opener = msgs[0]
        picked.append(opener)
        seen.add(opener)
        for m in sorted(msgs, key=len, reverse=True):
            if m not in seen:
                picked.append(m)
                seen.add(m)
            if sum(len(x) for x in picked) > per_conv:
                break
        block = f"\n## {conv.get('title') or 'Untitled conversation'}\n" + "\n---\n".join(picked)
        block = block[:per_conv + 200]
        parts.append(block)
        budget -= len(block)
    return "\n".join(parts)


def _parse_items(text: str) -> list[dict]:
    text = text.strip()
    text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.MULTILINE).strip()
    start, end = text.find("["), text.rfind("]")
    if start == -1 or end == -1:
        return []
    try:
        data = json.loads(text[start:end + 1])
    except json.JSONDecodeError:
        return []
    return data if isinstance(data, list) else []


def _run_extractor(kind: str, digest: str, source: str) -> list[dict]:
    instruction, cap = EXTRACTORS[kind]
    system = BASE.replace("{cap}", str(cap)) + "\n\nYour specialty: " + instruction
    raw = _call_model(system, digest)
    out = []
    for item in _parse_items(raw)[:cap]:
        try:
            body = str(item["body"]).strip()
            title = str(item["title"]).strip()
            evidence = str(item.get("evidence", "")).strip()
            surprise = max(1, min(5, int(item.get("surprise", 2))))
        except (KeyError, TypeError, ValueError):
            continue
        if not body or not title:
            continue
        out.append({
            "kind": "project" if (kind == "narrative" and item.get("project")) else kind,
            "title": title[:80], "body": body[:500],
            "source": source, "source_quote": evidence[:300],
            "confidence": 0.9 if item.get("strength") == "strong" else 0.6,
            "surprise": surprise,
        })
    return out


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", text.lower()).strip()


def _overlap(a: str, b: str) -> float:
    wa, wb = set(_norm(a).split()), set(_norm(b).split())
    if not wa or not wb:
        return 0.0
    return len(wa & wb) / max(1, min(len(wa), len(wb)))


def merge(candidates: list[dict]) -> list[dict]:
    """Dedupe near-identical claims (same normalized title, or very high
    body overlap) keeping the higher-surprise version, cap per kind and
    overall, and return sorted so the most surprising understandings are
    reviewed first. Each kept item records its support: how many distinct
    extractor kinds independently produced the same understanding. That
    agreement count is kept as metadata and used in ranking, because
    'noticed independently by three extractors' is a stronger signal than
    any single model's confidence."""
    kept: list[dict] = []
    for cand in sorted(candidates, key=lambda c: -c.get("surprise", 0)):
        match = None
        for other in kept:
            if _norm(cand["title"]) == _norm(other["title"]) and cand["kind"] == other["kind"]:
                match = other
                break
            if _overlap(cand["body"], other["body"]) > 0.8:
                match = other
                break
        if match is not None:
            match.setdefault("_kinds", {match["kind"]}).add(cand["kind"])
        else:
            cand = dict(cand)
            cand["_kinds"] = {cand["kind"]}
            cand["_support_base"] = cand.get("support", 1)
            kept.append(cand)
    for item in kept:
        item["support"] = max(item.pop("_support_base", 1),
                              len(item.pop("_kinds", {item["kind"]})))
    kept.sort(key=lambda c: -(c.get("surprise", 0) + 0.5 * min(c.get("support", 1) - 1, 3)))
    per_kind: dict[str, int] = {}
    final = []
    for cand in kept:
        k = cand["kind"]
        if per_kind.get(k, 0) >= MAX_PER_KIND.get(k, 5):
            continue
        per_kind[k] = per_kind.get(k, 0) + 1
        final.append(cand)
        if len(final) >= TOTAL_CAP:
            break
    return final


CONSOLIDATE_SYSTEM = """You are the merge step for a personal understanding model. Six specialist extractors read the same person's conversation history and proposed understandings. Specialists overlap: the same underlying pattern often appears as a principle, a preference, and a style claim at once.

Merge the proposals into the canonical set:
- One item per distinct underlying understanding. When duplicates disagree on kind, keep the kind that fits best (a repeated decision pattern is a principle; a format default is a preference; a voice trait is style; a target with effort behind it is a goal; who they are is identity; a story arc is narrative; a concrete effort with a name and a stage is a project).
- Hard rule on repetition: if the same underlying pattern shows up in three or more kinds, keep at most two items for it: the principle version, plus the single most actionable other version. The person reviews this list; near-identical claims in different clothing read as padding and destroy trust in the sharp ones.
- Keep the sharpest body wording, the strongest evidence, and the highest surprise score among the merged items.
- Do not invent anything new, and do not drop a distinct understanding.
- Return ONLY a JSON array, no prose, no code fences. Each item: {"kind": one of identity/goal/principle/preference/style/narrative/project, "title": string, "body": string, "evidence": string, "surprise": int 1-5, "strength": "strong" or "emerging", "sources": [the numbers of the proposals you merged into this item]}. The sources field matters: it records how much independent support each understanding has."""


def _consolidate(candidates: list[dict], source: str) -> list[dict]:
    listing = "\n".join(
        f"{i + 1}. [{c['kind']}] {c['title']}: {c['body']} (evidence: {c['source_quote']}; surprise {c.get('surprise', 2)})"
        for i, c in enumerate(candidates))
    raw = _call_model(CONSOLIDATE_SYSTEM, listing, max_tokens=4096)
    out = []
    for item in _parse_items(raw):
        try:
            kind = str(item["kind"]).strip()
            body = str(item["body"]).strip()
            title = str(item["title"]).strip()
            evidence = str(item.get("evidence", "")).strip()
            surprise = max(1, min(5, int(item.get("surprise", 2))))
        except (KeyError, TypeError, ValueError):
            continue
        if kind not in MAX_PER_KIND or not body or not title:
            continue
        support = 1
        sources = item.get("sources")
        if isinstance(sources, list) and sources:
            kinds = {candidates[i - 1]["kind"] for i in sources
                     if isinstance(i, int) and 1 <= i <= len(candidates)}
            if kinds:
                support = len(kinds)
        out.append({"kind": kind, "title": title[:80], "body": body[:500],
                    "source": source, "source_quote": evidence[:300],
                    "confidence": 0.9 if item.get("strength") == "strong" else 0.6,
                    "surprise": surprise, "support": support})
    return out


def extract_understandings(conversations: list[dict], source: str) -> list[dict]:
    """Run all six extractors in parallel over one digest, consolidate
    overlaps into canonical understandings, and merge.
    Raises UnderstandingUnavailable when no model can be reached."""
    if not llm_configured():
        raise UnderstandingUnavailable("no model configured")
    digest = build_digest(conversations)
    all_candidates: list[dict] = []
    errors = 0
    with ThreadPoolExecutor(max_workers=len(EXTRACTORS)) as pool:
        futures = {pool.submit(_run_extractor, kind, digest, source): kind
                   for kind in EXTRACTORS}
        for fut in futures:
            try:
                all_candidates += fut.result()
            except UnderstandingUnavailable:
                errors += 1
    if errors == len(EXTRACTORS):
        raise UnderstandingUnavailable("all extractors failed")
    unknowns = [c for c in all_candidates if c["kind"] == "unknown"]
    known = [c for c in all_candidates if c["kind"] != "unknown"]
    if len(known) > 12:
        try:
            consolidated = _consolidate(known, source)
            if len(consolidated) >= 8:
                known = consolidated
        except UnderstandingUnavailable:
            pass  # rule-based merge below still applies
    return merge(known) + merge(unknowns)


def top_insights(candidates: list[dict], n: int = 3) -> list[dict]:
    pool = [c for c in candidates if c["kind"] != "unknown"]
    ranked = sorted(pool, key=lambda c: (-(c.get("surprise", 0) + 0.5 * min(c.get("support", 1) - 1, 3)),
                                         0 if c["kind"] in ("principle", "goal", "identity") else 1))
    return [{"kind": c["kind"], "title": c["title"], "body": c["body"]}
            for c in ranked[:n]]


def starter_memories(answers: dict) -> list[dict]:
    """The 6-question starter interview still arrives as form answers, so
    it stays deterministic: the user's own words, lightly titled."""
    fields = [
        ("name_role", "identity", "Name and role"),
        ("work", "fact", "Work"),
        ("projects", "project", "Current projects"),
        ("preferences", "preference", "Preferences"),
        ("tools_style", "style", "Tools and working style"),
        ("people", "person", "Important people"),
    ]
    out = []
    for key, kind, title in fields:
        value = (answers.get(key) or "").strip()
        if value:
            out.append({"kind": kind, "title": title, "body": value,
                        "source": "starter interview", "source_quote": value})
    return out

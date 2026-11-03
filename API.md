# Memline Developer API (/v1)

Memory and understanding infrastructure for AI apps and agents. The API
is shaped like Mem0's on purpose: if your app already calls Mem0, you
can switch by changing the base URL and the key. What you get for the
switch is below, under "How it differs".

Base URL: `https://mindcarry.fly.dev/v1`
Auth: `Authorization: Bearer ml_...` (create a key in the app, Settings
tab; keys are stored hashed and shown once).

## Endpoints

| Method | Path | What it does |
|---|---|---|
| POST | `/v1/memories` | Add from `messages` or `text`. With `infer: true` (default), the understanding engine extracts typed understandings; with `infer: false` the text is stored verbatim. Same kind + title in the same scope supersedes the old memory and closes its validity window. |
| POST | `/v1/memories/search` | Hybrid search: `{query, user_id, agent_id, app_id, run_id, limit, as_of, threshold}`. Returns score components per result. |
| GET | `/v1/memories` | List active memories in a scope. |
| GET | `/v1/memories/{id}` | One memory. |
| PUT | `/v1/memories/{id}` | Replace the body; an UPDATE event is recorded and the memory is re-indexed. |
| DELETE | `/v1/memories/{id}` | Delete one memory. Its history stays readable. |
| DELETE | `/v1/memories` | Delete all active memories in a scope. |
| GET | `/v1/memories/{id}/history` | Full event history: ADD, UPDATE, SUPERSEDE, INVALIDATE, DELETE. |
| POST | `/v1/memories/{id}/invalidate` | Close the validity window now. Present search stops returning it; as-of search into the past still does. |
| GET | `/v1/graph?user_id=` | Reasoning over relationships: people, projects and how they connect (works with, works on, part of), derived from the user's memories. |
| GET | `/v1/understanding?user_id=` | The understanding for one end user: all active memories grouped by kind, including unknowns. (`/v1/profile` is kept as an alias.) |
| POST | `/v1/assemble_context` | The one-call endpoint: `{query, user_id, max_tokens}` returns assembled, ready-to-paste context plus the supporting understandings, what was omitted and why, the unknowns, and a confidence summary. Developers should not have to rebuild the planner. |
| POST | `/v1/remember` | The add endpoint under its guarantee name. Every extracted candidate passes the write gate (below) and comes back with a verdict: stored, rejected, or skipped, with the reason. |
| GET | `/v1/memory_health?user_id=` | Memory Integrity for one end user: grounded share, stale count, contradictions, superseded count, unknowns, gate pass rate, orphaned graph edges, coverage, and the most recent rejections. |
| GET | `/v1/rejections?user_id=` | What the write gate refused to store, and why. |

## The write gate

Every machine-extracted candidate is checked before storage:

- **Grounding.** The candidate's evidence must be supported by the
  source conversation in the same call. Ungrounded candidates are
  rejected with a reason and recorded (see `/v1/rejections`); they are
  never stored. Behavioral-pattern evidence is accepted and labeled
  `pattern`; verbatim developer writes are labeled `asserted`.
- **No feedback loops.** A candidate duplicating an active memory is
  skipped. Stored memories cannot multiply by being recalled and
  re-fed as input, the failure behind the category's worst junk audits.
- **Revision detection.** A candidate restating an existing slot with
  a new value supersedes it as a REVISION: the old memory's validity
  window closes and the change is in its history, instead of the two
  coexisting as a contradiction.
- Unknowns are exempt by design: an open question asserts ignorance,
  not a fact, so it is stored labeled `question` and excluded from the
  grounded percentage. The gate guards claims.

Search results carry a `why` array ("noticed independently by 3
extractors", "evidence verified against the source conversation",
"currently valid, not superseded", graph connections), so every
retrieval explains itself.

## Operations, measured

Measured 2026-11-02 on a single small VM (SQLite, local hashing embedder,
loopback, store of 1,050 memories seeded through this API; full method
in eval/PERF.md): search p50 371 ms / p95 419 ms; assemble_context p50
382 ms; verbatim add p50 82 ms; memory_health p50 86 ms. Storage is
about 4.2 KB per memory including embedding, graph edges and history.
Stated plainly: retrieval scoring currently runs in process over the
scope's memories, so search latency grows with store size; it is
comfortable at pilot scale and a vector index is the known next step
before large stores. Extraction adds are LLM-bound (seconds, by
design asynchronous in the consumer product).

## Guarantees

Every stored understanding has evidence. Every understanding can be
invalidated without deleting its history. Every retrieval is
explainable. Every contradiction is detectable (and counted, in
`/v1/memory_health`). Every deletion removes the memory's derived
graph edges. These are operational guarantees, not features.

Scoping: the API key's account is the tenant. `user_id`, `agent_id`,
`app_id` and `run_id` scope end users and sessions inside it, exactly
as in Mem0.

## Example

```bash
curl -X POST https://mindcarry.fly.dev/v1/memories \
  -H "Authorization: Bearer ml_YOUR_KEY" -H "Content-Type: application/json" \
  -d '{"messages": [{"role": "user", "content": "I am training for a marathon and I never eat meat."}],
       "user_id": "user-42"}'

curl -X POST https://mindcarry.fly.dev/v1/memories/search \
  -H "Authorization: Bearer ml_YOUR_KEY" -H "Content-Type: application/json" \
  -d '{"query": "what is she training for", "user_id": "user-42"}'
```

Every search result carries `score_components` (semantic, lexical,
coverage, graph_boost), `evidence` (the source quote the memory was
extracted from), `confidence`, `support_count` (how many independent
extractors produced it), and its `valid_from` / `valid_to` window.

## How it differs from Mem0

- **Understanding, not just facts.** Extraction is typed: identity,
  goals, principles, preferences, writing style, projects, people, and
  explicit unknowns, produced by specialist extractors in parallel plus
  a consolidation pass. On our initial smoke benchmark (small,
  synthetic, recorded extraction outputs; method and limits in
  `eval/RESULTS.md`), three stores over the same history and retrieval
  answered as follows: raw RAG over conversation chunks 8/13, a
  Mem0-style fact store 6/13, the understanding store 12/13, with facts
  at parity and the whole gap in goals, principles, style and identity.
  Treat these as a smoke signal, not a result. The live-extraction run
  (same fixture, real extractors) preserved the ordering:
  understanding 11/13, raw RAG 8/13, facts 4/13. The first independent
  dataset run (LongMemEval-S, 30-question subset, full protocol and
  limits in `eval/LONGMEMEVAL.md`) gave judged accuracy of 53% for the
  understanding store, 43% for facts and 40% for raw RAG, including a
  documented 0/5 failure on preference-style questions. Victory claims
  wait for the full set and external developers.
- **Temporal validity.** Every memory has a validity window. Facts that
  stop being true are invalidated, not deleted or silently overwritten,
  and `as_of` search answers for any moment in time.
- **Evidence and history.** Every memory carries its source quote and a
  full event history that survives deletion of the memory itself.
- **Transparent ranking.** Score components are returned, not hidden.

## Honest limits

- Extraction quality claims rest on a small synthetic benchmark so far;
  the live-extraction run (`eval/run_benchmark.py --live`) and public
  LongMemEval numbers are still to be produced.
- Without `EMBEDDING_API_KEY` set on the server, retrieval uses a local
  lexical hashing embedder; ranking rebalances automatically when a
  neural embedder is configured.
- The consumer approval inbox governs the end-user product. The /v1 API
  is machine-to-machine: the calling application is the approver, and
  every write is still evidence-carrying and fully auditable.

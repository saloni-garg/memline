# Memline

Trustworthy memory for AI applications. Every stored understanding is
grounded in evidence, time-aware, explainable, auditable, and revisable.

Most memory layers will store anything an extractor produces, including
hallucinations, duplicates, and facts that stopped being true months
ago, and will then retrieve them with confidence. Memline is built
around the opposite defaults:

- **A write gate.** Extracted candidates are verified against the
  source conversation before they are stored. Ungrounded candidates
  are rejected with a recorded reason, never silently kept. Duplicates
  never re-enter storage.
- **Temporal validity.** Every memory has a validity window. When a
  fact changes, the old value is superseded and its window closes; it
  stays available for as-of queries about the past and stops being
  asserted about the present.
- **Memory Health.** The store reports on itself: grounded percentage,
  contradictions, stale memories, superseded count, write rejection
  rate, and coverage, at `GET /v1/memory_health`.
- **Explainable retrieval.** Every search result carries its evidence
  and a plain-language `why` array.
- **Understanding, not just facts.** With an LLM configured, imports
  are extracted into typed understandings (identity, goals, principles,
  preferences, writing style, projects, people, and explicit
  unknowns), not flat fact strings.

## Start with an audit of the store you already have

Before adopting anything, run the diagnostic on your current memory:

    python scripts/migrate.py your_mem0_export.json --out audit/

It reports duplicate accumulation, contradiction chains (the same
slot changing value over time, never resolved), stale memories, and
provenance coverage, translated into product impact, plus a cleaned
store with validity windows applied. It also states plainly what an
export alone cannot tell you. A demonstration on synthetic data lives
in `eval/migration_demo/` and is labeled as synthetic.

## Run the server

    docker compose up -d          # or see SELFHOST.md for a native install

Then read the API documentation in `API.md` (also served at
`/api-docs`). Create an account in the web app, mint an API key in
Settings, and call the API:

    POST /v1/remember     store through the write gate
    POST /v1/memories/search
    POST /v1/assemble_context   token-budgeted context for one prompt
    GET  /v1/understanding      the typed profile, unknowns included
    GET  /v1/memory_health

Python and TypeScript clients are in `sdk/`, both dependency-free.

The API shape is deliberately familiar if you know Mem0: add, search,
get, update, delete, history, and user/agent/app/run scoping work the
way you expect, so switching is mostly a base URL change after the
migration audit.

## Benchmarks, with their limits attached

The evaluation harness is in `eval/` and is published with raw outputs
and failure analysis, because this category's benchmark numbers are
routinely overstated, including by vendors. Current state, in brief:

- On a small fixture built for higher-level understanding, the
  understanding store consistently outranks raw RAG, which outranks an
  atomic-fact store, across recorded and live extraction runs.
- On a 30-question LongMemEval-S subset: understanding 53%, facts
  43%, raw RAG 40%, with a documented failure on preference questions.
- These are smoke signals, not victories. Subset sizes, the small
  reader and judge model, and the local embedder all limit them;
  `eval/RESULTS.md` and `eval/LONGMEMEVAL.md` say exactly how.

Measured operations numbers, including where search latency grows
with store size, are in `eval/PERF.md`.

## Open core

The server, API, SDKs, migration and audit tooling, and the evaluation
harness are open source under Apache 2.0. The hosted service at
mindcarry.fly.dev and future enterprise capabilities (SSO, RBAC,
compliance, SLAs, managed backups and monitoring) are commercial.
See `OPEN_CORE.md`. Your data is never locked in: self-hosting is one
SQLite file, and full export is built in.

## License

Apache License 2.0. See `LICENSE`.

# Operations measurements

Measured 2026-11-02 on this project's VM (single small
machine, SQLite, local hashing embedder, loopback HTTP, uvicorn
defaults, store seeded through the public API).

| Operation | p50 | p95 |
|---|---|---|
| POST /v1/memories/search | 371.3 ms | 419.0 ms |
| POST /v1/assemble_context | 381.9 ms | 427.3 ms |
| POST /v1/memories (verbatim add) | 82.3 ms | 107.1 ms |
| GET /v1/memory_health | 85.7 ms | 173.1 ms |

- Store: 1050 memories, database file 4364 KB
  (4.16 KB per memory including embedding, graph edges
  and event history; growth is linear in this design).
- Seeding 1000 verbatim adds took 42.4s end to end
  (42.4 ms per add sustained).
- Extraction adds (infer=true) are dominated by the understanding
  engine: 8 LLM calls (7 specialist extractors in parallel plus
  consolidation), measured end to end at roughly 30 to 50 seconds per
  import in live verification. That path is asynchronous by design in
  the consumer product; API callers who need fast writes use verbatim
  adds or accept extraction latency for typed understanding.

Limits: loopback timings exclude network and TLS; a hosted deployment
adds both. The neural embedder, when configured, adds one embedding API
call per write and per search. SQLite on one machine is the current
scale ceiling; nothing here is a hosted SLA.

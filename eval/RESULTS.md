# Benchmark results

## The claim we are willing to make

Understanding is a better intermediate representation than atomic facts
for tasks that require reasoning over goals, identity, principles,
writing style, and longitudinal behavior, while remaining competitive
on factual recall.

Across our current evaluations, we consistently observe the same
ordering, Understanding > Raw RAG > Atomic facts, for tasks that
depend on higher-level user understanding. We do not claim the ordering
holds for purely factual workloads, and we publish the runs that cut
against us (eval/LONGMEMEVAL.md) alongside the ones that do not.

## Run: 2026-11-02, recorded extraction outputs, local embedder

Three systems over the same fixture history, through the same production
retrieval stack, top-3 answerability over 13 hand-written questions
(eval/fixture_qa.json):

| System | Fact | Goal | Principle | Style | Identity | Preference | Project | Total |
|---|---|---|---|---|---|---|---|---|
| Raw RAG (conversation chunks) | 3/4 | 1/2 | 1/2 | 1/2 | 0/1 | 1/1 | 1/1 | 8/13 |
| Facts (Mem0-style store) | 4/4 | 0/2 | 0/2 | 0/2 | 0/1 | 1/1 | 1/1 | 6/13 |
| Understanding (Memline store) | 3/4 | 2/2 | 2/2 | 2/2 | 1/1 | 1/1 | 1/1 | 12/13 |

Reading, honestly:

- Fact stores are at parity or slightly better on plain facts. Expected.
- Raw RAG beats the fact store overall. Atomic-fact extraction loses
  information: patterns that were visible across raw messages (a goal
  implied by behavior, a style shown by repeated edits) get flattened
  or dropped when each message becomes a standalone fact. Anyone
  claiming extraction is free should have to answer this row.
- The understanding store leads because it makes exactly those implicit
  patterns explicit and typed (goals, principles, style, identity:
  7/7, against 0/7 for facts and 2/7 for raw RAG), so retrieval can
  find them directly.
- Caveat that favors RAG here: the fixture is 35 user messages, so
  top-3 over 35 chunks is an easy retrieval problem. At thousands of
  chunks, raw RAG's precision and token cost degrade while a curated
  store does not. That scaling claim is argued, not measured here.

This run also caught two real bugs in our own stack (hash-embedder
noise outranking exact matches; generic verbatim adds superseding each
other), both fixed before these numbers were produced.

## Run: 2026-11-02, LIVE extraction (real LLM extractors, same fixture)

| System | Fact | Goal | Principle | Style | Identity | Preference | Project | Total |
|---|---|---|---|---|---|---|---|---|
| Raw RAG (conversation chunks) | 3/4 | 1/2 | 1/2 | 1/2 | 0/1 | 1/1 | 1/1 | 8/13 |
| Facts (live Mem0-style extraction) | 3/4 | 1/2 | 0/2 | 0/2 | 0/1 | 0/1 | 0/1 | 4/13 |
| Understanding (live Memline extraction) | 3/4 | 2/2 | 2/2 | 1/2 | 1/1 | 1/1 | 1/1 | 11/13 |

The ordering holds under live extraction: understanding ahead, raw RAG
second, atomic facts last. Two honest notes. First, the live fact
extractor scored below the recorded hand-written fact list (4 vs 6),
which means the recorded run was generous to the baseline. Second, the
live understanding run lost one style question to phrasing: the
extractor captured the pattern in different words than the question's
expected synonyms. Extraction phrasing variance is real and visible in
both directions.

## Limits, stated plainly

- Small synthetic benchmark. A smoke benchmark, not LongMemEval.
- The first table uses recorded extraction outputs; the live run
  (`run_benchmark.py --live`, real extractors) is reported in its own
  section above and preserved the ordering. The independent-dataset
  run lives in `eval/LONGMEMEVAL.md`.
- Retrieval used the local hashing embedder. A neural embedder
  (EMBEDDING_API_KEY) changes absolute numbers for all three systems.
- Answerability (expected content present in top-3) is a proxy for
  end-to-end QA accuracy, not the thing itself.
- Do not lead with these numbers externally until the full LongMemEval
  set (or a random 100) and external developers back them. The 30
  question subset in LONGMEMEVAL.md is a first signal, with its own
  stated limits.

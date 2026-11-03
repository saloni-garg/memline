# LongMemEval-S subset run: 2026-11-02

First independent-dataset run. Harness: eval/longmemeval.py. Raw
per-question output: eval/longmemeval_results.json.

## Protocol

- Dataset: LongMemEval-S (500 questions). Subset: the first 5 instances
  of each of the 6 question types in dataset order, 30 questions. Not
  random, not the full set.
- Three stores per question history, all queried through Memline's
  production retrieval (local hashing embedder, top 5):
  raw RAG (one chunk per conversation turn), facts (one Mem0-style
  atomic-fact extraction call), understanding (the production
  specialist-extractor pipeline).
- Extraction systems read the production digest (48k characters sampled
  per history). S histories run to roughly 115k tokens, so extraction
  sees a fraction of the history; raw RAG stores every turn. This
  truncation is shipped product behavior, exposed here on purpose.
- Reader: claude-haiku-4-5, instructed to answer only from retrieved
  context and to abstain otherwise. Judge: same model, official-style
  correctness prompt against the reference answer.
- No abstention (_abs) questions fell in this subset.

## Results (judged accuracy)

| System | Overall | knowledge-update | multi-session | single-session-assistant | single-session-preference | single-session-user | temporal-reasoning |
|---|---|---|---|---|---|---|---|
| Raw RAG | 12/30 (40%) | 1/5 | 1/5 | 3/5 | 2/5 | 3/5 | 2/5 |
| Facts | 13/30 (43%) | 2/5 | 1/5 | 4/5 | 2/5 | 2/5 | 2/5 |
| Understanding | 16/30 (53%) | 2/5 | 2/5 | 4/5 | 0/5 | 4/5 | 4/5 |

## Reading

- On a benchmark built for factual recall across long histories, the
  understanding store still leads, and its strongest types here are
  temporal-reasoning and single-session-user (4/5 each). The margin is
  thinner than on the fixture (53% vs 43/40%), which is what an honest
  prior would predict: LongMemEval is the fact store's home turf.
- single-session-preference is a documented failure: understanding 0/5
  against 2/5 for both baselines. Diagnosis from the raw outputs: the
  store captured the preferences and retrieval returned them; the
  reader then led with abstention ("I don't have information about
  your current setup") because preference questions pose as factual
  lookups with unstated premises, and a strict containment judge scores
  the tailoring that followed as incorrect. The official benchmark
  scores this type with a preference rubric, not containment, so our
  uniform judge understates all three systems here (2, 2, 0). It is
  also a real product finding: an assistant serving from understanding
  must apply preferences to recommendations, not abstain on them.
- knowledge-update ties facts (2/5): the temporal supersede path only
  engages when an extraction repeats a kind and title, which generic
  extraction over a digest rarely does. The machinery exists; wiring
  revision detection into extraction is the gap this exposes.

## Limits

- 30 of 500 questions, first-in-dataset-order per type. Small-n: one
  question is 3.3 points. Treat ordering as a signal, not a ranking.
- Absolute numbers are NOT comparable to published LongMemEval
  results: those use full pipelines with GPT-4o-class readers, neural
  retrieval and the official judge. Ours uses a Haiku reader and
  judge, a lexical local embedder, and top-5 retrieval.
- The judge is the same small model as the reader; judge strictness on
  rubric-style references (above) cuts both ways and is uncalibrated.
- Next steps before quoting externally: full 500 or a random 100,
  neural embedder, preference-rubric judge for that type, and a
  stronger reader to separate store quality from reader quality.

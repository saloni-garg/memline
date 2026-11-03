# Replicate these benchmarks

Everything in RESULTS.md and LONGMEMEVAL.md is reproducible from this
repo. Independent runs, especially runs that vary our choices, are the
point: if the ordering only holds with our reader, our judge and our
embedder, it is not a finding yet.

## Setup

```bash
python -m venv .venv && .venv/bin/pip install -r requirements.txt
export ANTHROPIC_API_KEY=...   # needed for --live and LongMemEval runs
```

## Fixture benchmark (13 questions, three storage models)

```bash
.venv/bin/python eval/run_benchmark.py          # recorded extraction outputs
.venv/bin/python eval/run_benchmark.py --live   # real LLM extractors
```

## LongMemEval-S subset

```bash
# dataset: HF repo xiaowu0162/longmemeval, file longmemeval_s,
# placed at eval/data/longmemeval_s
.venv/bin/python eval/longmemeval.py --per-type 5    # 30 questions
.venv/bin/python eval/longmemeval.py --per-type 20   # 120 questions
```

Raw per-question output lands in eval/longmemeval_results.json
(question, reference answer, each system's response and verdict), so
anyone can re-judge our judge.

## Choices we made that you should feel free to vary

- Reader and judge: claude-haiku-4-5 for both. A stronger reader
  separates store quality from reader quality; report which you used.
- Retrieval: production hybrid search, local hashing embedder, top 5
  (LongMemEval) and top 3 (fixture). Setting EMBEDDING_API_KEY switches
  to a neural embedder and rebalances ranking automatically.
- Extraction input: the production digest (48k characters sampled per
  history). Raw RAG is exempt by design; it stores every turn.
- Subset selection: first N per question type in dataset order, not
  random. Say so if you randomize; we will too in the next run.
- The single-session-preference type is scored by our uniform
  containment judge; the official benchmark uses a preference rubric.
  A rubric judge for that type is a welcome variation.

## What to send back

The results JSON, your variations from the list above, and any
questions where the verdict looks wrong to a human reader. Wrong
verdicts against us are as useful as wrong verdicts for us.

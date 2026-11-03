# Self-hosting Memline

Memline is a single FastAPI service with a single SQLite database
file. There is no separate vector database, queue, or cache to operate.
Verified end to end from a clean copy on 2026-11-02: fresh virtualenv,
install, boot, register, all working in under a minute of setup.

## Run it with Docker

    docker compose up -d

That builds the image from the included Dockerfile, stores the
database on a named volume, and serves on port 8080. Set
ANTHROPIC_API_KEY in the environment first if you want the
understanding engine. (The compose file and Dockerfile are the same
steps verified natively below; the image build itself is the standard
two-step pip install plus copy.)

## Run it natively

    python3 -m venv .venv
    .venv/bin/pip install -r requirements.txt
    MEMLINE_DB=/path/to/memline.db .venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port 8000

Open http://localhost:8000 for the consumer app and
http://localhost:8000/api-docs for the developer API.

## Configuration (environment variables)

- `MEMLINE_DB`: path to the SQLite file (default `memline.db` in
  the working directory). All state lives here: users, memories,
  embeddings, graph edges, event history, write rejections.
- `ANTHROPIC_API_KEY`: enables the understanding engine (extraction on
  import and on `infer=true` API adds). Without it, verbatim adds,
  search, temporal validity, the write gate's duplicate guard, Memory
  Health and the rest of the API work; extraction endpoints answer with
  an honest not-configured message.
- `MEMLINE_LLM_MODEL`: override the extraction model.
- `EMBEDDING_API_KEY`, `EMBEDDING_BASE_URL`, `EMBEDDING_MODEL`:
  optional neural embedder (any OpenAI-compatible embeddings endpoint).
  Without them, the built-in local hashing embedder is used and search
  results say so.

## Backup and exit

Back up by copying the SQLite file. Leave at any time the same way:
your data is one file, plus a full JSON export from Settings in the
consumer app or `GET /v1/memories` per user scope in the API. Nothing
about the data format is proprietary.

## Honest limits

SQLite on one process is the current scale ceiling; measured
operations numbers, including where search latency grows with store
size, are in `eval/PERF.md`. The code is open source under Apache 2.0; see the public
repository's LICENSE and OPEN_CORE.md for the boundary.

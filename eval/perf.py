"""Operations measurements for the developer platform, run locally.

Starts the real server (uvicorn, temp SQLite DB) on a scratch port,
seeds it through the public API, and times the endpoints a production
evaluator asks about: search, assemble_context, verbatim add, memory
health. Reports p50/p95 and store growth. Method and limits are written
into eval/PERF.md with the numbers: single small VM, local hashing
embedder, SQLite; these are our numbers in this environment, not a
hosted-production SLA.

Run: .venv/bin/python eval/perf.py [--seed 1000]
"""
import argparse
import json
import os
import statistics
import subprocess
import sys
import tempfile
import time
import urllib.request

BASE = "http://127.0.0.1:8123"
HERE = os.path.dirname(__file__)
ROOT = os.path.join(HERE, "..")


def call(method: str, path: str, payload=None, headers=None, cookies=None):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method,
                                 headers={"Content-Type": "application/json",
                                          **(headers or {})})
    if cookies:
        req.add_header("Cookie", cookies)
    start = time.perf_counter()
    with urllib.request.urlopen(req) as resp:
        body = resp.read()
        cookie = resp.headers.get("Set-Cookie")
    return (time.perf_counter() - start) * 1000, json.loads(body or b"{}"), cookie


def pct(samples: list[float], q: float) -> float:
    s = sorted(samples)
    return s[min(len(s) - 1, int(q * len(s)))]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=1000)
    args = ap.parse_args()

    tmp = tempfile.mkdtemp()
    db_path = os.path.join(tmp, "perf.db")
    env = {**os.environ, "MEMLINE_DB": db_path}
    server = subprocess.Popen(
        [os.path.join(ROOT, ".venv", "bin", "python"), "-m", "uvicorn",
         "app.main:app", "--port", "8123"],
        cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(60):
            try:
                call("GET", "/")
                break
            except Exception:
                time.sleep(0.5)
        _, _, cookie = call("POST", "/api/register",
                            {"email": "perf@example.com", "password": "password123"})
        _, key_resp, _ = call("POST", "/api/keys", {"name": "perf"}, cookies=cookie)
        auth = {"Authorization": f"Bearer {key_resp['key']}"}

        t0 = time.perf_counter()
        for i in range(args.seed):
            call("POST", "/v1/memories",
                 {"text": f"Perf fact {i}: the user discussed project topic {i} "
                          f"with detail level {i % 7} and prefers summary style {i % 3}.",
                  "user_id": "perf-u", "infer": False}, headers=auth)
        seed_ms = (time.perf_counter() - t0) * 1000

        search_ms = [call("POST", "/v1/memories/search",
                          {"query": "which project topic did the user discuss",
                           "user_id": "perf-u"}, headers=auth)[0] for _ in range(50)]
        assemble_ms = [call("POST", "/v1/assemble_context",
                            {"query": "brief me on the user", "user_id": "perf-u",
                             "max_tokens": 1500}, headers=auth)[0] for _ in range(20)]
        health_ms = [call("GET", "/v1/memory_health?user_id=perf-u",
                          headers=auth)[0] for _ in range(20)]
        add_ms = [call("POST", "/v1/memories",
                       {"text": f"Extra perf fact {i} recorded during timing.",
                        "user_id": "perf-u", "infer": False}, headers=auth)[0]
                  for i in range(50)]
        size_kb = os.path.getsize(db_path) / 1024
        total = args.seed + 50

        def row(name, samples):
            return (f"| {name} | {statistics.median(samples):.1f} ms | "
                    f"{pct(samples, 0.95):.1f} ms |")

        md = f"""# Operations measurements

Measured {time.strftime('%Y-%m-%d')} on this project's VM (single small
machine, SQLite, local hashing embedder, loopback HTTP, uvicorn
defaults, store seeded through the public API).

| Operation | p50 | p95 |
|---|---|---|
{row('POST /v1/memories/search', search_ms)}
{row('POST /v1/assemble_context', assemble_ms)}
{row('POST /v1/memories (verbatim add)', add_ms)}
{row('GET /v1/memory_health', health_ms)}

- Store: {total} memories, database file {size_kb:.0f} KB
  ({size_kb / total:.2f} KB per memory including embedding, graph edges
  and event history; growth is linear in this design).
- Seeding {args.seed} verbatim adds took {seed_ms / 1000:.1f}s end to end
  ({seed_ms / args.seed:.1f} ms per add sustained).
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
"""
        with open(os.path.join(HERE, "PERF.md"), "w") as fh:
            fh.write(md)
        print(md)
    finally:
        server.terminate()


if __name__ == "__main__":
    main()

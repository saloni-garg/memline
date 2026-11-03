"""Smoke test for the Python SDK against a throwaway local server.

    python sdk/python/smoke_test.py
"""
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.request

HERE = os.path.dirname(__file__)
ROOT = os.path.join(HERE, "..", "..")
sys.path.insert(0, HERE)
from memline import Memline  # noqa: E402

BASE = "http://127.0.0.1:8126"


def raw(method, path, payload=None, cookie=None):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method,
                                 headers={"Content-Type": "application/json"})
    if cookie:
        req.add_header("Cookie", cookie)
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read() or b"{}"), resp.headers.get("Set-Cookie")


def main() -> None:
    tmp = tempfile.mkdtemp()
    env = {**os.environ, "MEMLINE_DB": os.path.join(tmp, "smoke.db")}
    server = subprocess.Popen(
        [os.path.join(ROOT, ".venv", "bin", "python"), "-m", "uvicorn",
         "app.main:app", "--port", "8126"],
        cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(60):
            try:
                raw("GET", "/")
                break
            except Exception:
                time.sleep(0.5)
        _, cookie = raw("POST", "/api/register",
                        {"email": "sdk@example.com", "password": "password123"})
        key_resp, _ = raw("POST", "/api/keys", {"name": "sdk"}, cookie=cookie)
        ml = Memline(api_key=key_resp["key"], base_url=BASE)

        out = ml.remember(text="Jordan lives in Austin and works at Globex.",
                          user_id="u-sdk", infer=False)
        assert out["results"], out
        mid = out["results"][0]["id"]
        print("remember ok, grounding:", out["results"][0].get("grounding"))

        hits = ml.search("where does Jordan live", user_id="u-sdk")
        assert hits["results"], hits
        assert any("why" in r for r in hits["results"])
        print("search ok, why:", hits["results"][0]["why"][:2])

        ctx = ml.assemble_context("brief me", user_id="u-sdk")
        assert "Austin" in ctx["context"], ctx
        print("assemble_context ok")

        inv = ml.invalidate(mid)
        assert inv.get("valid_to"), inv
        after = ml.search("where does Jordan live", user_id="u-sdk")
        assert all(r["id"] != mid for r in after["results"])
        print("invalidate ok, present search clean")

        hist = ml.history(mid)
        assert hist["history"], hist
        print("history ok:", [e["event"] for e in hist["history"]])

        health = ml.memory_health(user_id="u-sdk")
        assert health["active_memories"] == 1, health  # invalidated, not deleted
        print("memory_health ok:", health["grounded_pct"], health["coverage"]["of"])
        print("SDK SMOKE TEST PASSED")
    finally:
        server.terminate()


if __name__ == "__main__":
    main()

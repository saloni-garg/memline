"""Memline Python client. Standard library only, no dependencies.

    from memline import Memline

    ml = Memline(api_key="ml_...", base_url="https://mindcarry.fly.dev")
    result = ml.remember(text="I live in Austin.", user_id="user-42")
    hits = ml.search("where does the user live?", user_id="user-42")
    ctx = ml.assemble_context("brief the assistant", user_id="user-42")
    health = ml.memory_health(user_id="user-42")

Every stored memory carries evidence, a grounding verdict and a
validity window. Writes pass the grounding gate: ungrounded extracted
candidates come back in the response's "rejected" list with a reason
instead of being stored. See API.md for the full contract.
"""
import json
import urllib.error
import urllib.parse
import urllib.request

__version__ = "0.1.0"
__all__ = ["Memline", "MemlineError"]


class MemlineError(Exception):
    def __init__(self, status: int, body: str):
        super().__init__(f"Memline API error {status}: {body[:300]}")
        self.status = status
        self.body = body


class Memline:
    def __init__(self, api_key: str, base_url: str = "https://mindcarry.fly.dev",
                 timeout: float = 120.0):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout

    def _call(self, method: str, path: str, payload: dict | None = None,
              params: dict | None = None) -> dict:
        url = self.base_url + path
        clean = {k: v for k, v in (params or {}).items() if v not in ("", None)}
        if clean:
            url += "?" + urllib.parse.urlencode(clean)
        data = json.dumps(payload).encode() if payload is not None else None
        req = urllib.request.Request(url, data=data, method=method, headers={
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        })
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return json.loads(resp.read() or b"{}")
        except urllib.error.HTTPError as exc:
            raise MemlineError(exc.code, exc.read().decode("utf-8", "replace")) from exc

    @staticmethod
    def _scope(user_id: str, agent_id: str, app_id: str, run_id: str = "") -> dict:
        out = {"user_id": user_id, "agent_id": agent_id, "app_id": app_id}
        if run_id:
            out["run_id"] = run_id
        return out

    def remember(self, text: str | None = None, messages: list[dict] | None = None,
                 user_id: str = "", agent_id: str = "", app_id: str = "",
                 run_id: str = "", infer: bool = True,
                 metadata: dict | None = None) -> dict:
        """Store through the write gate. With infer=True the understanding
        engine extracts typed understandings and the gate verifies each
        candidate's evidence against the source; the response reports
        results, rejected and skipped_duplicates separately."""
        payload = {**self._scope(user_id, agent_id, app_id, run_id),
                   "infer": infer, "metadata": metadata or {}}
        if text is not None:
            payload["text"] = text
        if messages is not None:
            payload["messages"] = messages
        return self._call("POST", "/v1/remember", payload)

    def add(self, **kwargs) -> dict:
        """POST /v1/memories; identical semantics to remember()."""
        text = kwargs.pop("text", None)
        messages = kwargs.pop("messages", None)
        payload = {**self._scope(kwargs.pop("user_id", ""), kwargs.pop("agent_id", ""),
                                 kwargs.pop("app_id", ""), kwargs.pop("run_id", "")),
                   "infer": kwargs.pop("infer", True),
                   "metadata": kwargs.pop("metadata", None) or {}}
        if text is not None:
            payload["text"] = text
        if messages is not None:
            payload["messages"] = messages
        return self._call("POST", "/v1/memories", payload)

    def search(self, query: str, user_id: str = "", agent_id: str = "",
               app_id: str = "", run_id: str = "", limit: int = 10,
               as_of: str | None = None, threshold: float = 0.0) -> dict:
        """Hybrid search over currently valid memories. Each result carries
        score components, evidence, and a plain-language why array.
        Pass as_of (ISO timestamp) to search the past instead."""
        payload = {**self._scope(user_id, agent_id, app_id, run_id),
                   "query": query, "limit": limit, "threshold": threshold}
        if as_of:
            payload["as_of"] = as_of
        return self._call("POST", "/v1/memories/search", payload)

    def get(self, memory_id: int) -> dict:
        return self._call("GET", f"/v1/memories/{memory_id}")

    def list(self, user_id: str = "", agent_id: str = "", app_id: str = "",
             limit: int = 100, offset: int = 0) -> dict:
        return self._call("GET", "/v1/memories", params={
            "user_id": user_id, "agent_id": agent_id, "app_id": app_id,
            "limit": limit, "offset": offset})

    def update(self, memory_id: int, text: str, metadata: dict | None = None) -> dict:
        return self._call("PUT", f"/v1/memories/{memory_id}",
                          {"text": text, "metadata": metadata})

    def delete(self, memory_id: int) -> dict:
        return self._call("DELETE", f"/v1/memories/{memory_id}")

    def delete_all(self, user_id: str = "", agent_id: str = "", app_id: str = "",
                   run_id: str = "") -> dict:
        return self._call("DELETE", "/v1/memories",
                          params={"user_id": user_id, "agent_id": agent_id,
                                  "app_id": app_id, "run_id": run_id})

    def history(self, memory_id: int) -> dict:
        """Full event history (ADD, UPDATE, SUPERSEDE, REVISION,
        INVALIDATE, DELETE), kept even after the memory is gone."""
        return self._call("GET", f"/v1/memories/{memory_id}/history")

    def invalidate(self, memory_id: int) -> dict:
        """Close the validity window now: the memory stops being asserted
        about the present without being deleted."""
        return self._call("POST", f"/v1/memories/{memory_id}/invalidate", {})

    def understanding(self, user_id: str = "") -> dict:
        """The typed understanding profile: identity, goals, principles,
        preferences, style, projects, people, and open unknowns."""
        return self._call("GET", "/v1/understanding", params={"user_id": user_id})

    def assemble_context(self, query: str, user_id: str = "", agent_id: str = "",
                         app_id: str = "", run_id: str = "",
                         max_tokens: int = 1500) -> dict:
        """Token-budgeted context for one prompt, with the supporting
        understandings, what was omitted and why, and the unknowns."""
        return self._call("POST", "/v1/assemble_context",
                          {**self._scope(user_id, agent_id, app_id, run_id),
                           "query": query, "max_tokens": max_tokens})

    def memory_health(self, user_id: str = "") -> dict:
        """Grounded percentage, contradictions, stale count, superseded
        count, orphaned graph edges, gate pass rate, coverage."""
        return self._call("GET", "/v1/memory_health", params={"user_id": user_id})

    def rejections(self, user_id: str = "", limit: int = 20) -> dict:
        """What the write gate refused to store, with reasons."""
        return self._call("GET", "/v1/rejections",
                          params={"user_id": user_id, "limit": limit})

    def graph(self, user_id: str = "") -> dict:
        return self._call("GET", "/v1/graph", params={"user_id": user_id})

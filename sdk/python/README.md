# memline (Python)

Client for the Memline API: memory where every write is grounded,
every fact is time-aware, and every retrieval explains itself.

    pip install ./sdk/python        # or from your vendored copy

    from memline import Memline

    ml = Memline(api_key="ml_...", base_url="https://mindcarry.fly.dev")

    # Writes pass the grounding gate. The response separates what was
    # stored, what was rejected as ungrounded, and what was skipped as
    # a duplicate.
    out = ml.remember(text="I live in Austin and my manager is Ruth.",
                      user_id="user-42")

    # Search returns evidence and a plain-language why per result.
    hits = ml.search("who is the user's manager?", user_id="user-42")

    # One call assembles token-budgeted context for a prompt.
    ctx = ml.assemble_context("brief the assistant", user_id="user-42")

    # The store reports on itself.
    print(ml.memory_health(user_id="user-42"))

Switching from Mem0: the API shape is deliberately familiar (add,
search, get, update, delete, history, user/agent/app/run scoping), and
`scripts/migrate.py` in the main repository audits and imports an
existing Mem0 export. No dependencies; standard library only.

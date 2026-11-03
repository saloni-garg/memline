# memline (TypeScript)

Client for the Memline API: memory where every write is grounded,
every fact is time-aware, and every retrieval explains itself.

    npm install memline        # once published; today, vendor this folder

    import { Memline } from "memline";

    const ml = new Memline({ apiKey: "ml_...", baseUrl: "https://mindcarry.fly.dev" });

    // Writes pass the grounding gate. The response separates what was
    // stored, what was rejected as ungrounded, and duplicates skipped.
    const out = await ml.remember({
      text: "I live in Austin and my manager is Ruth.",
      userId: "user-42",
    });

    const hits = await ml.search({ query: "who is the user's manager?", userId: "user-42" });
    const ctx = await ml.assembleContext({ query: "brief the assistant", userId: "user-42" });
    console.log(await ml.memoryHealth("user-42"));

Switching from Mem0: the API shape is deliberately familiar, and
`scripts/migrate.py` in the main repository audits and imports an
existing Mem0 export. Zero runtime dependencies; uses global fetch
(Node 18+, browsers, edge runtimes).

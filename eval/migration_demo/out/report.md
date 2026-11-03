# Memory migration audit

**Data provenance: synthetic demonstration data, generated with known failure modes for development; it is not a customer export and is not evidence that real stores look like this.**

Export analyzed: **106 memories** across 2 user scope(s).

| Finding | Count |
|---|---|
| Duplicate copies removed | 17 |
| Contradiction chains detected (same slot, changing value) | 4 |
| Memories upgraded to superseded with a validity window | 5 |
| Stale, never reconfirmed in 180+ days | 13 |
| Memories carrying any source evidence | 0 of 106 |
| Cleaned store size | 89 |

A contradiction chain is not deleted. The newest value stays current; each older value keeps its history with its validity window closed at the moment the newer value appeared, so the assistant stops asserting it about the present while remaining able to answer about the past.

## Impact: how this store is affecting your product today

- **Retrieval noise:** 16.0% of this store is duplicate copies. A retrieval that samples the store returns roughly 0.8 of its top 5 slots as repeats of something already in context, crowding out distinct information.
- **Wrong answers waiting to happen:** 5 outdated values (old locations, employers, managers) are still stored as if current. Any present-day lookup can return one, and the assistant will state it with full confidence.
- **Unverified answers:** 13 memories have not been reconfirmed in 180+ days and none of the 106 memories carries source evidence, so when a user disputes an answer there is nothing to check it against.
- **Users affected:** 2 of 2 user scopes carry at least one contradiction chain, stale fact, or material duplication.
- **Fixes:** 22 are automatic in this migration (duplicates removed, validity windows closed). 13 need a human decision (reconfirm or retire the stale memories).

Estimates and definitions: retrieval noise assumes retrieval samples the store roughly uniformly, so duplicates occupy context slots in proportion to their share of the store; outdated values counts every superseded value in a detected chain; users affected counts scopes with a chain, a stale memory, or 5+ duplicate copies.

## User scope: user-42

Top duplicate groups (extra copies beyond the first):
- 13x extra: "User prefers Vim for editing code"
- 4x extra: "User's favorite coffee is an oat milk latte."

Contradiction chain, slot **employer**:
- 2025-02-10: Northwind Traders ("User works at Northwind Traders.")
- 2026-01-15: Globex ("User works at Globex.")
  Current value: **Globex**. Older values are superseded, not deleted.

Contradiction chain, slot **location**:
- 2025-03-04: Portland ("User lives in Portland.")
- 2025-11-18: Austin ("User moved to Austin.")
- 2026-06-22: Denver ("User lives in Denver.")
  Current value: **Denver**. Older values are superseded, not deleted.

Contradiction chain, slot **manager**:
- 2026-02-01: Priya ("User's manager is Priya.")
- 2026-03-01: Tom ("User's manager is Tom.")
  Current value: **Tom**. Older values are superseded, not deleted.

Stale and never reconfirmed (sample of 5):
- 666 days old: "User prefers Vim for editing code"
- 660 days old: "User's favorite coffee is an oat milk latte."
- 630 days old: "User is a support engineer."
- 291 days old: "User works at Globex."
- 246 days old: "User's manager is Tom."

## User scope: user-7

Contradiction chain, slot **location**:
- 2025-08-01: Chicago ("User lives in Chicago.")
- 2026-04-01: Seattle ("User moved to Seattle.")
  Current value: **Seattle**. Older values are superseded, not deleted.

Stale and never reconfirmed (sample of 8):
- 458 days old: "User is a product designer."
- 215 days old: "User moved to Seattle."
- 185 days old: "User asked about recipe variation 0 with chickpeas."
- 184 days old: "User asked about recipe variation 1 with chickpeas."
- 183 days old: "User asked about recipe variation 2 with chickpeas."

## What this audit cannot tell you

An export shows the state of the store, not its production history. This report cannot say how often any memory was actually retrieved, whether a specific stale or contradictory memory ever reached a user, or how much token spend duplicates caused last month. Those answers need the team's retrieval logs or support records alongside the export. Where a finding above says a wrong value 'could be returned', that is the honest ceiling of what an export alone establishes; treat any clean result the same way: few findings in the export means the store is tidy, not that production answers were correct.

## What happens on import

- Duplicates never enter storage (the write gate skips them).
- Superseded memories are imported as history with closed validity windows, so present-day answers use only current values.
- Stale memories are imported flagged for reconfirmation, not silently trusted.
- From the first new write onward, every memory carries evidence, passes the grounding gate, and appears in Memory Health.

Method and limits: duplicates are exact on normalized content; slot chains use deterministic patterns for location, employer, manager and role, so paraphrased revisions in other slots need the semantic pass that runs inside Memline after import. Stale means old and never updated since creation, a proxy for unconfirmed, not proof of falsity.

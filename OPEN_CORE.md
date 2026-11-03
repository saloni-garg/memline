# Open core: what is open, what is commercial

Memline follows the open-core pattern used across memory
infrastructure: the core is open source under Apache 2.0 so engineers
can inspect it, self-host it, and never lose their memory layer if the
company behind it disappears. Operating a service is the business.

## Open source (this repository, Apache 2.0)

- The server and the full developer API
- The write gate, temporal validity, revision detection, Memory
  Health, explainable retrieval, and the understanding engine
- The consumer web app included in the server
- Python and TypeScript SDKs
- Migration and audit tooling (`scripts/migrate.py`)
- The evaluation harness, fixtures, and published raw results

## Commercial (hosted and enterprise)

- The managed cloud at mindcarry.fly.dev: operations, scaling,
  backups, monitoring, support
- Enterprise capabilities as they are built: SSO and enterprise
  authentication, RBAC, compliance packaging, SLAs

Nothing already open moves behind the commercial line. Features are
not removed from the open core to create upgrade pressure; the
commercial offering sells operations and enterprise requirements, not
hostage data.

## Data portability, either way

Self-hosters and hosted users get the same exit: one SQLite file, a
full JSON export, and an API that lists everything stored. Leaving
costs an afternoon, by design.

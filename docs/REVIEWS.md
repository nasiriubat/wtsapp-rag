# Review log

One entry per phase: what the code review and security review found, and
what was done about it. Findings that were not fixed say why.

## Phase 0 (v0.2) — code review, 3 Sept 2026

Fixed:

- Gateway image copied only `index.js` after the split into `lib.js` and
  `queue.js`; the container would have crash-looped. `COPY *.js`, and CI now
  runs both images, not just builds them.
- Retry queue retried 4xx responses forever, rewrote the whole file on every
  push, could be bricked by a half-written line, and let live messages
  overtake queued ones. Now: only outages (network, 5xx) are queued, pushes
  append, flushes write-then-rename, a bad line is skipped, and while the
  queue is non-empty new messages go behind it.
- App raced Postgres at startup once migrations moved into the app. Compose
  now has a db healthcheck, an app healthcheck on `/health`, and ordered
  `depends_on` conditions.
- `/health` hardcoded `db: ok` and had an unreachable 503 branch. Now it
  reports `db: down` with a 503 when the connection fails, and nothing else.
- Structured log events were JSON inside JSON. `extra=` fields are now
  top-level keys; `print` calls became log calls; gateway logs through pino.
- DSN was read at import time, so unit tests failed without a database
  password. One variable, `DATABASE_URL`, read at call time; compose builds
  it from `POSTGRES_PASSWORD`.
- `001_init.sql` had `IF NOT EXISTS` sprinkled in to adopt a v0.1 database.
  The runner now baselines instead; the schema file is plain again.
- Migration test hardcoded the file list; it now derives it from disk.
- Prometheus output lacked `# TYPE` lines. Added.
- CLAUDE.md said `migrations/`; the path is `app/migrations/`.

Recorded, not changed:

- `pytest-httpx` was installed before anything used it. Phase 1's provider
  tests use it.
- Phase 0 commits bundled several features each. From phase 1 on: one
  feature per commit with its tests, and an "Untested:" line in the message
  whenever a change cannot be exercised without a phone or a token.
- CI rebuilds images without layer cache. Acceptable at this size; revisit
  when a run exceeds ten minutes.

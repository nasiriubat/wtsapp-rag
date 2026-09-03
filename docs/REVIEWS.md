# Review log

One entry per phase: what the code review and security review found, and
what was done about it. Findings that were not fixed say why.

## Phase 1 (v0.3) — code review, 3 Sept 2026

Three of eight review angles completed before the session rate limit; the
rest re-run at the start of phase 2. Security pass done by hand over the
same range (see below).

Fixed:

- `/ingest` stored messages for unknown and disabled groups; the gateway's
  30-second-stale list or its replay queue could write data the admin had
  just switched off. The app now drops them itself.
- A group pinned to a disabled provider got "no provider configured" instead
  of falling back to the global default. `resolve()` walks pin then default
  and takes the first enabled one.
- Refusal was detected by comparing the model's output to the admin-editable
  refusal text. Models add punctuation or translate it, which turned refusals
  into "answers" with a random quote. The model now emits a fixed `NO_ANSWER`
  sentinel and the group's text is substituted afterwards.
- Providers that omit usage (some OpenAI-compatible servers) made cost NULL,
  which the budget sum ignored, silently disabling caps. Missing usage is now
  estimated from characters and logged as such.
- Opt-out only filtered new messages; a member's history stayed in chunks and
  could be quoted back. Opting someone out now erases their messages, drops
  every chunk from an episode they were in, and queues the rest for
  re-chunking. The chunk loop also skips opted-out senders.
- Budget check ran two month-wide sums on two connections; now one query.
  Month boundaries are explicitly UTC.
- Retention ran one unindexed scan per group; now one statement per table
  joined to groups.
- `query_log_group_ts` index dropped as premature.
- Duplication: shared `conftest.py` for tests, one `_patch` helper in the
  admin API, one `_one` helper in groups, dead `parseTriggers` removed.

Recorded, not changed:

- `/ask` opens several short-lived connections per question. Measured cost
  is a few milliseconds each on the same host; revisit with the phase 5
  load test rather than adding pooling now.
- The OpenAI-compatible client picks `max_completion_tokens` only for
  api.openai.com by host name. Any other host gets `max_tokens`, and the
  admin can override either through `options`. The phase 2 panel will
  prefill options per kind, which is the cleaner place for this.

Security pass (manual, same range):

- SQL: every user value is a bound parameter. Dynamic `SET` clauses take
  column names from pydantic model fields only, never from request keys.
- Auth: admin HTTP Basic and the gateway Bearer token both use
  `secrets.compare_digest`. Provider keys never appear in responses, audit
  rows, or logs; audit details redact `api_key`.
- Untrusted text (group messages, questions) reaches only SQL parameters,
  the LLM prompt with an explicit "content, not instructions" rule, and
  JSON responses. No shell, no file paths, no templates yet.
- Open: the admin API has no CSRF concern (Basic auth, no cookies) but the
  phase 2 panel will use a session cookie and must add CSRF protection.

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

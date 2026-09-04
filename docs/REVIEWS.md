# Review log

One entry per phase: what the code review and security review found, and
what was done about it. Findings that were not fixed say why.

## Phase 4 (v0.6) — code and security review, 4 Sept 2026

The review ran during a model rate limit, so three of eight code-review
angles and the security agent were cut short. The two angles that finished
are applied below and the security questions were worked through by hand;
the remaining angles re-run at the start of phase 5.

Security pass (by hand, over the correction, DM and extraction paths):

- Corrections are scoped to one group at every step: the quoted message must
  be the bot's own **and** in that group, the answer it is corrected against
  is looked up per group, and both the fact insert and the supersede update
  carry `group_id`. Nothing a member writes can reach another group's facts.
- **Fixed:** a member who had left a group could still ask about it privately
  because they had once written there. Where the channel can list members
  (WhatsApp) that list now decides; the "wrote here" evidence is only used
  where the platform cannot list (Telegram, Discord).
- Ids the model returns as `supersedes` are filtered to the candidates from
  the same group before use, and every value reaches SQL as a parameter.
- Private questions are never written to `messages`. They do land in
  `query_log` with the asker's id, which the admin can read; that is stated
  in the README's privacy note.
- Chat text reaches the model inside `<chat>` tags with the closing tag
  neutralised, in both the answer and extraction prompts, and both say the
  content is data.

Code review, fixed:

- A private question searched the winning group twice, paying for the
  reranker twice; the search is now passed to the answer step.
- `query_log.record` is the single writer for that table; the correction
  path and the extraction loop no longer hand-write their own inserts, and
  the argument list is keyword-only instead of eleven positionals.
- The ask log line derived "refused" from a missing quote, which is also how
  an answer citing an imported message looks; it logs the real outcome and
  latency now.
- `try_correction` hit the database before checking the cheap regex.
- Fact extraction re-embedded a chunk that already had an embedding.
- The gateway had two schedulers plus a re-entrancy flag; one chained loop
  cannot overlap itself, and the poll is fast only until the app answers.
- Duplication: `embed.passage_literal`, `db.secret_key` everywhere,
  `handleDirect` takes the channel's own payload, the wizard's relink
  delegates to the channels page.

## Phase 3 (v0.5) — code and security review, 4 Sept 2026

Security review: no high-confidence findings. Verified that every channel's
`send` targets the chat the question came from and that quote ids only pick
the message to reply to; retrieval is scoped by group; tokens leave the app
only over the gateway token. Two low notes fixed anyway: Discord answers no
longer parse `@everyone` or user pings (`allowedMentions: parse: []`), and
message ids are unique per group (migration 007) so a WhatsApp sender
choosing its own id cannot shadow a Telegram message.

Code review, fixed:

- The Channels page's Remove button sat inside the Save form; browsers drop
  the inner form, so it saved instead of removing. Forms are siblings now.
- The 30-second sync could start a channel twice when a start took longer
  than a tick; a `syncing` guard and parallel starts.
- Telegram's handler awaited the whole answer, blocking grammY's sequential
  polling for every other group; fire and forget like WhatsApp.
- A Telegram poller that died (409, revoked token) stayed in `running`
  forever; channels expose `dead()` and the orchestrator restarts them.
- A phone-side WhatsApp logout exited the whole process, taking Telegram and
  Discord down; it now clears the auth files and pairs again in place.
- Stopped or removed channels never reported a final state, so the panel
  showed "linked" forever; the orchestrator reports a blank state on stop.
- Relink was a global flag consumed by any config fetch even with no running
  WhatsApp; it is per channel, handed out once, and the wizard's "asking for
  a fresh QR" branch reads it again. Relink is refused until the socket is
  open, so a request during a restart no longer wedges the flag.
- Health and preflight read WhatsApp-only state; a Telegram-only install
  looked dead. They read all channels; the wizard's link step is explicitly
  the phone pairing.
- Discord fetched the referenced message for every reply before ingest;
  cheap checks run first and the fetch happens only when they miss. Trigger
  work runs after ingest for every channel.
- Telegram answers over 4096 characters threw; truncated like Discord.
- Discord's channel list was frozen at connect; recomputed per report.
- The gateway did nothing until the first config fetch succeeded, which
  under compose is well after boot; it polls every 5 s until then.
- Tests wrote to the real `data/queue.jsonl`; the queue path is injectable.
- `TELEGRAM_BOT_TOKEN`/`DISCORD_BOT_TOKEN` in `.env` contradicted the rule
  that admin-owned config lives in Postgres; removed.
- Duplication: one `KINDS` table with traits (token, pairs) replaces three
  copies; `db.secret_key()` is the one key accessor; `audit.redact` knows
  `token`; `admin.redirect` is the one flash helper; parse helpers next to
  the id encoders; `blankState()` shared.

Recorded, not changed:

- `wa_msg_id` is the column name for every channel's message id. Renaming
  is a migration across four tables; deferred to v1.x.
- `SECRET_KEY` signs sessions, derives CSRF tokens and encrypts secrets.
  Splitting it is a v1.x hardening item.
- The SQL `CHECK` on `channels.kind` duplicates `KINDS`; kept as a data
  guard, so a new kind is a migration plus a module.

## Phase 2 (v0.4) — code and security review, 4 Sept 2026

Security review (eight categories, whole `ca10a66..HEAD` range): no
high-confidence findings. Verified: Jinja autoescape on, the one `| safe` is
segno's SVG of the pairing QR, every hand-built HTMLResponse escapes, all
state changes sit behind session + CSRF, SQL `SET` clauses take column names
from pydantic models only, provider keys never leave the server, audit
redacts them.

Code review, fixed:

- **Relink was broken twice over.** The gateway deleted `auth_state`, which
  is a bind mount (EBUSY, swallowed by the config-poll catch), and the app
  only cleared the flag on a new QR, which a restarted gateway could never
  reach before re-reading the flag: an endless restart loop. Now the flag is
  handed out once (`take_relink`), the gateway calls `sock.logout()` in
  process, the close handler clears the directory's contents and reconnects.
- Refused/answered filters and the health card keyed on `cost IS NULL`,
  which called a model refusal "answered" and a budget stop "refused".
  Migration 004 adds `outcome`; filters, counts and the export use it.
- Import reported the file length, not rows written; re-uploads claimed
  thousands of duplicates. `insert` returns the cursor rowcount.
- A free-text time zone crashed every question in the group with
  `ZoneInfoNotFoundError`. Quiet hours are a validated model; HH:MM and IANA
  zone checked on save.
- Export `Content-Disposition` embedded the group name; non-Latin names
  (the wizard copies WhatsApp subjects in) raised in header encoding. ASCII
  file names now, and exports stream through a server-side cursor in batches.
- Form parsing turned bad numbers, a deleted provider id, whitespace-padded
  ids and negative caps into 500s. All validate to 422 through the same
  helpers the JSON API uses (`add_provider`, `apply_provider`, `add_group`,
  `apply_group`), which also removes three copies of the same rules.
- Login lockout was one global counter, so anyone could lock the admin out
  for a minute. Keyed by client address.
- Wizard result text was smuggled through a redirect unencoded; `&` and `#`
  truncated it. Now `ok=` plus a urlencoded `detail=`.
- QR SVG rendered on every 3-second poll; now once per QR.
- Health stats are one statement; a down database renders a message instead
  of a traceback. Disk is measured where the models live.
- Duplication: shared `browser` fixture and `post` helper, one JSONL streamer,
  kind list from `providers.KINDS`, month predicate from `budget`.
- Channel dropdown offered Telegram and Discord before they exist. WhatsApp
  only until phase 3.

Recorded, not changed:

- Admin pages open several connections per request. Same note as phase 1.
- `/api` uses HTTP Basic without CSRF; the only bodiless POST is the
  provider test. Low impact; the panel is the primary surface.
- Logout deletes the cookie but the signature stays valid for its 7 days.
  Server-side sessions are a v1.x item.
- Behind a TLS-terminating proxy uvicorn needs `--proxy-headers` for the
  cookie's `Secure` flag; goes in OPERATIONS.md at release.
- `segno` was added without a roadmap line; added to the phase 2 list.

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

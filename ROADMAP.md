# Roadmap to v1.0 — production-ready, audited

Status (3 Sept 2026): phases 0 and 1 done and reviewed; all four provider
kinds verified live. Phase 2 (admin panel, setup wizard) built; review
pending. Next: phase 3, Telegram and Discord.

v0.1 (Sept 2026) proved the loop: log a group, hybrid-search it, answer with a
quote-reply, refuse when unsure, log everything. v1.0 turns that into a system
one operator can run for many groups on several channels, with any LLM
provider, from an admin panel, with tests, an eval, and a security review
behind it.

## Definition of done for v1.0

Every line below is checked by a test, a CI job, a document, or a rehearsal.
None is asserted.

**Product**
- Channels: WhatsApp (Baileys), Telegram, Discord. WhatsApp Cloud API as an
  optional adapter for one-to-one and up-to-8-person groups on a business
  number.
- Many groups per instance, each with its own settings, any mix of channels.
- Providers: Anthropic, Gemini, OpenAI-compatible (covers OpenAI, OpenRouter,
  LiteLLM proxy, Groq, Mistral, Ollama, Together). Keys encrypted at rest.
  One active provider per group with a global default. Price table per model
  so cost figures are real.
- Embeddings and reranker stay local. No per-token cost for retrieval, no
  chat text leaves the box until the answer step.
- Admin panel: health, questions, group settings, providers, channels, cost
  and budget, data, eval. Setup wizard. Single admin login.
- Memory quality: correction loop, decision supersession (newest wins, with
  history), DM mode (ask privately, answer from your groups).
- Hard budget caps with auto-stop. Member opt-out and deletion.

**Engineering**
- Unit and integration tests, green in CI on every push. Node tests for the
  channel process, pytest for the app, Postgres service in CI.
- Migrations runner with numbered SQL files and a `schema_migrations` table.
- Ingest retry: no message lost across an app restart.
- `/health`, `/metrics` (Prometheus text), structured JSON logs.
- Backup and restore documented and rehearsed once.
- Eval harness with published numbers: answer accuracy, citation accuracy,
  abstention rate, p50/p95 latency, cost per question, by provider. Run on a
  public group-memory benchmark subset and a hand-made Finnish set.
- Load test at the volume of a busy group (500 messages/day, 50 questions/day)
  with the p95 answer latency recorded.
- Security: threat model, SECURITY.md listing what is and is not defended,
  prompt-injection handling for retrieved text, rate limit per asker, secrets
  never logged. A code review and a security review per phase.
- Docs: README, INSTALL, OPERATIONS runbook, CHANGELOG, CONTRIBUTING.

## Rules that stay from v0.1

- No dependency without naming it and why. Each phase lists its additions.
- No abstraction until a second implementation exists. The channel adapter is
  extracted in phase 3 when Telegram lands, not before.
- A setting exists only where two reasonable values exist. Provider, model,
  channel, triggers, thresholds, budgets, retention, opt-outs pass. Chunk
  size, fusion constants and prompt wording are code with tests.
- Files under 300 lines, split by feature.
- Comments explain why.

## Rules that change

- Errors at boundaries (network, LLM, channel APIs) are handled and retried.
  Bugs in our own code still crash loudly.
- Tests and CI are mandatory. A phase is not done with red CI.
- Config that the admin owns lives in Postgres, not `.env`. `.env` keeps only
  what is needed before the database exists: database password, secret key,
  and the first admin password.

## Phases

Each phase ends with: tests green, `code-review` and `security-review` run and
findings fixed or recorded, docs updated, a tagged commit. I test everything I
can without a phone or a token; the final phone test is yours.

### Phase 0 — foundation (v0.2)
- Migrations runner; move `001_init.sql` under it.
- pytest with a Postgres service, `node --test` for the gateway, ruff, GitHub
  Actions running all three plus image builds.
- Structured JSON logging, `/health`, `/metrics`.
- Ingest retry in the gateway with an on-disk queue; app-side idempotency
  already exists.
- Tests for what v0.1 shipped untested: chunking episodes, RRF fusion, the
  import parser, trigger detection, the quote payload.
- Deps: `pytest`, `ruff`, `httpx` (test client and outbound HTTP with timeouts
  and retries), `pytest-httpx` (mock outbound calls).

### Phase 1 — many groups, many providers (v0.3)
- Tables: `groups`, `settings`, `providers`, `budgets`, `audit_log`.
- Per-group settings replace the `.env` values: triggers, threshold, refusal
  text, answer language, retention, opt-outs, quiet hours.
- Provider clients: Anthropic, Gemini, OpenAI-compatible. One function shape,
  three files. Token and cost accounting per call. Keys encrypted with
  pgcrypto using `SECRET_KEY` from `.env`.
- Budget caps: monthly per group and global, auto-stop with one notice.
- Gateway handles every group the admin enabled; `GROUP_JID` goes away.
- Admin JSON API for all of the above, used by the panel in phase 2.
- Deps: none new in Python (pgcrypto is in Postgres).

### Phase 2 — admin panel and wizard (v0.4)
- Auth: one admin, password hash in DB, signed session cookie.
- Pages: health, questions (with feedback and "wrong, expected X"), group
  settings (threshold shows "N% of past questions would be refused"),
  providers (with test button), cost and budget, data (backfill upload,
  re-embed, member deletion, export).
- Setup wizard: preflight, LLM key, link WhatsApp (QR in browser), pick
  groups by name, round trip.
- Server-rendered Jinja2 + htmx, vendored, no build step, mobile-first.
- Deps: `jinja2`, `itsdangerous` (session signing), `python-multipart`
  (forms). htmx and Pico CSS vendored as static files.

### Phase 3 — channels (v0.5)
- Gateway becomes a multi-channel process: `channels/whatsapp.js`,
  `channels/telegram.js`, `channels/discord.js`, one shared contract to the
  app (`/ingest`, `/ask`, reply). This is the adapter extraction.
- Telegram via Bot API (privacy mode must be off; the wizard says so).
- Discord via gateway websocket (Message Content intent; the wizard says so).
- Channel configs stored encrypted in the DB; the gateway pulls them from the
  app and reconnects on change. Admin channels page and group discovery.
- Deps (Node): `grammy` (Telegram), `discord.js`.

### Phase 4 — memory quality (v0.6)
- Correction loop: a reply "wrong, it's X" to a bot answer stores a
  correction that outranks the original chunk.
- Facts with `superseded_by`: decisions extracted per chunk by the active
  provider, embedded, retrieved alongside chunks; newest wins and the answer
  says what changed and when.
- DM mode: a private chat with the bot answers from the groups that member
  belongs to; membership checked through the channel.
- Prompt-injection hardening: retrieved text is data, delimited and
  instructed as such; tests with adversarial chunks.

### Phase 5 — eval, load, tuning (v0.7)
- Eval loader through the import path. Public data confirmed available:
  EverMemBench (GitHub + Hugging Face `EverMind-AI/EverMemBench-Dynamic`) and
  SocialMemBench (Hugging Face `anon4data/socialmembench`, CC BY 4.0).
  GroupMemBench's dataset release is unconfirmed; use it if it appears. Plus
  a hand-made English+Finnish set from a real export.
- Scorer: exact match for abstention, LLM-judge for answers, id match for
  citations. Report to `docs/EVAL.md` with numbers per provider.
- Load test script and recorded p95. Tune rerank candidates, thresholds and
  chunking only with numbers in hand.
- Needs at least one real provider key from you for the judge and the runs.

### Phase 6 — WhatsApp Cloud API adapter (v0.8, optional)
- Webhook receiver in the gateway, template-free replies inside the 24-hour
  window, honest limits in the docs: one-to-one and groups up to 8, Official
  Business Account required, public HTTPS needed.

### Phase 7 — release (v1.0)
- Threat model and SECURITY.md. Final `security-review` over the whole tree.
- OPERATIONS runbook: upgrade, backup, restore (rehearsed), rotate keys,
  recover a banned number, read the logs.
- CHANGELOG, CONTRIBUTING, INSTALL. Version pins audited. Tag v1.0.0.
- Your phone test. Anything it finds is fixed before the tag.

## Still parked (see BACKLOG.md)

File upload and Drive ingest, voice and images, web search, MCP, auto wiki,
promise tracking, document generation, multi-tenant SaaS, Kubernetes.

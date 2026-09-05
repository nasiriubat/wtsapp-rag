# The v1.1 audit

On 5 September 2026, the day v1.0 shipped, three independent reviews read the
whole tree from three angles: code, architecture and scale; security and
operations; product, usability and documentation. Every high-severity claim
was verified by hand before it was accepted. This is the report, with what
was done about each finding. The changes landed as v1.1.0 in six phases; the
commit history and `CHANGELOG.md` tell the story in order.

Severity: **C** critical, **H** high, **M** medium, **L** low.

## Scorecard at v1.0

| Dimension | Grade | One line |
|---|---|---|
| Tech stack & package selection | **B+** | Right choices throughout; two unpinned model artifacts, one missing direct pin, pandas for one converter |
| Code quality | **B+** | Clean, small, well-commented; four broad `except Exception`s hide our own bugs |
| Architecture | **B** | Loop design is right; `os._exit` on any loop error turns one poison item into a permanent outage |
| Scalability | **C** | 5 missing indexes, 8 connections per question, HNSW post-filter starves the vector leg at ~10+ groups |
| Security | **C+** | Auth, CSRF, secrets: solid. Lockout bypass via `X-Forwarded-For`, unbounded webhook body, no default spend cap |
| Privacy / data protection | **C** | Retention and erasure cover 2 of 5 tables; group delete orphans everything and disables its expiry |
| Feature offering | **B** | Every README promise exists; missing: ask-from-panel, audit viewer, disconnect alert, member list |
| Usability | **C+** | Form errors render raw JSON and lose input; no loading states; flash broken on Questions |
| UI / UX | **B-** | Design system is good; mobile drops the IA; no dark mode; confirmations don't match risk |
| Docs | **B** | Best-in-class setup guide; ~10 factual mismatches with the UI, first README link bounces to Health |
| Operations / CI | **B-** | CI builds images and runs tests; no Dependabot, no audit scan, floating base images, no SIGTERM handling |



## Findings and what happened to them

Severity: **C** critical, **H** high, **M** medium, **L** low. Every location verified.

### A. Will take the service down

| # | Sev | Where | Problem | Status |
|---|---|---|---|---|
| A1 | **C** | `app/documents/read.py:82`, `app/documents/__init__.py:129`, `app/main.py:41-45` | `pdfplumber.open` is unguarded; `_index` catches only `Unreadable`; `_crash` does `os._exit(1)`. One corrupt PDF → app exits → restarts → same `pending` row → exits. **Permanent crash loop**, and the gateway never starts (waits on `service_healthy`). Reachable by any group member via `/ingest/file` when `index_files` is on. | fixed, phase 1 |
| A2 | **H** | `app/main.py:41-45` | `os._exit` also fires on a transient Postgres restart hit by any loop; drops every in-flight request, skips shutdown. | fixed, phase 1 |
| A3 | **H** | `app/chunking.py:44-56` | Pending-message query has no `LIMIT` (siblings have `PER_TICK=20`, `BATCH=3`). Import or Re-index of a big group loads every row and embeds them in one batch — multi-GB allocation, and onnxruntime's arena never shrinks. | fixed, phase 1 |
| A4 | **H** | `app/extraction.py:33-36` | On any provider error the loop `break`s without marking the chunk. A chunk that permanently 4xxs (content filter, size) stalls decision extraction for that group **forever**, silently. | fixed, phase 1 |
| A5 | **H** | `gateway/channels/whatsapp_cloud.js:57-61` | Webhook buffers the entire body before verifying the signature, no cap, no timeouts. The one deliberately public listener; an unauthenticated multi-GB POST OOMs the gateway and all four channels. | fixed, phase 1 |
| A6 | **M** | `gateway/core.js:48-53`, all three channels | Shared-file size check runs after the full download. Use `attachment.size` / `file_size` / `fileLength` first. | fixed, phase 1 |
| A7 | **M** | `gateway/channels/whatsapp.js:89-103` | Reconnect on close with no backoff — a tight loop against Meta is the surest way to get the number flagged. | fixed, phase 1 |
| A8 | **M** | `gateway/queue.js` | No size cap, whole file rewritten every 10 s tick, one permanently-5xx item blocks the queue forever. | fixed, phase 1 |
| A9 | **M** | `gateway/index.js:19-20`, no SIGTERM | `uncaughtException` is logged and swallowed (undefined V8 state); no graceful stop, so `docker compose stop` abandons an in-flight flush. | fixed, phase 1 |

### B. Security

| # | Sev | Where | Problem | Status |
|---|---|---|---|---|
| B1 | **C** | `app/Dockerfile:9` `--forwarded-allow-ips *` + `app/admin/auth.py:13-31` | Lockout keys on `request.client.host`, which any peer sets via `X-Forwarded-For`. Rotate the header → fresh 5-attempt bucket per request → **unlimited password guessing** on `/admin/login` and `/api`. `SECURITY.md:41` claims a protection that does not exist. Also `_failures` is never evicted → memory exhaustion. | fixed, phase 2 |
| B2 | **H** | `app/groups.py:50,62`, `app/budget.py:24-26` | Both budget caps default `None` → `exceeded()` returns `False` immediately. **A fresh install has no spend ceiling**; any member can loop `@agent` into an unbounded bill. `SECURITY.md` cites the cap as the mitigation. | fixed, phase 2 |
| B3 | **M** | `app/admin/auth.py:16-17` | Sessions not bound to the password; rotating a leaked `ADMIN_PASSWORD` leaves an attacker's cookie valid for 7 days. Fix is free: mix a password hash into the signer salt. | fixed, phase 2 |
| B4 | **M** | `app/answer.py:27-29`, `app/asking.py:127` | Tag neutralisation is exact-match, closing-tag only (`</CHAT>`, `</chat >`, a bare `<document>` pass). And `source_label` (an attacker-chosen **filename** from `/ingest/file`) is prepended verbatim to the reply sent to the group. | fixed, phase 2 |
| B5 | **M** | `app/main.py:81-100` | `/health` and `/metrics` unauthenticated on the same app the docs tell you to proxy; leak activity volume and refusal rates. | fixed, phase 2 |
| B6 | **M** | `.env` (0644), `gateway/auth_state/creds.json` (0644) | Master key and live WhatsApp session world-readable on a multi-user host. | documented and applied here; a preflight check cannot see the host's files |
| B7 | **L** | `app/templates/health.html:68` | Admin-supplied trigger strings rendered `\| safe`; `SECURITY.md:32-34` says there is only one `\| safe` and names a different one. | fixed, phase 2 |
| B8 | **L** | `whatsapp_cloud.js:23` | Verify-token compare is `===` while the HMAC path is timing-safe. | fixed, phase 1 |
| B9 | **L** | `app/audit.py:9` | `redact` is shallow; a key nested in provider `options` lands in `audit_log` in clear. | fixed, phase 2 |

### C. Privacy and data lifecycle

| # | Sev | Where | Problem | Status |
|---|---|---|---|---|
| C1 | **H** | `app/groups.py:132-134`, no FKs on `*.group_id` | **Deleting a group deletes only the group row.** Messages, chunks, facts, questions, documents are orphaned — and because `retention.run_once` joins `groups`, orphans are **never expired**. "Delete" converts data from "expires in N days" to "kept forever". | fixed, phase 2 |
| C2 | **H** | `app/retention.py:10-22` | Retention window applies to `chunks` and `messages` only. `query_log` (verbatim questions + answers + `sender_jid`) and `facts` (member statements + `sender_jid`) grow forever regardless of the setting. | fixed, phase 2 |
| C3 | **H** | `app/retention.py:49-74` | `purge_sender` never touches `query_log` or `facts`. After "Erase a member", their id, their questions and their corrections remain, and still show on `/admin/questions`. Incomplete GDPR erasure. | fixed, phase 2 |
| C4 | **M** | `gateway/core.js:83-87` | Every message logs the sender's phone number; nothing rotates it, erasure cannot reach it, and OPERATIONS.md tells you to tail it. | fixed, phase 2 |
| C5 | **M** | `docs/OPERATIONS.md:18-31` | Backups are plaintext chat history, manual, unencrypted, no rotation. | documented, phase 2 |
| C6 | **M** | `app/asking.py:131-139` | Early return when the source episode vanished skips `query_log.record` — but the provider was already called and paid. Invisible to the budget. | fixed, phase 1 |

### D. Scalability (what breaks first at 50 groups / 1M messages, in order)

| # | Sev | Where | Problem | Status |
|---|---|---|---|---|
| D1 | **H** | `app/retrieval.py:42,78` | `(group_id = %s OR group_id IS NULL)` on an HNSW index is **post-filtered**: pgvector collects the global top-`ef_search` (40) then filters. At ~10 equal groups the asking group gets ~4 of the 30 requested rows; at 50, 0-1. **No error, no log — answers just get worse.** The vector leg silently stops contributing. `pgvector/pgvector:pg16` is a floating tag so the fix options depend on which version you get. | fixed, phase 3 (iterative scans; tested with twenty groups) |
| D2 | **H** | `app/asking.py:42` (`_source`), `app/groups.py:144` (`dm_candidates`), `app/budget.py:14`, `app/asking.py:82` (`try_correction`), `app/facts.py:41` (`similar`) | **Five sequential scans per answered question**: `messages` by `(group_id, ts)` — the partial index excludes chunked rows; `messages` by `sender_jid` — no index; `query_log` — no index at all; `facts.embedding` — no vector index. Missing: `messages(group_id, ts)`, `messages(sender_jid)`, `query_log(group_id, ts)`, `query_log(ts)`, `facts` HNSW, `facts(superseded_by)`. | fixed, phase 3 (migration 011) |
| D3 | **H** | `app/db.py:7-11` and callers | One `psycopg.connect()` per unit of work: **8-9 TCP connects per `/ask`**, each a backend fork. ~11 concurrent questions saturate `max_connections=100`. CLAUDE.md forbids a pool library; threading one connection through `answer_in` collapses 8 → 2 with no dependency. | fixed, phase 3 (one connection per question, memoised settings) |
| D4 | **H** | `app/retrieval.py:96` | No concurrency limit on the reranker: 5 simultaneous questions = 5 ONNX sessions each grabbing every core. p95 collapses non-linearly; loops starve. | fixed, phase 3 |
| D5 | **H** | `app/asking.py:177-182` | A private question runs **5 full reranks** (one per candidate group) — ~16 s on the measured CPU — and throws four away. Embed once, fuse across groups, rerank once. | fixed, phase 3 |
| D6 | **H** | `app/retrieval.py:52-53` | OR-of-every-word FTS with stopwords kept: "who booked the cabin" matches every chunk containing "the", then `ts_rank_cd` sorts all of them. Linear in corpus. | fixed, phase 3; eval unchanged |
| D7 | **M** | `app/extraction.py:17-30` | Per tick, per group: `providers.resolve` + full `query_log` scan for budget, whether or not there is work. 50 groups = ~50 full scans / 90 s. | fixed, phase 3 |
| D8 | **M** | `app/admin/setup.py:41-44`, `README.md:66` | Real footprint is 2.8-3.5 GB (fp32 reranker 2.3 GB + e5 + markitdown/pandas + arenas). Preflight warns below 3 GB and says "about 2 GB". A 4 GB VPS OOMs under load. An int8 reranker export would cut ~1.7 GB **and** speed up the 3.3 s rerank. | fixed, phase 3 (int8 reranker; numbers in EVAL.md) |
| D9 | **H** | `app/groups.py:150-152` | After every app restart (or when Baileys' group fetch fails and returns `[]`), `member_of` falls back to "has ever written here" for ~30 s — **someone removed from a group can get private answers about it**. | fixed, phase 2 (migration 010) |

### E. Dependencies and supply chain

| # | Sev | Where | Problem | Status |
|---|---|---|---|---|
| E1 | **H** | `app/embed.py:11`, `app/retrieval.py:18` | Both HF model repos resolve `main` **at runtime on first boot**. `EmbeddedLLM/bge-reranker-v2-m3-onnx-o3-cpu` is an unaffiliated third-party re-export with no revision pin and no hash. A force-push or account compromise reaches every fresh install silently; two installs of one git tag can run different models. | fixed, phase 3 (pinned to commits) |
| E2 | **H** | `app/documents/read.py:13` | `pdfplumber` imported directly but not in `requirements.txt` — arrives only as a MarkItDown transitive. A MarkItDown minor bump breaks the app at import. | fixed, phase 3 |
| E3 | **M** | `app/requirements.txt:12` | `markitdown[xlsx]` pulls pandas (~72 MB with numpy) for one converter; `openpyxl` is already present. Also `magika` (an ML file-type detector run on every untrusted upload) is an unnamed transitive. No lock file, no hashes. | fixed, phase 3 (openpyxl directly; hashed lock) |
| E4 | **M** | `app/Dockerfile`, `gateway/Dockerfile` | Neither drops root — WhatsApp creds and the queue end up root-owned on the host bind mounts. Floating base tags. No gateway HEALTHCHECK. | fixed, phase 3 |
| E5 | **M** | `.github/` | No Dependabot/Renovate, no `pip-audit`/`npm audit`, no image scan, no SBOM. Baileys is an RC with no security backports. | fixed, phase 3 |
| E6 | **L** | `gateway/package.json` | `engines: node>=20` but only 22 is ever built or tested; no `test` script. | fixed, phase 3 |

### F. Tests

| # | Sev | Problem | Status |
|---|---|---|---|
| F1 | **H** | `.github/workflows/ci.yml` runs the suite against a DB named `assistant`, and `conftest.py` has no guard — the suite mutates global settings (`set_global(default_provider_id=None)`) and runs `retention.run_once()` (deletes real data). This is exactly how your live default provider was lost. CLAUDE.md forbids it; nothing enforces it. | fixed, phase 3 |
| F2 | **H** | `retrieval.search` is never tested end to end — `test_retrieval.py` covers two helpers; every `answer_in` test monkeypatches search away. The `SCOPE` clause, sigmoid, and `strict=True` zip are unverified. | fixed, phase 3 |
| F3 | **M** | Untested: documents image/scanned path, Cloud API positive path, `whatsapp.js` entirely, `index.js` orchestration, `core.ingest` ordering, the 10 MB cap. Inline cleanup in `test_documents.py`/`test_retention.py` leaks rows on failure. | fixed, phase 3 (index.js orchestration moved to supervisor.js and tested) |

### G. Usability, UI and IA

| # | Sev | Where | Problem | Status |
|---|---|---|---|---|
| G1 | **H** | `app/main.py` (no exception handler); raised from `pages_groups.py:81`, `pages_providers.py:27`, `admin_api.py:36`… | **A form error renders raw JSON on a blank page and loses everything typed.** "Helsinki" in Time zone → pydantic dump, 15 settings gone. | fixed, phase 4 |
| G2 | **H** | `app/groups.py:127-128`, `group.html:68` | Opt-out **erases the member's whole history on Save with no confirm** — the only irreversible action without one — and the returned count is discarded. | fixed, phase 4 |
| G3 | **H** | `pages_groups.py:123` | Quiet hours silently discarded unless both times set; "Saved." appears anyway. | fixed, phase 4 |
| G4 | **H** | `providers.html:91-92`, `setup.py:77` | Prices default 0 and the wizard never asks: **every wizard-onboarded install has €0.00 cost forever and inert budget caps**, with no hint in the UI. | fixed, phase 4 |
| G5 | **H** | `setup_test.html`, `setup.py:136-145` | The wizard's last step waits for a phone **forever**; there is no way to ask the assistant anything from the browser. | fixed, phase 5 |
| G6 | **H** | `admin/__init__.py:45`, `README:75` | README says open `/setup`; login always lands on `/admin`. And `/setup` never reaches a "done" state, so a working install shows an unfinished wizard forever. | fixed, phase 5 |
| G7 | **H** | `pages_questions.py` | Questions: no search, no group filter, forward-only pagination. Deleting a question shows no confirmation (flash not wired on that page; `providers.html` renders one no handler sets). | fixed, phase 4 |
| G8 | **M** | all templates | Zero `hx-indicator`/`hx-disabled-elt`: Test and List the models are paid calls with no feedback and no double-click guard. No `aria-live`. | fixed, phase 4 |
| G9 | **M** | `data.html:28,78` vs `:24,:47` | Confirmation inverted: Re-index (safe) confirms; Import (irreversible, wrong-group risk) does not; Delete chats / Clear log guarded by `confirm()` only. | fixed, phase 4 (import gets a confirmation naming the group; preview and undo are in BACKLOG.md) |
| G10 | **M** | `data.html:65`, `group.html:68` | Erase-a-member and opt-out want raw sender ids that appear **nowhere in the UI** — no member list exists. | fixed, phase 5 |
| G11 | **M** | `app.css:120-127` | Below 820 px the nav becomes nine wrapped links with the section labels hidden — the IA vanishes on a phone. No dark mode. Focus ring ~1.3:1. `<tr hx-get>` unreachable by keyboard. | fixed, phase 6 |
| G12 | **M** | `base.html:17-18`, `groups.html`, `providers.html` | "Which model answers?" has no home: no provider column on Groups, no "used by N groups" on Providers. Setup guide lives under "Running it". | fixed, phase 5 |
| G13 | **M** | `health.html:30-32,46` | "Questions today" is a rolling 24 h; sub-line quotes a refusal string the product never says; Disk reports the container. Cost tile rounds real spend to €0.00. | fixed, phase 4 |
| G14 | **M** | absent | No audit-log page (`/api/audit` exists, `SECURITY.md:51` advertises it); no channel-disconnect banner; no corrections/decisions viewer (members can poison memory invisibly); no onboarding message to the group. | audit page, banner and decisions viewer fixed in phase 5; the hello message is in BACKLOG.md |
| G15 | **M** | 12 inline handlers across templates | `onsubmit=confirm`, `oninput`, `onchange` → a CSP without `unsafe-inline` is impossible. Twenty lines of `app.js` removes all of it. | fixed, phase 4 |

### H. Docs

| # | Sev | Problem | Status |
|---|---|---|---|
| H1 | **H** | `SETUP.md:90-118` documents Name / prices / List the models / Test as wizard steps; the wizard has none of them. | resolved in phase 4: the wizard now has those fields |
| H2 | **M** | `SETUP.md:72` "user name is admin" — login has no username field. `:131` says "make sure Enabled" but never "press Save", and a fresh install has no channel row until you do. | fixed, phase 6 |
| H3 | **M** | `README:86` "everything the panel does is also a JSON API" — false (channels, documents, cost, import, erase are panel-only). | fixed, phase 6 |
| H4 | **M** | `OPERATIONS.md:110` "thumbs-down" — buttons are Good/Wrong/Clear. `:95` names outcomes the UI hides under "other". | fixed, phase 6 |
| H5 | **M** | `UNTESTED.md` says phone pairing is verified (`:6-13`) and still lists it as untested (`:25-27`). `ROADMAP.md` cites Pico CSS (removed), an `INSTALL` doc (never existed), and "all seven phases done" while phase 5's benchmark DoD is deferred per `EVAL.md:94`. | fixed, phase 6 |
| H6 | **L** | `SECURITY.md:41` and `:32-34` are factually wrong (see B1, B7). Version string hand-maintained in `base.html:34`. UI doc links point at the upstream repo. | fixed, phase 6; docs are still linked from the upstream repository (BACKLOG.md) |

---

## What was measured

Before and after numbers are in `docs/EVAL.md`: the reranker at 2281 ms
against 832 ms per ten full-length candidates, the load test from p50 5.3 s
to 3.3 s, the eval unchanged at 100% answer accuracy and 0% false refusal.

## What remains open

Listed under "Deferred from the v1.1 audit" in `BACKLOG.md`. None is a
correctness or safety finding.

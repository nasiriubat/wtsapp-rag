# Backlog

Everything here is deliberately **not** being built yet. Ideas go here so they
stop competing for attention. Nothing moves out of this file until v0.1 has run
in a real group for two weeks and the query log says it is needed.

## Rule for promoting an item

An item leaves the backlog only when the `query_log` shows a pattern of
questions that v0.1 answers badly, and this item is the fix. "It would be cool"
is not a reason.

---

## Market (Sept 2026)

Checked so the roadmap below is ordered by what is actually missing, not by
what sounds fun.

| Project | What it does | What it lacks |
|---|---|---|
| hoodini/whatsapp-public-logan (89★, MIT) | Baileys, logs to Supabase, daily summaries, answers mentions from last 15 msgs | Retrieval over history, citation, confidence, eval |
| korjavin/ragtgbot (Telegram, 4★) | Qdrant top-10 vector search, shows 5 source msgs | Chunking, hybrid, rerank, refusal, eval |
| GramSearch/telegram-search, SearchGram | Fuzzy search over exports, some RAG QA | Telegram only, search tool not assistant |
| wassengerhq, devmoreir4 bots | Document RAG for support | Not about the group's own history |
| OpenClaw (68k★), NanoClaw | Personal agents living in WhatsApp | Memory is agent notes, not cited group history. Complements, not competitors |
| Meta AI Message Summaries | Summarizes unread, per user, opt-in | No long-horizon questions, no citation |
| Slack AI, Teams Copilot | "What did we decide?" with sources, $10 to $21/seat | Not on WhatsApp |

**The absent feature:** verifiable, temporally correct answers to "what did we
decide". Nobody self-hostable ships all four of: quote-reply citation,
abstention, supersession (newest decision wins, with history), and published
numbers. GroupMemBench (Microsoft, May 2026) puts the best system at 46%
average and **27% on knowledge update**; EverMemBench says temporal reasoning
fails without explicit version semantics. v0.1 covers citation and abstention.
Supersession and the numbers are the contribution.

**Consequences for this file:**

- Digests, "catch me up", onboarding brief: Meta ships this natively now.
  Demoted.
- WhatsApp Cloud API: since Jan 2026 Meta allows only task-specific bots on the
  Business API, groups cap at 8. Demoted to a note.
- Eval harness: promoted from "Open source" to first thing after the two-week
  run.
- Facts with `superseded_by`: promoted to first feature after the eval.

## Promotion order after the two-week run

1. **Eval harness with published numbers.** Load a GroupMemBench subset through
   the Session 7 import path (it is already "rows in, messages out"), run
   `/ask`, score answer accuracy, citation accuracy, abstention rate, p50/p95
   latency, cost per question, by model. Add a small hand-written Finnish set
   from the real group's export because the public benchmarks are English.
   Publish the table.
2. **Facts with `superseded_by`.** Only if the "temporal failures" pile or the
   knowledge-update score says so.
3. **Correction loop.** Cheap, unique, feeds the facts table.
4. **Telegram adapter.** Zero ban risk, lets others run the eval without a
   burner SIM. `ChannelAdapter` is extracted then, not before.

---

## Phase 2 — sources

- **File upload ingest** — PDF (PyMuPDF), DOCX, XLSX, PPTX, CSV. Store extracted
  text as chunks tied to the source message.
- **Google Drive folder sync** — service account, folder shared with its email,
  `drive.file` scope, `changes.list` polling every 10 min with a stored
  `startPageToken`. Compare `md5Checksum`. Native Docs need `files.export`.
  Delete chunks on file trash — this is the classic bug.
- **Voice notes** — faster-whisper small, int8, CPU.
- **Images** — Tesseract OCR first, escalate to a vision model when OCR returns
  nothing legible.
- **Source authority weighting** — a signed contract in Drive should outrank a
  passing remark in chat. Add `source` and `authority` to chunks, expose to the
  reranker.

## Phase 3 — tool router

- Convert `/ask` to native tool calling. Each source becomes a tool.
- Uniform evidence shape across every source:
  `{ source_type, source_id, title, url, snippet, timestamp, author, confidence }`
- **Web access** — one capability, not two. `web_search` + `web_fetch` together.
  - Providers: SearXNG (self-hosted, unlimited, unreliable under load),
    Tavily (1,000/mo free, no card), Serper (2,500 one-time).
  - Brave killed its perpetual free tier in Feb 2026. Google CSE dies Jan 2027.
  - Fetch with trafilatura. No Playwright, no browser.
  - System prompt rule: **internal sources before external, always.**
- Tool results and fetched pages are **untrusted data**, never instructions.

## Phase 4 — MCP

- MCP client, streamable HTTP transport with token auth. Not stdio — that means
  running client code inside our container.
- Pin tool-definition hashes at approval time; require re-approval on change.
- Per-group tool allowlist.
- Inject only the top ~8 relevant tool schemas per turn (vector search over tool
  descriptions) plus a `search_tools` escape hatch. Otherwise 5 servers = 15–20k
  tokens of schema on every request.
- Bundled generic SQL MCP server for clients who cannot build their own:
  read-only grants, `sqlglot` parse rejecting anything but a single SELECT,
  column allowlist, statement timeout, forced LIMIT.
- Semantic layer: admin-defined named metrics backed by verified SQL. Try these
  before free-form generation. This is what makes text-to-SQL usable.
- Audit log for every DB query: who asked, what SQL, how many rows.

## Phase 5 — dashboard

Designed Sept 2026, not built. Earliest sensible start is after the two-week
run, because pages 2, 4 and 6 are empty until `query_log` has data and the
settings page only earns knobs the log asks for.

Shape: served by the same FastAPI process at `/admin`. Server-rendered pages,
htmx for interactivity, no build step, no second container. One admin password
in `.env`, session cookie. Mobile-first, because the admin is on the phone the
bot lives on. Do not mount the Docker socket anywhere.

Pages:

1. **Health** — WhatsApp linked, last message seen, last chunk built, models
   loaded, LLM key valid, disk and RAM. Same code as `./assistant doctor`.
   The wizard ends on this page.
2. **Questions** — `query_log` as a table: question, answer, confidence,
   latency, cost, feedback. Expand a row to see retrieved chunks with scores
   and which one was quoted. Thumbs up/down plus "wrong, expected X". Filters:
   refused, low confidence, negative feedback. Export JSONL. This table is
   the eval set; every thumbs-down is a future test case.
3. **Group settings** — trigger strings, bot name, answer language (match the
   question, or fixed), refusal text, confidence threshold, retention days,
   member opt-out list, quiet hours. The threshold control shows
   "at 0.42, 18% of past questions would have been refused", computed from
   `query_log`. That visual turns a magic number into a decision.
4. **Cost and budget** — tokens and euros per day/week/month by model and by
   asker. **Hard monthly cap with auto-stop** and one message to the group
   saying so; alert at 80%. An OSS tool that silently runs up an API bill gets
   one bad news cycle and never recovers.
5. **Data** — upload a chat export for backfill from the browser. Re-chunk and
   re-embed buttons. Delete one member's messages and chunks on request (we
   run in the EU). Full export.
6. **Eval** — run the eval set against the current config; show answer
   accuracy, citation accuracy, abstention rate, p50/p95 latency, cost per
   question over time. This is where the published numbers come from.

Configurability rule: a setting exists only where two values are both
reasonable. The seven on page 3 pass. Model, provider, system prompt override,
tool allowlists and connection manager (LLM keys, Drive, MCP) appear only when
a second option exists. A dropdown with one entry is a lie.

## Phase 6 — channels

- **Telegram first.** Official API, no restrictions, roughly a weekend.
  Gotcha: bots in groups have privacy mode ON by default and only see messages
  that mention them. Disable via BotFather or you get no history.
- Extract `ChannelAdapter` **when Telegram lands**, not before.
- **OpenClaw / NanoClaw**: they are agent harnesses, this is a memory backend
  with its own channel. Exposing `/ask` as a skill for them is a plausible
  distribution path once Telegram exists.
- WhatsApp Cloud API: demoted. Needs a public HTTPS webhook, which breaks the
  laptop-deploy story. Groups API caps at 8 participants and needs an Official
  Business Account. Since Jan 2026 only task-specific bots are allowed. The
  24-hour window makes proactive features impossible without templates. If it
  ever returns, the adapter needs a `supports_proactive` capability flag.

## Phase 7 — memory quality

- Facts table with `superseded_by` for temporal correctness. Promoted, see
  above. Try this **before** reaching for Graphiti + FalkorDB — it may be
  enough at this volume.
- Rolling daily summaries per group. Only as a retrieval aid, not a user
  feature (see Meta note above).
- Keep verbatim chunks as the primary retrieval path regardless. Extraction
  loses information; the graph is a secondary signal, not a replacement.

## Features that make it interesting (pick from the query log)

- **Correction loop** — reply "wrong, it's actually X" writes a correction fact
  that outranks the original. Cheap, high impact. Promoted, see above.
- **DM mode** — ask privately, answer from group knowledge. Removes the social
  cost of asking a basic question.
- **Auto-generated wiki** — living page per group: decisions, open questions,
  people, glossary. Turns a chat archive into an artifact.
- **Promise tracking** — detect "I'll send X Monday", follow up.
- **Document generation** — docx/xlsx/pdf sent as a **WhatsApp attachment**, not
  a link. Google Docs write-back is Workspace + Shared Drive only; service
  accounts have no Drive storage quota of their own.
- **Language bridging** — answer in the language of the question regardless of
  the source language.
- Demoted (Meta does these natively now): **Catch me up**, **Onboarding
  brief**, digests as a user-facing feature.

## Deployment

- Single `docker-compose.yml`, optional services behind Compose profiles,
  `COMPOSE_PROFILES` in `.env`.
- Install wizard: **outcome questions, not component pickers.** A first-run
  page at `/setup` after `docker compose up`. Target: under ten minutes from
  clone to first answer. Five steps:
  1. Preflight — Compose version, free RAM (embedder + reranker need ~2 GB),
     free disk, port 8000. Each line ✓/⚠/✗ with the fix next to it.
  2. LLM key — paste, the wizard makes one real call and shows the reply.
  3. Link WhatsApp — QR rendered in the browser, page polls until linked.
  4. Pick the group — list of groups the number is in, by name. Replaces
     `GROUP_JID` in `.env`. No JID copy-paste.
  5. Round trip — "send @agent hello"; the page waits and shows the reply.
     Optional: upload the export for backfill.
  Recommended path is all defaults. Manual path shows Group settings first.
- `./assistant doctor` as a permanent command, same code as the health page.
- Everything after step 5 is skippable.

## Open source

- License: **Apache 2.0**, decided Sept 2026. `LICENSE` is in the repo.
- Audience: communities and small teams that live in WhatsApp groups. Not
  customer-support bots.
- README positioning line: *"Slack AI for WhatsApp groups. Self-hosted. Answers
  'what did we decide' with a quote of the message it came from, or says it
  does not know."*
- README must state plainly that the WhatsApp adapter is an unofficial client,
  may violate WhatsApp's terms, and that numbers can be banned. Reports in 2026
  put spammy automation at 2 to 8 weeks before a ban; a read-mostly bot on a
  dedicated number in one group is the lowest-risk profile, not a safe one.
- Eval harness with **published numbers**: promoted, see top of file. Nobody in
  this category publishes honest numbers.
- Security write-up: prompt injection via tool results, group chat as a
  broadcast surface, MCP tool-definition pinning, read-only enforcement.
  Include what is *not* defended against.
- MCP conformance CLI (`mcp check <url>`) published standalone.

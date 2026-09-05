# Backlog

Everything here is deliberately **not** being built. `ROADMAP.md` holds what
is being built and in which order. An item leaves this file only when a
number says it is needed: a pattern in `query_log`, a failing eval case, or a
user request with a use case attached. "It would be cool" is not a reason.

---

## Market (Sept 2026)

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
fails without explicit version semantics. v0.1 covers citation and
abstention. Supersession (roadmap phase 4) and the numbers (phase 5) are the
contribution.

**WhatsApp Cloud API reality check:** since Jan 2026 Meta allows only
task-specific bots on the Business API, groups cap at 8 participants and need
an Official Business Account, and the 24-hour window blocks proactive
messages. It is a one-to-one and tiny-group channel. Big groups are only
reachable through the unofficial client. Roadmap phase 6 builds it with those
limits stated.

## Known limitations of v0.1 (fixed in roadmap phase 0 unless noted)

- Messages sent while the app is restarting are dropped. Phase 0: gateway
  retry queue.
- Gemini 3.x thinks by default, which may push a question past 5 s. Phase 1:
  per-provider generation options with a tested default.
- Cross-lingual questions score low on the reranker (Finnish question over an
  English chunk: 0.003). Phase 5: measure; if real, translate the query
  before search.

## Parked — sources

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

## Parked — tool router and web

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

## Parked — MCP

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
- MCP conformance CLI (`mcp check <url>`) published standalone.

## Deferred from the v1.1 audit (`docs/AUDIT.md`)

- A hello message posted to a group when it is enabled, so members learn the
  trigger word. Needs an outbound path from the app to each channel.
- Import preview and undo: parse the export first and show "1,432 messages,
  Mar 2024 to Sep 2026, into Cabin crew?" before inserting; keep the batch's
  ids so it can be undone.
- Upload progress for large files; a time limit on "reading…".
- Per-group analytics: refusal rate, trend, top askers.
- Knowledge export: documents and decisions as a file.
- A global default answer language; a picker for time zones.
- Post-relink group repair: map old group ids to the new number's view.
- Serving the docs from the panel, so a fork or an air-gapped install is not
  sent to the upstream repository.
- A `SECRET_KEY` rotation script that re-encrypts in one transaction, and
  splitting the session-signing key from the at-rest key.
- Baking the models into the image so first boot needs no network.

## Parked — memory and features

- Rolling daily summaries per group, as a retrieval aid only. Meta ships
  user-facing digests natively.
- Graph memory (Graphiti + FalkorDB). Only if the facts table (phase 4) is
  shown insufficient by the eval. Verbatim chunks stay primary regardless.
- **Auto-generated wiki** — living page per group: decisions, open questions,
  people, glossary.
- **Promise tracking** — detect "I'll send X Monday", follow up.
- **Onboarding brief** and **catch me up** — Meta does these natively now.
- **Document generation** — docx/xlsx/pdf sent as a WhatsApp attachment.
  Google Docs write-back is Workspace + Shared Drive only.
- **Language bridging** — answer in the language of the question regardless of
  source language. Partly covered by the answer-language setting.
- **OpenClaw / NanoClaw skill** — expose `/ask` as a skill for those harnesses.

## Parked — platform

- Multi-tenant SaaS: separate customers, billing, sign-up. Doubles the work
  and changes the security model.
- Kubernetes. Compose on one VM is the deployment story.
- OIDC / multiple admin users. One admin for v1.
- Docker socket is never mounted into the admin container, in any future.

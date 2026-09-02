# WhatsApp group assistant — v0.1

## What this is

Baileys logs WhatsApp group messages to Postgres. When triggered, the app
hybrid-searches the chat history and answers with a quote-reply citation.

That is the whole product right now. Nothing else.

## Architecture (do not deviate)

- `gateway/` — Node + Baileys. Connects to WhatsApp, POSTs messages to the app,
  sends replies. It contains no business logic.
- `app/` — Python + FastAPI. Ingest, chunking, embeddings, retrieval, answering.
  Single process.
- Postgres 16 + pgvector. Plain SQL via psycopg. No ORM.
- Config in `.env`, read with `os.environ`. No settings class, no config framework.

## Hard constraints

- **No new dependencies without asking me first.** Name it and say why.
- **No interface or abstraction until a SECOND implementation exists.** One
  channel means no ChannelAdapter. One provider means no ProviderInterface.
- **No config option for a value that has one value.**
- Files stay under 300 lines. Split by feature, not by layer.
- No `try/except` around things that cannot fail. Let it crash in v0.1.
- No queue, no Redis, no Celery, no background worker process. Use a loop.
- No premature indexes, no caching layer, no connection pooling library.
- Comments explain *why*, never *what*. Delete comments that restate the code.

## Not in scope

If I ask for any of these, say it is out of scope, offer to add it to
`BACKLOG.md`, and do not implement it:

Dashboard, install wizard, system-check/doctor, MCP client or server, web
search, Google Drive sync, file upload, voice notes, OCR, image handling,
multi-group support, Telegram adapter, WhatsApp Cloud API, ChannelAdapter
interface, graph database, Graphiti, Mem0, LiteLLM, document generation
(docx/xlsx/pdf), DM mode, digests, promise tracking, correction loop,
cost panel, auth, multi-tenancy, Kubernetes, CI/CD.

## Definition of done for v0.1

1. A message in the group lands in `messages` within a second.
2. `@agent what did we decide about X` gets an answer in under 5 seconds.
3. The reply is a quote-reply to the source message it drew from.
4. Low-confidence questions get "I don't have anything on that" instead of a
   guess.
5. Every question is written to `query_log` with retrieval, tokens, latency.

## Working style

- Plan before implementing. Show me the plan; I will cut it.
- One feature per session, then stop so I can commit.
- Start with the dumbest version that works. I will ask for robustness later.
- If you are unsure whether something is in scope, ask instead of building it.

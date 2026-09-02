# WhatsApp group assistant

Slack AI for WhatsApp groups. Self-hosted. Answers "what did we decide" with a
quote of the message it came from, or says it does not know.

> **Read this first.** The WhatsApp side uses [Baileys](https://github.com/WhiskeySockets/Baileys),
> an unofficial client. It may violate WhatsApp's terms and the number can be
> banned. Reports in 2026 put spammy automation at two to eight weeks before a
> ban. A read-mostly bot on a dedicated number in one group is the lowest-risk
> profile, not a safe one. Use a number you can afford to lose.

## What it does (v0.1)

- Logs every text message from one group to Postgres.
- On `@agent <question>`, a mention, or a reply to the bot, it hybrid-searches
  the group's history (vector + full-text, fused, reranked) and answers with
  Gemini Flash.
- The reply is a quote-reply to the source message the answer came from.
- Below a confidence threshold it replies "I don't have anything on that."
  and never calls the LLM.
- Every question is written to `query_log` with retrieved chunks, timings,
  tokens and latency. That table decides what gets built next.

## Quickstart

Needs Docker Compose v2, about 2 GB of RAM for the local models, a Gemini API
key, and a phone with plain WhatsApp on a dedicated number.

```
git clone https://github.com/nasiriubat/wtsapp-rag.git && cd wtsapp-rag
cp .env.example .env         # set POSTGRES_PASSWORD and GEMINI_API_KEY
docker compose up -d --build # first start downloads ~2.5 GB of models
docker compose logs -f gateway
```

Scan the QR with the phone. Send any message in the target group; the gateway
logs `group seen: <jid>`. Put that JID in `GROUP_JID` in `.env`, then:

```
docker compose restart gateway
```

Send `@agent hello` in the group. You should get a quote-reply.

### Backfill old history

Export the chat from the phone (`⋮ → More → Export chat → Without media`),
then:

```
docker compose exec -T app python scripts/import_export.py <group_jid> < export.txt
```

Handles iOS, Android and Finnish-locale formats. Re-running is idempotent.
Answers drawn from imported messages carry a text citation instead of a
quote, because WhatsApp cannot resolve quotes to messages it never saw.

## How it works

- `gateway/` — Node + Baileys. Forwards messages, detects triggers, sends
  quote-replies. No business logic.
- `app/` — Python + FastAPI, one process. Ingest, a 60-second chunking loop,
  retrieval, answering.
- Postgres 16 + pgvector, plain SQL.

Pipeline for one question, with numbers measured on a laptop CPU:

| Step | What | Time |
|---|---|---|
| Chunking | Episodes split on a 30-minute gap, max 15 messages or ~400 tokens, `Name: text` lines | background |
| Embed | `multilingual-e5-small`, 384 dims, `query:`/`passage:` prefixes | ~20 ms |
| Search | Vector top-30 + full-text top-30, reciprocal rank fusion (k=60) | ~10 ms |
| Rerank | `bge-reranker-v2-m3` on the top 10 | ~0.2 s for short chunks, ~3.3 s for 10 full ones |
| Answer | Gemini Flash over the top 8, or refusal without an LLM call | model-dependent |

Models: e5-small (MIT) from its official ONNX export; bge-reranker-v2-m3
(Apache 2.0) from a third-party ONNX export because BAAI publishes none and
fastembed only ships the base model. Both are loaded through fastembed's
custom-model hook.

## Status and roadmap

v0.1 is feature-complete and being tested on a real group. `BACKLOG.md` holds
the market read, the roadmap, and everything deliberately not built yet.
Next after two weeks of real use: an eval harness with published numbers on
GroupMemBench and EverMemBench, then temporal supersession of decisions.

## License

Apache 2.0.

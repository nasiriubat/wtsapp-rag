# Group chat assistant

Slack AI for WhatsApp groups. Self-hosted. Answers "what did we decide" with a
quote of the message it came from, or says it does not know.

> **Read this first.** The WhatsApp side uses [Baileys](https://github.com/WhiskeySockets/Baileys),
> an unofficial client. It may violate WhatsApp's terms and the number can be
> banned. Reports in 2026 put spammy automation at two to eight weeks before a
> ban. A read-mostly bot on a dedicated number in one group is the lowest-risk
> profile, not a safe one. Use a number you can afford to lose.

## What it does

- Logs every text message from the groups you enable to Postgres.
- On `@agent <question>`, a mention, or a reply to the bot, it hybrid-searches
  the group's history (vector + full-text, fused, reranked) and answers with
  the LLM provider you chose.
- The reply is a quote-reply to the source message the answer came from.
- Below a per-group confidence threshold it replies "I don't have anything on
  that." and never calls the LLM.
- Any LLM: Anthropic, Gemini, or anything OpenAI-compatible (OpenAI,
  OpenRouter, a LiteLLM proxy, Groq, Mistral, Together, Ollama). Keys are
  encrypted at rest. One global default, overridable per group.
- Channels: WhatsApp (paired phone), Telegram (bot token) and Discord (bot
  token), all through one gateway, mixed freely across groups. Set them up
  on the Channels page; the gateway picks changes up within 30 seconds.
- Decisions with history: each chunk is mined for decisions; a newer one
  supersedes the old, and answers say what changed and when. Reply "wrong,
  it's X" to an answer and the correction outranks the original.
- Ask privately: a DM to the bot is answered from the groups you belong to,
  with a text citation. Private questions are never stored as group messages,
  though like every question they appear in the admin's question log.
- Monthly budget caps per group and globally, member opt-out, quiet hours,
  retention. Every question is logged with retrieved chunks, timings, tokens
  and cost.
- Embeddings and the reranker run locally on CPU. No chat text leaves the box
  until the answer step.

Status: v0.5 (roadmap phase 3). Admin panel and setup wizard at
`http://localhost:8000/admin`. See `ROADMAP.md`.

Telegram: create the bot with @BotFather, run `/setprivacy` → Disable so it
sees every group message, add it to the group. Discord: create an
application, add a bot, enable the Message Content intent, invite it with
Read Messages, Send Messages and Read Message History. Paste the tokens on
the Channels page, then enable the groups that appear.

## Quickstart

Needs Docker Compose v2, about 2 GB of RAM for the local models, an LLM API
key, and a phone with plain WhatsApp on a dedicated number.

```
git clone https://github.com/nasiriubat/wtsapp-rag.git && cd wtsapp-rag
cp .env.example .env         # set the passwords and secrets; see the comments
docker compose up -d --build # first start downloads ~2.5 GB of models
```

Open `http://localhost:8000/setup`, log in with `ADMIN_PASSWORD`, and follow
the five steps: preflight, LLM key, scan the QR in the browser, tick the
groups to enable, send `@agent hello`. The admin panel is at
`http://localhost:8000/admin`: health, questions with feedback, group
settings, providers, cost, data.

Everything the panel does is also a JSON API with HTTP Basic auth under
`/api`, for scripts:

### Providers

Putting `GEMINI_API_KEY`, `OPENAI_API_KEY` or `OPENROUTER_API_KEY` in `.env`
before the first start seeds providers automatically. Otherwise, or to add
more:

```
curl -u admin:$ADMIN_PASSWORD localhost:8000/api/providers -H 'content-type: application/json' \
  -d '{"name":"Claude","kind":"anthropic","api_key":"sk-ant-...","model":"claude-sonnet-5","price_in":2,"price_out":10}'
curl -u admin:$ADMIN_PASSWORD -X POST localhost:8000/api/providers/1/test
curl -u admin:$ADMIN_PASSWORD -X PUT localhost:8000/api/settings -H 'content-type: application/json' \
  -d '{"default_provider_id":1}'
```

`kind` is `anthropic`, `gemini` or `openai`; the last takes a `base_url` for
any OpenAI-compatible server. `options` is merged into the request body for
provider-specific knobs (thinking budgets, effort, `max_completion_tokens`);
a null value removes a key. Prices are EUR per million tokens and drive the
cost figures and budget caps.

### Per-group settings

`PATCH /api/groups/{id}` with a `settings` object: `triggers`,
`confidence_threshold`, `refusal_text`, `answer_language`, `retention_days`,
`opt_out` (sender ids), `quiet_hours` (`{"start":"22:00","end":"07:00","tz":"Europe/Helsinki"}`),
`monthly_cap_eur`. `provider_id` overrides the global default. Global caps and
the default provider live at `/api/settings`. Every write is in `/api/audit`.

### Backfill old history

Export the chat from the phone (`⋮ → More → Export chat → Without media`),
then:

```
docker compose exec -T app python scripts/import_export.py <group_jid> < export.txt
```

Handles iOS, Android, Finnish-locale and US (month-first) formats. Re-running
is idempotent. Answers drawn from imported messages carry a text citation
instead of a quote, because WhatsApp cannot resolve quotes to messages it
never saw.

## How it works

- `gateway/` — Node. One module per channel under `channels/` (Baileys,
  grammY, discord.js) over a shared core that pulls groups and channel
  configs from the app, forwards messages, and sends quote-replies. Failed
  deliveries wait in an on-disk queue. No business logic.
- `app/` — Python + FastAPI, one process. Ingest, a 60-second chunking loop,
  retrieval, providers, admin API, retention. Applies `app/migrations/*.sql`
  at startup. `/health` and `/metrics` for monitoring; logs are JSON lines.
- Postgres 16 + pgvector, plain SQL. Provider keys encrypted with pgcrypto.

Pipeline for one question, with numbers measured on a laptop CPU:

| Step | What | Time |
|---|---|---|
| Chunking | Episodes split on a 30-minute gap, max 15 messages or ~400 tokens, `Name: text` lines | background |
| Embed | `multilingual-e5-small`, 384 dims, `query:`/`passage:` prefixes | ~20 ms |
| Search | Vector top-30 + full-text top-30, reciprocal rank fusion (k=60) | ~10 ms |
| Rerank | `bge-reranker-v2-m3` on the top 10 | ~0.2 s short chunks, ~3.3 s full ones |
| Answer | The group's provider over the top 8, or refusal without an LLM call | ~1 to 2 s |

## Development

```
pip install -r app/requirements-dev.txt
ruff check app && ruff format --check app
pytest                      # unit tests; set DATABASE_URL, SECRET_KEY, ADMIN_PASSWORD, GATEWAY_TOKEN for the integration tests
cd gateway && node --test
```

CI runs all of it plus both Docker images on every push. `docs/REVIEWS.md`
records each phase's code and security review; `docs/UNTESTED.md` lists what
only a phone can verify.

## License

Apache 2.0.

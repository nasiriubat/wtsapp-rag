# Build sessions

Seven sessions, one per day. Each is a separate Claude Code conversation.

**Every session:** plan mode first → read the plan → cut half of it →
implement → review the diff → commit → stop.

---

## Before session 1

Not coding tasks. Do these by hand.

- [ ] SIM in a phone, regular WhatsApp registered on it (not Business app, not
      Business API — plain WhatsApp)
- [ ] Test group created with 2–3 people
- [ ] Gemini API key
- [ ] Docker + Docker Compose v2 on the VM
- [ ] Export your real group history: `⋮ → More → Export chat → Without media`.
      Keep the `.txt` for session 7.
- [x] `git init`, `LICENSE` (Apache 2.0), `CLAUDE.md`, `BACKLOG.md` committed

---

## Session 1 — Postgres and the gateway

> Read CLAUDE.md first.
>
> Set up `docker-compose.yml` with Postgres 16 + pgvector and apply
> `migrations/001_init.sql`.
>
> Then create a minimal Node service in `gateway/` using
> `@whiskeysockets/baileys` that connects via QR, persists auth state to
> `gateway/auth_state/`, listens for group messages, and POSTs each one as JSON
> to `http://app:8000/ingest`.
>
> No reply logic yet. No trigger detection yet. Just connect and forward.

**Done when:** you scan the QR and see message JSON in the gateway logs.

---

## Session 2 — Ingest

> Create `app/` — FastAPI with `POST /ingest` that inserts into `messages`.
> Idempotent on `wa_msg_id`. Add it to docker-compose.

**Done when:** a message sent in the group appears in the `messages` table.

---

## Session 3 — Trigger and round trip

> Add trigger detection in the gateway. It fires on any of:
> 1. a true JID mention — our own JID in `contextInfo.mentionedJid`
> 2. the message text starting with any string in `TRIGGERS` from `.env`
>    (comma-separated, case-insensitive)
> 3. a reply to one of our own messages — `contextInfo.participant` equals our
>    own JID. The gateway has no database, so it must not look up `is_bot`.
>
> On trigger, POST to `/ask`. `/ask` returns `{ answer, quote }` where `quote`
> is either `null` or `{ wa_msg_id, sender_jid, is_bot, body }`. The gateway
> quote-replies to `quote` when present, otherwise to the triggering message.
> Baileys needs the message key (`remoteJid`, `id`, `participant`, `fromMe`)
> plus a body stub to build a quote; that is why `/ask` returns all four.
> Record the bot's own sent message in `messages` with `is_bot = true`.
>
> For now `/ask` returns `{ "answer": "got it", "quote": null }`.

**Done when:** `@agent hello` in the group gets "got it" as a quote-reply.

This is the most important milestone. Everything after it is improving an
answer that already round-trips.

---

## Session 4 — Chunking and embeddings

> Add chunking. Group unchunked messages into episodes: split on a 30-minute
> gap between messages, cap at 15 messages or ~400 tokens per chunk. Format the
> chunk content as `Name: text` lines, one per message — the speaker prefix
> must be inside the chunk text, not only in metadata.
>
> Embed each chunk with `multilingual-e5-small` via `fastembed` (CPU, ONNX).
> Prefix the text with `passage: ` before embedding; e5 models are trained
> with that prefix and recall drops measurably without it. Store the chunk
> content without the prefix.
> Insert into `chunks` with `first_msg_id`, `start_ts`, `end_ts`. Mark the
> source messages `chunked = true`.
>
> Run this as a loop every 60 seconds inside the same FastAPI process using a
> startup background task. No separate worker, no queue.

**Done when:** `SELECT count(*) FROM chunks` grows as people talk.

---

## Session 5 — Retrieval

> Implement retrieval in `/ask`:
> 1. embed the question, prefixed with `query: ` (see session 4)
> 2. vector search top-30 on `chunks.embedding`
> 3. full-text search top-30 on `chunks.tsv`
> 4. fuse with reciprocal rank fusion (k=60)
> 5. rerank the top 20 with `bge-reranker-v2-m3` via fastembed
> 6. return the top 8
>
> Time each step and log the milliseconds. The 5-second budget is tight on
> CPU: rerank of 20 chunks is expected at 1 to 3 s, Gemini Flash 1 to 2 s. If
> rerank is over budget, cut candidates from 20 to 10 before touching models.
>
> The group is English + Finnish. Finnish compounding weakens the full-text
> leg, so the vector leg may need more weight in the fusion. Measure first,
> tune only if the eyeball test says so.
>
> Have `/ask` return the reranked chunks as JSON for now so I can inspect them.
> No answer generation yet.

**Done when:** you can eyeball the retrieved chunks and they look relevant.

---

## Session 6 — Answering

> Generate the answer with Gemini Flash from the reranked chunks.
>
> - If the top rerank score is below `CONFIDENCE_THRESHOLD`, return
>   "I don't have anything on that." with `quote: null` and do not call the
>   LLM at all.
> - Otherwise build a prompt with the chunks, each labelled with its date range,
>   and instruct the model to answer only from them and to say it does not know
>   rather than guess.
> - Return `{ answer, quote }` where `quote` is the top-ranked chunk's first
>   message: `{ wa_msg_id, sender_jid, is_bot, body }`. The gateway
>   quote-replies to it (session 3).
> - If that `wa_msg_id` starts with `import:` (session 7), WhatsApp cannot
>   resolve the quote. Return `quote: null` and prepend a citation line to the
>   answer instead: `From 12 Mar 2026, Anna: "<first line of the message>"`.
> - Write every request to `query_log`: question, retrieved chunk ids and
>   scores, answer, confidence, tokens in/out, latency.

**Done when:** a real question gets a real answer that quote-replies to the
conversation it came from, and a nonsense question gets the refusal.

---

## Session 7 — Backfill

> Write a one-off script `app/scripts/import_export.py` that parses a WhatsApp
> chat export `.txt` into the `messages` table.
>
> Handle: the `[DD/MM/YYYY, HH:MM:SS] Name: text` and
> `DD/MM/YYYY, HH:MM - Name: text` formats, multi-line message bodies,
> system messages (joins, leaves, encryption notice), and the `<Media omitted>`
> / `‎` placeholder lines. Synthesise stable `wa_msg_id` values prefixed with
> `import:` so re-running is idempotent and session 6 can tell them apart.
> Use `import:<name>` as `sender_jid`.
>
> Keep it as two plain functions: one that parses the file into message dicts,
> one that inserts message dicts. The eval harness later feeds benchmark
> conversations through the same insert function. Two functions, no class, no
> interface.
>
> After import, let the chunking loop pick everything up.

**Done when:** the bot can answer a question about something from three months
ago.

---

## Then stop

Ship it to the real group. Use it daily for **two weeks**. Write nothing new.

After two weeks, read `query_log` and sort the failures into two piles:

- **Retrieval failures** — the answer was in the history and it did not find it.
  → fix chunking, retrieval, reranking.
- **Temporal failures** — it found the old answer instead of the current one.
  → this is when the facts table with `superseded_by` earns its place.

Anything that is not one of those two piles goes back in `BACKLOG.md`.

Before fixing either pile, build the eval harness (first item in
`BACKLOG.md`). Fixes without a number are guesses.

---

## Session rules

- **One feature per session.** Long sessions accumulate scope.
- **Plan mode first, always.** Then cut the plan.
- **Ask for the dumbest version.** "Simplest thing that works, no error handling
  yet" produces better starting code than "production-ready".
- **Read every diff.** Look for: files you did not ask for, config for values
  with one setting, abstractions with one implementation, defensive `try/except`
  around code that cannot throw.
- **Every idea goes to BACKLOG.md, not into the code.**
- If Claude Code proposes a dependency, make it justify it. The dependency list
  is where scope hides.

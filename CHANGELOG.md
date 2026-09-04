# Changelog

## v1.0.0 — 5 September 2026

First release. A self-hosted assistant that answers questions about a group's
own chat history, quoting the message it drew from or saying it does not know.

**Channels.** WhatsApp through an unofficial client, Telegram and Discord
through their official bot APIs, and the WhatsApp Cloud API for private
questions on a business number. One gateway process runs whichever the admin
enabled and restarts them when their configuration changes.

**Providers.** Anthropic, Google Gemini, and anything speaking the OpenAI
chat-completions format, which covers OpenAI, OpenRouter, a LiteLLM proxy,
Groq, Mistral, Together and Ollama. Keys are encrypted at rest, one global
default with a per-group override, and a Test button that makes one real call.

**Memory.** Messages are grouped into episodes, embedded with
`multilingual-e5-small` and reranked with `bge-reranker-v2-m3`, both locally on
CPU. Decisions are extracted per episode and superseded when the group changes
its mind, so an answer can say what changed and when. Replying "wrong, it's X"
to an answer stores a correction that outranks it.

**Admin panel** at `/admin` with a five-step setup wizard: health, questions
with feedback and a JSONL export, per-group settings, providers, channels,
cost with hard budget caps, and data import, re-embedding, member erasure and
export.

**Numbers.** `docs/EVAL.md` publishes answer accuracy, citation accuracy,
abstention, false refusal, latency and cost per question for two models on a
bilingual eval set, plus a load test. Two defaults changed because of what it
measured.

**Operations.** Migrations apply at startup, `/health` and `/metrics` for
monitoring, JSON logs, an on-disk retry queue so a restart loses no message,
and a rehearsed backup and restore in `docs/OPERATIONS.md`.

Known limits are in `SECURITY.md` (what is not defended) and
`docs/UNTESTED.md` (what no automated test could reach).

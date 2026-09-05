# Changelog

## v1.1.0 — 5 September 2026

The tech-lead audit release. `docs/AUDIT.md` has every finding and what was
done about it; the short version:

**Nothing takes the service down.** A corrupt PDF used to crash-loop the app
every fifteen seconds. Background loops now log, back off and show on
`/health`; a document that trips the parser is quarantined with the reason;
chunking is bounded per tick; decision extraction skips a chunk the provider
refuses instead of stalling the group; the Cloud API webhook caps its body at
1 MB before checking the signature; the gateway's retry queue is bounded with
a dead-letter file, WhatsApp reconnects with backoff, shared files are refused
by their declared size before download, and SIGTERM stops everything cleanly.

**Security and privacy do what the docs say.** The login lockout could be
dodged by rotating `X-Forwarded-For`; only `TRUSTED_PROXY` may set forwarded
headers now and a global throttle backs the per-client one. Sessions are
tied to the password, so rotating it logs everyone out. A fresh install has a
€10 monthly cap and ten questions per member per ten minutes. Deleting a group
deletes everything it produced; retention and member erasure cover the
question log and decisions too; membership survives a restart; every spelling
of the prompt tags is neutralised; the gateway logs a keyed hash instead of
phone numbers; `/metrics` and the detailed `/health` need the gateway token.

**Scale.** Six indexes every answer was missing, one connection per question
instead of nine, iterative HNSW scans so retrieval keeps working past a dozen
groups, one rerank per private question instead of five, two reranks at a
time on half the cores each. The reranker is the onnx-community int8 export:
2.7× faster on real chunks, the same eval score, and the models volume drops
from 4.3 GB to 1 GB. Both models are pinned to a commit. Dependencies install
from a hashed lock; pillow, starlette and python-multipart move past
published advisories; both images run without root; CI audits both
dependency sets and keeps a bill of materials. The test suite refuses any
database not named `*_test`.

**The panel.** Form errors are a page with the way back, and the group page
comes back filled in; results show once via a signed cookie; Questions can be
searched, filtered by group and paged both ways; confirmations match what
they guard, with typed confirmation on the two most destructive; every htmx
button shows it is working; no inline script and a Content Security Policy;
prices left at zero are called out; Health says what its numbers are and
refreshes. **Ask it from here** on the Questions page and the wizard's last
step: the answer, the citation and the retrieved chunks, no phone needed. The
wizard finishes. Login lands where you were going. An Audit log page, a
banner when an enabled channel is not connected, members and decisions on
record per group, an "Answers with" column. A phone-width menu that keeps the
sections, dark mode, a visible focus ring.

**Upgrading from v1.0** needs one command for the models volume; see
`docs/OPERATIONS.md`.

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

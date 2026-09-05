# Security

## Reporting

Open a private security advisory on the GitHub repository, or email the
maintainer. Please do not open a public issue for something exploitable.

## What this system is

One operator runs one instance for their own groups. Everything is on one
host: Postgres, a Python app, and a Node gateway that talks to WhatsApp,
Telegram and Discord. There is one admin. Group members are not users of the
system; they are the source of its data.

## Who we defend against

**Group members are untrusted.** Their messages, display names, group titles
and chosen message ids all reach the database, the model prompt and the admin
panel. Everything below follows from that.

- **Injection through chat.** Excerpts reach the model inside `<chat>` tags
  with the closing tag neutralised, and the system prompt names them content,
  never instructions. There are no tools behind the answer step, so the worst
  a successful injection achieves is a misleading answer, not an action.
- **Cross-group leakage.** Retrieval, facts, corrections and citations are
  filtered by `group_id` at every step. A private question is answered only
  from groups the asker belongs to: where a channel can list members that list
  decides, so someone who has left cannot keep asking.
- **Message id squatting.** WhatsApp lets a sender choose its message id.
  Uniqueness is per group, so a crafted id cannot shadow another channel's
  message.
- **XSS in the panel.** Templates autoescape, the few hand-built HTML
  fragments escape explicitly, and the one `| safe` renders a QR code the
  server drew itself.
- **A member choosing a file name.** Files shared in a chat are named by
  whoever shared them, and the name ends up in the prompt and in the reply.
  Control characters and angle brackets are stripped, the name is capped, and
  every spelling of the prompt's `<chat>` and `<document>` tags inside
  material is neutralised, not just the exact closing tag.
- **One person flooding the bot.** A sender gets ten questions in ten
  minutes across all groups; past that they are told to wait, before any
  retrieval or provider call. A fresh install also ships with a €10 monthly
  cap, so an unnoticed loop cannot run up an open-ended bill.
- **Mention abuse.** Discord answers are sent with no mention parsing, so an
  answer that quotes `@everyone` from the chat pings nobody.

## Access control

- The admin panel uses one password, a signed session cookie (`HttpOnly`,
  `SameSite=Lax`) and a CSRF token derived from the session. Login is rate
  limited twice: five wrong guesses pause one client for a minute, and twenty
  wrong guesses a minute from anywhere pause everyone, so rotating
  `X-Forwarded-For` buys nothing. Only the addresses in `TRUSTED_PROXY` may
  set forwarded headers at all. The JSON API under `/api` uses HTTP Basic
  with the same password and its own lockout bucket.
- Sessions are signed with a salt that includes the password, so changing
  `ADMIN_PASSWORD` logs every session out, including a thief's.
- The gateway authenticates with a shared bearer token. `/ingest`, `/ask` and
  the gateway's config and state endpoints accept nothing without it.
- Provider keys and channel tokens are encrypted at rest with pgcrypto using
  `SECRET_KEY` and masked in the audit log and the panel. A provider key is
  never returned by any endpoint. Channel tokens are returned to the gateway
  by `/gateway/config`, which requires `GATEWAY_TOKEN`: that token is
  therefore worth as much as the channel tokens themselves.
- Every admin write is recorded in `audit_log` with the actor and the change,
  secrets masked at any depth, and shown on the panel's Audit log page.
- The panel serves a Content Security Policy with no inline script, the
  result of an action travels in a signed one-shot cookie rather than the
  URL, and the login's `next` only ever points at a path on this site.

## What is not defended

Say these out loud before running it:

- **The WhatsApp adapter is an unofficial client.** It may violate WhatsApp's
  terms and the number can be banned. Use a number you can afford to lose.
- **The admin is fully trusted.** They can read every message, add a provider
  that points anywhere, and export everything. There is one role, no
  per-group admins, and no second factor.
- **`SECRET_KEY` protects secrets at rest only.** Anyone who can read the
  environment or the database volume with that key can read every provider key
  and channel token. It also signs sessions and derives CSRF tokens; splitting
  those is a later change.
- **A stolen session cookie is valid until it expires** (seven days) or
  until the password is changed. Logging out deletes the cookie but does not
  revoke the signature.
- **No transport security of its own.** Serve the panel and the Cloud API
  webhook behind TLS you control, and run uvicorn with `--proxy-headers` so
  the session cookie is marked `Secure`.
- **Prompt content is sent to the provider you configure.** Retrieval and
  reranking are local, but the excerpts that answer a question leave the host
  in the answer call.
- **Members cannot see or control their own data.** Opt-out and erasure are
  admin actions.
- **No protection against a malicious provider.** A provider you configure
  sees the excerpts you send it.
- **Denial of service is out of scope** beyond the login lockout, the
  per-sender question limit, the budget cap, the 1 MB webhook body cap and
  the bounded retry queue. Nothing rate-limits `/ingest` itself.
- **Login itself has no CSRF token**, so a third party can force a visiting
  admin's browser into a session they control. It gets them no access to this
  instance; it can mislead the admin about which instance they are looking at.
- **Nothing is published to the network by default.** Compose binds Postgres,
  the panel and the webhook to loopback. Whatever you put in front of them is
  yours to secure, and `--proxy-headers` is already set so the session cookie
  is marked `Secure` behind a TLS proxy.
- **Membership is what the channel last reported.** The list is kept in the
  database, so a restart does not widen access. For WhatsApp, a group the
  gateway has not reported yet has no members at all; for Telegram and
  Discord, which cannot list members, having written in the group is the
  evidence there is.
- **The gateway's own log** identifies senders by a keyed hash, not their
  number, so it can be kept longer than the chat itself.

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
- **Mention abuse.** Discord answers are sent with no mention parsing, so an
  answer that quotes `@everyone` from the chat pings nobody.

## Access control

- The admin panel uses one password, a signed session cookie (`HttpOnly`,
  `SameSite=Lax`) and a CSRF token derived from the session. Login is rate
  limited per client address. The JSON API under `/api` uses HTTP Basic with
  the same password.
- The gateway authenticates with a shared bearer token. `/ingest`, `/ask` and
  the gateway's config and state endpoints accept nothing without it.
- Provider keys and channel tokens are encrypted at rest with pgcrypto using
  `SECRET_KEY`, never returned by any endpoint, and masked in the audit log.
- Every admin write is recorded in `audit_log` with the actor and the change.

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
- **A stolen session cookie is valid until it expires** (seven days). Logging
  out deletes the cookie but does not revoke the signature.
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
- **Denial of service is out of scope.** There is no request throttling beyond
  the login lockout and the monthly budget cap.

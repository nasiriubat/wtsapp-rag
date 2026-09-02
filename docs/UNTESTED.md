# What has not been verified against the real thing

Updated per phase. Everything else in the repo has a test, a CI job, or a
recorded manual check behind it.

## Needs a phone (WhatsApp)

- Trigger detection on a live group: mention, prefix, reply-to-bot. Unit
  tests cover the logic against synthetic Baileys objects; the shape of real
  Baileys 7 messages with LID participants is assumed from its docs.
- Quote-reply delivery: whether WhatsApp resolves the quote stub built from
  `{wa_msg_id, sender_jid, is_bot, body}`.
- Recording our own sent message with `is_bot = true`.
- Reconnect after a dropped socket; the logged-out path.

## Verified with a real key (3 Sept 2026)

- Gemini `gemini-3.8-flash` answer path: real answer with the decision date,
  quote payload pointing at the source message, 256 tokens in, 37 out,
  1.98 s end to end of which 1.77 s was the model.

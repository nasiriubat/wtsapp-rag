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
- The gateway staying silent when the app returns `answer: null`.
- Wizard steps 3 to 5 against a real link: the QR the gateway reports
  scanning successfully, `groupFetchAllParticipating` returning the group
  list, and the round-trip detector seeing the first real question.
- Relink: the gateway logging out in process, clearing its auth files and
  pairing again with a fresh QR when the admin asks.

- Private messages on WhatsApp: the DM branch in the gateway (LID and phone
  JIDs), the member lists from `groupFetchAllParticipating`, and the
  correction reply flow (quoting a bot message then replying "wrong, …").
  The app side of all three is covered by tests through `/ask`.

## Needs a Telegram or Discord bot token

- Telegram and Discord channels end to end: connecting, seeing groups,
  trigger detection, quote-replies. The payload mapping and trigger logic
  are unit-tested against the documented update shapes; grammY and
  discord.js were never run against the real APIs here. No tokens in `.env`.

## Verified live (3 Sept 2026)

- Anthropic `claude-opus-5`, Gemini `gemini-3.8-flash`, OpenAI `gpt-5.4-mini`
  and OpenRouter `openai/gpt-5.4-mini` each answered the provider test endpoint with "OK"
  and a real question about seeded chat with a correct answer and a quote
  payload pointing at the source message. Switching a group's provider
  through the admin API changed which one answered; `query_log` recorded the
  provider id, tokens and cost.
- Cold `docker compose up`: db healthy, then app healthy, then gateway
  started and printed a QR.

# Contributing

## Getting it running

```
cp .env.example .env          # set the passwords and secrets
docker compose up -d --build  # first start downloads ~2.5 GB of models
pip install -r app/requirements-dev.txt
```

## Before you open a pull request

```
ruff check app && ruff format --check app
pytest                        # set DATABASE_URL, SECRET_KEY, ADMIN_PASSWORD, GATEWAY_TOKEN
cd gateway && npm ci --legacy-peer-deps && node --test
```

CI runs all three plus both Docker images. A red CI is not ready to review.

## What the code expects of you

The full rules are in `CLAUDE.md`; the ones that get pull requests sent back:

- **No new dependency without saying why in the pull request.** The list is
  where scope hides.
- **No abstraction until a second implementation exists.** The channel
  contract appeared when Telegram landed, not before.
- **A setting exists only where two values are both reasonable.** Chunk sizes
  and fusion constants are code with tests, not options.
- **Files stay under 300 lines.** Split by feature, not by layer.
- **Comments explain why.** Delete comments that restate the code.
- **Handle errors at boundaries** (network, providers, channel APIs, user
  input) and let bugs in our own code crash loudly.
- Chat content is data, never instructions. Anything a group member wrote is
  untrusted everywhere it goes.

## Changing retrieval or prompts

Measure it. `docs/EVAL.md` explains how to run the eval set and what each
number means; put the before and after in the pull request. Two defaults have
already changed because the eval disagreed with an opinion.

## Adding a channel

1. A module under `gateway/channels/` exporting `start(core, config, log)`
   that returns `{ report, stop }` and optionally `dead` and `relink`. Map the
   platform's messages to the shared payload, decide triggers, send replies.
2. An entry in `channels.KINDS` with the secrets it needs.
3. A migration relaxing the `channels.kind` check.
4. Unit tests for the payload mapping and trigger rules against the
   platform's documented shapes, as in `gateway/test/channels.test.js`.

## Adding a provider

A module under `app/providers/` with one `generate(provider, system, prompt)`
returning `(text, tokens_in, tokens_out)`, plus an entry in `providers.KINDS`
and tests with `pytest-httpx`. Most services need no new module: they speak
the OpenAI format and only need a base URL.

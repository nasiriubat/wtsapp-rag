# Setup guide

From an empty machine to a bot answering in your group. Roughly fifteen
minutes, most of it waiting for models to download.

Contents: [1 Install](#1-install) · [2 Sign in](#2-sign-in) ·
[3 Add a model provider](#3-add-a-model-provider) ·
[4 Connect a channel](#4-connect-a-channel) · [5 Choose groups](#5-choose-groups) ·
[6 Ask the first question](#6-ask-the-first-question) ·
[7 Import older history](#7-import-older-history) ·
[8 Tune a group](#8-tune-a-group) ·
[9 Change or remove a connection](#9-change-or-remove-a-connection) ·
[10 Troubleshooting](#10-troubleshooting)

---

## Before you start

| You need | Why |
|---|---|
| Docker Desktop or Docker Engine with Compose v2 | Runs all three services |
| About 3 GB of free RAM and 5 GB of disk | The embedding and reranking models run locally |
| One API key from a model provider | Writes the answers. Step 3 lists where to get one |
| A phone with WhatsApp, or a Telegram or Discord bot | The channel it listens on |

The WhatsApp channel uses an unofficial client. It may violate WhatsApp's
terms and the number can be banned. A dedicated number is safest. Your own
number works too, and your own messages are answered normally, but the risk
is then on your main account.

---

## 1 Install

```
git clone https://github.com/nasiriubat/wtsapp-rag.git
cd wtsapp-rag
cp .env.example .env
```

Fill in the four secrets in `.env`. These commands print values you can paste:

```
openssl rand -hex 16   # POSTGRES_PASSWORD
openssl rand -hex 32   # SECRET_KEY
openssl rand -hex 32   # GATEWAY_TOKEN
```

`ADMIN_PASSWORD` is the password you will type to sign in. Pick something you
can remember, or generate one and store it in a password manager.

Then start everything:

```
docker compose up -d --build
```

The first start downloads about 2.5 GB of models, which takes a few minutes.
Watch it finish with `docker compose logs -f app`, or just wait until
`http://localhost:8000/admin` answers.

**Back up `.env` somewhere separate from the database.** `SECRET_KEY` is the
only thing that can decrypt the provider keys and channel tokens inside a
database dump.

---

## 2 Sign in

Open **http://localhost:8000/admin**. The user name is `admin` and the
password is `ADMIN_PASSWORD` from `.env`. Five wrong attempts pause sign-in
for a minute.

Everything is bound to localhost. To reach the panel from another machine,
put a reverse proxy with TLS in front of it rather than publishing the port.

The wizard at **http://localhost:8000/setup** walks the same five steps this
guide does, and remembers where you are.

---

## 3 Add a model provider

The provider writes the answers. Retrieval and reranking stay on your machine,
so the only thing that leaves it is the question plus the excerpts that answer
it.

Go to **Providers → Add a provider**, or the wizard's Model step.

| Provider | Where the key comes from | Kind | Base URL | A good starting model |
|---|---|---|---|---|
| Anthropic | [console.anthropic.com/settings/keys](https://console.anthropic.com/settings/keys) | `anthropic` | leave empty | `claude-sonnet-5` |
| Google Gemini | [aistudio.google.com/apikey](https://aistudio.google.com/apikey) | `gemini` | leave empty | `gemini-3.8-flash` |
| OpenAI | [platform.openai.com/api-keys](https://platform.openai.com/api-keys) | `openai` | leave empty | `gpt-5.4-mini` |
| OpenRouter | [openrouter.ai/keys](https://openrouter.ai/keys) | `openai` | `https://openrouter.ai/api/v1` | `openai/gpt-5.4-mini` |
| Groq | [console.groq.com/keys](https://console.groq.com/keys) | `openai` | `https://api.groq.com/openai/v1` | one of their hosted models |
| Mistral | [console.mistral.ai/api-keys](https://console.mistral.ai/api-keys) | `openai` | `https://api.mistral.ai/v1` | `mistral-small-latest` |
| Together | [api.together.xyz/settings/api-keys](https://api.together.xyz/settings/api-keys) | `openai` | `https://api.together.xyz/v1` | any chat model they list |
| Ollama, on your own machine | no key; type any text | `openai` | `http://host.docker.internal:11434/v1` | whatever you have pulled |
| LiteLLM proxy | your proxy's key | `openai` | `https://your-proxy/v1` | whatever it routes |

Then:

1. **Name** is yours to choose. It appears on the Cost page.
2. **Prices** are euros per million tokens, input and output, from that
   provider's pricing page. They start at 0, which makes every answer look
   free and makes budget caps useless, so fill them in.
3. Press **Test**. It makes one real call and shows the reply or the error.
4. The first provider you add becomes the default for every group. A group can
   override it on its own page.

The eval in [EVAL.md](EVAL.md) found a small model answered a bilingual set as
accurately as a much larger one, for a twentieth of the cost. Start small.

---

## 4 Connect a channel

Go to **Channels**. Each one is independent; you can run all four.

### WhatsApp, by pairing a phone

1. On the Channels page make sure WhatsApp is **Enabled**.
2. Open **Setup → Connect WhatsApp**. A QR code appears within a few seconds.
3. On the phone: **WhatsApp → Settings → Linked devices → Link a device**, and
   scan it.
4. The page turns green and tells you how many groups that number is in.

The pairing survives restarts. It lives in `gateway/auth_state/`.

### Telegram

1. Open [@BotFather](https://t.me/BotFather) in Telegram and send `/newbot`.
   Choose a name and a username ending in `bot`. He replies with a token that
   looks like `123456:AAF...`.
2. Send `/setprivacy`, choose your bot, and select **Disable**. Without this a
   bot only sees messages that mention it, so it cannot build any memory.
3. Add the bot to the group like any other member.
4. Paste the token on the Channels page and enable it.
5. Have somebody write in the group. Telegram bots cannot list their groups,
   so a group only appears once it has spoken.

### Discord

1. Go to [discord.com/developers/applications](https://discord.com/developers/applications)
   and press **New Application**.
2. Open **Bot** in the sidebar, press **Reset Token**, and copy it.
3. On the same page, under **Privileged Gateway Intents**, turn on
   **MESSAGE CONTENT INTENT**. Without it every message arrives empty.
4. Open **OAuth2 → URL Generator**. Tick the **bot** scope, then the
   permissions **Read Messages/View Channels**, **Send Messages** and
   **Read Message History**. Copy the generated URL, open it, and invite the
   bot to your server.
5. Paste the token on the Channels page and enable it. Text channels appear as
   soon as it connects.

### WhatsApp Cloud API, Meta's official one

This one answers **private messages** on a business number: someone who is in
one of your groups can message the business number and get an answer with a
citation. It cannot watch group chats, because Meta caps Cloud API groups at 8
participants and requires an Official Business Account.

It needs a public HTTPS address, so put a reverse proxy or a tunnel in front
of the gateway's port 8080 first.

1. Go to [developers.facebook.com/apps](https://developers.facebook.com/apps)
   and create an app of type **Business**.
2. Add the **WhatsApp** product. Meta creates a test business account and a
   test number for you.
3. Open **WhatsApp → API Setup**. Copy the **Phone number ID** and press
   **Generate access token**. That token expires in 24 hours; for a permanent
   one create a System User in
   [business.facebook.com/settings](https://business.facebook.com/settings),
   give it the `whatsapp_business_messaging` permission on the app, and
   generate a token that does not expire.
4. Open **App settings → Basic** and copy the **App secret**. The assistant
   uses it to verify that a webhook really came from Meta.
5. Invent a **verify token**. It is any string you choose; Meta echoes it back
   once to prove you own the endpoint.
6. Paste all four values on the Channels page and enable the channel. The
   gateway starts listening on port 8080.
7. Back in Meta: **WhatsApp → Configuration → Webhook → Edit**. Callback URL
   is `https://your-domain/webhook/whatsapp_cloud`, the verify token is the
   one you invented. Save, then **Manage** and subscribe to the `messages`
   field.

Meta only allows a reply inside 24 hours of the person's last message, so the
assistant answers questions and does not start conversations.

---

## 5 Choose groups

Go to **Setup → Groups**, or **Groups** in the sidebar. Everything your
channels can see is listed. Tick the ones the assistant should listen to.

Only messages sent **after** you enable a group are stored. Step 7 covers
older history.

---

## 6 Ask the first question

In one of those groups, send:

```
@agent hello
```

Expect **"I don't have anything on that."** That is the correct answer: the
group has no history yet and hello is not a question. It proves the whole path
works. The Questions page will show the attempt with what it retrieved.

Three ways to get the bot's attention, all equivalent:

- start a message with a trigger word, `@agent` by default,
- mention the bot's number or username,
- reply to one of its messages.

---

## 7 Import older history

To answer about anything said before it joined:

1. On the phone, open the group, then **⋮ → More → Export chat → Without
   media**. Send the `.txt` to yourself.
2. In the panel go to **Data → Import chat history**, pick the group, upload
   the file.
3. Give the indexer a minute. The Health page shows chunks being built.

Re-uploading the same export is safe; duplicates are skipped. Answers drawn
from imported messages carry a text citation rather than a quote-reply,
because WhatsApp cannot quote a message it never saw.

---

## 8 Tune a group

Each group's page has four sections.

**Basics.** Display name, which provider answers, and whether the group is
active at all.

**Answering.** Trigger words. The confidence threshold, which defaults to 0 so
every question reaches the model and the model decides whether it can answer;
raising it saves provider calls but the eval found it refuses real questions.
The refusal text, and the answer language, where `auto` follows the question.

**Memory.** Decision tracking mines each new chunk for decisions so answers can
say what changed and when; it costs one small model call per chunk. Private
questions let members of this group message the bot directly. The correction
acknowledgement is what it replies when somebody corrects it.

**Limits and privacy.** A monthly euro cap for this group, a retention window
in days, opted-out members whose history is erased when you save, and quiet
hours during which it stays silent.

---

## 9 Change or remove a connection

**Change the WhatsApp number.** Channels → WhatsApp → **Link a different
number**. The gateway logs out, clears the old pairing and shows a fresh QR at
Setup → Connect WhatsApp. Nothing in the database is touched, so old messages
and answers stay. Groups stay enabled, but their ids belong to the old
account's view of them: if the new number is not in the same groups, enable
the right ones again on the Groups page.

**The number was banned.** Same flow, plus a new phone and number. If the
gateway cannot start at all, stop it, delete the contents of
`gateway/auth_state/`, start it, and scan again.

**Remove Telegram, Discord or the Cloud API.** Channels → **Remove**. The
token is deleted and the gateway stops that channel within 30 seconds. Their
groups stay in the database; delete them from the Groups page if you want
them gone. WhatsApp cannot be removed, only disabled, because it is the
channel the panel's linking flow belongs to.

**Rotate a token without downtime.** Paste the new one over the old one on the
Channels page. Blank fields keep what is stored, so you only retype what
changed.

**Delete a group's data.** Groups → the group → **Remove group** stops it
being used. To erase what was said, use Data → **Erase a member** for one
person, or set a retention window so everything ages out.

---

## 10 Troubleshooting

| What you see | What to check |
|---|---|
| No reply at all | Channels page: is the channel connected? Then Questions: did the question arrive? If not, the trigger did not fire. Check the group is enabled and the trigger word matches. |
| "I don't have anything on that" for everything | The group has no history yet. Import the chat export, or wait for the conversation to be chunked, which happens after a 30-minute gap. |
| "No LLM provider is configured" | Providers page: add one, or the group points at a disabled provider. |
| "The monthly answer budget is used up" | Cost page, or the group's own cap. |
| The QR never appears | `docker compose logs gateway`. The gateway needs the app to be up first; it retries every five seconds. |
| Telegram bot sees nothing | `/setprivacy` → Disable in BotFather, then remove and re-add the bot to the group. |
| Discord messages arrive empty | MESSAGE CONTENT INTENT is off in the developer portal. |
| Meta rejects the webhook | It must be HTTPS and publicly reachable, and the verify token must match exactly. |
| Answers are slow | Health page shows the median. The local reranker is the bottleneck when several questions arrive at once; see [EVAL.md](EVAL.md). |
| Something else | [OPERATIONS.md](OPERATIONS.md) has the runbook: logs, backups, restore, rotating secrets. |

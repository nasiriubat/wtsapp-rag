# Operations

Everything here has been run against a real instance. Commands assume the
repository root and `docker compose`.

## Daily life

```
docker compose ps                  # what is up
docker compose logs -f app         # JSON lines, one object per event
docker compose logs -f gateway     # channel connections and every message seen
curl -s localhost:8000/health      # {"db": "ok", "loops": "ok"}; 503 when either is not
curl -s -H "authorization: Bearer $GATEWAY_TOKEN" localhost:8000/health   # plus backlog and stalled loops
curl -s -H "authorization: Bearer $GATEWAY_TOKEN" localhost:8000/metrics  # Prometheus text: ingest, answers, latency
```

The admin panel's Health page shows the same figures plus spend and disk.

## Backup

The database holds everything: messages, chunks, facts, settings, and the
provider keys and channel tokens encrypted with `SECRET_KEY`. **A dump is the
plain text of every conversation the assistant has logged.** It is personal
data and inherits whatever retention and access rules the chats themselves
have; a dump left in a home directory is the easiest way to lose it all.

Encrypt it on the way out. [age](https://age-encryption.org) is one small
tool that does nothing else:

```
docker compose exec -T db pg_dump -U assistant -Fc assistant \
  | age -r age1yourpublickey... > backup-$(date +%F).dump.age
```

Then put it somewhere that is not this machine, and delete copies older than
you need. A nightly line in cron or a systemd timer does the job:

```
0 3 * * * cd /srv/wtsap-rag && docker compose exec -T db pg_dump -U assistant -Fc assistant | age -r age1... > /backups/assistant-$(date +\%F).dump.age && find /backups -name 'assistant-*.age' -mtime +30 -delete
```

**Back up `.env` with it, in a different place.** A dump without `SECRET_KEY`
restores the rows but no key or token in it can be decrypted. Keep `.env`
readable by you alone (`chmod 600 .env`), and the same for
`gateway/auth_state/`, which is a live WhatsApp session.

The `gateway/auth_state/` directory holds the WhatsApp pairing. Losing it
means scanning a new QR, nothing worse.

## Restore

Rehearsed on 4 Sept 2026 with a 48 KB dump: row counts matched and an
encrypted provider key decrypted afterwards with the same `SECRET_KEY`.

```
docker compose up -d db
docker compose exec -T db psql -U assistant -d postgres -c "DROP DATABASE IF EXISTS assistant"
docker compose exec -T db psql -U assistant -d postgres -c "CREATE DATABASE assistant"
age -d -i key.txt backup-2026-09-04.dump.age | docker compose exec -T db pg_restore -U assistant -d assistant --no-owner
docker compose up -d
```

Check it took:

```
docker compose exec -T db psql -U assistant -d assistant \
  -c "SELECT count(*) FROM messages" -c "SELECT version FROM schema_migrations ORDER BY version"
```

## Upgrade

```
git pull
docker compose up -d --build
docker compose logs -f app | grep applied     # migrations run at startup
```

Migrations are numbered files under `app/migrations/`, applied once and
recorded in `schema_migrations`. There is no down migration: restore from a
dump to go back.

**Upgrading from v1.0.** The app image no longer runs as root, and the models
volume it created as root is not writable by the new user. Once, before the
first start of the new image:

```
docker compose run --rm --user root --no-deps --entrypoint sh app -c "chown -R app:app /models"
```

The same applies to `gateway/auth_state/` and `gateway/data/` on a Linux
host: `chown -R 1000:1000` them once. v1.1 also switches to a smaller
reranker; the old model directories under the volume can be deleted
(`models--EmbeddedLLM--*`, `models--BAAI--*`, about 3.3 GB).

## Rotate secrets

- **Provider key or channel token:** paste the new one on the Providers or
  Channels page. The old value is overwritten; nothing else changes.
- **`ADMIN_PASSWORD`:** edit `.env`, `docker compose up -d app`. Every
  session is logged out at once, yours included; that is the point.
- **`GATEWAY_TOKEN`:** edit `.env`, then restart both services together, or
  the gateway will be rejected until it restarts.
- **`SECRET_KEY`:** this one is not a simple swap. It decrypts every stored
  provider key and channel token. Change it only with an empty providers and
  channels table, or re-enter every secret afterwards.

## The WhatsApp number is banned

It happens; the README says so up front. The database is untouched, so:

1. Get a new number and a new phone.
2. `docker compose stop gateway && rm -rf gateway/auth_state/*`
3. `docker compose start gateway`, open `/setup/link`, scan the new QR.
4. Enable the groups again on the Groups page. Old history stays; new
   messages carry the new number's ids.

## The bot answers nothing

In order:

1. `/health` — is the database up, is the unchunked backlog growing?
2. Channels page — is the channel connected? If the gateway has not reported,
   check `docker compose logs gateway`.
3. Questions page — do questions arrive at all? An outcome of `budget` means
   the monthly cap is spent; `no_provider` means no provider is configured or
   the pinned one is disabled.
4. Providers page — press Test. It makes one real call and shows the error.
5. Group page — quiet hours, opt-out, and the confidence threshold all make
   the bot silent or refusing on purpose.

## The bot answers badly

Read the Questions page. Expand a row to see the chunks it retrieved with
their scores. Then:

- The right conversation was not retrieved: a retrieval problem. Check the
  chunk it did pick; re-embed the group from the Data page after a chunking
  change.
- The right conversation was retrieved but the answer is wrong: mark it with
  **Wrong** and a note. Those rows are the eval set.
- The answer is out of date: reply to it in the group with "wrong, it's X".
  That stores a correction that outranks what the answer was built on.

Measure before and after with `scripts/eval.py`; see `docs/EVAL.md`.

## Costs

The Cost page breaks the month down by provider and by group and enforces the
caps. Every answer, refusal and fact-extraction call is a row in `query_log`
with its tokens and cost. Extraction runs one small call per new chunk; turn
it off per group with "Track decisions" if a group is chatty and dull.

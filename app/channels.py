"""Channel rows: which messaging platforms the gateway runs, and their tokens."""

import json
import os

import db

KINDS = ("whatsapp", "telegram", "discord")
NEEDS_TOKEN = {"telegram", "discord"}


def _key():
    return os.environ["SECRET_KEY"]


def list_all(with_config=False):
    """Rows for the admin (token masked) or for the gateway (decrypted)."""
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT kind, enabled, updated_at, config IS NOT NULL AS configured, "
            "pgp_sym_decrypt(config, %s) AS config FROM channels ORDER BY kind",
            (_key(),),
        ).fetchall()
    out = []
    for r in rows:
        config = json.loads(r["config"]) if r["config"] else {}
        out.append({**r, "config": config if with_config else {k: "***" for k in config}})
    return out


def get(kind):
    return next((c for c in list_all(with_config=True) if c["kind"] == kind), None)


def upsert(kind, config=None, enabled=True):
    if kind not in KINDS:
        raise ValueError(f"unknown channel kind {kind!r}")
    # config=None keeps the stored token, so enable/disable does not need it.
    if kind in NEEDS_TOKEN and config is None and get(kind) is None:
        raise ValueError(f"{kind} needs a bot token")
    if kind in NEEDS_TOKEN and config is not None and not config.get("token"):
        raise ValueError(f"{kind} needs a bot token")
    with db.connect() as conn:
        conn.execute(
            """
            INSERT INTO channels (kind, config, enabled, updated_at)
            VALUES (%s, pgp_sym_encrypt(%s, %s), %s, now())
            ON CONFLICT (kind) DO UPDATE
              SET config = coalesce(EXCLUDED.config, channels.config),
                  enabled = EXCLUDED.enabled, updated_at = now()
            """,
            (kind, json.dumps(config) if config is not None else None, _key(), enabled),
        )
    return get(kind)


def set_enabled(kind, enabled):
    with db.connect() as conn:
        conn.execute("UPDATE channels SET enabled = %s, updated_at = now() WHERE kind = %s", (enabled, kind))
    return get(kind)


def delete(kind):
    with db.connect() as conn:
        conn.execute("DELETE FROM channels WHERE kind = %s AND kind <> 'whatsapp'", (kind,))

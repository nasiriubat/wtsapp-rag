"""Channel rows: which messaging platforms the gateway runs, and their tokens."""

import json

import audit
import db

# One table of kinds. `token`: needs a bot token. `pairs`: pairs with a phone
# and can be asked to pair again.
KINDS = {
    "whatsapp": {"token": False, "pairs": True},
    "telegram": {"token": True, "pairs": False},
    "discord": {"token": True, "pairs": False},
}
_SELECT = "kind, enabled, updated_at, config IS NOT NULL AS configured, pgp_sym_decrypt(config, %s) AS config"


def _row(r, with_config):
    config = json.loads(r["config"]) if r["config"] else {}
    return {**r, "config": config if with_config else audit.redact(config)}


def list_all(with_config=False):
    """Rows for the admin (token masked) or for the gateway (decrypted)."""
    with db.connect() as conn:
        rows = conn.execute(f"SELECT {_SELECT} FROM channels ORDER BY kind", (db.secret_key(),)).fetchall()
    return [_row(r, with_config) for r in rows]


def get(kind):
    with db.connect() as conn:
        row = conn.execute(
            f"SELECT {_SELECT} FROM channels WHERE kind = %s", (db.secret_key(), kind)
        ).fetchone()
    return _row(row, True) if row else None


def upsert(kind, config=None, enabled=True):
    """config=None keeps the stored token, so enable/disable does not need it."""
    if kind not in KINDS:
        raise ValueError(f"unknown channel kind {kind!r}")
    has_token = config.get("token") if config is not None else get(kind) is not None
    if KINDS[kind]["token"] and not has_token:
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
            (kind, json.dumps(config) if config is not None else None, db.secret_key(), enabled),
        )


def delete(kind):
    with db.connect() as conn:
        conn.execute("DELETE FROM channels WHERE kind = %s AND kind <> 'whatsapp'", (kind,))

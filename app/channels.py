"""Channel rows: which messaging platforms the gateway runs, and their secrets."""

import json

import audit
import db

# One table of kinds. `fields` are the secrets the admin must supply, `pairs`
# means it links to a phone and can be asked to pair again, `dm_only` means it
# answers private messages rather than watching groups.
KINDS = {
    "whatsapp": {"fields": (), "pairs": True, "dm_only": False},
    "telegram": {"fields": ("token",), "pairs": False, "dm_only": False},
    "discord": {"fields": ("token",), "pairs": False, "dm_only": False},
    "whatsapp_cloud": {
        "fields": ("token", "phone_number_id", "verify_token", "app_secret"),
        "pairs": False,
        "dm_only": True,
    },
}
_SELECT = "kind, enabled, updated_at, config IS NOT NULL AS configured, pgp_sym_decrypt(config, %s) AS config"


def _row(r, with_config):
    config = json.loads(r["config"]) if r["config"] else {}
    return {**r, "config": config if with_config else audit.redact(config)}


def list_all(with_config=False):
    """Rows for the admin (secrets masked) or for the gateway (decrypted)."""
    with db.connect() as conn:
        rows = conn.execute(f"SELECT {_SELECT} FROM channels ORDER BY kind", (db.secret_key(),)).fetchall()
    return [_row(r, with_config) for r in rows]


def get(kind):
    with db.connect() as conn:
        row = conn.execute(
            f"SELECT {_SELECT} FROM channels WHERE kind = %s", (db.secret_key(), kind)
        ).fetchone()
    return _row(row, True) if row else None


def missing(kind, config):
    return [f for f in KINDS[kind]["fields"] if not (config or {}).get(f)]


def upsert(kind, config=None, enabled=True):
    """`config` is merged into what is stored, so an unchanged secret can be
    left blank and enable/disable needs no secrets at all."""
    if kind not in KINDS:
        raise ValueError(f"unknown channel kind {kind!r}")
    current = get(kind)
    merged = {**(current["config"] if current else {}), **(config or {})}
    if gaps := missing(kind, merged):
        raise ValueError(f"{kind} needs {', '.join(gaps)}")
    with db.connect() as conn:
        conn.execute(
            """
            INSERT INTO channels (kind, config, enabled, updated_at)
            VALUES (%s, pgp_sym_encrypt(%s, %s), %s, now())
            ON CONFLICT (kind) DO UPDATE
              SET config = EXCLUDED.config, enabled = EXCLUDED.enabled, updated_at = now()
            """,
            (kind, json.dumps(merged), db.secret_key(), enabled),
        )


def delete(kind):
    with db.connect() as conn:
        conn.execute("DELETE FROM channels WHERE kind = %s AND kind <> 'whatsapp'", (kind,))

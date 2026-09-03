"""LLM providers: stored encrypted in Postgres, one function shape for all kinds."""

import json
import os
from decimal import Decimal

import db

from . import anthropic, gemini, openai_compat

KINDS = {"anthropic": anthropic, "gemini": gemini, "openai": openai_compat}

_COLUMNS = "id, name, kind, base_url, model, price_in, price_out, options, enabled, created_at"


def _key():
    return os.environ["SECRET_KEY"]


def get(provider_id):
    """Full row including the decrypted key. Never return this to a browser."""
    with db.connect() as conn:
        return conn.execute(
            f"SELECT {_COLUMNS}, pgp_sym_decrypt(api_key, %s) AS api_key FROM providers WHERE id = %s",
            (_key(), provider_id),
        ).fetchone()


def list_all():
    """Rows without keys, for the admin."""
    with db.connect() as conn:
        return conn.execute(f"SELECT {_COLUMNS} FROM providers ORDER BY id").fetchall()


def create(name, kind, api_key, model, base_url=None, price_in=0, price_out=0, options=None, enabled=True):
    if kind not in KINDS:
        raise ValueError(f"unknown provider kind {kind!r}")
    with db.connect() as conn:
        return conn.execute(
            f"""
            INSERT INTO providers
              (name, kind, base_url, api_key, model, price_in, price_out, options, enabled)
            VALUES (%s, %s, %s, pgp_sym_encrypt(%s, %s), %s, %s, %s, %s, %s)
            RETURNING {_COLUMNS}
            """,
            (
                name,
                kind,
                base_url,
                api_key,
                _key(),
                model,
                price_in,
                price_out,
                json.dumps(options or {}),
                enabled,
            ),
        ).fetchone()


def update(provider_id, **fields):
    sets, params = [], []
    for k, v in fields.items():
        if k == "api_key":
            sets.append("api_key = pgp_sym_encrypt(%s, %s)")
            params += [v, _key()]
        elif k == "options":
            sets.append("options = %s")
            params.append(json.dumps(v))
        else:
            sets.append(f"{k} = %s")
            params.append(v)
    with db.connect() as conn:
        return conn.execute(
            f"UPDATE providers SET {', '.join(sets)} WHERE id = %s RETURNING {_COLUMNS}",
            (*params, provider_id),
        ).fetchone()


def delete(provider_id):
    with db.connect() as conn:
        conn.execute("DELETE FROM providers WHERE id = %s", (provider_id,))


def resolve(group, global_settings):
    """The first enabled provider of: the group's own, then the global default.
    A disabled pin falls back instead of blocking the group."""
    for provider_id in (group["provider_id"], global_settings["default_provider_id"]):
        if provider_id is None:
            continue
        provider = get(provider_id)
        if provider and provider["enabled"]:
            return provider
    return None


def generate(provider, system, prompt):
    return KINDS[provider["kind"]].generate(provider, system, prompt)


def cost(provider, tokens_in, tokens_out):
    per_million = Decimal(tokens_in) * Decimal(provider["price_in"]) + Decimal(tokens_out) * Decimal(
        provider["price_out"]
    )
    return per_million / Decimal(1_000_000)


def check(provider):
    """One tiny real call. Used by the admin's test button."""
    text, _, _ = generate(provider, "Reply with the single word OK.", "ping")
    return text

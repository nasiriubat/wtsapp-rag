"""Carry a v0.1 install forward, and repair a config that cannot answer.

v0.1 configured everything in .env; v1 keeps that in Postgres. On first start
with an empty database, the old variables become rows. After that they are
ignored."""

import logging
import os

import groups
import providers

log = logging.getLogger(__name__)

# (env var, name, kind, model, base_url env var). Prices stay 0 until the admin
# fills them in; model names are today's cheap defaults and can be changed.
SEEDS = [
    ("ANTHROPIC_API_KEY", "Claude (from .env)", "anthropic", "claude-opus-5", None),
    ("CLAUDE_API_KEY", "Claude (from .env)", "anthropic", "claude-opus-5", None),
    ("GEMINI_API_KEY", "Gemini (from .env)", "gemini", "gemini-3.8-flash", None),
    ("OPENAI_API_KEY", "OpenAI (from .env)", "openai", "gpt-5.4-mini", None),
    ("OPENROUTER_API_KEY", "OpenRouter (from .env)", "openai", "openai/gpt-5.4-mini", "OPENROUTER_BASE_URL"),
]


def ensure_default(prefer=None):
    """The global default has to name a provider that exists and is enabled.
    When it does not, every question is refused with "no provider is configured",
    which reads like a missing key rather than a deleted or disabled row. Adopt
    another provider instead, and say so. `prefer` is the one just added."""
    current = groups.global_settings()["default_provider_id"]
    if current is not None:
        row = providers.get(current)
        if row is not None and row["enabled"]:
            return row
    enabled = [p for p in providers.list_all() if p["enabled"]]
    chosen = next((p for p in enabled if p["id"] == prefer), None) or (enabled[0] if enabled else None)
    if chosen is None and current is None:
        return None
    groups.set_global(default_provider_id=chosen["id"] if chosen else None)
    log.warning(
        "the default provider was missing; adopted another",
        extra={"provider": chosen["name"] if chosen else None},
    )
    return chosen


def run():
    env = os.environ
    if not providers.list_all():
        seeded = set()
        for var, name, kind, model, base_var in SEEDS:
            if not env.get(var) or name in seeded:
                continue
            seeded.add(name)
            base_url = env.get(base_var) if base_var else None
            if base_var and not base_url:
                base_url = "https://openrouter.ai/api/v1"
            p = providers.create(name, kind, env[var], model, base_url=base_url)
            if groups.global_settings()["default_provider_id"] is None:
                groups.set_global(default_provider_id=p["id"])
            log.info("bootstrapped provider from env; set its prices in the admin", extra={"provider": name})
    if env.get("GROUP_JID") and not groups.list_all():
        settings = {}
        if env.get("TRIGGERS"):
            settings["triggers"] = [t.strip() for t in env["TRIGGERS"].split(",") if t.strip()]
        if env.get("CONFIDENCE_THRESHOLD"):
            settings["confidence_threshold"] = float(env["CONFIDENCE_THRESHOLD"])
        groups.create("whatsapp", env["GROUP_JID"], settings=settings)
        log.info("bootstrapped group from GROUP_JID", extra={"group": env["GROUP_JID"]})
    ensure_default()

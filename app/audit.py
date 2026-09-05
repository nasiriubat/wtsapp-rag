import json

import db

SECRET_KEYS = {"api_key", "token", "app_secret", "verify_token"}


def redact(value):
    """Secrets can sit at any depth: provider options are an open dict."""
    if isinstance(value, dict):
        return {k: ("***" if k in SECRET_KEYS else redact(v)) for k, v in value.items()}
    if isinstance(value, list):
        return [redact(v) for v in value]
    return value


def log(action, target, detail=None):
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO audit_log (actor, action, target, detail) VALUES (%s, %s, %s, %s)",
            (
                "admin",
                action,
                target,
                json.dumps(redact(detail), default=str) if detail is not None else None,
            ),
        )

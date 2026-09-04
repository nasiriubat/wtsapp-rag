import json

import db

SECRET_KEYS = {"api_key", "token", "app_secret", "verify_token"}


def redact(detail):
    return {k: ("***" if k in SECRET_KEYS else v) for k, v in detail.items()}


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

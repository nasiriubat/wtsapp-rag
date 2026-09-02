"""Groups and their settings. Defaults live here, overrides in groups.settings."""

import json
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field

import db

REFUSAL = "I don't have anything on that."


class Settings(BaseModel):
    triggers: list[str] = ["@agent"]
    confidence_threshold: float = Field(0.1, ge=0, le=1)
    refusal_text: str = REFUSAL
    answer_language: str = "auto"  # or a language name the model understands
    retention_days: int | None = Field(None, ge=1)
    opt_out: list[str] = []  # sender ids whose messages are never stored
    quiet_hours: dict | None = None  # {"start": "22:00", "end": "07:00", "tz": "Europe/Helsinki"}
    monthly_cap_eur: float | None = Field(None, ge=0)


class GlobalSettings(BaseModel):
    default_provider_id: int | None = None
    monthly_cap_eur: float | None = Field(None, ge=0)


def in_quiet_hours(settings, now=None):
    q = settings["quiet_hours"]
    if not q:
        return False
    tz = ZoneInfo(q.get("tz", "UTC"))
    local = (now or datetime.now(UTC)).astimezone(tz).strftime("%H:%M")
    start, end = q["start"], q["end"]
    # A window like 22:00 to 07:00 wraps past midnight.
    return start <= local < end if start <= end else local >= start or local < end


def _merge(row):
    if row is None:
        return None
    return {**row, "settings": Settings(**row["settings"]).model_dump()}


def get(external_id):
    with db.connect() as conn:
        return _merge(conn.execute("SELECT * FROM groups WHERE external_id = %s", (external_id,)).fetchone())


def get_by_id(group_id):
    with db.connect() as conn:
        return _merge(conn.execute("SELECT * FROM groups WHERE id = %s", (group_id,)).fetchone())


def list_all():
    with db.connect() as conn:
        return [_merge(r) for r in conn.execute("SELECT * FROM groups ORDER BY id").fetchall()]


def create(channel, external_id, name=None, settings=None, provider_id=None, enabled=True):
    s = Settings(**(settings or {})).model_dump()
    with db.connect() as conn:
        return _merge(
            conn.execute(
                """
                INSERT INTO groups (channel, external_id, name, enabled, provider_id, settings)
                VALUES (%s, %s, %s, %s, %s, %s) RETURNING *
                """,
                (channel, external_id, name, enabled, provider_id, json.dumps(s)),
            ).fetchone()
        )


def update(group_id, **fields):
    if "settings" in fields:
        fields["settings"] = json.dumps(Settings(**fields["settings"]).model_dump())
    assignments = ", ".join(f"{k} = %s" for k in fields)
    with db.connect() as conn:
        return _merge(
            conn.execute(
                f"UPDATE groups SET {assignments} WHERE id = %s RETURNING *",
                (*fields.values(), group_id),
            ).fetchone()
        )


def delete(group_id):
    with db.connect() as conn:
        conn.execute("DELETE FROM groups WHERE id = %s", (group_id,))


def global_settings():
    with db.connect() as conn:
        rows = conn.execute("SELECT key, value FROM settings").fetchall()
    return GlobalSettings(**{r["key"]: r["value"] for r in rows}).model_dump()


def set_global(**values):
    clean = GlobalSettings(**{**global_settings(), **values}).model_dump()
    with db.connect() as conn:
        for key, value in clean.items():
            conn.execute(
                "INSERT INTO settings (key, value) VALUES (%s, %s) "
                "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value",
                (key, json.dumps(value)),
            )
    return clean

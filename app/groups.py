"""Groups and their settings. Defaults live here, overrides in groups.settings."""

import json
import re
import time
from datetime import UTC, datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, Field, field_validator

import db
import retention

REFUSAL = "I don't have anything on that."


class QuietHours(BaseModel):
    start: str
    end: str
    tz: str = "UTC"

    @field_validator("start", "end")
    @classmethod
    def _hhmm(cls, v):
        if not re.fullmatch(r"\d{2}:\d{2}", v):
            raise ValueError("use HH:MM")
        return v

    @field_validator("tz")
    @classmethod
    def _known_zone(cls, v):
        try:
            ZoneInfo(v)
        except (ZoneInfoNotFoundError, ValueError) as e:
            raise ValueError(f"unknown time zone {v!r}; use an IANA name like Europe/Helsinki") from e
        return v


class Settings(BaseModel):
    triggers: list[str] = ["@agent"]
    # 0 means every question reaches the model, which decides whether the
    # excerpts answer it. The reranker's score is not comparable across
    # languages, so gating on it refused 44% of answerable questions in the
    # eval; raise this only to save provider calls. See docs/EVAL.md.
    confidence_threshold: float = Field(0.0, ge=0, le=1)
    refusal_text: str = REFUSAL
    answer_language: str = "auto"  # or a language name the model understands
    retention_days: int | None = Field(None, ge=1)
    opt_out: list[str] = []  # sender ids whose messages are erased and never stored again
    quiet_hours: QuietHours | None = None
    monthly_cap_eur: float | None = Field(None, ge=0)  # calendar month, UTC
    decision_tracking: bool = True  # extract decisions from chunks; one small provider call per chunk
    # Files shared in the chat become searchable knowledge. Off by default: it
    # makes the gateway download media, which is the behaviour most likely to
    # get a WhatsApp number flagged, and every image costs one model call.
    index_files: bool = False
    allow_dm: bool = True  # members may ask the bot privately about this group
    correction_ack: str = "Noted, I'll go with that from now on."


class GlobalSettings(BaseModel):
    default_provider_id: int | None = None
    # A fresh install fails safe: one member looping the bot cannot run up an
    # open-ended bill. The admin raises or clears it on the Cost page.
    monthly_cap_eur: float | None = Field(10.0, ge=0)


def in_quiet_hours(settings, now=None):
    q = settings["quiet_hours"]
    if not q:
        return False
    local = (now or datetime.now(UTC)).astimezone(ZoneInfo(q["tz"])).strftime("%H:%M")
    start, end = q["start"], q["end"]
    # A window like 22:00 to 07:00 wraps past midnight.
    return start <= local < end if start <= end else local >= start or local < end


def _merge(row):
    if row is None:
        return None
    return {**row, "settings": Settings(**row["settings"]).model_dump()}


def _one(sql, params):
    with db.connect() as conn:
        return _merge(conn.execute(sql, params).fetchone())


def get(external_id):
    return _one("SELECT * FROM groups WHERE external_id = %s", (external_id,))


def get_by_id(group_id):
    return _one("SELECT * FROM groups WHERE id = %s", (group_id,))


def list_all():
    with db.connect() as conn:
        return [_merge(r) for r in conn.execute("SELECT * FROM groups ORDER BY id").fetchall()]


def create(channel, external_id, name=None, settings=None, provider_id=None, enabled=True):
    s = Settings(**(settings or {})).model_dump()
    return _one(
        """
        INSERT INTO groups (channel, external_id, name, enabled, provider_id, settings)
        VALUES (%s, %s, %s, %s, %s, %s) RETURNING *
        """,
        (channel, external_id.strip(), name, enabled, provider_id, json.dumps(s)),
    )


def update(group_id, **fields):
    if "settings" in fields:
        fields["settings"] = json.dumps(Settings(**fields["settings"]).model_dump())
    assignments = ", ".join(f"{k} = %s" for k in fields)
    return _one(f"UPDATE groups SET {assignments} WHERE id = %s RETURNING *", (*fields.values(), group_id))


def apply(group_id, **fields):
    """Update a group and honour what the change implies. Opting a member out
    is an erasure, not just a filter on new messages. Returns (row, purged)."""
    before = get_by_id(group_id)
    if before is None:
        return None, []
    row = update(group_id, **fields)
    if row is None:
        return None, []
    purged = []
    for sender in set(row["settings"]["opt_out"]) - set(before["settings"]["opt_out"]):
        purged.append((sender, retention.purge_sender(row["external_id"], sender)))
    return row, purged


def delete(group_id):
    """The group and everything it produced. Orphaned rows would otherwise
    outlive the retention window forever, because retention joins on groups.
    Returns the counts, or None when there was no such group."""
    row = get_by_id(group_id)
    if row is None:
        return None
    counts = retention.purge_group(row["external_id"])
    with db.connect() as conn:
        conn.execute("DELETE FROM groups WHERE id = %s", (group_id,))
    return counts


def dm_candidates(sender_jid, reported_members):
    """Groups a private question may be answered from: enabled, DMs allowed,
    and the sender is a member. Where the channel can list members that list
    decides, so someone who has left cannot keep asking. Where it cannot
    (Telegram, Discord), having written there is the evidence we have."""
    with db.connect() as conn:
        wrote = {
            r["group_id"]
            for r in conn.execute(
                "SELECT DISTINCT group_id FROM messages WHERE sender_jid = %s", (sender_jid,)
            )
        }

    def member_of(g):
        listed = reported_members.get(g["external_id"])
        if listed is not None:
            return sender_jid in listed
        # WhatsApp can list members. No list yet means the gateway has not
        # reported this group, and until it does nobody is a member of it.
        if g["channel"] == "whatsapp":
            return False
        return g["external_id"] in wrote

    # A private question is still a question from this group: opting out and
    # quiet hours silence it here too.
    return [
        g
        for g in list_all()
        if g["enabled"]
        and g["settings"]["allow_dm"]
        and sender_jid not in g["settings"]["opt_out"]
        and not in_quiet_hours(g["settings"])
        and member_of(g)
    ]


# Global settings change a few times a year and are read on every question
# and every extraction tick. A short memo, dropped on every write.
_settings_memo = {"at": 0.0, "value": None}
MEMO_SECONDS = 30


def global_settings():
    now = time.monotonic()
    if _settings_memo["value"] is not None and now - _settings_memo["at"] < MEMO_SECONDS:
        return dict(_settings_memo["value"])
    with db.connect() as conn:
        rows = conn.execute("SELECT key, value FROM settings").fetchall()
    value = GlobalSettings(**{r["key"]: r["value"] for r in rows}).model_dump()
    _settings_memo.update(at=now, value=value)
    return dict(value)


def forget_settings():
    _settings_memo.update(at=0.0, value=None)


def set_global(**values):
    forget_settings()
    clean = GlobalSettings(**{**global_settings(), **values}).model_dump()
    with db.connect() as conn:
        for key in values:
            conn.execute(
                "INSERT INTO settings (key, value) VALUES (%s, %s) "
                "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value",
                (key, json.dumps(clean[key])),
            )
    forget_settings()
    return clean

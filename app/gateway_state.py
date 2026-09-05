"""What each channel of the gateway last told us: connection, QR, the groups
it can see, and whether the admin asked it to pair again. In memory on
purpose; the gateway re-reports every 30 s. The one thing that is kept is
who is in each group, because a private question is answered on it."""

import time

import segno

import channels
import db


def _blank():
    return {
        "connected": False,
        "jid": None,
        "qr": None,
        "qr_svg": None,
        "groups": [],
        "reported_at": None,
        "relink": False,
    }


_state = {kind: _blank() for kind in channels.KINDS}


def update(channel, **fields):
    s = _state[channel]
    if "qr" in fields and fields["qr"] != s["qr"]:
        # Rendered once per QR, not once per 3-second poll of the wizard page.
        fields["qr_svg"] = segno.make(fields["qr"], error="m").svg_inline(scale=4) if fields["qr"] else None
    s.update(fields, reported_at=time.time())
    if "groups" in fields:
        _remember_members(channel, fields["groups"])


def _remember_members(channel, groups):
    """A report is authoritative for its channel: a group it no longer lists
    was left, and a group listed with nobody in it is one nobody may ask about."""
    listed = [g for g in groups if g.get("members")]
    with db.connect() as conn, conn.transaction():
        conn.execute(
            "DELETE FROM gateway_members WHERE channel = %s AND group_id <> ALL(%s)",
            (channel, [g["id"] for g in listed]),
        )
        for g in listed:
            conn.execute(
                "INSERT INTO gateway_members (group_id, channel, members) VALUES (%s, %s, %s) "
                "ON CONFLICT (group_id) DO UPDATE SET channel = excluded.channel, "
                "members = excluded.members, reported_at = now()",
                (g["id"], channel, list(g["members"])),
            )


def request_relink(channel):
    _state[channel]["relink"] = True


def take_relink():
    """One-shot: the channels asked to pair again, cleared on hand-out."""
    kinds = [k for k, s in _state.items() if s["relink"]]
    for k in kinds:
        _state[k]["relink"] = False
    return kinds


def get(channel):
    return dict(_state[channel])


def all_channels():
    return {k: dict(v) for k, v in _state.items()}


def any_reported():
    return any(s["reported_at"] for s in _state.values())


def seen_groups():
    """Every group any channel can see, tagged with its channel, for the pickers."""
    return [{**g, "channel": kind} for kind, s in _state.items() for g in s["groups"]]


def members():
    """external id -> set of member ids, for channels that can list them. Read
    from the database, so it survives a restart."""
    with db.connect() as conn:
        rows = conn.execute("SELECT group_id, members FROM gateway_members").fetchall()
    return {r["group_id"]: set(r["members"]) for r in rows}

"""What each channel of the gateway last told us: connection, QR, the groups
it can see, and whether the admin asked it to pair again. In memory on
purpose; the gateway re-reports every 30 s."""

import time

import segno

import channels


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

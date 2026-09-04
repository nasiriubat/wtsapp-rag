"""What each channel of the gateway last told us: connection, QR, the groups
it can see. In memory on purpose; the gateway re-reports every 30 s."""

import time

import segno

import channels


def _blank():
    return {"connected": False, "jid": None, "qr": None, "qr_svg": None, "groups": [], "reported_at": None}


_state = {kind: _blank() for kind in channels.KINDS}
_relink = False


def update(channel="whatsapp", **fields):
    s = _state.setdefault(channel, _blank())
    if "qr" in fields and fields["qr"] != s["qr"]:
        # Rendered once per QR, not once per 3-second poll of the wizard page.
        fields["qr_svg"] = segno.make(fields["qr"], error="m").svg_inline(scale=4) if fields["qr"] else None
    s.update(fields, reported_at=time.time())


def request_relink():
    global _relink
    _relink = True


def take_relink():
    """One-shot: true once, for the gateway that fetches it."""
    global _relink
    flag, _relink = _relink, False
    return flag


def relink_pending():
    return _relink


def get(channel="whatsapp"):
    return dict(_state.setdefault(channel, _blank()))


def all_channels():
    return {k: dict(v) for k, v in _state.items()}


def seen_groups():
    """Every group any channel can see, tagged with its channel, for the pickers."""
    return [{**g, "channel": kind} for kind, s in _state.items() for g in s["groups"]]

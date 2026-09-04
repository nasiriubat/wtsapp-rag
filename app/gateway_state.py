"""What the gateway last told us: connection, QR, the groups it can see.
In memory on purpose; the gateway re-reports on connect and every 30 s."""

import time

import segno

_state = {
    "connected": False,
    "jid": None,
    "qr": None,
    "qr_svg": None,
    "groups": [],
    "reported_at": None,
    "relink": False,
}


def update(**fields):
    if fields.get("qr") != _state["qr"]:
        # Rendered once per QR, not once per 3-second poll of the wizard page.
        fields["qr_svg"] = (
            segno.make(fields["qr"], error="m").svg_inline(scale=4) if fields.get("qr") else None
        )
    _state.update(fields, reported_at=time.time())


def request_relink():
    _state["relink"] = True


def take_relink():
    """One-shot: true once, for the gateway that fetches it."""
    flag, _state["relink"] = _state["relink"], False
    return flag


def get():
    return dict(_state)

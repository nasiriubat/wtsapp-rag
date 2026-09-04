"""What the gateway last told us: connection, QR, the groups it can see.
In memory on purpose; the gateway re-reports on connect and every 30 s."""

import time

_state = {"connected": False, "jid": None, "qr": None, "groups": [], "reported_at": None, "relink": False}


def update(**fields):
    _state.update(fields, reported_at=time.time())
    if fields.get("qr"):
        # A fresh QR means the relink the admin asked for has happened.
        _state["relink"] = False


def request_relink():
    _state["relink"] = True


def get():
    return dict(_state)

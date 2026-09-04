from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

import admin
import audit
import channels
import gateway_state

pages = APIRouter()
actions = APIRouter()

HELP = {
    "whatsapp": "Pairs with a phone; there is no token.",
    "telegram": "Create a bot with @BotFather, then /setprivacy → Disable so it sees every group message. "
    "Add the bot to the group. Groups appear here once someone writes in them.",
    "discord": "Create an application at discord.com/developers, add a Bot, enable the Message Content "
    "intent, and invite it with the bot scope and Read Messages, Send Messages, Read Message History "
    "permissions. Channels appear here as soon as it connects.",
}


def status(row, state):
    """(text, css class) for one channel's header line."""
    if row is None:
        return "not set up", "muted"
    if not row["enabled"]:
        return "disabled", "muted"
    if state["connected"]:
        n = len(state["groups"])
        who = f" as {state['jid']}" if state["jid"] else ""
        return f"connected{who}, {n} group{'s' if n != 1 else ''} visible", "ok"
    if state["relink"]:
        return "pairing again, waiting for the gateway", "muted"
    if state["reported_at"]:
        return "enabled, not connected", "bad"
    return "enabled, gateway has not reported", "muted"


@pages.get("/channels", response_class=HTMLResponse)
def page(request: Request, message: str | None = None):
    rows = {c["kind"]: c for c in channels.list_all()}
    state = gateway_state.all_channels()
    view = [
        {
            "kind": k,
            "traits": t,
            "row": rows.get(k),
            "state": state[k],
            "status": status(rows.get(k), state[k]),
        }
        for k, t in channels.KINDS.items()
    ]
    return admin.render(request, "channels.html", view=view, help=HELP, message=message)


@actions.post("/channels/{kind}")
def save(kind: str, token: str = Form(""), enabled: bool = Form(False)):
    if kind not in channels.KINDS:
        raise HTTPException(404)
    token = token.strip()
    try:
        channels.upsert(kind, {"token": token} if token else None, enabled)
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    audit.log("channel.update", kind, {"enabled": enabled, "token": token or "(kept)"})
    return admin.redirect("/admin/channels", "Saved. The gateway picks it up within 30 seconds.")


@actions.post("/channels/{kind}/delete")
def delete(kind: str):
    channels.delete(kind)
    audit.log("channel.delete", kind)
    return RedirectResponse("/admin/channels", status_code=303)


@actions.post("/channels/{kind}/relink")
def relink(kind: str):
    if not channels.KINDS.get(kind, {}).get("pairs"):
        raise HTTPException(404, "this channel does not pair")
    gateway_state.request_relink(kind)
    audit.log("gateway.relink", kind)
    return RedirectResponse("/setup/link", status_code=303)

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

import admin
import audit
import channels
import gateway_state

pages = APIRouter()
actions = APIRouter()

HELP = {
    "whatsapp": "Pairs with a phone; there is no token. Watches the groups it is in.",
    "telegram": "Create a bot with @BotFather, then /setprivacy → Disable so it sees every group message. "
    "Add the bot to the group. Groups appear here once someone writes in them.",
    "discord": "Create an application at discord.com/developers, add a Bot, enable the Message Content "
    "intent, and invite it with the bot scope and Read Messages, Send Messages, Read Message History "
    "permissions. Channels appear here as soon as it connects.",
    "whatsapp_cloud": "Meta's official API, for private questions on a business number. It answers people "
    "who are in one of your groups, inside WhatsApp's 24-hour window. It cannot watch group chats: Meta "
    "caps those at 8 participants and requires an Official Business Account. Needs a public HTTPS webhook "
    "at /webhook/whatsapp_cloud on the gateway.",
}
LABELS = {
    "token": "Access token",
    "phone_number_id": "Phone number id",
    "verify_token": "Webhook verify token (you choose it)",
    "app_secret": "App secret",
}


def status(kind, row, state):
    """(text, css class) for one channel's header line."""
    if row is None:
        return "not set up", "muted"
    if not row["enabled"]:
        return "disabled", "muted"
    if state["connected"]:
        n = len(state["groups"])
        who = f" as {state['jid']}" if state["jid"] else ""
        seen = "" if channels.KINDS[kind]["dm_only"] else f", {n} group{'s' if n != 1 else ''} visible"
        return f"connected{who}{seen}", "ok"
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
            "kind": kind,
            "traits": traits,
            "row": rows.get(kind),
            "state": state[kind],
            "status": status(kind, rows.get(kind), state[kind]),
            "fields": [(f, LABELS.get(f, f)) for f in traits["fields"]],
        }
        for kind, traits in channels.KINDS.items()
    ]
    return admin.render(request, "channels.html", view=view, help=HELP, message=message)


@actions.post("/channels/{kind}")
async def save(kind: str, request: Request):
    if kind not in channels.KINDS:
        raise HTTPException(404)
    form = await request.form()
    # Blank means "keep what is stored", so a secret is typed once.
    config = {f: form.get(f, "").strip() for f in channels.KINDS[kind]["fields"] if form.get(f, "").strip()}
    enabled = form.get("enabled") == "true"
    try:
        channels.upsert(kind, config or None, enabled)
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    audit.log("channel.update", kind, {"enabled": enabled, **dict.fromkeys(config, "set")})
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

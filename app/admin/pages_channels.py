from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

import admin
import audit
import channels
import gateway_state

pages = APIRouter()
actions = APIRouter()

HELP = {
    "telegram": "Create a bot with @BotFather, then /setprivacy → Disable so it sees every group message. "
    "Add the bot to the group. Groups appear here once someone writes in them.",
    "discord": "Create an application at discord.com/developers, add a Bot, enable the Message Content "
    "intent, and invite it with the bot scope and Read Messages, Send Messages, Read Message History "
    "permissions. Channels appear here as soon as it connects.",
}


@pages.get("/channels", response_class=HTMLResponse)
def page(request: Request, message: str | None = None):
    rows = {c["kind"]: c for c in channels.list_all()}
    return admin.render(
        request,
        "channels.html",
        kinds=channels.KINDS,
        rows=rows,
        state=gateway_state.all_channels(),
        relink=gateway_state.relink_pending(),
        help=HELP,
        message=message,
    )


@actions.post("/channels/{kind}")
def save(kind: str, token: str = Form(""), enabled: bool = Form(False)):
    if kind not in channels.KINDS:
        raise HTTPException(404)
    config = {"token": token.strip()} if token.strip() else None
    try:
        channels.upsert(kind, config, enabled)
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    audit.log("channel.update", kind, {"enabled": enabled, "token": "***" if config else "(kept)"})
    return RedirectResponse("/admin/channels?message=Saved.+The+gateway+picks+it+up+within+30+seconds.", 303)


@actions.post("/channels/{kind}/delete")
def delete(kind: str):
    channels.delete(kind)
    audit.log("channel.delete", kind)
    return RedirectResponse("/admin/channels", status_code=303)


@actions.post("/channels/whatsapp/relink")
def relink():
    gateway_state.request_relink()
    audit.log("gateway.relink", "whatsapp")
    return RedirectResponse("/setup/link", status_code=303)

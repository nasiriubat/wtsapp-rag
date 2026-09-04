import io

from fastapi import APIRouter, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse

import admin
import audit
import db
import groups
import retention
from admin import jsonl
from scripts.import_export import insert, parse

pages = APIRouter()
actions = APIRouter()


@pages.get("/data", response_class=HTMLResponse)
def page(request: Request, message: str | None = None):
    with db.connect() as conn:
        counts = {
            r["group_id"]: r
            for r in conn.execute(
                "SELECT group_id, count(*) AS messages, min(ts) AS first, max(ts) AS last "
                "FROM messages GROUP BY group_id"
            )
        }
    return admin.render(request, "data.html", groups=groups.list_all(), counts=counts, message=message)


def _redirect(message):
    return RedirectResponse(f"/admin/data?message={message.replace(' ', '+')}", status_code=303)


@actions.post("/data/import")
async def import_export(group_id: int = Form(), file: UploadFile = None):
    group = groups.get_by_id(group_id)
    if group is None or file is None:
        raise HTTPException(422, "pick a group and a file")
    # Same decoding as the CLI path, so the same line hashes to the same id.
    text = (await file.read()).decode("utf-8")
    n = insert(group["external_id"], parse(io.StringIO(text)))
    audit.log("data.import", group["external_id"], {"file": file.filename, "messages": n})
    return _redirect(f"Imported {n} new messages into {group['name'] or 'the group'}")


@actions.post("/data/reembed/{group_id}")
def reembed(group_id: int):
    """Drop a group's chunks and let the loop rebuild them. For after a chunking
    or embedding change."""
    group = groups.get_by_id(group_id)
    if group is None:
        raise HTTPException(404)
    with db.connect() as conn, conn.transaction():
        n = conn.execute("DELETE FROM chunks WHERE group_id = %s", (group["external_id"],)).rowcount
        conn.execute("UPDATE messages SET chunked = false WHERE group_id = %s", (group["external_id"],))
    audit.log("data.reembed", group["external_id"], {"chunks": n})
    return _redirect(f"Dropped {n} chunks; rebuilding within a minute")


@actions.post("/data/purge")
def purge(group_id: int = Form(), sender: str = Form()):
    group = groups.get_by_id(group_id)
    if group is None or not sender.strip():
        raise HTTPException(422)
    n = retention.purge_sender(group["external_id"], sender.strip())
    audit.log("member.purge", group["external_id"], {"sender": sender.strip(), "messages": n})
    return _redirect(f"Erased {n} messages from {sender.strip()}")


@pages.get("/data/export/{group_id}.jsonl")
def export(group_id: int):
    group = groups.get_by_id(group_id)
    if group is None:
        raise HTTPException(404)
    return jsonl.stream(
        "SELECT wa_msg_id, sender_jid, sender_name, body, is_bot, ts FROM messages "
        "WHERE group_id = %s ORDER BY ts",
        (group["external_id"],),
        f"messages-{group_id}.jsonl",
    )

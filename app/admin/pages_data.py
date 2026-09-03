import io
import json

from fastapi import APIRouter, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse

import admin
import audit
import db
import groups
import retention
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


@actions.post("/data/import")
async def import_export(group_id: int = Form(), file: UploadFile = None):
    group = groups.get_by_id(group_id)
    if group is None or file is None:
        raise HTTPException(422, "pick a group and a file")
    text = (await file.read()).decode("utf-8", errors="replace")
    n = insert(group["external_id"], parse(io.StringIO(text)))
    audit.log("data.import", group["external_id"], {"file": file.filename, "messages": n})
    return RedirectResponse(
        f"/admin/data?message=Imported+{n}+messages+into+{group['name'] or 'the+group'}", 303
    )


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
    return RedirectResponse(f"/admin/data?message=Dropped+{n}+chunks;+rebuilding+within+a+minute", 303)


@actions.post("/data/purge")
def purge(group_id: int = Form(), sender: str = Form()):
    group = groups.get_by_id(group_id)
    if group is None or not sender.strip():
        raise HTTPException(422)
    n = retention.purge_sender(group["external_id"], sender.strip())
    audit.log("member.purge", group["external_id"], {"sender": sender.strip(), "messages": n})
    return RedirectResponse(f"/admin/data?message=Erased+{n}+messages+from+{sender.strip()}", 303)


@pages.get("/data/export/{group_id}.jsonl")
def export(group_id: int):
    group = groups.get_by_id(group_id)
    if group is None:
        raise HTTPException(404)

    def lines():
        with db.connect() as conn:
            for r in conn.execute(
                "SELECT wa_msg_id, sender_jid, sender_name, body, is_bot, ts FROM messages "
                "WHERE group_id = %s ORDER BY ts",
                (group["external_id"],),
            ):
                yield json.dumps(r, default=str) + "\n"

    name = (group["name"] or group["external_id"]).replace(" ", "_")
    headers = {"content-disposition": f'attachment; filename="{name}.jsonl"'}
    return StreamingResponse(lines(), media_type="application/x-ndjson", headers=headers)

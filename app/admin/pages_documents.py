from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse

import admin
import audit
import documents
import groups

pages = APIRouter()
actions = APIRouter()


def _view(request, message=None):
    rows = documents.list_all()
    return admin.render(
        request,
        "documents.html",
        documents=rows,
        groups=groups.list_all(),
        pending=any(r["status"] == "pending" for r in rows),
        max_mb=documents.MAX_BYTES // 1024 // 1024,
        message=message,
    )


@pages.get("/documents", response_class=HTMLResponse)
def page(request: Request, message: str | None = None):
    return _view(request, message)


@pages.get("/documents/table", response_class=HTMLResponse)
def table(request: Request):
    """Polled by the page while something is still being read."""
    rows = documents.list_all()
    return admin.render(
        request, "documents_table.html", documents=rows, pending=any(r["status"] == "pending" for r in rows)
    )


@actions.post("/documents")
async def upload(group_id: str = Form(""), files: list[UploadFile] = File(default=[])):
    files = [f for f in files if f.filename]
    if not files:
        raise HTTPException(422, "pick at least one file")
    group = groups.get_by_id(int(group_id)) if group_id else None
    if group_id and group is None:
        raise HTTPException(404)
    external_id = group["external_id"] if group else None
    added, refused = 0, []
    for f in files:
        try:
            documents.create(external_id, f.filename, f.content_type, await f.read())
            added += 1
        except documents.Unreadable as e:
            refused.append(f"{f.filename}: {e}")
    audit.log("document.upload", external_id or "all", {"files": added})
    where = group["name"] or "the group" if group else "every group"
    note = f"Uploaded {added} file{'s' if added != 1 else ''} for {where}; reading them now"
    return admin.redirect("/admin/documents", "; ".join([note, *refused]))


@actions.post("/documents/{document_id}/reindex")
def reindex(document_id: int):
    if documents.get(document_id) is None:
        raise HTTPException(404)
    documents.reindex(document_id)
    audit.log("document.reindex", str(document_id))
    return admin.redirect("/admin/documents", "Re-indexing; it will be searchable again shortly")


@actions.post("/documents/{document_id}/delete")
def delete(document_id: int):
    row = documents.get(document_id)
    if row is None:
        raise HTTPException(404)
    documents.delete(document_id)
    audit.log("document.delete", str(document_id), {"filename": row["filename"]})
    return admin.redirect("/admin/documents", f"Deleted {row['filename']}")

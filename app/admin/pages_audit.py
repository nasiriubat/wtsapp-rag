from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

import admin
import db

pages = APIRouter()
actions = APIRouter()
PAGE = 50


@pages.get("/audit", response_class=HTMLResponse)
def page(request: Request, action: str = "", page: int = 1):
    page = max(page, 1)
    with db.connect() as conn:
        actions_seen = [
            r["action"] for r in conn.execute("SELECT DISTINCT action FROM audit_log ORDER BY action")
        ]
        rows = conn.execute(
            "SELECT id, ts, actor, action, target, detail FROM audit_log "
            "WHERE (%(action)s = '' OR action = %(action)s) "
            "ORDER BY id DESC LIMIT %(limit)s OFFSET %(offset)s",
            {"action": action, "limit": PAGE + 1, "offset": (page - 1) * PAGE},
        ).fetchall()
    return admin.render(
        request,
        "audit.html",
        rows=rows[:PAGE],
        more=len(rows) > PAGE,
        page=page,
        action=action,
        actions_seen=actions_seen,
    )

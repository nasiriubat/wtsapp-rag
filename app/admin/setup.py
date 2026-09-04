"""Five-step setup wizard: preflight, provider, link, groups, round trip."""

import os
from urllib.parse import urlencode

import psycopg
from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

import admin
import admin_api
import db
import gateway_state
import groups
import providers
from admin import health, pages_channels

pages = APIRouter()
actions = APIRouter()
STEPS = [
    ("preflight", "System check"),
    ("provider", "Model"),
    ("link", "Connect WhatsApp"),
    ("groups", "Groups"),
    ("test", "Try it"),
]


def _page(request, step, **ctx):
    return admin.render(request, f"setup_{step}.html", step=step, steps=STEPS, **ctx)


def preflight_checks():
    checks = []
    try:
        with db.connect() as conn:
            conn.execute("SELECT 1")
        checks.append(("ok", "Postgres", "connected"))
    except psycopg.Error as e:
        checks.append(("bad", "Postgres", f"{e}. Is the db service healthy?"))
    ram_gb = os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / 1e9
    checks.append(
        ("ok" if ram_gb >= 3 else "warn", "Memory", f"{ram_gb:.1f} GB. The models need about 2 GB.")
    )
    free = health.disk_free_gb()
    checks.append(
        ("ok" if free >= 2 else "warn", "Disk", f"{free:.1f} GB free where models and the queue live.")
    )
    if gateway_state.any_reported():
        checks.append(("ok", "Gateway", "reporting"))
    else:
        checks.append(("warn", "Gateway", "has not reported yet. Check `docker compose logs gateway`."))
    return checks


@admin.setup_pages.get("")
def preflight(request: Request):
    return _page(request, "preflight", checks=preflight_checks())


@pages.get("/provider", response_class=HTMLResponse)
def provider(request: Request, ok: int | None = None, detail: str = ""):
    return _page(
        request,
        "provider",
        providers=providers.list_all(),
        ok=ok,
        detail=detail,
        kinds=sorted(providers.KINDS),
    )


@actions.post("/provider")
def add_provider(kind: str = Form(), api_key: str = Form(), model: str = Form(), base_url: str = Form("")):
    row = admin_api.add_provider(
        {
            "name": kind.capitalize(),
            "kind": kind,
            "api_key": api_key,
            "model": model,
            "base_url": base_url or None,
        }
    )
    try:
        result = {"ok": 1, "detail": admin_api.run_provider_test(row["id"])[:60]}
    except HTTPException as e:
        result = {"ok": 0, "detail": str(e.detail)[:200]}
    return RedirectResponse(f"/setup/provider?{urlencode(result)}", status_code=303)


@pages.get("/link", response_class=HTMLResponse)
def link(request: Request):
    return _page(request, "link")


@pages.get("/link/status", response_class=HTMLResponse)
def link_status(request: Request):
    # The wizard's link step is the phone pairing; other channels join on the Channels page.
    return admin.render(request, "setup_link_status.html", gateway=gateway_state.get("whatsapp"))


@actions.post("/link/relink")
def relink():
    return pages_channels.relink("whatsapp")


@pages.get("/groups", response_class=HTMLResponse)
def pick_groups(request: Request):
    known = {g["external_id"]: g for g in groups.list_all()}
    return _page(request, "groups", seen=gateway_state.seen_groups(), known=known)


@actions.post("/groups")
async def enable_groups(request: Request):
    form = await request.form()
    seen = {g["id"]: g for g in gateway_state.seen_groups()}
    created = 0
    for external_id in form.getlist("group"):
        if groups.get(external_id) is None and external_id in seen:
            g = seen[external_id]
            admin_api.add_group(
                {"channel": g["channel"], "external_id": external_id, "name": g.get("subject")}
            )
            created += 1
    return RedirectResponse(f"/setup/test?created={created}", status_code=303)


@pages.get("/test", response_class=HTMLResponse)
def round_trip(request: Request, created: int = 0):
    with db.connect() as conn:
        since = conn.execute("SELECT coalesce(max(id), 0) AS id FROM query_log").fetchone()["id"]
    enabled = [g for g in groups.list_all() if g["enabled"]]
    return _page(request, "test", since=since, groups=enabled, created=created)


@pages.get("/test/status", response_class=HTMLResponse)
def round_trip_status(request: Request, since: int):
    with db.connect() as conn:
        row = conn.execute(
            "SELECT q.question, q.answer, g.name FROM query_log q "
            "LEFT JOIN groups g ON g.external_id = q.group_id "
            "WHERE q.id > %s ORDER BY q.id DESC LIMIT 1",
            (since,),
        ).fetchone()
    return admin.render(request, "setup_test_status.html", row=row, since=since)

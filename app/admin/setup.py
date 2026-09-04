"""Five-step setup wizard: preflight, provider, link, groups, round trip."""

import os
import shutil

import psycopg
import segno
from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

import admin
import admin_api
import audit
import db
import gateway_state
import groups
import providers

pages = APIRouter()
actions = APIRouter()
STEPS = ["preflight", "provider", "link", "groups", "test"]


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
        (
            "ok" if ram_gb >= 3 else "warn",
            "Memory",
            f"{ram_gb:.1f} GB. The embedder and reranker need about 2 GB.",
        )
    )
    free_gb = shutil.disk_usage("/").free / 1e9
    checks.append(("ok" if free_gb >= 5 else "warn", "Disk", f"{free_gb:.1f} GB free. Models take 2.5 GB."))
    g = gateway_state.get()
    if g["reported_at"]:
        checks.append(("ok", "Gateway", "reporting"))
    else:
        checks.append(("warn", "Gateway", "has not reported yet. Check `docker compose logs gateway`."))
    return checks


def preflight(request: Request):
    """Registered on "/setup" itself by admin/__init__.py."""
    return _page(request, "preflight", checks=preflight_checks())


@pages.get("/provider", response_class=HTMLResponse)
def provider(request: Request, tested: str | None = None):
    return _page(
        request, "provider", providers=providers.list_all(), tested=tested, kinds=sorted(providers.KINDS)
    )


@actions.post("/provider")
def add_provider(kind: str = Form(), api_key: str = Form(), model: str = Form(), base_url: str = Form("")):
    if kind not in providers.KINDS:
        raise HTTPException(422, "unknown kind")
    row = providers.create(kind.capitalize(), kind, api_key, model, base_url or None)
    audit.log("provider.create", str(row["id"]), {"kind": kind, "model": model, "via": "setup"})
    if groups.global_settings()["default_provider_id"] is None:
        groups.set_global(default_provider_id=row["id"])
    try:
        reply = admin_api.run_provider_test(row["id"])
        tested = f"ok: replied {reply[:40]!r}"
    except HTTPException as e:
        tested = f"failed: {e.detail}"
    return RedirectResponse(f"/setup/provider?tested={tested}", status_code=303)


@pages.get("/link", response_class=HTMLResponse)
def link(request: Request):
    return _page(request, "link")


@pages.get("/link/status", response_class=HTMLResponse)
def link_status(request: Request):
    g = gateway_state.get()
    svg = segno.make(g["qr"], error="m").svg_inline(scale=4) if g["qr"] else None
    return admin.render(request, "setup_link_status.html", gateway=g, svg=svg)


@actions.post("/link/relink")
def relink():
    gateway_state.request_relink()
    audit.log("gateway.relink", "whatsapp")
    return RedirectResponse("/setup/link", status_code=303)


@pages.get("/groups", response_class=HTMLResponse)
def pick_groups(request: Request):
    known = {g["external_id"]: g for g in groups.list_all()}
    seen = gateway_state.get()["groups"]
    return _page(request, "groups", seen=seen, known=known)


@actions.post("/groups")
async def enable_groups(request: Request):
    form = await request.form()
    subjects = {g["id"]: g.get("subject") for g in gateway_state.get()["groups"]}
    created = 0
    for external_id in form.getlist("group"):
        if groups.get(external_id) is None:
            groups.create("whatsapp", external_id, subjects.get(external_id))
            audit.log("group.create", external_id, {"via": "setup"})
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

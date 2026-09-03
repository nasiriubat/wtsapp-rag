from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import ValidationError

import admin
import admin_api
import audit
import db
import gateway_state
import groups
import providers

pages = APIRouter()
actions = APIRouter()
CHANNELS = ("whatsapp", "telegram", "discord")


@pages.get("/groups", response_class=HTMLResponse)
def index(request: Request):
    known = {g["external_id"] for g in groups.list_all()}
    seen = [g for g in gateway_state.get()["groups"] if g.get("id") not in known]
    return admin.render(request, "groups.html", groups=groups.list_all(), seen=seen, channels=CHANNELS)


@actions.post("/groups")
def create(channel: str = Form(), external_id: str = Form(), name: str = Form("")):
    if channel not in CHANNELS:
        raise HTTPException(422, "unknown channel")
    if groups.get(external_id):
        raise HTTPException(409, "group already exists")
    row = groups.create(channel, external_id.strip(), name.strip() or None)
    audit.log("group.create", external_id, {"channel": channel, "name": name})
    return RedirectResponse(f"/admin/groups/{row['id']}", status_code=303)


@pages.get("/groups/{group_id}", response_class=HTMLResponse)
def edit(request: Request, group_id: int, saved: bool = False):
    group = groups.get_by_id(group_id)
    if group is None:
        raise HTTPException(404)
    return admin.render(
        request,
        "group.html",
        group=group,
        providers=providers.list_all(),
        default_id=groups.global_settings()["default_provider_id"],
        threshold=threshold_stat(group["external_id"], group["settings"]["confidence_threshold"]),
        saved=saved,
    )


def threshold_stat(external_id, value):
    """What this threshold would have done to the last 200 questions."""
    with db.connect() as conn:
        row = conn.execute(
            """
            SELECT count(*) AS n, count(*) FILTER (WHERE confidence < %s) AS refused
            FROM (SELECT confidence FROM query_log WHERE group_id = %s ORDER BY id DESC LIMIT 200) q
            """,
            (value, external_id),
        ).fetchone()
    if not row["n"]:
        return f"At {value:.2f}: no questions logged for this group yet."
    pct = 100 * row["refused"] / row["n"]
    return f"At {value:.2f}: {pct:.0f}% of the last {row['n']} questions would have been refused " + (
        f"({row['refused']})."
    )


@pages.get("/groups/{group_id}/threshold", response_class=HTMLResponse)
def threshold(group_id: int, value: float):
    group = groups.get_by_id(group_id)
    if group is None:
        raise HTTPException(404)
    return HTMLResponse(admin.escape(threshold_stat(group["external_id"], value)))


def _lines(raw):
    return [x.strip() for x in raw.replace(",", "\n").splitlines() if x.strip()]


@actions.post("/groups/{group_id}")
def save(
    group_id: int,
    name: str = Form(""),
    enabled: bool = Form(False),
    provider_id: str = Form(""),
    triggers: str = Form("@agent"),
    confidence_threshold: float = Form(0.1),
    refusal_text: str = Form(groups.REFUSAL),
    answer_language: str = Form("auto"),
    retention_days: str = Form(""),
    opt_out: str = Form(""),
    quiet_start: str = Form(""),
    quiet_end: str = Form(""),
    quiet_tz: str = Form("UTC"),
    monthly_cap_eur: str = Form(""),
):
    settings = {
        "triggers": _lines(triggers) or ["@agent"],
        "confidence_threshold": confidence_threshold,
        "refusal_text": refusal_text.strip() or groups.REFUSAL,
        "answer_language": answer_language.strip() or "auto",
        "retention_days": int(retention_days) if retention_days.strip() else None,
        "opt_out": _lines(opt_out),
        "quiet_hours": {"start": quiet_start, "end": quiet_end, "tz": quiet_tz}
        if quiet_start and quiet_end
        else None,
        "monthly_cap_eur": float(monthly_cap_eur) if monthly_cap_eur.strip() else None,
    }
    try:
        groups.Settings(**settings)
    except ValidationError as e:
        raise HTTPException(422, str(e)) from e
    fields = {
        "name": name.strip() or None,
        "enabled": enabled,
        "provider_id": int(provider_id) if provider_id else None,
        "settings": settings,
    }
    admin_api.apply_group(group_id, fields)
    return RedirectResponse(f"/admin/groups/{group_id}?saved=1", status_code=303)


@actions.post("/groups/{group_id}/delete")
def delete(group_id: int):
    groups.delete(group_id)
    audit.log("group.delete", str(group_id))
    return RedirectResponse("/admin/groups", status_code=303)

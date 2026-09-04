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


@pages.get("/groups", response_class=HTMLResponse)
def index(request: Request):
    rows = groups.list_all()
    known = {g["external_id"] for g in rows}
    seen = [g for g in gateway_state.seen_groups() if g["id"] not in known]
    return admin.render(request, "groups.html", groups=rows, seen=seen, channels=groups.CHANNELS)


@actions.post("/groups")
def create(channel: str = Form(), external_id: str = Form(), name: str = Form("")):
    row = admin_api.add_group({"channel": channel, "external_id": external_id, "name": name.strip() or None})
    return RedirectResponse(f"/admin/groups/{row['id']}", status_code=303)


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
    pct, n, refused = 100 * row["refused"] / row["n"], row["n"], row["refused"]
    return f"At {value:.2f}: {pct:.0f}% of the last {n} questions would have been refused ({refused})."


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


@pages.get("/groups/{group_id}/threshold", response_class=HTMLResponse)
def threshold(group_id: int, value: float):
    group = groups.get_by_id(group_id)
    if group is None:
        raise HTTPException(404)
    return HTMLResponse(admin.escape(threshold_stat(group["external_id"], value)))


def _lines(raw):
    return [x.strip() for x in raw.replace(",", "\n").splitlines() if x.strip()]


def _number(raw, cast, field):
    if not raw.strip():
        return None
    try:
        return cast(raw)
    except ValueError as e:
        raise HTTPException(422, f"{field}: not a number") from e


@actions.post("/groups/{group_id}")
def save(
    group_id: int,
    name: str = Form(""),
    enabled: bool = Form(False),
    provider_id: str = Form(""),
    triggers: str = Form(""),
    confidence_threshold: float = Form(0.1),
    refusal_text: str = Form(""),
    answer_language: str = Form(""),
    retention_days: str = Form(""),
    opt_out: str = Form(""),
    quiet_start: str = Form(""),
    quiet_end: str = Form(""),
    quiet_tz: str = Form("UTC"),
    monthly_cap_eur: str = Form(""),
):
    # Empty fields fall back to the Settings defaults through validation.
    raw = {
        "confidence_threshold": confidence_threshold,
        "retention_days": _number(retention_days, int, "retention days"),
        "opt_out": _lines(opt_out),
        "monthly_cap_eur": _number(monthly_cap_eur, float, "monthly cap"),
    }
    if triggers.strip():
        raw["triggers"] = _lines(triggers)
    if refusal_text.strip():
        raw["refusal_text"] = refusal_text.strip()
    if answer_language.strip():
        raw["answer_language"] = answer_language.strip()
    if quiet_start and quiet_end:
        raw["quiet_hours"] = {"start": quiet_start, "end": quiet_end, "tz": quiet_tz.strip() or "UTC"}
    fields = {
        "name": name.strip() or None,
        "enabled": enabled,
        "provider_id": _number(provider_id, int, "provider"),
        "settings": raw,
    }
    admin_api.apply_group(group_id, fields)
    return RedirectResponse(f"/admin/groups/{group_id}?saved=1", status_code=303)


@actions.post("/groups/{group_id}/delete")
def delete(group_id: int):
    groups.delete(group_id)
    audit.log("group.delete", str(group_id))
    return RedirectResponse("/admin/groups", status_code=303)

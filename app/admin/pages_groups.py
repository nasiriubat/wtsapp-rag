from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

import admin
import admin_api
import channels
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
    return admin.render(request, "groups.html", groups=rows, seen=seen, channels=list(channels.KINDS))


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


def _edit_page(request, group, error=None, status=200):
    return admin.render(
        request,
        "group.html",
        group=group,
        providers=providers.list_all(),
        default_id=groups.global_settings()["default_provider_id"],
        threshold=threshold_stat(group["external_id"], float(group["settings"]["confidence_threshold"])),
        error=error,
        status_code=status,
    )


@pages.get("/groups/{group_id}", response_class=HTMLResponse)
def edit(request: Request, group_id: int):
    group = groups.get_by_id(group_id)
    if group is None:
        raise HTTPException(404)
    return _edit_page(request, group)


@pages.get("/groups/{group_id}/threshold", response_class=HTMLResponse)
def threshold(group_id: int, confidence_threshold: float):
    group = groups.get_by_id(group_id)
    if group is None:
        raise HTTPException(404)
    return HTMLResponse(admin.escape(threshold_stat(group["external_id"], confidence_threshold)))


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
    request: Request,
    group_id: int,
    name: str = Form(""),
    enabled: bool = Form(False),
    provider_id: str = Form(""),
    triggers: str = Form(""),
    confidence_threshold: float = Form(0.0),
    refusal_text: str = Form(""),
    answer_language: str = Form(""),
    retention_days: str = Form(""),
    opt_out: str = Form(""),
    quiet_start: str = Form(""),
    quiet_end: str = Form(""),
    quiet_tz: str = Form("UTC"),
    monthly_cap_eur: str = Form(""),
    decision_tracking: bool = Form(False),
    allow_dm: bool = Form(False),
    index_files: bool = Form(False),
    correction_ack: str = Form(""),
):
    group = groups.get_by_id(group_id)
    if group is None:
        raise HTTPException(404)

    # What was typed, kept as typed, so a form that fails validation comes back
    # with every field as the admin left it rather than as an error page.
    def as_typed():
        quiet = {"start": quiet_start, "end": quiet_end, "tz": quiet_tz} if quiet_start or quiet_end else None
        settings = {
            **group["settings"],
            "triggers": _lines(triggers),
            "confidence_threshold": confidence_threshold,
            "refusal_text": refusal_text,
            "answer_language": answer_language,
            "retention_days": retention_days,
            "opt_out": _lines(opt_out),
            "quiet_hours": quiet,
            "monthly_cap_eur": monthly_cap_eur,
            "decision_tracking": decision_tracking,
            "allow_dm": allow_dm,
            "index_files": index_files,
            "correction_ack": correction_ack,
        }
        return {
            **group,
            "name": name,
            "enabled": enabled,
            "provider_id": provider_id or None,
            "settings": settings,
        }

    if bool(quiet_start) != bool(quiet_end):
        return _edit_page(request, as_typed(), "Quiet hours need both a start and an end, or neither.", 422)
    try:
        # Empty fields fall back to the Settings defaults through validation.
        raw = {
            "confidence_threshold": confidence_threshold,
            "retention_days": _number(retention_days, int, "retention days"),
            "opt_out": _lines(opt_out),
            "monthly_cap_eur": _number(monthly_cap_eur, float, "monthly cap"),
            "decision_tracking": decision_tracking,
            "allow_dm": allow_dm,
            "index_files": index_files,
        }
        if correction_ack.strip():
            raw["correction_ack"] = correction_ack.strip()
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
        row, purged = admin_api.apply_group(group_id, fields)
    except HTTPException as e:
        if e.status_code != 422:
            raise
        return _edit_page(request, as_typed(), _plain(e.detail), 422)
    note = "Saved."
    if purged:
        erased = ", ".join(f"{sender} ({c['messages']} messages)" for sender, c in purged)
        note = f"Saved. Erased everything written by {erased}."
    return admin.redirect(f"/admin/groups/{group_id}", note)


def _plain(detail):
    """pydantic's report of a bad field, as one sentence."""
    text = str(detail)
    if "validation error" in text:
        lines = [ln.strip() for ln in text.splitlines()[1:] if ln.strip() and not ln.startswith("    For")]
        text = "; ".join(
            f"{lines[i]}: {lines[i + 1].split('[')[0].strip()}" for i in range(0, len(lines) - 1, 2)
        )
    return text


@actions.post("/groups/{group_id}/delete")
def delete(group_id: int):
    counts = admin_api.remove_group(group_id)
    gone = ", ".join(f"{n} {what}" for what, n in counts.items() if n)
    return admin.redirect("/admin/groups", f"Removed the group and {gone or 'nothing else'}")

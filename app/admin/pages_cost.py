from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

import admin
import audit
import db
import groups

pages = APIRouter()
actions = APIRouter()

MONTH = "ts >= date_trunc('month', now() AT TIME ZONE 'UTC') AT TIME ZONE 'UTC'"


@pages.get("/cost", response_class=HTMLResponse)
def page(request: Request):
    with db.connect() as conn:
        by_provider = conn.execute(
            f"""
            SELECT coalesce(p.name, 'refused / none') AS name, count(*) AS n,
                   coalesce(sum(q.cost), 0) AS cost, coalesce(sum(q.tokens_in), 0) AS tokens_in,
                   coalesce(sum(q.tokens_out), 0) AS tokens_out
            FROM query_log q LEFT JOIN providers p ON p.id = q.provider_id
            WHERE {MONTH} GROUP BY p.name ORDER BY cost DESC
            """
        ).fetchall()
        by_group = conn.execute(
            f"""
            SELECT coalesce(g.name, q.group_id) AS name, g.settings->>'monthly_cap_eur' AS cap,
                   count(*) AS n, coalesce(sum(q.cost), 0) AS cost
            FROM query_log q LEFT JOIN groups g ON g.external_id = q.group_id
            WHERE {MONTH} GROUP BY g.name, q.group_id, cap ORDER BY cost DESC
            """
        ).fetchall()
        by_day = conn.execute(
            """
            SELECT date_trunc('day', ts)::date AS day, count(*) AS n, coalesce(sum(cost), 0) AS cost
            FROM query_log WHERE ts > now() - interval '30 days'
            GROUP BY day ORDER BY day
            """
        ).fetchall()
    total = sum(r["cost"] for r in by_provider)
    peak = max((r["cost"] for r in by_day), default=0) or 1
    return admin.render(
        request,
        "cost.html",
        by_provider=by_provider,
        by_group=by_group,
        by_day=by_day,
        total=total,
        peak=peak,
        cap=groups.global_settings()["monthly_cap_eur"],
    )


@actions.post("/cost/cap")
def set_cap(monthly_cap_eur: str = Form("")):
    value = float(monthly_cap_eur) if monthly_cap_eur.strip() else None
    groups.set_global(monthly_cap_eur=value)
    audit.log("settings.update", "global", {"monthly_cap_eur": value})
    return RedirectResponse("/admin/cost", status_code=303)

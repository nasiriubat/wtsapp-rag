import shutil

from fastapi import Request

import admin
import budget
import db
import gateway_state
import groups


def stats():
    with db.connect() as conn:
        counts = conn.execute(
            """
            SELECT (SELECT count(*) FROM messages) AS messages,
                   (SELECT count(*) FROM chunks) AS chunks,
                   (SELECT count(*) FROM messages WHERE NOT chunked) AS unchunked,
                   (SELECT max(ts) FROM messages) AS last_message,
                   (SELECT max(end_ts) FROM chunks) AS last_chunk,
                   (SELECT count(*) FROM query_log WHERE ts > now() - interval '1 day') AS questions_today,
                   (SELECT count(*) FROM query_log WHERE ts > now() - interval '1 day'
                      AND answer IS NOT NULL AND cost IS NULL) AS refused_today
            """
        ).fetchone()
        latency = conn.execute(
            """
            SELECT percentile_cont(0.5) WITHIN GROUP (ORDER BY latency_ms) AS p50,
                   percentile_cont(0.95) WITHIN GROUP (ORDER BY latency_ms) AS p95
            FROM query_log WHERE ts > now() - interval '7 days'
            """
        ).fetchone()
    return {**counts, **latency}


def page(request: Request):
    _, spent = budget.spent_this_month("")
    disk = shutil.disk_usage("/")
    return admin.render(
        request,
        "health.html",
        stats=stats(),
        gateway=gateway_state.get(),
        groups=groups.list_all(),
        spent=spent,
        cap=groups.global_settings()["monthly_cap_eur"],
        disk_free_gb=round(disk.free / 1e9, 1),
    )

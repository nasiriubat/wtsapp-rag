import os
import shutil

import psycopg
from fastapi import Request

import admin
import budget
import db
import gateway_state
import groups


def stats():
    """One statement for everything the health card shows."""
    with db.connect() as conn:
        return conn.execute(
            f"""
            SELECT (SELECT count(*) FROM messages) AS messages,
                   (SELECT count(*) FROM chunks) AS chunks,
                   (SELECT count(*) FROM messages WHERE NOT chunked) AS unchunked,
                   (SELECT max(ts) FROM messages) AS last_message,
                   (SELECT end_ts FROM chunks ORDER BY id DESC LIMIT 1) AS last_chunk,
                   t.questions_today, t.refused_today, w.p50, w.p95, m.spent
            FROM (SELECT count(*) AS questions_today,
                         count(*) FILTER (WHERE outcome = 'refused') AS refused_today
                  FROM query_log WHERE ts > now() - interval '1 day') t,
                 (SELECT percentile_cont(0.5) WITHIN GROUP (ORDER BY latency_ms) AS p50,
                         percentile_cont(0.95) WITHIN GROUP (ORDER BY latency_ms) AS p95
                  FROM query_log WHERE ts > now() - interval '7 days') w,
                 (SELECT coalesce(sum(cost), 0) AS spent FROM query_log WHERE {budget.MONTH_SQL}) m
            """
        ).fetchone()


def disk_free_gb():
    # /models holds the downloaded models; the database has its own volume and
    # reports through pg_database_size on the health JSON.
    return round(shutil.disk_usage("/models" if os.path.isdir("/models") else "/").free / 1e9, 1)


@admin.router.get("")
def page(request: Request):
    try:
        s = stats()
    except psycopg.Error as e:
        return admin.render(
            request, "health.html", db_error=str(e).strip(), stats=None, channels=gateway_state.all_channels()
        )
    return admin.render(
        request,
        "health.html",
        db_error=None,
        stats=s,
        channels=gateway_state.all_channels(),
        groups=groups.list_all(),
        cap=groups.global_settings()["monthly_cap_eur"],
        disk_free_gb=disk_free_gb(),
    )

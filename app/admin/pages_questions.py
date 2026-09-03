import json

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, StreamingResponse

import admin
import db

pages = APIRouter()
actions = APIRouter()

FILTERS = {
    "all": "TRUE",
    "answered": "cost IS NOT NULL",
    "refused": "cost IS NULL",
    "negative": "feedback = -1",
    "low": "confidence < 0.3",
}


@pages.get("/questions", response_class=HTMLResponse)
def index(request: Request, filter: str = "all", before: int | None = None):
    where = FILTERS.get(filter, "TRUE")
    with db.connect() as conn:
        rows = conn.execute(
            f"""
            SELECT q.*, g.name AS group_name FROM query_log q
            LEFT JOIN groups g ON g.external_id = q.group_id
            WHERE {where} AND (%s::bigint IS NULL OR q.id < %s)
            ORDER BY q.id DESC LIMIT 50
            """,
            (before, before),
        ).fetchall()
    return admin.render(request, "questions.html", rows=rows, filter=filter, filters=FILTERS)


def _detail(question_id):
    with db.connect() as conn:
        row = conn.execute("SELECT * FROM query_log WHERE id = %s", (question_id,)).fetchone()
        if row is None:
            raise HTTPException(404)
        ids = [c["chunk_id"] for c in (row["retrieved"] or {}).get("chunks", [])]
        chunks = conn.execute(
            "SELECT id, content, start_ts FROM chunks WHERE id = ANY(%s)", (ids,)
        ).fetchall()
    by_id = {c["id"]: c for c in chunks}
    retrieved = [{**c, "chunk": by_id.get(c["chunk_id"])} for c in (row["retrieved"] or {}).get("chunks", [])]
    return row, retrieved


@pages.get("/questions/{question_id}", response_class=HTMLResponse)
def detail(request: Request, question_id: int):
    row, retrieved = _detail(question_id)
    return admin.render(request, "question_detail.html", row=row, retrieved=retrieved)


@actions.post("/questions/{question_id}/feedback", response_class=HTMLResponse)
def feedback(request: Request, question_id: int, value: int = Form(), note: str = Form("")):
    if value not in (-1, 0, 1):
        raise HTTPException(422)
    with db.connect() as conn:
        conn.execute(
            "UPDATE query_log SET feedback = %s, feedback_note = %s WHERE id = %s",
            (value or None, note.strip() or None, question_id),
        )
    row, retrieved = _detail(question_id)
    return admin.render(request, "question_detail.html", row=row, retrieved=retrieved)


@pages.get("/questions.jsonl")
def export():
    """Every question with its outcome and feedback: the eval set."""

    def lines():
        with db.connect() as conn:
            for r in conn.execute(
                "SELECT id, ts, group_id, question, answer, confidence, feedback, feedback_note, retrieved "
                "FROM query_log ORDER BY id"
            ):
                yield json.dumps(r, default=str) + "\n"

    headers = {"content-disposition": "attachment; filename=questions.jsonl"}
    return StreamingResponse(lines(), media_type="application/x-ndjson", headers=headers)

import asyncio
import json
import logging
import os
import pathlib
import time
import traceback
from contextlib import asynccontextmanager
from datetime import datetime

import psycopg
from fastapi import Depends, FastAPI, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import admin
import admin_api
import answer
import bootstrap
import budget
import chunking
import db
import embed
import gateway_api
import groups
import migrate
import observe
import providers
import retention
import retrieval

NO_PROVIDER = "No LLM provider is configured yet. Ask the admin to add one."
log = logging.getLogger("app")


async def loop(fn, seconds):
    while True:
        await asyncio.to_thread(fn)
        await asyncio.sleep(seconds)


def _crash(task):
    # A dead loop behind a live server is worse than a restart.
    if not task.cancelled() and task.exception():
        traceback.print_exception(task.exception())
        os._exit(1)


@asynccontextmanager
async def lifespan(app):
    observe.setup_logging()
    migrate.run()
    bootstrap.run()
    # Two independent downloads and ONNX sessions; wall time is the max, not the sum.
    await asyncio.gather(asyncio.to_thread(embed.warm), asyncio.to_thread(retrieval.warm))
    tasks = [
        asyncio.create_task(loop(chunking.run_once, 60)),
        asyncio.create_task(loop(retention.run_once, 3600)),
    ]
    for t in tasks:
        t.add_done_callback(_crash)
    yield
    for t in tasks:
        t.cancel()


app = FastAPI(lifespan=lifespan)
app.include_router(gateway_api.router)
app.include_router(admin_api.router)
app.include_router(admin.public)
app.include_router(admin.router)
app.include_router(admin.forms)
app.include_router(admin.setup_pages)
app.include_router(admin.setup_forms)
app.mount(
    "/static", StaticFiles(directory=str(pathlib.Path(__file__).resolve().parent / "static")), name="static"
)


@app.get("/health")
def health(response: Response):
    # uvicorn only serves after lifespan finished, so models are loaded whenever
    # this answers. The database is the only thing that can be down.
    try:
        with db.connect() as conn:
            last = conn.execute("SELECT end_ts FROM chunks ORDER BY id DESC LIMIT 1").fetchone()
            pending = conn.execute("SELECT count(*) AS n FROM messages WHERE NOT chunked").fetchone()["n"]
    except psycopg.Error as e:
        response.status_code = 503
        return {"db": "down", "error": str(e).strip()}
    return {"db": "ok", "last_chunk_ts": last["end_ts"] if last else None, "unchunked_messages": pending}


@app.get("/metrics")
def metrics():
    return Response(observe.render(), media_type="text/plain; version=0.0.4")


class Message(BaseModel):
    wa_msg_id: str
    group_id: str
    sender_jid: str
    sender_name: str | None = None
    body: str | None = None
    quoted_msg_id: str | None = None
    is_bot: bool = False
    ts: datetime


@app.post("/ingest", dependencies=[Depends(gateway_api.require_token)])
def ingest(m: Message):
    # The app owns the group list. The gateway's copy can be 30 s stale or replayed
    # from its queue, so unknown, disabled and opted-out senders are dropped here.
    group = groups.get(m.group_id)
    if group is None or not group["enabled"] or m.sender_jid in group["settings"]["opt_out"]:
        observe.count("ingest_total", outcome="dropped")
        return {"ok": True}
    with db.connect() as conn:
        conn.execute(
            """
            INSERT INTO messages
              (wa_msg_id, group_id, sender_jid, sender_name, body, quoted_msg_id, is_bot, ts)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (wa_msg_id) DO NOTHING
            """,
            (m.wa_msg_id, m.group_id, m.sender_jid, m.sender_name, m.body, m.quoted_msg_id, m.is_bot, m.ts),
        )
    observe.count("ingest_total", outcome="stored")
    return {"ok": True}


class Question(BaseModel):
    question: str
    group_id: str
    sender_jid: str
    sender_name: str | None = None
    wa_msg_id: str


def _source(chunk):
    with db.connect() as conn:
        return conn.execute(
            "SELECT wa_msg_id, sender_jid, sender_name, is_bot, body, ts FROM messages WHERE wa_msg_id = %s",
            (chunk["first_msg_id"],),
        ).fetchone()


def _cite(text, src):
    # Imported messages have synthetic ids, so WhatsApp cannot resolve a quote to
    # them. A text citation is the fallback.
    if src["wa_msg_id"].startswith("import:"):
        first_line = (src["body"] or "").splitlines()[0]
        return f'From {src["ts"]:%d %b %Y}, {src["sender_name"]}: "{first_line}"\n\n{text}', None
    quote = {k: src[k] for k in ("wa_msg_id", "sender_jid", "is_bot", "body")}
    return text, quote


def _log_question(q, chunks, timings, text, confidence, tokens, provider, cost, latency_ms, outcome):
    retrieved = {
        "chunks": [{"chunk_id": c["id"], "score": c["score"], "source": c["source"]} for c in chunks],
        "timings": timings,
    }
    with db.connect() as conn:
        conn.execute(
            """
            INSERT INTO query_log
              (group_id, sender_jid, question, retrieved, answer, confidence,
               tokens_in, tokens_out, latency_ms, provider_id, cost, outcome)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                q.group_id,
                q.sender_jid,
                q.question,
                json.dumps(retrieved),
                text,
                confidence,
                tokens[0],
                tokens[1],
                latency_ms,
                provider["id"] if provider else None,
                cost,
                outcome,
            ),
        )


@app.post("/ask", dependencies=[Depends(gateway_api.require_token)])
def ask(q: Question):
    group = groups.get(q.group_id)
    if group is None or not group["enabled"]:
        return {"answer": None, "quote": None}
    s = group["settings"]
    if q.sender_jid in s["opt_out"] or groups.in_quiet_hours(s):
        observe.count("ask_total", outcome="suppressed")
        return {"answer": None, "quote": None}

    t0 = time.perf_counter()
    chunks, timings = retrieval.search(q.group_id, q.question)
    confidence = chunks[0]["score"] if chunks else 0.0
    text, quote, tokens, cost, provider = s["refusal_text"], None, (None, None), None, None
    outcome = "refused"
    if confidence >= s["confidence_threshold"]:
        global_settings = groups.global_settings()
        provider = providers.resolve(group, global_settings)
        if provider is None:
            text, outcome = NO_PROVIDER, "no_provider"
        elif budget.exceeded(group, global_settings):
            text, outcome = budget.BUDGET_TEXT, "budget"
        else:
            t = time.perf_counter()
            text, *tokens = answer.generate(q.question, chunks, provider, s)
            timings["llm_ms"] = round((time.perf_counter() - t) * 1000)
            cost = providers.cost(provider, *tokens)
            if answer.is_refusal(text):
                text = s["refusal_text"]
            else:
                text, quote = _cite(text, _source(chunks[0]))
                outcome = "answered"
    latency_ms = round((time.perf_counter() - t0) * 1000)
    observe.count("ask_total", outcome=outcome)
    observe.observe_latency(latency_ms / 1000)
    log.info(
        "ask",
        extra={
            "group": q.group_id,
            "confidence": round(confidence, 3),
            "latency_ms": latency_ms,
            "outcome": outcome,
        },
    )
    _log_question(q, chunks, timings, text, confidence, tuple(tokens), provider, cost, latency_ms, outcome)
    return {"answer": text, "quote": quote}

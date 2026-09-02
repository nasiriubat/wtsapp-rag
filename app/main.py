import asyncio
import json
import logging
import os
import time
import traceback
from contextlib import asynccontextmanager
from datetime import datetime

import psycopg
from fastapi import FastAPI, Response
from pydantic import BaseModel

import answer
import chunking
import db
import embed
import migrate
import observe
import retrieval

THRESHOLD = float(os.environ["CONFIDENCE_THRESHOLD"])
REFUSAL = "I don't have anything on that."
log = logging.getLogger("app")


async def chunk_loop():
    while True:
        await asyncio.to_thread(chunking.run_once)
        await asyncio.sleep(60)


def _crash(task):
    # A dead loop behind a live server is worse than a restart.
    if not task.cancelled() and task.exception():
        traceback.print_exception(task.exception())
        os._exit(1)


@asynccontextmanager
async def lifespan(app):
    observe.setup_logging()
    migrate.run()
    # Two independent downloads and ONNX sessions; wall time is the max, not the sum.
    await asyncio.gather(asyncio.to_thread(embed.warm), asyncio.to_thread(retrieval.warm))
    task = asyncio.create_task(chunk_loop())
    task.add_done_callback(_crash)
    yield
    task.cancel()


app = FastAPI(lifespan=lifespan)


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


@app.post("/ingest")
def ingest(m: Message):
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
    observe.count("ingest_total")
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


@app.post("/ask")
def ask(q: Question):
    t0 = time.perf_counter()
    chunks, timings = retrieval.search(q.group_id, q.question)
    confidence = chunks[0]["score"] if chunks else 0.0
    tokens_in = tokens_out = None
    text, quote = REFUSAL, None
    if confidence >= THRESHOLD:
        t = time.perf_counter()
        text, tokens_in, tokens_out = answer.generate(q.question, chunks)
        timings["llm_ms"] = round((time.perf_counter() - t) * 1000)
        if text != REFUSAL:
            text, quote = _cite(text, _source(chunks[0]))
    latency_ms = round((time.perf_counter() - t0) * 1000)
    refused = text == REFUSAL
    observe.count("ask_total", outcome="refused" if refused else "answered")
    observe.observe_latency(latency_ms / 1000)
    log.info(
        "ask",
        extra={
            "group": q.group_id,
            "confidence": round(confidence, 3),
            "latency_ms": latency_ms,
            "refused": refused,
        },
    )

    retrieved = {
        "chunks": [{"chunk_id": c["id"], "score": c["score"], "source": c["source"]} for c in chunks],
        "timings": timings,
    }
    with db.connect() as conn:
        conn.execute(
            """
            INSERT INTO query_log
              (group_id, sender_jid, question, retrieved, answer, confidence,
               tokens_in, tokens_out, latency_ms)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                q.group_id,
                q.sender_jid,
                q.question,
                json.dumps(retrieved),
                text,
                confidence,
                tokens_in,
                tokens_out,
                latency_ms,
            ),
        )
    return {"answer": text, "quote": quote}

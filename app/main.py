import asyncio
import base64
import binascii
import logging
import pathlib
import time
from contextlib import asynccontextmanager
from datetime import datetime

import psycopg
from fastapi import Depends, FastAPI, Header, HTTPException, Request, Response
from fastapi.exception_handlers import http_exception_handler, request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import admin
import admin_api
import asking
import bootstrap
import chunking
import db
import documents
import embed
import extraction
import gateway_api
import groups
import migrate
import observe
import retention
import retrieval

log = logging.getLogger("app")


# Each background loop and how often it should tick. /health reports a loop
# that has not completed cleanly in three intervals, so a stalled one is
# visible without taking the server down with it.
LOOPS = [
    (chunking.run_once, 60),
    (extraction.run_once, 90),
    (documents.index_pending, 15),
    (retention.run_once, 3600),
]
last_ok: dict[str, float] = {}
MAX_BACKOFF = 600


async def loop(fn, seconds):
    """A tick that raises is logged and retried after a growing pause. Crashing
    the process instead would turn one poisonous row into a restart loop that
    never clears it."""
    name = fn.__module__
    last_ok[name] = time.monotonic()
    delay = seconds
    while True:
        try:
            await asyncio.to_thread(fn)
            last_ok[name] = time.monotonic()
            delay = seconds
        except Exception:
            log.exception("loop failed", extra={"loop": name, "retry_s": delay})
            delay = min(delay * 2, MAX_BACKOFF)
        await asyncio.sleep(delay)


def stalled_loops(now=None):
    now = time.monotonic() if now is None else now
    return {
        fn.__module__: round(now - last_ok[fn.__module__])
        for fn, seconds in LOOPS
        if fn.__module__ in last_ok and now - last_ok[fn.__module__] > 3 * seconds
    }


@asynccontextmanager
async def lifespan(app):
    observe.setup_logging()
    migrate.run()
    bootstrap.run()
    # Two independent downloads and ONNX sessions; wall time is the max, not the sum.
    await asyncio.gather(asyncio.to_thread(embed.warm), asyncio.to_thread(retrieval.warm))
    tasks = [asyncio.create_task(loop(fn, seconds)) for fn, seconds in LOOPS]
    yield
    for t in tasks:
        t.cancel()


app = FastAPI(lifespan=lifespan)


def _wants_page(request):
    return request.url.path.startswith(("/admin", "/setup")) and "text/html" in request.headers.get(
        "accept", ""
    )


@app.exception_handler(HTTPException)
async def _http_error(request: Request, exc: HTTPException):
    # A redirect to the login page is an HTTPException too; only real errors
    # become a page.
    if _wants_page(request) and exc.status_code >= 400:
        return admin.error_response(request, exc.status_code, exc.detail)
    return await http_exception_handler(request, exc)


@app.exception_handler(RequestValidationError)
async def _validation_error(request: Request, exc: RequestValidationError):
    if _wants_page(request):
        fields = "; ".join(f"{'.'.join(str(p) for p in e['loc'][1:])}: {e['msg']}" for e in exc.errors())
        return admin.error_response(request, 422, fields or "the form was not filled in correctly")
    return await request_validation_exception_handler(request, exc)


@app.middleware("http")
async def _panel_headers(request: Request, call_next):
    response = await call_next(request)
    if request.url.path.startswith(("/admin", "/setup")):
        # No inline script anywhere in the panel, so the policy can say so.
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
            "script-src 'self'; frame-ancestors 'none'; form-action 'self'"
        )
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "same-origin"
    return response


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
def health(response: Response, authorization: str = Header(default="")):
    """Anyone may ask whether it is up. What is stalled and how much is queued
    says how busy the groups are, so that part needs the gateway token."""
    # uvicorn only serves after lifespan finished, so models are loaded whenever
    # this answers. What can be down is the database, or a background loop.
    try:
        with db.connect() as conn:
            last = conn.execute("SELECT end_ts FROM chunks ORDER BY id DESC LIMIT 1").fetchone()
            pending = conn.execute("SELECT count(*) AS n FROM messages WHERE NOT chunked").fetchone()["n"]
    except psycopg.Error as e:
        # The detail names the host, port and user; that goes to the log, which
        # is authenticated, not to an endpoint anyone can call.
        log.error("health check failed", extra={"err": str(e).strip()})
        response.status_code = 503
        return {"db": "down"}
    stalled = stalled_loops()
    if stalled:
        response.status_code = 503
    out = {"db": "ok", "loops": "ok" if not stalled else "stalled"}
    if gateway_api.token_ok(authorization):
        out.update(
            stalled_loops=stalled, last_chunk_ts=last["end_ts"] if last else None, unchunked_messages=pending
        )
    return out


@app.get("/metrics", dependencies=[Depends(gateway_api.require_token)])
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
            ON CONFLICT (group_id, wa_msg_id) DO NOTHING
            """,
            (m.wa_msg_id, m.group_id, m.sender_jid, m.sender_name, m.body, m.quoted_msg_id, m.is_bot, m.ts),
        )
    observe.count("ingest_total", outcome="stored")
    return {"ok": True}


class SharedFile(BaseModel):
    group_id: str
    sender_jid: str
    filename: str
    mime: str | None = None
    data: str  # base64; the gateway caps the size before it gets here


@app.post("/ingest/file", dependencies=[Depends(gateway_api.require_token)])
def ingest_file(f: SharedFile):
    """A file shared in a group the admin has opted into indexing. Everything
    else about it is the same as an upload in the panel."""
    group = groups.get(f.group_id)
    if group is None or not group["enabled"] or not group["settings"]["index_files"]:
        return {"ok": True, "stored": False}
    if f.sender_jid in group["settings"]["opt_out"]:
        return {"ok": True, "stored": False}
    try:
        raw = base64.b64decode(f.data, validate=True)
    except binascii.Error:
        raise HTTPException(422, "data is not base64") from None
    try:
        documents.create(f.group_id, f.filename, f.mime, raw)
    except documents.Unreadable as e:
        log.info("shared file refused", extra={"group": f.group_id, "reason": str(e)})
        return {"ok": True, "stored": False}
    log.info("shared file stored", extra={"group": f.group_id, "bytes": len(raw)})
    return {"ok": True, "stored": True}


class Question(BaseModel):
    question: str
    group_id: str | None = None  # None: a private question, answered from the sender's groups
    sender_jid: str
    sender_name: str | None = None
    wa_msg_id: str
    quoted_msg_id: str | None = None


@app.post("/ask", dependencies=[Depends(gateway_api.require_token)])
def ask(q: Question):
    throttled = asking.throttle(q)
    if throttled:
        return {"answer": throttled["answer"], "quote": None}
    if q.group_id is None:
        res = asking.answer_privately(q)
        return {"answer": res["answer"], "quote": None}
    group = groups.get(q.group_id)
    if group is None or not group["enabled"]:
        return {"answer": None, "quote": None}
    s = group["settings"]
    if q.sender_jid in s["opt_out"] or groups.in_quiet_hours(s):
        observe.count("ask_total", outcome="suppressed")
        return {"answer": None, "quote": None}
    res = asking.try_correction(q, group) or asking.answer_in(q, group)
    log.info(
        "ask",
        extra={
            "group": q.group_id,
            "outcome": res["outcome"],
            "confidence": round(res.get("confidence") or 0.0, 3),
            "latency_ms": (res.get("timings") or {}).get("total_ms"),
        },
    )
    return {"answer": res["answer"], "quote": res["quote"]}

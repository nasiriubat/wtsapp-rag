import asyncio
import os
import traceback
from contextlib import asynccontextmanager
from datetime import datetime

from fastapi import FastAPI
from pydantic import BaseModel

import chunking
import db
import retrieval


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
    task = asyncio.create_task(chunk_loop())
    task.add_done_callback(_crash)
    yield
    task.cancel()


app = FastAPI(lifespan=lifespan)


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
            (m.wa_msg_id, m.group_id, m.sender_jid, m.sender_name, m.body,
             m.quoted_msg_id, m.is_bot, m.ts),
        )
    return {"ok": True}


class Question(BaseModel):
    question: str
    group_id: str
    sender_jid: str
    sender_name: str | None = None
    wa_msg_id: str


@app.post("/ask")
def ask(q: Question):
    chunks, timings = retrieval.search(q.group_id, q.question)
    return {"chunks": chunks, "timings": timings}

"""One writer for the query_log table: questions, refusals and extraction runs."""

import json
from contextlib import nullcontext

import db


def record(
    *,
    group_id,
    question,
    outcome,
    sender_jid=None,
    answer=None,
    chunks=(),
    fact_ids=(),
    timings=None,
    confidence=None,
    tokens=(None, None),
    provider=None,
    cost=None,
    conn=None,
):
    retrieved = {
        "chunks": [{"chunk_id": c["id"], "score": c["score"], "source": c["source"]} for c in chunks],
        "facts": list(fact_ids),
        "timings": timings or {},
    }
    with nullcontext(conn) if conn is not None else db.connect() as conn:
        conn.execute(
            """
            INSERT INTO query_log
              (group_id, sender_jid, question, retrieved, answer, confidence,
               tokens_in, tokens_out, latency_ms, provider_id, cost, outcome)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                group_id,
                sender_jid,
                question,
                json.dumps(retrieved),
                answer,
                confidence,
                tokens[0],
                tokens[1],
                (timings or {}).get("total_ms"),
                provider["id"] if provider else None,
                cost,
                outcome,
            ),
        )

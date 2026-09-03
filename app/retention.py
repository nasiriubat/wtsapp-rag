"""Data lifecycle: retention windows and member erasure."""

import logging

import db

log = logging.getLogger(__name__)


def run_once():
    with db.connect() as conn:
        for table, col in (("chunks", "end_ts"), ("messages", "ts")):
            n = conn.execute(
                f"""
                DELETE FROM {table} t USING groups g
                WHERE t.group_id = g.external_id
                  AND g.settings->>'retention_days' IS NOT NULL
                  AND t.{col} < now() - make_interval(days => (g.settings->>'retention_days')::int)
                """
            ).rowcount
            if n:
                log.info("retention", extra={"table": table, "deleted": n})


def purge_sender(group_external_id, sender_jid):
    """Erase one member: their messages, and every chunk built from an episode
    that contained them. The other messages of those episodes are re-chunked
    by the loop, so nothing they said survives inside a chunk either."""
    with db.connect() as conn, conn.transaction():
        conn.execute(
            """
            CREATE TEMP TABLE affected ON COMMIT DROP AS
            SELECT c.id, c.start_ts, c.end_ts FROM chunks c
            WHERE c.group_id = %s AND EXISTS (
              SELECT 1 FROM messages m
              WHERE m.group_id = c.group_id AND m.sender_jid = %s AND m.ts BETWEEN c.start_ts AND c.end_ts)
            """,
            (group_external_id, sender_jid),
        )
        conn.execute(
            "UPDATE messages m SET chunked = false FROM affected a "
            "WHERE m.group_id = %s AND m.ts BETWEEN a.start_ts AND a.end_ts",
            (group_external_id,),
        )
        chunks = conn.execute("DELETE FROM chunks WHERE id IN (SELECT id FROM affected)").rowcount
        messages = conn.execute(
            "DELETE FROM messages WHERE group_id = %s AND sender_jid = %s", (group_external_id, sender_jid)
        ).rowcount
    log.info("purged sender", extra={"group": group_external_id, "messages": messages, "chunks": chunks})
    return messages

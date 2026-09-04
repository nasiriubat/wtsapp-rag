"""Background loop: turn new chunks into facts, group by group, with the
group's provider. Bounded per tick so one busy group cannot starve the rest."""

import logging

import budget
import db
import facts
import groups
import providers

log = logging.getLogger(__name__)
PER_TICK = 20


def _log(group_id, chunk_id, added, tokens_in, tokens_out, provider):
    with db.connect() as conn:
        conn.execute(
            """
            INSERT INTO query_log
              (group_id, question, answer, tokens_in, tokens_out, provider_id, cost, outcome)
            VALUES (%s, %s, %s, %s, %s, %s, %s, 'extract')
            """,
            (
                group_id,
                f"[extract] chunk {chunk_id}",
                f"{added} facts",
                tokens_in,
                tokens_out,
                provider["id"],
                providers.cost(provider, tokens_in, tokens_out),
            ),
        )


def run_once():
    global_settings = groups.global_settings()
    for group in groups.list_all():
        if not group["enabled"] or not group["settings"]["decision_tracking"]:
            continue
        provider = providers.resolve(group, global_settings)
        if provider is None or budget.exceeded(group, global_settings):
            continue
        with db.connect() as conn:
            pending = conn.execute(
                "SELECT id, group_id, content, first_msg_id, start_ts, end_ts FROM chunks "
                "WHERE group_id = %s AND NOT facts_extracted ORDER BY id LIMIT %s",
                (group["external_id"], PER_TICK),
            ).fetchall()
        for chunk in pending:
            try:
                added, tin, tout = facts.extract(chunk, provider)
            except Exception as e:  # noqa: BLE001  (a provider outage must not stop the loop)
                log.warning("extraction failed", extra={"chunk": chunk["id"], "err": str(e)})
                break
            with db.connect() as conn:
                conn.execute("UPDATE chunks SET facts_extracted = true WHERE id = %s", (chunk["id"],))
            _log(group["external_id"], chunk["id"], added, tin, tout, provider)

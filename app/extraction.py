"""Background loop: turn new chunks into facts, group by group, with the
group's provider. Bounded per tick so one busy group cannot starve the rest."""

import logging

import httpx

import budget
import db
import facts
import groups
import providers
import query_log

log = logging.getLogger(__name__)
PER_TICK = 20


def _refused(err):
    """A 4xx other than rate limiting is the provider's final word on this chunk."""
    if not isinstance(err, httpx.HTTPStatusError):
        return False
    status = err.response.status_code
    return 400 <= status < 500 and status != 429


def _mark(chunk_id):
    with db.connect() as conn:
        conn.execute("UPDATE chunks SET facts_extracted = true WHERE id = %s", (chunk_id,))


def run_once():
    global_settings = groups.global_settings()
    with db.connect() as conn:
        pending_by_group = {
            r["group_id"]: r["n"]
            for r in conn.execute(
                "SELECT group_id, count(*) AS n FROM chunks WHERE NOT facts_extracted GROUP BY group_id"
            )
        }
    for group in groups.list_all():
        if not pending_by_group.get(group["external_id"]):
            continue  # nothing to do: no provider lookup, no budget scan
        if not group["enabled"] or not group["settings"]["decision_tracking"]:
            continue
        provider = providers.resolve(group, global_settings)
        if provider is None or budget.exceeded(group, global_settings):
            continue
        with db.connect() as conn:
            pending = conn.execute(
                "SELECT id, group_id, content, first_msg_id, start_ts, end_ts, embedding FROM chunks "
                "WHERE group_id = %s AND NOT facts_extracted ORDER BY id LIMIT %s",
                (group["external_id"], PER_TICK),
            ).fetchall()
        for chunk in pending:
            try:
                added, tokens_in, tokens_out = facts.extract(chunk, provider)
            except Exception as e:  # noqa: BLE001  (a provider outage must not stop the loop)
                if _refused(e):
                    # The provider will never take this chunk (content filter, too
                    # long). Leaving it unmarked would block every chunk behind it.
                    log.warning("chunk skipped by provider", extra={"chunk": chunk["id"], "err": str(e)})
                    _mark(chunk["id"])
                    continue
                log.warning("extraction failed", extra={"chunk": chunk["id"], "err": str(e)})
                break
            _mark(chunk["id"])
            query_log.record(
                group_id=group["external_id"],
                question=f"[extract] chunk {chunk['id']}",
                answer=f"{added} facts",
                outcome="extract",
                tokens=(tokens_in, tokens_out),
                provider=provider,
                cost=providers.cost(provider, tokens_in, tokens_out),
            )

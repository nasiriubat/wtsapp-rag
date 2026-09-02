import logging

import db
import groups

log = logging.getLogger(__name__)


def run_once():
    for g in groups.list_all():
        days = g["settings"]["retention_days"]
        if days is None:
            continue
        with db.connect() as conn:
            chunks = conn.execute(
                "DELETE FROM chunks WHERE group_id = %s AND end_ts < now() - make_interval(days => %s)",
                (g["external_id"], days),
            ).rowcount
            messages = conn.execute(
                "DELETE FROM messages WHERE group_id = %s AND ts < now() - make_interval(days => %s)",
                (g["external_id"], days),
            ).rowcount
        if chunks or messages:
            log.info("retention", extra={"group": g["external_id"], "chunks": chunks, "messages": messages})

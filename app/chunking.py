import logging
from datetime import UTC, datetime, timedelta
from itertools import groupby

import db
import embed

log = logging.getLogger(__name__)
GAP = timedelta(minutes=30)
MAX_MESSAGES = 15
MAX_CHARS = 1600  # roughly 400 tokens


def _full(episode):
    return len(episode) >= MAX_MESSAGES or sum(len(m["body"]) for m in episode) >= MAX_CHARS


def episodes(messages, now):
    out, cur = [], []
    for m in messages:
        if cur and (m["ts"] - cur[-1]["ts"] > GAP or _full(cur)):
            out.append(cur)
            cur = []
        cur.append(m)
    # The tail stays open until 30 minutes of silence. Otherwise every tick
    # would cut a live conversation into fragments.
    if cur and (_full(cur) or now - cur[-1]["ts"] > GAP):
        out.append(cur)
    return out


def _content(episode):
    return "\n".join(f"{m['sender_name'] or m['sender_jid']}: {m['body']}" for m in episode)


def run_once():
    now = datetime.now(UTC)
    with db.connect() as conn:
        # Our own answers are derived from the history; indexing them would make
        # retrieval feed on itself. Empty bodies carry nothing to search.
        conn.execute(
            "UPDATE messages SET chunked = true WHERE NOT chunked AND (is_bot OR body IS NULL OR body = '')"
        )
        rows = conn.execute(
            """
            SELECT m.group_id, m.wa_msg_id, m.sender_name, m.sender_jid, m.body, m.ts
            FROM messages m LEFT JOIN groups g ON g.external_id = m.group_id
            WHERE NOT m.chunked AND NOT coalesce(g.settings->'opt_out' ? m.sender_jid, false)
            ORDER BY m.group_id, m.ts
            """
        ).fetchall()
        for group_id, msgs in groupby(rows, key=lambda r: r["group_id"]):
            eps = episodes(list(msgs), now)
            if not eps:
                continue
            vectors = embed.passages([_content(ep) for ep in eps])
            for ep, vec in zip(eps, vectors, strict=True):
                with conn.transaction():
                    conn.execute(
                        """
                        INSERT INTO chunks (group_id, content, first_msg_id, start_ts, end_ts, embedding)
                        VALUES (%s, %s, %s, %s, %s, %s::vector)
                        """,
                        (
                            group_id,
                            _content(ep),
                            ep[0]["wa_msg_id"],
                            ep[0]["ts"],
                            ep[-1]["ts"],
                            embed.literal(vec),
                        ),
                    )
                    # Scoped: message ids are unique per group, not globally, so
                    # an id chosen in one group must not flag another's message.
                    conn.execute(
                        "UPDATE messages SET chunked = true WHERE group_id = %s AND wa_msg_id = ANY(%s)",
                        (group_id, [m["wa_msg_id"] for m in ep]),
                    )
            log.info("chunked", extra={"group": group_id, "episodes": len(eps)})

from datetime import datetime, timedelta, timezone
from itertools import groupby

import db
import embed

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
    now = datetime.now(timezone.utc)
    with db.connect() as conn:
        # Our own answers are derived from the history; indexing them would make
        # retrieval feed on itself. Empty bodies carry nothing to search.
        conn.execute(
            "UPDATE messages SET chunked = true WHERE NOT chunked AND (is_bot OR body IS NULL OR body = '')"
        )
        rows = conn.execute(
            """
            SELECT group_id, wa_msg_id, sender_name, sender_jid, body, ts
            FROM messages WHERE NOT chunked ORDER BY group_id, ts
            """
        ).fetchall()
        for group_id, msgs in groupby(rows, key=lambda r: r["group_id"]):
            eps = episodes(list(msgs), now)
            if not eps:
                continue
            vectors = embed.passages([_content(ep) for ep in eps])
            for ep, vec in zip(eps, vectors):
                with conn.transaction():
                    conn.execute(
                        """
                        INSERT INTO chunks (group_id, content, first_msg_id, start_ts, end_ts, embedding)
                        VALUES (%s, %s, %s, %s, %s, %s::vector)
                        """,
                        (group_id, _content(ep), ep[0]["wa_msg_id"], ep[0]["ts"], ep[-1]["ts"], embed.literal(vec)),
                    )
                    conn.execute(
                        "UPDATE messages SET chunked = true WHERE wa_msg_id = ANY(%s)",
                        ([m["wa_msg_id"] for m in ep],),
                    )
            print(f"chunked {len(eps)} episodes for {group_id}")

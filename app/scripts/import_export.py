"""Load a WhatsApp chat export (.txt) into the messages table.

    docker compose exec -T app python scripts/import_export.py <group_jid> < export.txt

Re-running is idempotent: wa_msg_id is derived from the message content.
"""

import hashlib
import os
import re
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import db  # noqa: E402

# Exports carry the phone's local time with no zone marker.
TZ = ZoneInfo("Europe/Helsinki")

# Covers iOS "[12/03/2026, 14:05:33] Name: text", Android "12/03/2026, 14:05 - Name: text",
# and the Finnish locale "12.3.2026 klo 14.05.33". Day comes first in all of them.
HEADER = re.compile(
    r"^\[?(?P<date>\d{1,2}[./]\d{1,2}[./]\d{2,4})(?:,\s*|\s+klo\s+)"
    r"(?P<time>\d{1,2}[:.]\d{2}(?:[:.]\d{2})?)\s*(?P<ampm>[AaPp]\.?[Mm]\.?)?\]?\s*(?:-\s*)?"
    r"(?P<rest>.*)$"
)
NAMED = re.compile(r"^(?P<name>[^:]+?):\s(?P<text>.*)$", re.S)
PLACEHOLDER = re.compile(
    r"^<?(?:Media|image|video|audio|sticker|GIF|document|Contact card) omitted>?$|^<attached:", re.I
)
# WhatsApp sprinkles bidi marks at line starts and around names; they are invisible
# in an editor and break every regex above.
INVISIBLE = "‎‏‪‫‬‭‮"


def _month_first(lines):
    # A US-locale export is month-first. The file itself tells us: any first
    # field above 12 means day-first, any second field above 12 means month-first.
    # Ambiguous files (every day <= 12) default to day-first, like WhatsApp
    # everywhere outside the US.
    for line in lines:
        head = HEADER.match(line.strip(INVISIBLE))
        if not head:
            continue
        first, second, _ = (int(x) for x in re.split(r"[./]", head["date"]))
        if first > 12:
            return False
        if second > 12:
            return True
    return False


def _timestamp(date, time, ampm, month_first):
    d, m, y = (int(x) for x in re.split(r"[./]", date))
    if month_first:
        d, m = m, d
    if y < 100:
        y += 2000
    parts = [int(x) for x in re.split(r"[:.]", time)]
    hour, minute = parts[0], parts[1]
    second = parts[2] if len(parts) > 2 else 0
    if ampm:
        pm = ampm.lower().startswith("p")
        hour = hour % 12 + (12 if pm else 0)
    return datetime(y, m, d, hour, minute, second, tzinfo=TZ)


def parse(lines):
    lines = [raw.rstrip("\n") for raw in lines]
    month_first = _month_first(lines)
    messages = []
    for raw in lines:
        line = raw.strip(INVISIBLE)
        head = HEADER.match(line)
        if head:
            named = NAMED.match(head["rest"])
            if not named:
                messages.append(None)  # system line: joins, leaves, encryption notice
                continue
            messages.append(
                {
                    "ts": _timestamp(head["date"], head["time"], head["ampm"], month_first),
                    "sender_name": named["name"].strip(INVISIBLE + " "),
                    "body": named["text"].strip(INVISIBLE),
                }
            )
        elif messages and messages[-1] is not None:
            messages[-1]["body"] += "\n" + line
    out = []
    for m in messages:
        if m is None:
            continue
        m["body"] = m["body"].strip()
        if not m["body"] or PLACEHOLDER.match(m["body"]):
            continue
        out.append(m)
    return out


def insert(group_id, messages):
    rows = []
    for m in messages:
        digest = hashlib.sha1(
            f"{group_id}|{m['ts'].isoformat()}|{m['sender_name']}|{m['body']}".encode()
        ).hexdigest()
        rows.append(
            (
                f"import:{digest[:16]}",
                group_id,
                f"import:{m['sender_name']}",
                m["sender_name"],
                m["body"],
                m["ts"],
            )
        )
    with db.connect() as conn:
        with conn.cursor() as cur:
            cur.executemany(
                """
                INSERT INTO messages (wa_msg_id, group_id, sender_jid, sender_name, body, ts)
                VALUES (%s, %s, %s, %s, %s, %s) ON CONFLICT (wa_msg_id) DO NOTHING
                """,
                rows,
            )
            # Rows actually written; re-imports report 0, not the file length.
            return cur.rowcount


if __name__ == "__main__":
    group_id = sys.argv[1]
    parsed = parse(sys.stdin)
    n = insert(group_id, parsed)
    print(f"parsed {n} messages into {group_id}")

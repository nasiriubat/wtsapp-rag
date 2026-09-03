import uuid
from datetime import UTC, datetime, timedelta

from conftest import AUTH, needs_db

pytestmark = needs_db
NOW = datetime(2026, 9, 3, 12, 0, tzinfo=UTC)


def _seed(gid, rows):
    import db

    with db.connect() as conn:
        for i, (sender, body, ts) in enumerate(rows):
            conn.execute(
                "INSERT INTO messages (wa_msg_id, group_id, sender_jid, sender_name, body, ts, chunked) "
                "VALUES (%s, %s, %s, %s, %s, %s, true)",
                (f"{gid}-{i}", gid, sender, sender, body, ts),
            )


def test_opting_out_erases_history_and_rebuilds_affected_chunks(client):
    import db
    import groups

    gid = f"test-{uuid.uuid4()}@g.us"
    group = groups.create("whatsapp", gid)
    _seed(
        gid,
        [
            ("anna", "a1", NOW),
            ("bob", "b1", NOW + timedelta(minutes=1)),
            ("anna", "a2", NOW + timedelta(hours=5)),
        ],
    )
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO chunks (group_id, content, first_msg_id, start_ts, end_ts) "
            "VALUES (%s, %s, %s, %s, %s)",
            (gid, "anna: a1\nbob: b1", f"{gid}-0", NOW, NOW + timedelta(minutes=1)),
        )
        conn.execute(
            "INSERT INTO chunks (group_id, content, first_msg_id, start_ts, end_ts) "
            "VALUES (%s, %s, %s, %s, %s)",
            (gid, "anna: a2", f"{gid}-2", NOW + timedelta(hours=5), NOW + timedelta(hours=5)),
        )

    res = client.patch(f"/api/groups/{group['id']}", json={"settings": {"opt_out": ["bob"]}}, auth=AUTH)
    assert res.status_code == 200

    with db.connect() as conn:
        left = conn.execute(
            "SELECT sender_jid, chunked FROM messages WHERE group_id = %s ORDER BY ts", (gid,)
        ).fetchall()
        chunks = conn.execute("SELECT content FROM chunks WHERE group_id = %s", (gid,)).fetchall()
        purge = conn.execute(
            "SELECT detail FROM audit_log WHERE action = 'member.purge' AND target = %s", (gid,)
        ).fetchone()
    # bob is gone; anna's episode with bob is queued for re-chunking; her later chunk is untouched.
    assert [(r["sender_jid"], r["chunked"]) for r in left] == [("anna", False), ("anna", True)]
    assert [c["content"] for c in chunks] == ["anna: a2"]
    assert purge["detail"]["messages"] == 1

    with db.connect() as conn:
        conn.execute("DELETE FROM chunks WHERE group_id = %s", (gid,))
        conn.execute("DELETE FROM messages WHERE group_id = %s", (gid,))
    groups.delete(group["id"])


def test_retention_deletes_only_past_the_window(client):
    import db
    import groups
    import retention

    gid = f"test-{uuid.uuid4()}@g.us"
    group = groups.create("whatsapp", gid, settings={"retention_days": 30})
    old, new = datetime.now(UTC) - timedelta(days=40), datetime.now(UTC) - timedelta(days=1)
    _seed(gid, [("anna", "old", old), ("anna", "new", new)])
    retention.run_once()
    with db.connect() as conn:
        left = conn.execute("SELECT body FROM messages WHERE group_id = %s", (gid,)).fetchall()
        conn.execute("DELETE FROM messages WHERE group_id = %s", (gid,))
    assert [r["body"] for r in left] == ["new"]
    groups.delete(group["id"])

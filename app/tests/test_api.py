import uuid

from conftest import GW, needs_db

pytestmark = needs_db


def test_ingest_is_idempotent_and_drops_unknown_groups(client):
    import db
    import groups

    gid = f"test-{uuid.uuid4()}@g.us"
    body = {
        "wa_msg_id": f"{gid}-1",
        "group_id": gid,
        "sender_jid": "1@s",
        "body": "hello",
        "ts": "2026-09-02T20:00:00Z",
    }

    assert client.post("/ingest", json=body, headers=GW).json() == {"ok": True}
    with db.connect() as conn:
        assert (
            conn.execute("SELECT count(*) AS n FROM messages WHERE group_id = %s", (gid,)).fetchone()["n"]
            == 0
        )

    group = groups.create("whatsapp", gid)
    for _ in range(2):
        assert client.post("/ingest", json=body, headers=GW).json() == {"ok": True}
    with db.connect() as conn:
        assert (
            conn.execute("SELECT count(*) AS n FROM messages WHERE group_id = %s", (gid,)).fetchone()["n"]
            == 1
        )
        conn.execute("DELETE FROM messages WHERE group_id = %s", (gid,))
    groups.delete(group["id"])


def test_health_reports_db_state(client, monkeypatch):
    res = client.get("/health")
    assert res.status_code == 200
    assert res.json()["db"] == "ok"

    monkeypatch.setenv("DATABASE_URL", "postgresql://nobody:x@127.0.0.1:1/none")
    res = client.get("/health")
    assert res.status_code == 503
    assert res.json()["db"] == "down"


def test_metrics_endpoint_is_prometheus_text(client):
    res = client.get("/metrics")
    assert res.status_code == 200
    assert "# TYPE ask_latency_seconds histogram" in res.text


def test_every_migration_file_is_recorded(client):
    import db
    import migrate

    with db.connect() as conn:
        rows = conn.execute("SELECT version FROM schema_migrations ORDER BY version").fetchall()
    assert [r["version"] for r in rows] == sorted(p.name for p in migrate.DIR.glob("*.sql"))

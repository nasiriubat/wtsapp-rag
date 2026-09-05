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
    from conftest import GW

    assert client.get("/metrics").status_code == 401  # says how busy the groups are
    res = client.get("/metrics", headers=GW)
    assert res.status_code == 200
    assert "# TYPE ask_latency_seconds histogram" in res.text


def test_every_migration_file_is_recorded(client):
    import db
    import migrate

    with db.connect() as conn:
        rows = conn.execute("SELECT version FROM schema_migrations ORDER BY version").fetchall()
    assert [r["version"] for r in rows] == sorted(p.name for p in migrate.DIR.glob("*.sql"))


def test_a_loop_that_raises_backs_off_instead_of_ending_the_process():
    import asyncio

    import main

    ticks = []

    def flaky():
        ticks.append(1)
        if len(ticks) == 1:
            raise RuntimeError("one bad tick")

    async def run():
        task = asyncio.create_task(main.loop(flaky, 0.01))
        await asyncio.sleep(0.2)
        task.cancel()

    asyncio.run(run())
    assert len(ticks) >= 3  # it kept going after the failure


def test_health_reports_a_stalled_loop(client, monkeypatch):
    import time

    import main

    fn, seconds = main.LOOPS[0]
    from conftest import GW

    monkeypatch.setitem(main.last_ok, fn.__module__, time.monotonic() - 10 * seconds)
    res = client.get("/health", headers=GW)
    assert res.status_code == 503
    assert res.json()["loops"] == "stalled" and fn.__module__ in res.json()["stalled_loops"]

    monkeypatch.setitem(main.last_ok, fn.__module__, time.monotonic())
    assert client.get("/health").json()["loops"] == "ok"

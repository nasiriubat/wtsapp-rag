import os
import uuid

import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.skipif(not os.environ.get("DATABASE_URL"), reason="needs Postgres (DATABASE_URL)")


@pytest.fixture(scope="module")
def client():
    import db
    import migrate
    from main import app

    migrate.run()
    # No lifespan: that would load the models and start the chunk loop.
    yield TestClient(app)
    with db.connect() as conn:
        conn.execute("DELETE FROM messages WHERE group_id LIKE 'test-%'")


def test_ingest_is_idempotent(client):
    import db

    group = f"test-{uuid.uuid4()}@g.us"
    body = {
        "wa_msg_id": f"{group}-1",
        "group_id": group,
        "sender_jid": "1@s",
        "sender_name": "Anna",
        "body": "hello",
        "ts": "2026-09-02T20:00:00Z",
    }
    for _ in range(2):
        assert client.post("/ingest", json=body).json() == {"ok": True}
    with db.connect() as conn:
        n = conn.execute("SELECT count(*) AS n FROM messages WHERE group_id = %s", (group,)).fetchone()["n"]
    assert n == 1


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

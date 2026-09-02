"""The /ask decision tree with retrieval and the LLM replaced by fakes.
Needs Postgres for groups, providers and the query log."""

import os
import uuid
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.skipif(not os.environ.get("DATABASE_URL"), reason="needs Postgres (DATABASE_URL)")

GW = {"authorization": f"Bearer {os.environ.get('GATEWAY_TOKEN', '')}"}
NOW = datetime(2026, 9, 3, 12, 0, tzinfo=UTC)


def fake_chunks(score):
    return [
        {
            "id": 1,
            "content": "Anna: x",
            "first_msg_id": "src-1",
            "start_ts": NOW,
            "end_ts": NOW,
            "score": score,
            "source": "vector",
        }
    ], {"embed_ms": 1}


@pytest.fixture()
def env(monkeypatch):
    import db
    import groups
    import migrate
    import providers
    import retrieval
    from main import app

    migrate.run()
    gid = f"test-{uuid.uuid4()}@g.us"
    group = groups.create("whatsapp", gid, settings={"confidence_threshold": 0.5})
    provider = providers.create("p", "openai", "k", "m", price_in=1, price_out=1)
    groups.set_global(default_provider_id=provider["id"])
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO messages (wa_msg_id, group_id, sender_jid, sender_name, body, ts) "
            "VALUES (%s, %s, %s, %s, %s, %s)",
            ("src-1", gid, "1@s", "Anna", "the source", NOW),
        )
    monkeypatch.setattr(retrieval, "search", lambda g, q: fake_chunks(0.9))
    monkeypatch.setattr(providers, "generate", lambda p, s, u: ("An answer.", 100, 10))
    yield {"client": TestClient(app), "gid": gid, "group": group, "provider": provider}
    with db.connect() as conn:
        conn.execute("DELETE FROM messages WHERE wa_msg_id = 'src-1'")
        conn.execute("DELETE FROM query_log WHERE group_id = %s", (gid,))
    groups.delete(group["id"])
    providers.delete(provider["id"])
    groups.set_global(default_provider_id=None)


def ask(env, **over):
    body = {"question": "q?", "group_id": env["gid"], "sender_jid": "2@s", "wa_msg_id": "m1", **over}
    return env["client"].post("/ask", json=body, headers=GW)


def test_rejects_without_gateway_token(env):
    res = env["client"].post(
        "/ask", json={"question": "q", "group_id": env["gid"], "sender_jid": "2@s", "wa_msg_id": "m"}
    )
    assert res.status_code == 401


def test_unknown_group_is_silent(env):
    assert ask(env, group_id="nobody@g.us").json() == {"answer": None, "quote": None}


def test_answers_with_quote_and_logs_cost(env):
    import db

    res = ask(env).json()
    assert res["answer"] == "An answer."
    assert res["quote"]["wa_msg_id"] == "src-1"
    with db.connect() as conn:
        row = conn.execute("SELECT * FROM query_log WHERE group_id = %s", (env["gid"],)).fetchone()
    assert row["provider_id"] == env["provider"]["id"]
    assert float(row["cost"]) == pytest.approx(110 / 1_000_000)


def test_refuses_below_threshold_without_calling_provider(env, monkeypatch):
    import providers
    import retrieval

    monkeypatch.setattr(retrieval, "search", lambda g, q: fake_chunks(0.2))
    monkeypatch.setattr(providers, "generate", lambda *a: pytest.fail("provider must not be called"))
    assert ask(env).json() == {"answer": "I don't have anything on that.", "quote": None}


def test_budget_cap_stops_answering(env):
    import groups

    groups.update(env["group"]["id"], settings={**env["group"]["settings"], "monthly_cap_eur": 0})
    assert ask(env).json()["answer"].startswith("The monthly answer budget is used up")


def test_no_provider_configured(env):
    import groups

    groups.set_global(default_provider_id=None)
    assert ask(env).json()["answer"].startswith("No LLM provider is configured")


def test_opted_out_member_and_quiet_hours_are_silent(env):
    import groups

    groups.update(env["group"]["id"], settings={**env["group"]["settings"], "opt_out": ["2@s"]})
    assert ask(env).json() == {"answer": None, "quote": None}
    groups.update(
        env["group"]["id"],
        settings={**env["group"]["settings"], "quiet_hours": {"start": "00:00", "end": "23:59", "tz": "UTC"}},
    )
    assert ask(env, sender_jid="3@s").json() == {"answer": None, "quote": None}


def test_opted_out_member_is_not_stored(env):
    import db
    import groups

    groups.update(env["group"]["id"], settings={**env["group"]["settings"], "opt_out": ["9@s"]})
    body = {
        "wa_msg_id": f"{env['gid']}-o",
        "group_id": env["gid"],
        "sender_jid": "9@s",
        "body": "x",
        "ts": "2026-09-03T00:00:00Z",
    }
    assert env["client"].post("/ingest", json=body, headers=GW).json() == {"ok": True}
    with db.connect() as conn:
        n = conn.execute(
            "SELECT count(*) AS n FROM messages WHERE wa_msg_id = %s", (body["wa_msg_id"],)
        ).fetchone()["n"]
    assert n == 0

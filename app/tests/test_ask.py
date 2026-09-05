"""The /ask decision tree with retrieval and the LLM replaced by fakes.
Needs Postgres for groups, providers and the query log."""

import uuid
from datetime import UTC, datetime

import pytest
from conftest import GW, needs_db

pytestmark = needs_db
NOW = datetime(2026, 9, 3, 12, 0, tzinfo=UTC)


def fake_chunks(score, gid=None):
    chunk = {
        "id": 1,
        "group_id": gid,
        "content": "Anna: x",
        "first_msg_id": "src-1",
        "start_ts": NOW,
        "end_ts": NOW,
    }
    return [{**chunk, "score": score, "source": "vector"}], {"embed_ms": 1}


@pytest.fixture()
def env(client, monkeypatch):
    import db
    import groups
    import providers
    import retrieval

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
    import facts

    monkeypatch.setattr(retrieval, "search", lambda g, q, conn=None: fake_chunks(0.9, g))
    monkeypatch.setattr(facts, "search", lambda g, q, conn=None: [])
    monkeypatch.setattr(providers, "generate", lambda p, s, u: ("An answer.", 100, 10))
    yield {"client": client, "gid": gid, "group": group, "provider": provider}
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
    body = {"question": "q", "group_id": env["gid"], "sender_jid": "2@s", "wa_msg_id": "m"}
    assert env["client"].post("/ask", json=body).status_code == 401


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


def test_model_sentinel_becomes_the_groups_refusal_text(env, monkeypatch):
    import groups
    import providers

    groups.update(env["group"]["id"], settings={**env["group"]["settings"], "refusal_text": "Ei tietoa."})
    monkeypatch.setattr(providers, "generate", lambda p, s, u: ("NO_ANSWER.", 100, 2))
    assert ask(env).json() == {"answer": "Ei tietoa.", "quote": None}


def test_missing_usage_is_estimated_so_budgets_still_count(env, monkeypatch):
    import db
    import providers

    monkeypatch.setattr(providers, "generate", lambda p, s, u: ("An answer.", None, None))
    ask(env)
    with db.connect() as conn:
        row = conn.execute(
            "SELECT tokens_in, cost FROM query_log WHERE group_id = %s", (env["gid"],)
        ).fetchone()
    assert row["tokens_in"] > 0 and float(row["cost"]) > 0


def test_refuses_below_threshold_without_calling_provider(env, monkeypatch):
    import providers
    import retrieval

    monkeypatch.setattr(retrieval, "search", lambda g, q, conn=None: fake_chunks(0.2, g))
    monkeypatch.setattr(providers, "generate", lambda *a: pytest.fail("provider must not be called"))
    assert ask(env).json() == {"answer": "I don't have anything on that.", "quote": None}


def test_budget_cap_stops_answering(env):
    import groups

    groups.update(env["group"]["id"], settings={**env["group"]["settings"], "monthly_cap_eur": 0})
    assert ask(env).json()["answer"].startswith("The monthly answer budget is used up")


def test_disabled_pinned_provider_falls_back_to_default(env):
    import groups
    import providers

    pinned = providers.create("off", "openai", "k", "m", enabled=False)
    groups.update(env["group"]["id"], provider_id=pinned["id"])
    assert ask(env).json()["answer"] == "An answer."
    providers.delete(pinned["id"])


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
        ).fetchone()
    assert n["n"] == 0

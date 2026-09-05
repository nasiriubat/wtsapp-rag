"""Ask from the panel, the finished wizard, the audit page, the banner,
members and decisions on a group."""

import time
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from conftest import needs_db, post

pytestmark = needs_db


@pytest.fixture()
def ready(browser, monkeypatch):
    """A group with a provider, retrieval and the model faked."""
    import db
    import facts
    import groups
    import providers
    import retrieval

    gid = f"p5-{uuid.uuid4()}@g.us"
    group = groups.create("whatsapp", gid, name="Cabin crew")
    provider = providers.create("p", "openai", "k", "m", price_in=1, price_out=1)
    before = groups.global_settings()["default_provider_id"]
    groups.set_global(default_provider_id=provider["id"])
    now = datetime.now(UTC)
    chunk = {
        "id": 1,
        "group_id": gid,
        "content": "Anna: sauna on Friday",
        "first_msg_id": "src",
        "start_ts": now - timedelta(days=1),
        "end_ts": now + timedelta(days=1),
        "score": 0.9,
        "source": "vector",
        "document_id": None,
        "source_label": None,
    }
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO messages (wa_msg_id, group_id, sender_jid, sender_name, body, ts) VALUES "
            "('src', %s, 'anna@s', 'Anna', 'sauna on Friday', now()), "
            "('m2', %s, 'bob@s', 'Bob', 'ok', now())",
            (gid, gid),
        )
        conn.execute(
            "INSERT INTO facts (group_id, statement, kind, valid_from) "
            "VALUES (%s, 'Sauna is on Fridays', 'decision', now())",
            (gid,),
        )
    monkeypatch.setattr(retrieval, "search", lambda g, q, conn=None: ([dict(chunk)], {"embed_ms": 1}))
    monkeypatch.setattr(facts, "search", lambda g, q, conn=None: [])
    monkeypatch.setattr(providers, "generate", lambda p, s, u: ("Friday at six.", 10, 5))
    yield {"browser": browser, "group": group, "gid": gid}
    groups.delete(group["id"])
    providers.delete(provider["id"])
    groups.set_global(default_provider_id=before)


def test_asking_from_the_panel_answers_and_logs_like_a_member(ready):
    import db

    b, group = ready["browser"], ready["group"]
    res = b.post(
        "/admin/questions/ask",
        data={"csrf": b.csrf, "group_id": str(group["id"]), "question": "when is the sauna?"},
        headers={"hx-request": "true"},
    )
    assert res.status_code == 200
    assert "Friday at six." in res.text and "Retrieved 1 chunk" in res.text and "sauna on Friday" in res.text
    with db.connect() as conn:
        row = conn.execute(
            "SELECT sender_jid, outcome FROM query_log WHERE group_id = %s ORDER BY id DESC LIMIT 1",
            (ready["gid"],),
        ).fetchone()
    assert row["sender_jid"] == "admin:panel" and row["outcome"] == "answered"
    # The box is on the Questions page and the wizard's last step.
    assert "Ask it from here" in b.get("/admin/questions").text
    assert "Ask it from here" in b.get("/setup/test").text


def test_login_returns_to_the_page_that_was_asked_for(client):
    import os

    client.cookies.clear()
    res = client.get("/setup/groups", follow_redirects=False)
    assert res.status_code == 303 and res.headers["location"] == "/admin/login?next=/setup/groups"
    page = client.get("/admin/login?next=/setup/groups").text
    assert 'name="next" value="/setup/groups"' in page
    res = client.post(
        "/admin/login",
        data={"password": os.environ["ADMIN_PASSWORD"], "next": "/setup/groups"},
        follow_redirects=False,
    )
    assert res.headers["location"] == "/setup/groups"
    # Never off-site.
    res = client.post(
        "/admin/login",
        data={"password": os.environ["ADMIN_PASSWORD"], "next": "//evil.example"},
        follow_redirects=False,
    )
    assert res.headers["location"] == "/admin"
    client.cookies.clear()


def test_the_wizard_says_so_once_everything_is_in_place(ready):
    import gateway_state

    b = ready["browser"]
    gateway_state.update("whatsapp", connected=True, jid="358@s", groups=[])
    page = b.get("/setup").text
    assert "You're set up" in page and "Cabin crew" in page and "Ask it something" in page
    assert "System check" in b.get("/setup?checks=1").text
    gateway_state.update("whatsapp", connected=False, groups=[])


def test_a_missing_gateway_stops_the_wizard(browser, monkeypatch):
    import gateway_state

    monkeypatch.setattr(gateway_state, "any_reported", lambda: False)
    page = browser.get("/setup?checks=1").text
    assert "failed" in page and "Fix the failed line first" in page and "Next: choose a model" not in page


def test_the_audit_page_lists_changes_and_filters_by_action(browser):
    import audit

    audit.log("test.marker", "t-1", {"api_key": "sk-secret", "note": "hello"})
    page = browser.get("/admin/audit").text
    assert "test.marker" in page and "hello" in page and "sk-secret" not in page
    assert "test.marker" in browser.get("/admin/audit?action=test.marker").text
    assert "t-1" not in browser.get("/admin/audit?action=nothing.like.this").text


def test_a_disconnected_channel_is_announced_on_every_page_but_the_wizard(browser, monkeypatch):
    import gateway_state

    monkeypatch.setattr(gateway_state, "STARTED", time.time() - 1000)
    gateway_state.update("whatsapp", connected=False, qr=None, groups=[])
    gateway_state._state["whatsapp"]["reported_at"] = time.time()
    assert "is enabled but disconnected" in browser.get("/admin/cost").text
    assert "is enabled but disconnected" not in browser.get("/setup/link").text
    gateway_state.update("whatsapp", connected=True, groups=[])
    assert "is enabled but" not in browser.get("/admin/cost").text
    gateway_state.update("whatsapp", connected=False, groups=[])


def test_members_and_decisions_show_on_the_group_page_and_can_be_acted_on(ready):
    import db

    b, group, gid = ready["browser"], ready["group"], ready["gid"]
    page = b.get(f"/admin/groups/{group['id']}").text
    assert "Anna" in page and "bob@s" in page and "Sauna is on Fridays" in page
    assert "Answers with" in b.get("/admin/groups").text

    res = post(b, f"/admin/groups/{group['id']}/optout", sender="bob@s")
    assert res.status_code == 303
    page = b.get(f"/admin/groups/{group['id']}").text
    assert "bob@s opted out. Erased 1 messages" in page
    with db.connect() as conn:
        assert not conn.execute(
            "SELECT 1 FROM messages WHERE group_id = %s AND sender_jid = 'bob@s'", (gid,)
        ).fetchall()
        fact_id = conn.execute("SELECT id FROM facts WHERE group_id = %s", (gid,)).fetchone()["id"]
    res = post(b, f"/admin/groups/{group['id']}/facts/{fact_id}/delete")
    assert res.status_code == 303
    assert "Sauna is on Fridays" not in b.get(f"/admin/groups/{group['id']}").text

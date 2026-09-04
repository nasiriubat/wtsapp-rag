import os
import uuid

import pytest
from conftest import GW, needs_db

pytestmark = needs_db


@pytest.fixture()
def browser(client):
    client.cookies.clear()
    client.post("/admin/login", data={"password": os.environ["ADMIN_PASSWORD"]}, follow_redirects=False)
    client.csrf = client.get("/admin").text.split('name="csrf" value="')[1].split('"')[0]
    yield client
    client.cookies.clear()


def test_preflight_lists_checks(browser):
    page = browser.get("/setup").text
    assert "Postgres" in page and "connected" in page and "Memory" in page


def test_provider_step_adds_tests_and_sets_default(browser, monkeypatch):
    import groups
    import providers

    monkeypatch.setattr(providers, "check", lambda p: "OK")
    before = groups.global_settings()["default_provider_id"]
    groups.set_global(default_provider_id=None)
    res = browser.post(
        "/setup/provider",
        data={"csrf": browser.csrf, "kind": "openai", "api_key": "k", "model": "m"},
        follow_redirects=False,
    )
    assert res.status_code == 303 and "tested=ok" in res.headers["location"]
    pid = groups.global_settings()["default_provider_id"]
    assert pid is not None and providers.get(pid)["kind"] == "openai"
    assert (
        "1 provider configured" in browser.get("/setup/provider").text
        or "configured" in browser.get("/setup/provider").text
    )
    providers.delete(pid)
    groups.set_global(default_provider_id=before)


def test_link_status_renders_qr_then_linked(browser, client):
    import gateway_state

    gateway_state.update(connected=False, qr="1@abc,def,ghi", groups=[])
    frag = browser.get("/setup/link/status").text
    assert "<svg" in frag and "Keep this page open" in frag

    # The gateway reports through its own endpoint with the token.
    res = client.post(
        "/gateway/state",
        json={
            "connected": True,
            "jid": "358@s.whatsapp.net",
            "groups": [{"id": "1@g.us", "subject": "Cabin"}],
        },
        headers=GW,
    )
    assert res.status_code == 200
    frag = browser.get("/setup/link/status").text
    assert "Linked as 358@s.whatsapp.net" in frag and "1 group" in frag


def test_relink_flag_round_trips_through_config(browser, client):
    import gateway_state

    assert (
        browser.post("/setup/link/relink", data={"csrf": browser.csrf}, follow_redirects=False).status_code
        == 303
    )
    assert client.get("/gateway/config", headers=GW).json()["relink"] is True
    gateway_state.update(connected=False, qr="new-qr")
    assert client.get("/gateway/config", headers=GW).json()["relink"] is False


def test_groups_step_enables_selected_groups(browser):
    import gateway_state
    import groups

    gid = f"test-{uuid.uuid4()}@g.us"
    gateway_state.update(connected=True, groups=[{"id": gid, "subject": "Cabin crew"}])
    assert "Cabin crew" in browser.get("/setup/groups").text
    res = browser.post("/setup/groups", data={"csrf": browser.csrf, "group": gid}, follow_redirects=False)
    assert res.status_code == 303 and "created=1" in res.headers["location"]
    g = groups.get(gid)
    assert g["name"] == "Cabin crew" and g["enabled"]
    groups.delete(g["id"])


def test_round_trip_status_detects_a_new_question(browser):
    import db

    with db.connect() as conn:
        since = conn.execute("SELECT coalesce(max(id), 0) AS id FROM query_log").fetchone()["id"]
    assert "Waiting" in browser.get(f"/setup/test/status?since={since}").text
    with db.connect() as conn:
        qid = conn.execute(
            "INSERT INTO query_log (group_id, question, answer) "
            "VALUES ('x@g.us', 'hello', 'got it') RETURNING id"
        ).fetchone()["id"]
    frag = browser.get(f"/setup/test/status?since={since}").text
    assert "Round trip works" in frag and "got it" in frag
    with db.connect() as conn:
        conn.execute("DELETE FROM query_log WHERE id = %s", (qid,))

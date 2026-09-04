import uuid

from conftest import GW, needs_db, post

pytestmark = needs_db


def test_preflight_lists_checks(browser):
    page = browser.get("/setup").text
    assert "Postgres" in page and "connected" in page and "Memory" in page


def test_provider_step_adds_tests_and_sets_default(browser, monkeypatch):
    import groups
    import providers

    monkeypatch.setattr(providers, "check", lambda p: "OK & ready #1")
    before = groups.global_settings()["default_provider_id"]
    groups.set_global(default_provider_id=None)
    res = post(browser, "/setup/provider", kind="openai", api_key="k", model="m")
    assert res.status_code == 303 and "ok=1" in res.headers["location"]
    pid = groups.global_settings()["default_provider_id"]
    assert pid is not None and providers.get(pid)["kind"] == "openai"
    page = browser.get(res.headers["location"]).text
    assert "Test passed" in page and "OK &amp; ready #1" in page and "configured" in page
    providers.delete(pid)
    groups.set_global(default_provider_id=before)


def test_link_status_renders_qr_then_linked(browser, client):
    import gateway_state

    gateway_state.update("whatsapp", connected=False, qr="1@abc,def,ghi", groups=[])
    frag = browser.get("/setup/link/status").text
    assert "<svg" in frag and "Keep this page open" in frag

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


def test_relink_flag_is_handed_to_the_gateway_once(browser, client):
    assert post(browser, "/setup/link/relink").status_code == 303
    assert client.get("/gateway/config", headers=GW).json()["relink"] == ["whatsapp"]
    assert client.get("/gateway/config", headers=GW).json()["relink"] == []


def test_groups_step_enables_selected_groups(browser):
    import gateway_state
    import groups

    gid = f"test-{uuid.uuid4()}@g.us"
    gateway_state.update("whatsapp", connected=True, groups=[{"id": gid, "subject": "Cabin crew"}])
    assert "Cabin crew" in browser.get("/setup/groups").text
    res = post(browser, "/setup/groups", group=gid)
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
    assert "round trip works" in frag and "got it" in frag
    with db.connect() as conn:
        conn.execute("DELETE FROM query_log WHERE id = %s", (qid,))

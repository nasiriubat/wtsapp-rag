import os
import uuid

import pytest
from conftest import needs_db

pytestmark = needs_db


@pytest.fixture()
def browser(client):
    client.cookies.clear()
    client.post("/admin/login", data={"password": os.environ["ADMIN_PASSWORD"]}, follow_redirects=False)
    page = client.get("/admin").text
    client.csrf = page.split('name="csrf" value="')[1].split('"')[0]
    yield client
    client.cookies.clear()


def post(browser, path, **data):
    return browser.post(path, data={"csrf": browser.csrf, **data}, follow_redirects=False)


def test_provider_lifecycle_through_forms(browser, monkeypatch):
    import providers

    res = post(
        browser,
        "/admin/providers",
        name="Router",
        kind="openai",
        api_key="sk-x",
        model="m",
        base_url="https://openrouter.ai/api/v1",
        price_in="1",
        price_out="2",
        options='{"temperature": 0.3}',
    )
    assert res.status_code == 303
    page = browser.get("/admin/providers").text
    assert "Router" in page and "sk-x" not in page
    pid = next(p["id"] for p in providers.list_all() if p["name"] == "Router")
    assert providers.get(pid)["options"] == {"temperature": 0.3}

    res = post(browser, f"/admin/providers/{pid}", name="Router2", model="m2", enabled="true", options="")
    assert res.status_code == 303 and providers.get(pid)["model"] == "m2"
    assert providers.get(pid)["api_key"] == "sk-x"  # empty key field keeps the old one

    bad = post(browser, f"/admin/providers/{pid}", name="x", model="m", options="not json")
    assert bad.status_code == 422

    monkeypatch.setattr(providers, "check", lambda p: "OK")
    res = browser.post(f"/admin/providers/{pid}/test", headers={"X-CSRF-Token": browser.csrf})
    assert res.status_code == 200 and "OK" in res.text

    assert post(browser, f"/admin/providers/{pid}/default").status_code == 303
    import groups

    assert groups.global_settings()["default_provider_id"] == pid
    assert post(browser, f"/admin/providers/{pid}/delete").status_code == 303
    assert providers.get(pid) is None
    groups.set_global(default_provider_id=None)


def test_group_settings_form_roundtrip_and_threshold_stat(browser):
    import db
    import groups

    gid = f"test-{uuid.uuid4()}@g.us"
    res = post(browser, "/admin/groups", channel="whatsapp", external_id=gid, name="Cabin")
    assert res.status_code == 303
    group_id = int(res.headers["location"].rsplit("/", 1)[1])
    with db.connect() as conn:
        for conf in (0.05, 0.5, 0.9):
            conn.execute(
                "INSERT INTO query_log (group_id, question, confidence, answer) VALUES (%s, 'q', %s, 'a')",
                (gid, conf),
            )

    page = browser.get(f"/admin/groups/{group_id}").text
    assert "Cabin" in page and "33% of the last 3 questions" in page
    frag = browser.get(f"/admin/groups/{group_id}/threshold?value=0.6").text
    assert "67% of the last 3 questions" in frag

    res = post(
        browser,
        f"/admin/groups/{group_id}",
        name="Cabin crew",
        enabled="true",
        triggers="@bot, hey",
        confidence_threshold="0.3",
        refusal_text="Ei tietoa.",
        answer_language="Finnish",
        retention_days="30",
        opt_out="",
        quiet_start="22:00",
        quiet_end="07:00",
        quiet_tz="Europe/Helsinki",
        monthly_cap_eur="5",
    )
    assert res.status_code == 303
    g = groups.get_by_id(group_id)
    assert g["name"] == "Cabin crew" and g["settings"]["triggers"] == ["@bot", "hey"]
    assert g["settings"]["quiet_hours"] == {"start": "22:00", "end": "07:00", "tz": "Europe/Helsinki"}
    assert g["settings"]["monthly_cap_eur"] == 5 and g["settings"]["retention_days"] == 30

    bad = post(browser, f"/admin/groups/{group_id}", confidence_threshold="7")
    assert bad.status_code == 422

    assert post(browser, f"/admin/groups/{group_id}/delete").status_code == 303
    assert groups.get_by_id(group_id) is None
    with db.connect() as conn:
        conn.execute("DELETE FROM query_log WHERE group_id = %s", (gid,))

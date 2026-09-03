import os
import uuid

import pytest
from conftest import needs_db

pytestmark = needs_db


@pytest.fixture()
def browser(client):
    client.cookies.clear()
    client.post("/admin/login", data={"password": os.environ["ADMIN_PASSWORD"]}, follow_redirects=False)
    client.csrf = client.get("/admin").text.split('name="csrf" value="')[1].split('"')[0]
    yield client
    client.cookies.clear()


@pytest.fixture()
def group():
    import db
    import groups

    gid = f"test-{uuid.uuid4()}@g.us"
    g = groups.create("whatsapp", gid, name="Cabin")
    yield g
    with db.connect() as conn:
        conn.execute("DELETE FROM query_log WHERE group_id = %s", (gid,))
        conn.execute("DELETE FROM chunks WHERE group_id = %s", (gid,))
        conn.execute("DELETE FROM messages WHERE group_id = %s", (gid,))
    groups.delete(g["id"])


def test_questions_list_detail_feedback_and_export(browser, group):
    import db

    with db.connect() as conn:
        qid = conn.execute(
            "INSERT INTO query_log (group_id, question, answer, confidence, cost, retrieved) "
            "VALUES (%s, 'who books?', 'Mikko.', 0.8, 0.001, %s) RETURNING id",
            (
                group["external_id"],
                '{"chunks": [{"chunk_id": 999999, "score": 0.8, "source": "vector"}], '
                '"timings": {"embed_ms": 3}}',
            ),
        ).fetchone()["id"]

    page = browser.get("/admin/questions").text
    assert "who books?" in page and "Cabin" in page
    assert "who books?" in browser.get("/admin/questions?filter=answered").text
    assert "who books?" not in browser.get("/admin/questions?filter=refused").text

    detail = browser.get(f"/admin/questions/{qid}").text
    assert "no longer exists" in detail and "embed 3 ms" in detail

    res = browser.post(
        f"/admin/questions/{qid}/feedback",
        data={"csrf": browser.csrf, "value": "-1", "note": "expected Anna"},
    )
    assert res.status_code == 200
    with db.connect() as conn:
        row = conn.execute("SELECT feedback, feedback_note FROM query_log WHERE id = %s", (qid,)).fetchone()
    assert (row["feedback"], row["feedback_note"]) == (-1, "expected Anna")

    export = browser.get("/admin/questions.jsonl")
    assert export.status_code == 200 and '"expected Anna"' in export.text


def test_cost_page_and_global_cap(browser, group):
    import groups

    page = browser.get("/admin/cost").text
    assert "this month" in page
    res = browser.post(
        "/admin/cost/cap", data={"csrf": browser.csrf, "monthly_cap_eur": "12.5"}, follow_redirects=False
    )
    assert res.status_code == 303 and groups.global_settings()["monthly_cap_eur"] == 12.5
    browser.post("/admin/cost/cap", data={"csrf": browser.csrf, "monthly_cap_eur": ""})
    assert groups.global_settings()["monthly_cap_eur"] is None


def test_data_import_reembed_purge_export(browser, group):
    import db

    export = "[02/09/2026, 10:00:15] Anna: Hello all\n[02/09/2026, 10:01:20] Bob: Hi there\n"
    res = browser.post(
        "/admin/data/import",
        data={"csrf": browser.csrf, "group_id": str(group["id"])},
        files={"file": ("chat.txt", export.encode(), "text/plain")},
        follow_redirects=False,
    )
    assert res.status_code == 303 and "Imported+2" in res.headers["location"]
    assert browser.get("/admin/data").text.count("Cabin") >= 1

    with db.connect() as conn:
        conn.execute(
            "INSERT INTO chunks (group_id, content, first_msg_id, start_ts, end_ts) "
            "VALUES (%s, 'x', 'y', now(), now())",
            (group["external_id"],),
        )
        conn.execute("UPDATE messages SET chunked = true WHERE group_id = %s", (group["external_id"],))
    res = browser.post(
        f"/admin/data/reembed/{group['id']}", data={"csrf": browser.csrf}, follow_redirects=False
    )
    assert res.status_code == 303
    with db.connect() as conn:
        assert (
            conn.execute(
                "SELECT count(*) AS n FROM chunks WHERE group_id = %s", (group["external_id"],)
            ).fetchone()["n"]
            == 0
        )
        pending = conn.execute(
            "SELECT count(*) AS n FROM messages WHERE group_id = %s AND NOT chunked", (group["external_id"],)
        ).fetchone()["n"]
    assert pending == 2

    res = browser.post(
        "/admin/data/purge",
        data={"csrf": browser.csrf, "group_id": str(group["id"]), "sender": "import:Bob"},
        follow_redirects=False,
    )
    assert res.status_code == 303 and "Erased+1" in res.headers["location"]

    out = browser.get(f"/admin/data/export/{group['id']}.jsonl")
    assert out.status_code == 200
    assert "Hello all" in out.text and "Hi there" not in out.text

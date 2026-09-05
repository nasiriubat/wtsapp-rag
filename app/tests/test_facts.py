import uuid
from datetime import UTC, datetime, timedelta

import pytest
from conftest import needs_db

pytestmark = needs_db
NOW = datetime(2026, 9, 4, 12, 0, tzinfo=UTC)


@pytest.fixture()
def group(client, monkeypatch):
    import db
    import embed
    import groups

    # Deterministic tiny "embeddings": no model download in tests.
    def fake(texts):
        return [
            [1.0 if "cabin" in t.lower() else 0.0, 1.0 if "wood" in t.lower() else 0.0] + [0.0] * 382
            for t in texts
        ]

    monkeypatch.setattr(embed, "passages", fake)
    monkeypatch.setattr(embed, "query", lambda t: fake([t])[0])
    gid = f"test-{uuid.uuid4()}@g.us"
    g = groups.create("whatsapp", gid)
    yield g
    with db.connect() as conn:
        conn.execute("DELETE FROM facts WHERE group_id = %s", (gid,))
        conn.execute("DELETE FROM query_log WHERE group_id = %s", (gid,))
        conn.execute("DELETE FROM chunks WHERE group_id = %s", (gid,))
    groups.delete(g["id"])


def test_parse_tolerates_fences_and_junk():
    import facts

    assert facts._parse('```json\n{"facts": [{"statement": "A", "supersedes": [3, "x"]}]}\n```') == [
        ("A", [3])
    ]
    assert facts._parse("not json") == []
    assert facts._parse('{"facts": [{"statement": "  "}]}') == []


def test_newer_decision_supersedes_and_search_shows_history(group):
    import facts

    gid = group["external_id"]
    old = facts.add(gid, "Mikko books the Rovaniemi cabin", "decision", "m1", NOW - timedelta(days=10))
    new = facts.add(gid, "Mikko books the Kuusamo cabin instead", "decision", "m2", NOW, supersedes=[old])
    rows = facts.search(gid, "which cabin?")
    assert [r["id"] for r in rows] == [new]
    assert rows[0]["replaced"][0]["statement"] == "Mikko books the Rovaniemi cabin"
    text = facts.format_for_prompt(rows)
    assert "Kuusamo" in text and "replaces" in text and "Rovaniemi" in text


def test_restating_an_active_fact_adds_nothing(group):
    import facts

    gid = group["external_id"]
    first = facts.add(gid, "Mikko books the cabin", "decision", "m1", NOW)
    assert facts.add(gid, "Mikko books the cabin.", "decision", "m2", NOW) is None
    assert facts.add(gid, "Sara books the cabin", "decision", "m3", NOW, supersedes=[first]) is not None


def test_supersedes_only_own_groups_active_facts(group):
    import facts

    other = facts.add("someone-else@g.us", "Their cabin", "decision", "x", NOW)
    mine = facts.add(group["external_id"], "Our cabin", "decision", "m", NOW, supersedes=[other])
    assert facts.search("someone-else@g.us", "cabin")[0]["id"] == other
    import db

    with db.connect() as conn:
        conn.execute("DELETE FROM facts WHERE id IN (%s, %s)", (other, mine))


def test_extract_calls_provider_once_per_chunk_and_logs_cost(group, monkeypatch):
    import db
    import extraction
    import facts
    import providers

    gid = group["external_id"]
    provider = providers.create("p", "openai", "k", "m", price_in=1, price_out=1)
    import groups

    groups.set_global(default_provider_id=provider["id"])
    calls = []

    def fake_generate(p, system, prompt):
        calls.append(prompt)
        return '{"facts": [{"statement": "Mikko books the Kuusamo cabin", "supersedes": []}]}', 200, 20

    monkeypatch.setattr(providers, "generate", fake_generate)
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO chunks (group_id, content, first_msg_id, start_ts, end_ts) "
            "VALUES (%s, %s, 'm1', %s, %s)",
            (gid, "Anna: cabin?\nMikko: I book Kuusamo", NOW, NOW),
        )
    extraction.run_once()
    extraction.run_once()  # second tick: nothing left to extract
    # Other groups in a shared dev database may be extracted too; count ours.
    assert sum("I book Kuusamo" in c for c in calls) == 1
    assert [r["statement"] for r in facts.search(gid, "cabin")] == ["Mikko books the Kuusamo cabin"]
    with db.connect() as conn:
        row = conn.execute("SELECT outcome, cost FROM query_log WHERE group_id = %s", (gid,)).fetchone()
        done = conn.execute("SELECT facts_extracted FROM chunks WHERE group_id = %s", (gid,)).fetchone()
    assert row["outcome"] == "extract" and float(row["cost"]) > 0 and done["facts_extracted"]
    providers.delete(provider["id"])
    groups.set_global(default_provider_id=None)


def test_extraction_respects_group_setting(group, monkeypatch):
    import db
    import extraction
    import groups
    import providers

    groups.update(group["id"], settings={**group["settings"], "decision_tracking": False})
    monkeypatch.setattr(providers, "generate", lambda *a: pytest.fail("must not extract"))
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO chunks (group_id, content, first_msg_id, start_ts, end_ts) "
            "VALUES (%s, 'x', 'm', %s, %s)",
            (group["external_id"], NOW, NOW),
        )
    extraction.run_once()


def test_a_chunk_the_provider_refuses_is_skipped_but_an_outage_is_retried(group, monkeypatch):
    import httpx

    import db
    import extraction
    import groups
    import providers

    gid = group["external_id"]
    provider = providers.create("p", "openai", "k", "m")
    groups.set_global(default_provider_id=provider["id"])

    def http_error(status):
        req = httpx.Request("POST", "https://x")
        return httpx.HTTPStatusError("nope", request=req, response=httpx.Response(status, request=req))

    with db.connect() as conn:
        conn.execute(
            "INSERT INTO chunks (group_id, content, first_msg_id, start_ts, end_ts) VALUES "
            "(%s, 'poison', 'm1', %s, %s), (%s, 'fine', 'm2', %s, %s)",
            (gid, NOW, NOW, gid, NOW, NOW),
        )

    def extracted():
        with db.connect() as conn:
            rows = conn.execute(
                "SELECT content, facts_extracted FROM chunks WHERE group_id = %s ORDER BY id", (gid,)
            ).fetchall()
        return {r["content"]: r["facts_extracted"] for r in rows}

    # A 400 is final for that chunk: mark it and carry on to the next one.
    monkeypatch.setattr(providers, "generate", lambda p, s, prompt: (_ for _ in ()).throw(http_error(400)))
    extraction.run_once()
    assert extracted() == {"poison": True, "fine": True}

    # A 503 or a 429 is the provider's problem: leave the chunk for the next tick.
    with db.connect() as conn:
        conn.execute("UPDATE chunks SET facts_extracted = false WHERE group_id = %s", (gid,))
    monkeypatch.setattr(providers, "generate", lambda p, s, prompt: (_ for _ in ()).throw(http_error(503)))
    extraction.run_once()
    assert extracted() == {"poison": False, "fine": False}
    monkeypatch.setattr(providers, "generate", lambda p, s, prompt: (_ for _ in ()).throw(http_error(429)))
    extraction.run_once()
    assert extracted() == {"poison": False, "fine": False}

    providers.delete(provider["id"])
    groups.set_global(default_provider_id=None)

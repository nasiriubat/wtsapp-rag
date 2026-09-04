import os
import uuid

import pytest

pytestmark = pytest.mark.skipif(not os.environ.get("DATABASE_URL"), reason="needs Postgres (DATABASE_URL)")


def test_env_values_become_rows_once(monkeypatch):
    import bootstrap
    import groups
    import migrate
    import providers

    migrate.run()
    if providers.list_all() or groups.list_all():
        pytest.skip("bootstrap only runs on an empty database")
    gid = f"test-{uuid.uuid4()}@g.us"
    for var, *_ in bootstrap.SEEDS:
        monkeypatch.delenv(var, raising=False)
    for var in ("GEMINI_API_KEY", "OPENAI_API_KEY", "OPENROUTER_API_KEY", "OPENROUTER_BASE_URL"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("GEMINI_API_KEY", "g-key")
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-key")
    monkeypatch.setenv("GROUP_JID", gid)
    monkeypatch.setenv("TRIGGERS", "@agent, hey")
    monkeypatch.setenv("CONFIDENCE_THRESHOLD", "0.3")
    bootstrap.run()
    bootstrap.run()  # a second start must not duplicate anything

    ps, gs = providers.list_all(), groups.list_all()
    assert [p["kind"] for p in ps] == ["gemini", "openai"]
    assert ps[1]["base_url"] == "https://openrouter.ai/api/v1"
    assert providers.get(ps[0]["id"])["api_key"] == "g-key"
    assert groups.global_settings()["default_provider_id"] == ps[0]["id"]
    assert len(gs) == 1 and gs[0]["settings"]["triggers"] == ["@agent", "hey"]
    assert gs[0]["settings"]["confidence_threshold"] == 0.3

    groups.delete(gs[0]["id"])
    for p in ps:
        providers.delete(p["id"])
    groups.set_global(default_provider_id=None)

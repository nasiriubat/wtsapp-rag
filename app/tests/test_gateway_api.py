import os
import uuid

import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.skipif(not os.environ.get("DATABASE_URL"), reason="needs Postgres (DATABASE_URL)")


def test_config_lists_enabled_groups_with_triggers():
    import groups
    import migrate
    from main import app

    migrate.run()
    client = TestClient(app)
    on = groups.create("whatsapp", f"test-{uuid.uuid4()}@g.us", settings={"triggers": ["@Bot"]})
    off = groups.create("whatsapp", f"test-{uuid.uuid4()}@g.us", enabled=False)

    assert client.get("/gateway/config").status_code == 401
    res = client.get("/gateway/config", headers={"authorization": f"Bearer {os.environ['GATEWAY_TOKEN']}"})
    listed = {g["external_id"]: g for g in res.json()["groups"]}
    assert listed[on["external_id"]]["triggers"] == ["@Bot"]
    assert off["external_id"] not in listed

    groups.delete(on["id"])
    groups.delete(off["id"])

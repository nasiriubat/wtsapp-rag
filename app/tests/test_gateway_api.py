import uuid

from conftest import GW, needs_db

pytestmark = needs_db


def test_config_lists_enabled_groups_with_triggers(client):
    import groups

    on = groups.create("whatsapp", f"test-{uuid.uuid4()}@g.us", settings={"triggers": ["@Bot"]})
    off = groups.create("whatsapp", f"test-{uuid.uuid4()}@g.us", enabled=False)

    assert client.get("/gateway/config").status_code == 401
    listed = {g["external_id"]: g for g in client.get("/gateway/config", headers=GW).json()["groups"]}
    assert listed[on["external_id"]]["triggers"] == ["@Bot"]
    assert off["external_id"] not in listed

    groups.delete(on["id"])
    groups.delete(off["id"])

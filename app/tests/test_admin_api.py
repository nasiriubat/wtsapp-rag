import uuid

from conftest import AUTH, needs_db

pytestmark = needs_db


def test_requires_basic_auth(client):
    assert client.get("/api/providers").status_code == 401
    assert client.get("/api/providers", auth=("admin", "wrong")).status_code == 401


def test_provider_crud_never_returns_the_key(client):
    import db

    body = {
        "name": "OpenRouter",
        "kind": "openai",
        "api_key": "sk-secret",
        "model": "x",
        "base_url": "https://openrouter.ai/api/v1",
        "price_in": 1,
        "price_out": 2,
    }
    created = client.post("/api/providers", json=body, auth=AUTH)
    assert created.status_code == 201
    pid = created.json()["id"]
    assert "api_key" not in created.json()
    assert "sk-secret" not in created.text

    listed = client.get("/api/providers", auth=AUTH).json()
    assert any(p["id"] == pid for p in listed) and "sk-secret" not in str(listed)

    patched = client.patch(f"/api/providers/{pid}", json={"model": "y", "api_key": "sk-new"}, auth=AUTH)
    assert patched.json()["model"] == "y"
    assert client.patch(f"/api/providers/{pid}", json={}, auth=AUTH).status_code == 422

    with db.connect() as conn:
        raw = conn.execute("SELECT api_key FROM providers WHERE id = %s", (pid,)).fetchone()["api_key"]
        entries = conn.execute("SELECT detail FROM audit_log WHERE target = %s", (str(pid),)).fetchall()
    assert b"sk-new" not in bytes(raw)
    assert all("sk-" not in str(e["detail"]) for e in entries)

    assert client.delete(f"/api/providers/{pid}", auth=AUTH).status_code == 204
    assert not any(p["id"] == pid for p in client.get("/api/providers", auth=AUTH).json())


def test_unknown_provider_kind_is_rejected(client):
    body = {"name": "x", "kind": "cohere", "api_key": "k", "model": "m"}
    assert client.post("/api/providers", json=body, auth=AUTH).status_code == 422


def test_group_crud_and_settings_validation(client):
    gid = f"test-{uuid.uuid4()}@g.us"
    created = client.post(
        "/api/groups", json={"channel": "whatsapp", "external_id": gid, "name": "Cabin"}, auth=AUTH
    )
    assert created.status_code == 201
    group_id = created.json()["id"]
    assert created.json()["settings"]["triggers"] == ["@agent"]

    dup = client.post("/api/groups", json={"channel": "whatsapp", "external_id": gid}, auth=AUTH)
    assert dup.status_code == 409

    bad = client.patch(f"/api/groups/{group_id}", json={"settings": {"confidence_threshold": 7}}, auth=AUTH)
    assert bad.status_code == 422

    ok = client.patch(
        f"/api/groups/{group_id}", json={"settings": {"triggers": ["@bot"], "monthly_cap_eur": 5}}, auth=AUTH
    )
    assert ok.json()["settings"]["triggers"] == ["@bot"]
    assert ok.json()["settings"]["monthly_cap_eur"] == 5
    assert client.patch("/api/groups/999999", json={"name": "x"}, auth=AUTH).status_code == 404

    assert client.delete(f"/api/groups/{group_id}", auth=AUTH).status_code == 204


def test_global_settings_roundtrip(client):
    assert (
        client.put("/api/settings", json={"monthly_cap_eur": 20}, auth=AUTH).json()["monthly_cap_eur"] == 20
    )
    assert client.get("/api/settings", auth=AUTH).json()["monthly_cap_eur"] == 20
    client.put("/api/settings", json={"monthly_cap_eur": None}, auth=AUTH)


def test_audit_and_questions_endpoints(client):
    assert client.get("/api/audit", auth=AUTH).status_code == 200
    assert isinstance(client.get("/api/questions?limit=5", auth=AUTH).json(), list)

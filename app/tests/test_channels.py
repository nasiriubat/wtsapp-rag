import pytest
from conftest import GW, needs_db, post

pytestmark = needs_db


@pytest.fixture()
def clean():
    import channels

    yield
    channels.delete("telegram")
    channels.delete("discord")
    channels.upsert("whatsapp", None, True)


def test_whatsapp_row_exists_after_migration(client):
    import channels

    kinds = [c["kind"] for c in channels.list_all()]
    assert "whatsapp" in kinds


def test_token_is_encrypted_and_masked(client, clean):
    import channels
    import db

    channels.upsert("telegram", {"token": "123:abc"})
    assert channels.get("telegram")["config"] == {"token": "123:abc"}
    masked = next(c for c in channels.list_all() if c["kind"] == "telegram")
    assert masked["config"] == {"token": "***"} and masked["configured"]
    with db.connect() as conn:
        raw = conn.execute("SELECT config FROM channels WHERE kind = 'telegram'").fetchone()["config"]
    assert b"123:abc" not in bytes(raw)
    with pytest.raises(ValueError):
        channels.upsert("discord", {})


def test_gateway_config_hands_out_enabled_channels_with_tokens(client, clean):
    import channels

    channels.upsert("telegram", {"token": "123:abc"})
    channels.upsert("discord", {"token": "d-token"}, enabled=False)
    cfg = client.get("/gateway/config", headers=GW).json()
    by_kind = {c["kind"]: c for c in cfg["channels"]}
    assert by_kind["telegram"]["config"] == {"token": "123:abc"}
    assert "discord" not in by_kind and by_kind["whatsapp"]["config"] == {}


def test_state_is_kept_per_channel(client, clean):
    import gateway_state

    body = {
        "channel": "telegram",
        "connected": True,
        "jid": "@my_bot",
        "groups": [{"id": "tg:-1", "subject": "Crew"}],
    }
    assert client.post("/gateway/state", json=body, headers=GW).status_code == 200
    assert gateway_state.get("telegram")["jid"] == "@my_bot"
    assert gateway_state.get("whatsapp")["jid"] != "@my_bot"
    assert any(g["id"] == "tg:-1" for g in gateway_state.seen_groups())
    assert client.post("/gateway/state", json={**body, "channel": "irc"}, headers=GW).status_code == 422


def test_channels_page_saves_token_and_toggles(browser, clean):
    import channels

    page = browser.get("/admin/channels").text
    assert "BotFather" in page and "Message Content" in page
    res = post(browser, "/admin/channels/telegram", token="123:abc", enabled="true")
    assert res.status_code == 303
    assert channels.get("telegram")["config"] == {"token": "123:abc"}

    # Disabling without retyping the token keeps it.
    assert post(browser, "/admin/channels/telegram", token="").status_code == 303
    tg = channels.get("telegram")
    assert tg["enabled"] is False and tg["config"] == {"token": "123:abc"}
    assert post(browser, "/admin/channels/discord", token="", enabled="true").status_code == 422

    assert post(browser, "/admin/channels/telegram/delete").status_code == 303
    assert channels.get("telegram") is None
    assert post(browser, "/admin/channels/whatsapp/delete").status_code == 303
    assert channels.get("whatsapp") is not None  # WhatsApp cannot be removed

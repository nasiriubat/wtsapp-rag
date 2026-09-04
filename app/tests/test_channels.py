import uuid

import pytest
from conftest import GW, needs_db, post

pytestmark = needs_db


@pytest.fixture()
def clean():
    import channels

    yield
    channels.delete("telegram")
    channels.delete("discord")
    channels.delete("whatsapp_cloud")
    channels.upsert("whatsapp", None, True)


def test_a_multi_field_channel_needs_all_of_them_and_merges_updates(client, clean):
    import channels

    with pytest.raises(ValueError, match="phone_number_id"):
        channels.upsert("whatsapp_cloud", {"token": "t"})
    full = {"token": "t", "phone_number_id": "1", "verify_token": "v", "app_secret": "s"}
    channels.upsert("whatsapp_cloud", full)
    # One field retyped, the rest kept.
    channels.upsert("whatsapp_cloud", {"token": "t2"})
    assert channels.get("whatsapp_cloud")["config"] == {**full, "token": "t2"}
    masked = next(c for c in channels.list_all() if c["kind"] == "whatsapp_cloud")["config"]
    assert masked["token"] == masked["app_secret"] == masked["verify_token"] == "***"
    assert masked["phone_number_id"] == "1"  # an identifier, not a secret


def test_the_channels_page_renders_every_secret_field(browser, clean):
    page = browser.get("/admin/channels").text
    assert "Phone number id" in page and "App secret" in page and "24-hour window" in page
    res = post(browser, "/admin/channels/whatsapp_cloud", token="t", enabled="true")
    assert res.status_code == 422  # the other three are missing


def test_the_admin_api_shares_the_panels_login_lockout():
    import pytest as _pytest

    from admin import auth

    who = f"client-{uuid.uuid4()}"
    for _ in range(5):
        assert auth.check_password("wrong", who) is False
    with _pytest.raises(Exception, match="too many attempts"):
        auth.check_password("wrong", who)


def test_chunking_only_flags_its_own_groups_messages(client, monkeypatch):
    import chunking
    import db
    import embed
    import groups

    monkeypatch.setattr(embed, "passages", lambda texts: [[0.1] * 384 for _ in texts])
    # The same message id in two groups: WhatsApp lets a sender choose it.
    a, b = (groups.create("whatsapp", f"test-{uuid.uuid4()}@g.us") for _ in range(2))
    ids = (a["external_id"], b["external_id"])
    with db.connect() as conn:
        for external_id in ids:
            conn.execute(
                "INSERT INTO messages (wa_msg_id, group_id, sender_jid, sender_name, body, ts) "
                "VALUES ('shared-id', %s, '1@s', 'Anna', 'hello there everyone', now() - interval '2 days')",
                (external_id,),
            )
    chunking.run_once()
    with db.connect() as conn:
        # Unscoped, the first group's pass flagged the second's message too and
        # it was never embedded: one chunk instead of two.
        chunks = conn.execute("SELECT group_id FROM chunks WHERE group_id IN (%s, %s)", ids).fetchall()
        conn.execute("DELETE FROM chunks WHERE group_id IN (%s, %s)", ids)
        conn.execute("DELETE FROM messages WHERE wa_msg_id = 'shared-id'")
    assert {c["group_id"] for c in chunks} == set(ids)
    groups.delete(a["id"])
    groups.delete(b["id"])


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

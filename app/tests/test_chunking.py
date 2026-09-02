from datetime import UTC, datetime, timedelta

from chunking import MAX_CHARS, MAX_MESSAGES, _content, episodes

NOW = datetime(2026, 9, 3, 12, 0, tzinfo=UTC)


def msg(minutes_ago, body="hi", name="Anna"):
    return {
        "ts": NOW - timedelta(minutes=minutes_ago),
        "body": body,
        "sender_name": name,
        "sender_jid": "1@s",
    }


def test_splits_on_thirty_minute_gap():
    eps = episodes([msg(180), msg(179), msg(90), msg(89)], NOW)
    assert [len(e) for e in eps] == [2, 2]


def test_tail_stays_open_until_silence():
    eps = episodes([msg(180), msg(5)], NOW)
    assert len(eps) == 1
    assert eps[0][0]["ts"] == msg(180)["ts"]


def test_tail_closes_when_full():
    eps = episodes([msg(5 - i / 10) for i in range(MAX_MESSAGES)], NOW)
    assert len(eps) == 1 and len(eps[0]) == MAX_MESSAGES


def test_caps_on_message_count():
    eps = episodes([msg(100 - i) for i in range(MAX_MESSAGES + 1)], NOW)
    assert [len(e) for e in eps] == [MAX_MESSAGES, 1]


def test_caps_on_characters():
    big = msg(100, body="x" * MAX_CHARS)
    eps = episodes([big, msg(99), msg(98)], NOW)
    assert [len(e) for e in eps] == [1, 2]


def test_content_uses_name_then_jid():
    ep = [msg(10, "hello", "Anna"), {**msg(9, "hey"), "sender_name": None}]
    assert _content(ep) == "Anna: hello\n1@s: hey"

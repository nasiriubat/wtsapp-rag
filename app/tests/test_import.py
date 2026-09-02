from datetime import datetime
from zoneinfo import ZoneInfo

from scripts.import_export import parse

LRM = "‎"
TZ = ZoneInfo("Europe/Helsinki")

EXPORT = [
    "[02/09/2026, 10:00:15] Anna: Hello all",
    "[02/09/2026, 10:01:20] Mikko: Hi",
    "this is a second line",
    f"[02/09/2026, 10:02:00] Sara: {LRM}image omitted",
    "[02/09/2026, 10:03:00] Anna added Mikko",
    "12/03/2026, 14:05 - Anna: Android style: with colon in body",
    "12.3.2026 klo 14.06.10 - Sara: Finnish style",
    f"{LRM}[02/09/2026, 10:05:00] Anna: {LRM}<attached: 00000012-PHOTO.jpg>",
    "02/09/2026, 10:06 - Media omitted",
    "Messages and calls are end-to-end encrypted.",
]


def test_parses_all_formats_and_drops_noise():
    msgs = parse(EXPORT)
    assert [m["sender_name"] for m in msgs] == ["Anna", "Mikko", "Anna", "Sara"]
    assert msgs[1]["body"] == "Hi\nthis is a second line"
    assert msgs[2]["body"] == "Android style: with colon in body"
    assert msgs[0]["ts"] == datetime(2026, 9, 2, 10, 0, 15, tzinfo=TZ)
    assert msgs[3]["ts"] == datetime(2026, 3, 12, 14, 6, 10, tzinfo=TZ)


def test_invisible_marks_are_stripped():
    assert all(LRM not in m["body"] for m in parse(EXPORT))


def test_us_export_is_month_first():
    msgs = parse(["1/2/26, 9:05 PM - Bob: first", "1/13/26, 8:00 AM - Bob: second"])
    assert msgs[0]["ts"] == datetime(2026, 1, 2, 21, 5, tzinfo=TZ)
    assert msgs[1]["ts"] == datetime(2026, 1, 13, 8, 0, tzinfo=TZ)


def test_ambiguous_dates_default_to_day_first():
    msgs = parse(["1/2/26, 9:05 - Bob: only ambiguous dates"])
    assert msgs[0]["ts"] == datetime(2026, 2, 1, 9, 5, tzinfo=TZ)

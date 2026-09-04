from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

import groups


def test_settings_defaults():
    s = groups.Settings().model_dump()
    assert s["triggers"] == ["@agent"]
    assert s["confidence_threshold"] == 0.0
    assert s["refusal_text"] == groups.REFUSAL
    assert s["retention_days"] is None


def test_settings_reject_bad_values():
    with pytest.raises(ValidationError):
        groups.Settings(confidence_threshold=1.5)
    with pytest.raises(ValidationError):
        groups.Settings(retention_days=0)


def test_quiet_hours_wrap_past_midnight():
    s = groups.Settings(quiet_hours={"start": "22:00", "end": "07:00", "tz": "Europe/Helsinki"}).model_dump()
    # 23:30 Helsinki in September is 20:30 UTC.
    assert groups.in_quiet_hours(s, datetime(2026, 9, 3, 20, 30, tzinfo=UTC))
    # 12:00 Helsinki is 09:00 UTC.
    assert not groups.in_quiet_hours(s, datetime(2026, 9, 3, 9, 0, tzinfo=UTC))
    assert not groups.in_quiet_hours(groups.Settings().model_dump())


def test_quiet_hours_same_day_window():
    s = groups.Settings(quiet_hours={"start": "09:00", "end": "17:00", "tz": "UTC"}).model_dump()
    assert groups.in_quiet_hours(s, datetime(2026, 9, 3, 12, 0, tzinfo=UTC))
    assert not groups.in_quiet_hours(s, datetime(2026, 9, 3, 18, 0, tzinfo=UTC))

from datetime import datetime, timedelta

import pytest

from nosudo.timeparse import (
    TimeParseError,
    format_oncalendar,
    format_remaining,
    parse_duration,
    parse_until,
    resolve_lift_time,
)


@pytest.mark.parametrize(
    "text, seconds",
    [
        ("45s", 45),
        ("90m", 90 * 60),
        ("2h", 2 * 3600),
        ("1h30m", 90 * 60),
        ("3d", 3 * 86400),
    ],
)
def test_parse_duration_valid(text, seconds):
    assert parse_duration(text) == timedelta(seconds=seconds)


@pytest.mark.parametrize("text", ["", "abc", "10x", "1.5h", "0m", "-5m"])
def test_parse_duration_invalid(text):
    with pytest.raises(TimeParseError):
        parse_duration(text)


def test_resolve_requires_exactly_one():
    with pytest.raises(TimeParseError):
        resolve_lift_time()
    with pytest.raises(TimeParseError):
        resolve_lift_time(for_="1h", until="18:00")


def test_resolve_for_is_in_future():
    now = datetime(2026, 6, 12, 12, 0).astimezone()
    lift = resolve_lift_time(for_="2h", now=now)
    assert lift == (now + timedelta(hours=2)).replace(microsecond=0)


def test_resolve_until_past_rejected():
    with pytest.raises(TimeParseError):
        resolve_lift_time(until="2000-01-01T00:00")


def test_parse_until_hhmm_rolls_to_next_occurrence():
    now = datetime(2026, 6, 12, 20, 0).astimezone()
    # 08:00 has already passed at 20:00 -> should land tomorrow.
    lift = parse_until("08:00", now=now)
    assert lift > now
    assert lift.hour == 8


def test_format_oncalendar():
    dt = datetime(2026, 6, 12, 18, 30, 0).astimezone()
    assert format_oncalendar(dt) == "2026-06-12 18:30:00"


def test_format_remaining():
    now = datetime(2026, 6, 12, 12, 0).astimezone()
    lift = now + timedelta(hours=2, minutes=13)
    assert format_remaining(lift, now=now) == "2h 13m"
    assert format_remaining(now - timedelta(minutes=1), now=now) == "expired"

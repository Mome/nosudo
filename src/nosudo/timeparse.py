"""Parse ``--for`` durations and ``--until`` timestamps into an absolute time.

Everything is normalized to a timezone-aware ``datetime`` in the system local
timezone, which is also how the systemd ``OnCalendar`` line is rendered.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta

_DURATION_TOKEN = re.compile(r"(\d+)([smhd])")
_UNIT_SECONDS = {"s": 1, "m": 60, "h": 3600, "d": 86400}


class TimeParseError(ValueError):
    """Raised when user-supplied time input cannot be parsed or is in the past."""


def parse_duration(text: str) -> timedelta:
    """Parse a compact duration like ``90m``, ``2h``, ``1h30m``, ``3d``."""
    text = text.strip().lower()
    if not text:
        raise TimeParseError("empty duration")
    # Ensure the whole string is made of <number><unit> tokens, nothing else.
    if _DURATION_TOKEN.sub("", text):
        raise TimeParseError(
            f"invalid duration {text!r}; use forms like 90m, 2h, 1h30m, 3d"
        )
    seconds = sum(
        int(value) * _UNIT_SECONDS[unit]
        for value, unit in _DURATION_TOKEN.findall(text)
    )
    if seconds <= 0:
        raise TimeParseError("duration must be greater than zero")
    return timedelta(seconds=seconds)


def _now_local(now: datetime | None) -> datetime:
    return (now or datetime.now()).astimezone()


def parse_until(text: str, now: datetime | None = None) -> datetime:
    """Parse an absolute restore time.

    Accepts ``HH:MM`` / ``HH:MM:SS`` (the next occurrence from now) or an ISO
    date-time ``YYYY-MM-DDTHH:MM`` / ``YYYY-MM-DD HH:MM``.
    """
    text = text.strip()
    current = _now_local(now)

    for fmt in ("%H:%M", "%H:%M:%S"):
        try:
            t = datetime.strptime(text, fmt).time()
        except ValueError:
            continue
        candidate = current.replace(
            hour=t.hour, minute=t.minute, second=t.second, microsecond=0
        )
        if candidate <= current:  # time already passed today -> tomorrow
            candidate += timedelta(days=1)
        return candidate

    for fmt in ("%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            naive = datetime.strptime(text, fmt)
        except ValueError:
            continue
        return naive.astimezone()  # interpret as local time

    raise TimeParseError(
        f"invalid time {text!r}; use HH:MM or YYYY-MM-DDTHH:MM"
    )


def resolve_lift_time(
    *,
    for_: str | None = None,
    until: str | None = None,
    now: datetime | None = None,
) -> datetime:
    """Compute the absolute lift time from exactly one of ``for_``/``until``."""
    if (for_ is None) == (until is None):
        raise TimeParseError("specify exactly one of --for or --until")
    current = _now_local(now)
    if for_ is not None:
        lift = current + parse_duration(for_)
    else:
        assert until is not None  # guaranteed by the exactly-one check above
        lift = parse_until(until, now=current)
    if lift <= current:
        raise TimeParseError("lift time is in the past")
    return lift.replace(microsecond=0)


def format_oncalendar(lift_at: datetime) -> str:
    """Render a systemd ``OnCalendar`` value in local wall-clock time."""
    return lift_at.astimezone().strftime("%Y-%m-%d %H:%M:%S")


def format_remaining(lift_at: datetime, now: datetime | None = None) -> str:
    """Human-readable remaining time, e.g. ``2h 13m`` or ``expired``."""
    delta = lift_at - _now_local(now)
    total = int(delta.total_seconds())
    if total <= 0:
        return "expired"
    days, rem = divmod(total, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, _ = divmod(rem, 60)
    parts = []
    if days:
        parts.append(f"{days}d")
    if hours:
        parts.append(f"{hours}h")
    if minutes or not parts:
        parts.append(f"{minutes}m")
    return " ".join(parts)

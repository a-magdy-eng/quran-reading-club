"""Reading-day arithmetic.

A *reading day* is a calendar date in the group's timezone, shifted by the
configured reset time. With reset_minute = 240 (04:00), the reading day
"2026-11-23" runs from 2026-11-23 04:00 local to 2026-11-24 04:00 local.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta
from functools import lru_cache
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError, available_timezones

from .clock import UTC


@lru_cache(maxsize=64)
def zone(name: str) -> ZoneInfo:
    return ZoneInfo(name)


def is_valid_timezone(name: str) -> bool:
    try:
        zone(name)
        return True
    except (ZoneInfoNotFoundError, ValueError):
        return False


@lru_cache(maxsize=1)
def all_timezones() -> list[str]:
    return sorted(available_timezones())


def day_for(instant: datetime, tz: str, reset_minute: int) -> date:
    local = instant.astimezone(zone(tz))
    # Subtract the reset offset in wall-clock terms.
    naive = local.replace(tzinfo=None) - timedelta(minutes=reset_minute)
    return naive.date()


def day_start(day: date, tz: str, reset_minute: int) -> datetime:
    """UTC instant at which a reading day begins."""
    naive = datetime.combine(day, time()) + timedelta(minutes=reset_minute)
    local = naive.replace(tzinfo=zone(tz))
    return local.astimezone(UTC)


def day_end(day: date, tz: str, reset_minute: int) -> datetime:
    return day_start(day + timedelta(days=1), tz, reset_minute)


def day_bounds(day: date, tz: str, reset_minute: int) -> tuple[datetime, datetime]:
    return day_start(day, tz, reset_minute), day_end(day, tz, reset_minute)


def iter_days(first: date, last: date):
    d = first
    while d <= last:
        yield d
        d += timedelta(days=1)

"""Injectable clock so that day boundaries and streaks can be tested deterministically."""
from __future__ import annotations

import threading
from datetime import datetime, timedelta, timezone

UTC = timezone.utc


class Clock:
    def now(self) -> datetime:
        return datetime.now(UTC)


class FakeClock(Clock):
    """A manually driven clock (used by the test-suite)."""

    def __init__(self, start: datetime):
        if start.tzinfo is None:
            raise ValueError("FakeClock needs an aware datetime")
        self._now = start.astimezone(UTC)
        self._lock = threading.Lock()

    def now(self) -> datetime:
        with self._lock:
            return self._now

    def set(self, value: datetime) -> None:
        with self._lock:
            self._now = value.astimezone(UTC)

    def advance(self, seconds: float = 0, **kwargs) -> datetime:
        with self._lock:
            self._now = self._now + timedelta(seconds=seconds, **kwargs)
            return self._now


def to_utc(value: datetime | None) -> datetime | None:
    """SQLite returns naive datetimes; everything stored in the DB is UTC."""
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def naive_utc(value: datetime) -> datetime:
    """Normalise an aware datetime to the naive-UTC form stored in SQLite."""
    return value.astimezone(UTC).replace(tzinfo=None)

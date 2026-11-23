"""Streak engine.

Two layers:

1. Pure functions (`current_streak`, `longest_streak`) over an ordered list of
   (day, status) entries. These are fully deterministic and unit-tested.
2. Database functions that *evaluate* a reading day (who completed, who failed,
   who is excused) and *finalise* it once it is over. A day is never finalised
   before its end plus a grace period, and finalisation is idempotent (unique
   constraint on (group_id, day)), so restarts and concurrent callers are safe.

Day statuses:
  success - every required member completed and at least one member completed
  failed  - at least one required member did not complete
  neutral - nobody was required (e.g. everyone joined that day and nobody read)
  pending - today, not yet successful (not over yet; never treated as a failure)

Member outcomes:
  completed - met both minimums (pages and active time)
  failed    - did not meet them
  excused   - joined the group during that day and did not complete it
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .clock import naive_utc, to_utc
from .models import (
    DailyProgress,
    Group,
    GroupDay,
    GroupDayMember,
    GroupSettings,
    GroupStreak,
    Membership,
    UserStreak,
)
from .timeutil import day_bounds, day_end, day_for

SUCCESS = "success"
FAILED = "failed"
NEUTRAL = "neutral"
PENDING = "pending"

COMPLETED = "completed"
EXCUSED = "excused"

# A day is finalised only this long after it ends, so that a heartbeat that
# was in flight at the boundary can still be credited to the day it belongs to.
FINALIZE_GRACE = timedelta(seconds=120)

ONE_DAY = timedelta(days=1)


# --------------------------------------------------------------------------
# Pure streak arithmetic
# --------------------------------------------------------------------------
def current_streak(entries: list[tuple[date, str]], reset_day: date | None = None) -> int:
    """Consecutive successful days ending at the most recent entry.

    `entries` must be sorted by day. A missing day (gap) breaks the streak,
    neutral/pending days neither extend nor break it, a failed day breaks it.
    Days on or before `reset_day` are ignored (manual reset).
    """
    count = 0
    expected: date | None = None
    for day, status in reversed(entries):
        if reset_day is not None and day <= reset_day:
            break
        if expected is not None and day != expected:
            break
        expected = day - ONE_DAY
        if status == SUCCESS:
            count += 1
        elif status == FAILED:
            break
    return count


def longest_streak(entries: list[tuple[date, str]]) -> int:
    best = run = 0
    prev: date | None = None
    for day, status in entries:
        if prev is not None and day - prev > ONE_DAY:
            run = 0
        if status == SUCCESS:
            run += 1
            best = max(best, run)
        elif status == FAILED:
            run = 0
        prev = day
    return best


def outcome_to_status(outcome: str) -> str:
    return {COMPLETED: SUCCESS, FAILED: FAILED, EXCUSED: NEUTRAL}.get(outcome, NEUTRAL)


# --------------------------------------------------------------------------
# Day evaluation
# --------------------------------------------------------------------------
@dataclass
class MemberOutcome:
    user_id: int
    outcome: str
    pages_read: int
    active_seconds: float


@dataclass
class DayEvaluation:
    day: date
    status: str
    members: list[MemberOutcome]

    @property
    def required_count(self) -> int:
        return sum(1 for m in self.members if m.outcome != EXCUSED)

    @property
    def completed_count(self) -> int:
        return sum(1 for m in self.members if m.outcome == COMPLETED)


def members_for_day(db: Session, group_id: int, start: datetime, end: datetime) -> list[Membership]:
    """Members who belong to the group at the end of the day."""
    end_n = naive_utc(end)
    return list(
        db.scalars(
            select(Membership)
            .where(
                Membership.group_id == group_id,
                Membership.joined_at < end_n,
                (Membership.left_at.is_(None)) | (Membership.left_at >= end_n),
            )
            .order_by(Membership.joined_at, Membership.id)
        )
    )


def evaluate_day(db: Session, group: Group, settings: GroupSettings, day: date) -> DayEvaluation:
    start, end = day_bounds(day, settings.timezone, settings.reset_minute)
    members = members_for_day(db, group.id, start, end)
    progress = {
        dp.user_id: dp
        for dp in db.scalars(select(DailyProgress).where(DailyProgress.group_id == group.id, DailyProgress.day == day))
    }
    outcomes = []
    for m in members:
        dp = progress.get(m.user_id)
        if dp is not None and dp.completed:
            outcome = COMPLETED
        elif to_utc(m.joined_at) >= start:
            outcome = EXCUSED
        else:
            outcome = FAILED
        outcomes.append(
            MemberOutcome(m.user_id, outcome, dp.pages_read if dp else 0, dp.active_seconds if dp else 0.0)
        )
    if any(o.outcome == FAILED for o in outcomes):
        status = FAILED
    elif any(o.outcome == COMPLETED for o in outcomes):
        status = SUCCESS
    else:
        status = NEUTRAL
    return DayEvaluation(day, status, outcomes)


def last_finalized_day(db: Session, group_id: int) -> date | None:
    return db.scalar(select(func.max(GroupDay.day)).where(GroupDay.group_id == group_id))


def effective_today(db: Session, group: Group, settings: GroupSettings, now: datetime) -> date:
    """The reading day that activity at `now` is credited to.

    Normally the calendar reading day. If an admin moved the timezone/reset time
    backwards so that today's date was already finalised, activity goes to the
    next unfinalised day instead of rewriting history.
    """
    today = day_for(now, settings.timezone, settings.reset_minute)
    last = last_finalized_day(db, group.id)
    if last is not None and today <= last:
        return last + ONE_DAY
    return today


def finalize_group(db: Session, group: Group, now: datetime) -> list[date]:
    """Finalise every reading day of this group that is over (plus grace). Idempotent."""
    settings = group.settings
    last = last_finalized_day(db, group.id)
    day = (last + ONE_DAY) if last is not None else group.first_day
    today = day_for(now, settings.timezone, settings.reset_minute)
    finalized: list[date] = []
    while day < today and now >= day_end(day, settings.timezone, settings.reset_minute) + FINALIZE_GRACE:
        ev = evaluate_day(db, group, settings, day)
        gd = GroupDay(
            group_id=group.id,
            day=day,
            status=ev.status,
            required_count=ev.required_count,
            completed_count=ev.completed_count,
            finalized_at=naive_utc(now),
        )
        gd.members = [
            GroupDayMember(user_id=m.user_id, outcome=m.outcome, pages_read=m.pages_read, active_seconds=m.active_seconds)
            for m in ev.members
        ]
        db.add(gd)
        finalized.append(day)
        day += ONE_DAY
    if finalized:
        db.flush()
        refresh_streak_cache(db, group, now)
    return finalized


# --------------------------------------------------------------------------
# Streak summaries (finalised history + live provisional days)
# --------------------------------------------------------------------------
@dataclass
class StreakSummary:
    current: int
    longest: int
    today_status: str  # success | pending


def _provisional_days(db: Session, group: Group, now: datetime) -> list[DayEvaluation]:
    """Evaluations for days that are not finalised yet (today, and possibly
    yesterday during the grace period), oldest first."""
    settings = group.settings
    last = last_finalized_day(db, group.id)
    first = (last + ONE_DAY) if last is not None else group.first_day
    today = effective_today(db, group, settings, now)
    out = []
    d = first
    while d <= today:
        out.append(evaluate_day(db, group, settings, d))
        d += ONE_DAY
    return out


def _live_status(ev: DayEvaluation, is_today: bool) -> str:
    if is_today and ev.status != SUCCESS:
        return PENDING
    return ev.status


def group_streak(db: Session, group: Group, now: datetime) -> StreakSummary:
    rows = db.execute(
        select(GroupDay.day, GroupDay.status).where(GroupDay.group_id == group.id).order_by(GroupDay.day)
    ).all()
    entries = [(d, s) for d, s in rows]
    provisional = _provisional_days(db, group, now)
    for i, ev in enumerate(provisional):
        entries.append((ev.day, _live_status(ev, i == len(provisional) - 1)))
    current = current_streak(entries, group.settings.streak_reset_day)
    today_status = entries[-1][1] if entries else PENDING
    return StreakSummary(current, max(longest_streak(entries), current), today_status)


def user_streak_entries(db: Session, group: Group, user_id: int, now: datetime) -> list[tuple[date, str]]:
    rows = db.execute(
        select(GroupDay.day, GroupDayMember.outcome)
        .join(GroupDayMember, GroupDayMember.group_day_id == GroupDay.id)
        .where(GroupDay.group_id == group.id, GroupDayMember.user_id == user_id)
        .order_by(GroupDay.day)
    ).all()
    entries = [(d, outcome_to_status(o)) for d, o in rows]
    provisional = _provisional_days(db, group, now)
    for i, ev in enumerate(provisional):
        mine = next((m for m in ev.members if m.user_id == user_id), None)
        if mine is None:
            continue
        status = outcome_to_status(mine.outcome)
        if i == len(provisional) - 1 and status != SUCCESS:
            status = PENDING
        entries.append((ev.day, status))
    return entries


def user_streak(db: Session, group: Group, user_id: int, now: datetime) -> StreakSummary:
    entries = user_streak_entries(db, group, user_id, now)
    current = current_streak(entries)
    today_status = entries[-1][1] if entries else PENDING
    return StreakSummary(current, max(longest_streak(entries), current), today_status)


def refresh_streak_cache(db: Session, group: Group, now: datetime) -> None:
    """Persist finalised-history streak values into group_streaks / user_streaks."""
    rows = db.execute(
        select(GroupDay.day, GroupDay.status).where(GroupDay.group_id == group.id).order_by(GroupDay.day)
    ).all()
    entries = [(d, s) for d, s in rows]
    gs = db.get(GroupStreak, group.id)
    if gs is None:
        gs = GroupStreak(group_id=group.id)
        db.add(gs)
    gs.current = current_streak(entries, group.settings.streak_reset_day)
    gs.longest = longest_streak(entries)
    gs.last_finalized_day = entries[-1][0] if entries else None
    gs.updated_at = naive_utc(now)

    user_ids = {
        uid
        for (uid,) in db.execute(
            select(GroupDayMember.user_id)
            .join(GroupDay, GroupDay.id == GroupDayMember.group_day_id)
            .where(GroupDay.group_id == group.id)
            .distinct()
        )
    }
    for uid in user_ids:
        urows = db.execute(
            select(GroupDay.day, GroupDayMember.outcome)
            .join(GroupDayMember, GroupDayMember.group_day_id == GroupDay.id)
            .where(GroupDay.group_id == group.id, GroupDayMember.user_id == uid)
            .order_by(GroupDay.day)
        ).all()
        uentries = [(d, outcome_to_status(o)) for d, o in urows]
        us = db.get(UserStreak, (uid, group.id))
        if us is None:
            us = UserStreak(user_id=uid, group_id=group.id)
            db.add(us)
        us.current = current_streak(uentries)
        us.longest = longest_streak(uentries)
        us.updated_at = naive_utc(now)

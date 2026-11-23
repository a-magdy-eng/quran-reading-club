"""Reading sessions, the server-side active-time ledger and page counting.

How time is credited
--------------------
The browser measures *active* time (tab visible, window focused, user not idle)
and sends a heartbeat every ~15 s with the active milliseconds since the last
heartbeat, broken down by page. The server never trusts that number blindly:

* credit <= reported active time
* credit <= wall-clock time since the previous accepted heartbeat (+2 s jitter)
* credit <= wall-clock duration of the whole session minus time already credited
* credit <= 60 s per heartbeat
* heartbeats carry a strictly increasing sequence number (replays are ignored)
* a user has at most ONE active session; starting another one closes the old
  one, so two tabs/devices can never double-count time
* a session that has not sent a heartbeat for 90 s is closed

How pages are counted
---------------------
Credited time is attributed to the page(s) it was spent on. A mushaf page
counts as "read" the first time its accumulated active time reaches the
group's `min_page_seconds` (default 20 s). Each page can be counted only once
per khatma (complete reading of the Quran), so going back and forth,
re-visiting or reloading a page never adds pages. Flipping through pages
quickly adds nothing because no page accumulates enough time.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .clock import naive_utc, to_utc
from .models import (
    DailyProgress,
    Group,
    GroupDay,
    GroupSettings,
    Membership,
    PageProgress,
    ReaderState,
    ReadingSession,
)
from .quran import TOTAL_PAGES
from .streaks import effective_today
from .timeutil import day_for, day_start

HEARTBEAT_INTERVAL_SECONDS = 15
STALE_SESSION_SECONDS = 90
MAX_CREDIT_PER_HEARTBEAT = 60.0
CLOCK_TOLERANCE_SECONDS = 2.0
MAX_PAGE_ENTRIES = 40
KHATMA_MIN_PAGES = 544  # 90% of the mushaf must be counted before starting a new khatma


class TrackingError(Exception):
    def __init__(self, code: str, message: str, status: int = 409):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


# --------------------------------------------------------------------------
# Daily progress rows
# --------------------------------------------------------------------------
def get_or_create_daily(db: Session, user_id: int, group_id: int, day: date, settings: GroupSettings) -> DailyProgress:
    dp = db.scalar(
        select(DailyProgress).where(
            DailyProgress.user_id == user_id, DailyProgress.group_id == group_id, DailyProgress.day == day
        )
    )
    if dp is None:
        dp = DailyProgress(
            user_id=user_id,
            group_id=group_id,
            day=day,
            active_seconds=0.0,
            pages_read=0,
            required_pages=settings.min_pages,
            required_seconds=settings.min_seconds,
            completed=False,
        )
        db.add(dp)
        db.flush()
    return dp


def check_completion(dp: DailyProgress, now: datetime) -> bool:
    """Mark the day complete once both minimums are met. Never un-completes."""
    if not dp.completed and dp.pages_read >= dp.required_pages and dp.active_seconds >= dp.required_seconds:
        dp.completed = True
        dp.completed_at = naive_utc(now)
        return True
    return False


def progress_dict(dp: DailyProgress | None, settings: GroupSettings, day: date) -> dict:
    req_pages = dp.required_pages if dp else settings.min_pages
    req_secs = dp.required_seconds if dp else settings.min_seconds
    pages = dp.pages_read if dp else 0
    secs = dp.active_seconds if dp else 0.0
    return {
        "day": day.isoformat(),
        "pages_read": pages,
        "active_seconds": round(secs, 1),
        "required_pages": req_pages,
        "required_seconds": req_secs,
        "remaining_pages": max(0, req_pages - pages),
        "remaining_seconds": max(0.0, round(req_secs - secs, 1)),
        "completed": bool(dp and dp.completed),
        "completed_at": to_utc(dp.completed_at).isoformat() if dp and dp.completed_at else None,
    }


def today_progress(db: Session, user_id: int, group: Group, now: datetime) -> dict:
    settings = group.settings
    day = effective_today(db, group, settings, now)
    dp = db.scalar(
        select(DailyProgress).where(
            DailyProgress.user_id == user_id, DailyProgress.group_id == group.id, DailyProgress.day == day
        )
    )
    return progress_dict(dp, settings, day)


# --------------------------------------------------------------------------
# Reader state (bookmark + khatma)
# --------------------------------------------------------------------------
def get_reader_state(db: Session, user_id: int, now: datetime) -> ReaderState:
    rs = db.get(ReaderState, user_id)
    if rs is None:
        rs = ReaderState(user_id=user_id, current_page=1, khatma=1, updated_at=naive_utc(now))
        db.add(rs)
        db.flush()
    return rs


def counted_pages(db: Session, user_id: int, khatma: int) -> list[int]:
    return list(
        db.scalars(
            select(PageProgress.page)
            .where(PageProgress.user_id == user_id, PageProgress.khatma == khatma, PageProgress.counted_at.is_not(None))
            .order_by(PageProgress.page)
        )
    )


def start_new_khatma(db: Session, user_id: int, now: datetime) -> ReaderState:
    rs = get_reader_state(db, user_id, now)
    done = len(counted_pages(db, user_id, rs.khatma))
    if done < KHATMA_MIN_PAGES:
        raise TrackingError(
            "khatma_incomplete",
            f"Read at least {KHATMA_MIN_PAGES} of {TOTAL_PAGES} pages before starting a new khatma ({done} so far).",
            400,
        )
    rs.khatma += 1
    rs.current_page = 1
    rs.updated_at = naive_utc(now)
    return rs


def validate_page(page: int) -> int:
    if not isinstance(page, int) or not 1 <= page <= TOTAL_PAGES:
        raise TrackingError("bad_page", f"Page must be between 1 and {TOTAL_PAGES}.", 422)
    return page


# --------------------------------------------------------------------------
# Sessions
# --------------------------------------------------------------------------
def close_session(sess: ReadingSession, now: datetime, reason: str) -> None:
    if sess.status == "active":
        sess.status = "ended"
        sess.end_reason = reason
        # A session can never end later than its last proof of life.
        sess.ended_at = naive_utc(min(now, to_utc(sess.last_heartbeat_at) + timedelta(seconds=HEARTBEAT_INTERVAL_SECONDS)))


def close_stale_sessions(db: Session, now: datetime, user_id: int | None = None) -> int:
    cutoff = naive_utc(now - timedelta(seconds=STALE_SESSION_SECONDS))
    q = select(ReadingSession).where(ReadingSession.status == "active", ReadingSession.last_heartbeat_at < cutoff)
    if user_id is not None:
        q = q.where(ReadingSession.user_id == user_id)
    n = 0
    for sess in db.scalars(q):
        close_session(sess, now, "timeout")
        n += 1
    return n


def start_session(
    db: Session, user_id: int, group: Group, client_id: str, page: int, now: datetime, client_info: str | None = None
) -> ReadingSession:
    validate_page(page)
    for other in db.scalars(
        select(ReadingSession).where(ReadingSession.user_id == user_id, ReadingSession.status == "active")
    ):
        close_session(other, now, "restarted" if other.client_id == client_id else "superseded")
    sess = ReadingSession(
        user_id=user_id,
        group_id=group.id,
        client_id=client_id[:64],
        status="active",
        started_at=naive_utc(now),
        last_heartbeat_at=naive_utc(now),
        last_seq=0,
        start_page=page,
        end_page=page,
        pages_read=0,
        active_seconds=0.0,
        client_info=(client_info or "")[:200],
    )
    db.add(sess)
    rs = get_reader_state(db, user_id, now)
    rs.current_page = page
    rs.updated_at = naive_utc(now)
    db.flush()
    return sess


@dataclass
class HeartbeatResult:
    credited_seconds: float
    newly_counted: list[int] = field(default_factory=list)
    duplicate: bool = False


def _get_page_progress(db: Session, user_id: int, khatma: int, page: int) -> PageProgress:
    pp = db.scalar(
        select(PageProgress).where(
            PageProgress.user_id == user_id, PageProgress.khatma == khatma, PageProgress.page == page
        )
    )
    if pp is None:
        pp = PageProgress(user_id=user_id, khatma=khatma, page=page, dwell_seconds=0.0)
        db.add(pp)
        db.flush()
    return pp


def _day_is_finalized(db: Session, group_id: int, day: date) -> bool:
    return db.scalar(select(GroupDay.id).where(GroupDay.group_id == group_id, GroupDay.day == day)) is not None


def heartbeat(
    db: Session,
    user_id: int,
    membership: Membership,
    session_id: int,
    seq: int,
    page: int,
    active_ms: float,
    page_ms: dict,
    now: datetime,
) -> tuple[ReadingSession, HeartbeatResult]:
    sess = db.get(ReadingSession, session_id)
    if sess is None or sess.user_id != user_id:
        raise TrackingError("no_session", "Reading session not found.", 404)
    if sess.status != "active":
        raise TrackingError("session_" + (sess.end_reason or "ended"), "This reading session has ended.")
    if sess.group_id != membership.group_id:
        close_session(sess, now, "left_group")
        raise TrackingError("session_left_group", "You are no longer in this session's group.")
    last = to_utc(sess.last_heartbeat_at)
    if (now - last).total_seconds() > STALE_SESSION_SECONDS:
        close_session(sess, now, "timeout")
        raise TrackingError("session_timeout", "The session timed out.")
    validate_page(page)
    if seq <= sess.last_seq:
        return sess, HeartbeatResult(0.0, duplicate=True)

    group: Group = membership_group(db, membership)
    settings = group.settings

    elapsed = max(0.0, (now - last).total_seconds())
    session_wall = max(0.0, (now - to_utc(sess.started_at)).total_seconds())
    reported = max(0.0, float(active_ms or 0) / 1000.0)
    credit = min(
        reported,
        elapsed + CLOCK_TOLERANCE_SECONDS,
        session_wall + CLOCK_TOLERANCE_SECONDS - sess.active_seconds,
        MAX_CREDIT_PER_HEARTBEAT,
    )
    credit = max(0.0, credit)

    # --- attribute credit to pages --------------------------------------
    per_page: dict[int, float] = {}
    for key, ms in list((page_ms or {}).items())[:MAX_PAGE_ENTRIES]:
        try:
            p, v = int(key), float(ms)
        except (TypeError, ValueError):
            continue
        if 1 <= p <= TOTAL_PAGES and v > 0:
            per_page[p] = per_page.get(p, 0.0) + v / 1000.0
    attributed = sum(per_page.values())
    if attributed <= 0:
        per_page = {page: credit}
        attributed = credit
    credit = min(credit, attributed)
    scale = credit / attributed if attributed > 0 else 0.0
    per_page = {p: s * scale for p, s in per_page.items()}

    # --- split across a reading-day boundary --------------------------------
    cur_day = effective_today(db, group, settings, now)
    prev_day = day_for(last, settings.timezone, settings.reset_minute)
    allocations: list[tuple[date, float]] = [(cur_day, 1.0)]
    if prev_day < cur_day and elapsed > 0 and not _day_is_finalized(db, group.id, prev_day):
        boundary = day_start(cur_day, settings.timezone, settings.reset_minute)
        frac_new = min(1.0, max(0.0, (now - boundary).total_seconds() / elapsed))
        allocations = [(prev_day, 1.0 - frac_new), (cur_day, frac_new)]

    rs = get_reader_state(db, user_id, now)
    result = HeartbeatResult(credited_seconds=credit)
    for day, frac in allocations:
        if frac <= 0:
            continue
        dp = get_or_create_daily(db, user_id, group.id, day, settings)
        dp.active_seconds += credit * frac
        for p, secs in sorted(per_page.items()):
            if secs <= 0:
                continue
            pp = _get_page_progress(db, user_id, rs.khatma, p)
            pp.dwell_seconds += secs * frac
            if pp.counted_at is None and pp.dwell_seconds >= settings.min_page_seconds:
                pp.counted_at = naive_utc(now)
                pp.counted_day = day
                pp.group_id = group.id
                pp.session_id = sess.id
                dp.pages_read += 1
                sess.pages_read += 1
                result.newly_counted.append(p)
        check_completion(dp, now)

    sess.active_seconds += credit
    sess.last_heartbeat_at = naive_utc(now)
    sess.last_seq = seq
    sess.end_page = page
    rs.current_page = page
    rs.updated_at = naive_utc(now)
    db.flush()
    return sess, result


def end_session(db: Session, user_id: int, session_id: int, now: datetime, reason: str = "closed") -> ReadingSession:
    sess = db.get(ReadingSession, session_id)
    if sess is None or sess.user_id != user_id:
        raise TrackingError("no_session", "Reading session not found.", 404)
    close_session(sess, now, reason)
    return sess


def membership_group(db: Session, membership: Membership) -> Group:
    return db.get(Group, membership.group_id)


def page_dwell(db: Session, user_id: int, khatma: int, page: int) -> tuple[float, bool]:
    pp = db.scalar(
        select(PageProgress).where(
            PageProgress.user_id == user_id, PageProgress.khatma == khatma, PageProgress.page == page
        )
    )
    if pp is None:
        return 0.0, False
    return pp.dwell_seconds, pp.counted_at is not None


def apply_requirement_change(db: Session, group: Group, now: datetime) -> int:
    """After settings change, update today's *uncompleted* rows to the new
    requirements. Completed days (today or earlier) are never touched."""
    settings = group.settings
    day = effective_today(db, group, settings, now)
    n = 0
    for dp in db.scalars(
        select(DailyProgress).where(
            DailyProgress.group_id == group.id, DailyProgress.day == day, DailyProgress.completed.is_(False)
        )
    ):
        dp.required_pages = settings.min_pages
        dp.required_seconds = settings.min_seconds
        check_completion(dp, now)
        n += 1
    return n


def total_counted_pages(db: Session, user_id: int) -> int:
    return db.scalar(
        select(func.count(PageProgress.id)).where(PageProgress.user_id == user_id, PageProgress.counted_at.is_not(None))
    ) or 0

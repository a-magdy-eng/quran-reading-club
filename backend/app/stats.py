"""Read models for the dashboards, personal statistics and calendars."""
from __future__ import annotations

from datetime import date, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .clock import to_utc
from .groups import active_members, current_assignment
from .models import (
    DailyProgress,
    Group,
    GroupDay,
    GroupDayMember,
    Membership,
    ReadingSession,
    User,
)
from .quran import TOTAL_PAGES, get_quran
from .streaks import (
    COMPLETED,
    EXCUSED,
    _provisional_days,
    effective_today,
    group_streak,
    user_streak,
)
from .timeutil import day_bounds
from .tracking import (
    KHATMA_MIN_PAGES,
    STALE_SESSION_SECONDS,
    counted_pages,
    get_reader_state,
    progress_dict,
    total_counted_pages,
)

READING_NOW_SECONDS = 45


def iso(dt: datetime | None) -> str | None:
    return to_utc(dt).isoformat() if dt else None


def settings_dict(group: Group) -> dict:
    s = group.settings
    return {
        "min_pages": s.min_pages,
        "min_minutes": round(s.min_seconds / 60, 2),
        "min_seconds": s.min_seconds,
        "timezone": s.timezone,
        "reset_minute": s.reset_minute,
        "reset_time": f"{s.reset_minute // 60:02d}:{s.reset_minute % 60:02d}",
        "inactivity_timeout_seconds": s.inactivity_timeout_seconds,
        "min_page_seconds": s.min_page_seconds,
        "streak_reset_day": s.streak_reset_day.isoformat() if s.streak_reset_day else None,
    }


def assignment_dict(db: Session, group_id: int) -> dict | None:
    a = current_assignment(db, group_id)
    if a is None:
        return None
    q = get_quran()
    return {
        "id": a.id,
        "start_page": a.start_page,
        "end_page": a.end_page,
        "note": a.note,
        "label": q.describe_range(a.start_page, a.end_page),
        "start": q.page_summary(a.start_page),
        "end": q.page_summary(a.end_page),
        "assigned_at": iso(a.assigned_at),
    }


def position_dict(db: Session, user_id: int, now: datetime) -> dict:
    rs = get_reader_state(db, user_id, now)
    summary = get_quran().page_summary(rs.current_page)
    return {
        **summary,
        "khatma": rs.khatma,
        "khatmas_completed": rs.khatma - 1,
        "updated_at": iso(rs.updated_at),
    }


def _active_sessions(db: Session, user_ids: list[int], now: datetime) -> dict[int, ReadingSession]:
    if not user_ids:
        return {}
    out = {}
    for s in db.scalars(
        select(ReadingSession).where(ReadingSession.user_id.in_(user_ids), ReadingSession.status == "active")
    ):
        if (now - to_utc(s.last_heartbeat_at)).total_seconds() <= READING_NOW_SECONDS:
            out[s.user_id] = s
    return out


def dashboard(db: Session, group: Group, viewer_id: int, now: datetime) -> dict:
    settings = group.settings
    today = effective_today(db, group, settings, now)
    start, end = day_bounds(today, settings.timezone, settings.reset_minute)
    members = active_members(db, group.id)
    uids = [m.user_id for m in members]
    users = {u.id: u for u in db.scalars(select(User).where(User.id.in_(uids)))} if uids else {}
    progress = {
        dp.user_id: dp
        for dp in db.scalars(select(DailyProgress).where(DailyProgress.group_id == group.id, DailyProgress.day == today))
    }
    reading_now = _active_sessions(db, uids, now)

    rows = []
    required = completed = 0
    for m in members:
        u = users[m.user_id]
        dp = progress.get(m.user_id)
        prog = progress_dict(dp, settings, today)
        joined_today = to_utc(m.joined_at) >= start
        if prog["completed"]:
            status = "done"
        elif joined_today and not dp:
            status = "new"
        elif dp and (dp.pages_read > 0 or dp.active_seconds > 0):
            status = "in_progress"
        else:
            status = "not_started"
        if prog["completed"]:
            completed += 1
            required += 1
        elif not joined_today:
            required += 1
        st = user_streak(db, group, m.user_id, now)
        rows.append(
            {
                "user_id": u.id,
                "username": u.username,
                "display_name": u.display_name,
                "role": m.role,
                "is_you": u.id == viewer_id,
                "joined_at": iso(m.joined_at),
                "excused_today": joined_today and not prog["completed"],
                "status": status,
                "today": prog,
                "reading_now": m.user_id in reading_now,
                "streak": {"current": st.current, "longest": st.longest},
                "position": position_dict(db, m.user_id, now),
            }
        )
    gst = group_streak(db, group, now)
    return {
        "group": {
            "id": group.id,
            "name": group.name,
            "member_count": len(members),
            "max_members": group.max_members,
        },
        "now": now.isoformat(),
        "today": today.isoformat(),
        "day_start": start.isoformat(),
        "deadline": end.isoformat(),
        "settings": settings_dict(group),
        "streak": {"current": gst.current, "longest": gst.longest, "today_status": gst.today_status},
        "completion": {
            "completed": completed,
            "required": required,
            "percent": round(100 * completed / required) if required else 0,
            "all_done": required > 0 and completed == required,
        },
        "pages_today": sum(r["today"]["pages_read"] for r in rows),
        "members": rows,
        "assignment": assignment_dict(db, group.id),
    }


def calendar(db: Session, group: Group, now: datetime, days: int = 180, user_id: int | None = None) -> dict:
    """Finalised days plus provisional (unfinished) ones, newest last."""
    days = max(7, min(days, 1000))
    since = effective_today(db, group, group.settings, now) - timedelta(days=days - 1)
    names = {u.id: u.display_name for u in db.scalars(select(User))}
    out = []
    gds = db.scalars(
        select(GroupDay).where(GroupDay.group_id == group.id, GroupDay.day >= since).order_by(GroupDay.day)
    ).all()
    for gd in gds:
        members = [
            {
                "user_id": m.user_id,
                "name": names.get(m.user_id, "?"),
                "outcome": m.outcome,
                "pages_read": m.pages_read,
                "active_seconds": round(m.active_seconds),
            }
            for m in gd.members
        ]
        if user_id is not None and not any(m["user_id"] == user_id for m in members):
            continue
        out.append(
            {
                "day": gd.day.isoformat(),
                "status": gd.status,
                "provisional": False,
                "completed_count": gd.completed_count,
                "required_count": gd.required_count,
                "members": members,
            }
        )
    provisional = _provisional_days(db, group, now)
    for i, ev in enumerate(provisional):
        if ev.day < since:
            continue
        is_today = i == len(provisional) - 1
        members = [
            {
                "user_id": m.user_id,
                "name": names.get(m.user_id, "?"),
                "outcome": m.outcome if (m.outcome != "failed" or not is_today) else "pending",
                "pages_read": m.pages_read,
                "active_seconds": round(m.active_seconds),
            }
            for m in ev.members
        ]
        if user_id is not None and not any(m["user_id"] == user_id for m in members):
            continue
        status = ev.status
        if is_today and status != "success":
            status = "pending"
        out.append(
            {
                "day": ev.day.isoformat(),
                "status": status,
                "provisional": True,
                "completed_count": ev.completed_count,
                "required_count": ev.required_count,
                "members": members,
            }
        )
    return {"days": out, "today": effective_today(db, group, group.settings, now).isoformat()}


def session_dict(s: ReadingSession) -> dict:
    q = get_quran()
    return {
        "id": s.id,
        "status": s.status,
        "end_reason": s.end_reason,
        "started_at": iso(s.started_at),
        "ended_at": iso(s.ended_at),
        "last_heartbeat_at": iso(s.last_heartbeat_at),
        "start_page": s.start_page,
        "end_page": s.end_page,
        "start_sura": q.page_summary(s.start_page)["sura_tname"],
        "end_sura": q.page_summary(s.end_page)["sura_tname"],
        "pages_read": s.pages_read,
        "active_seconds": round(s.active_seconds, 1),
        "client_info": s.client_info,
    }


def member_stats(db: Session, group: Group, user: User, membership: Membership | None, now: datetime) -> dict:
    settings = group.settings
    today = effective_today(db, group, settings, now)
    dp_today = db.scalar(
        select(DailyProgress).where(
            DailyProgress.user_id == user.id, DailyProgress.group_id == group.id, DailyProgress.day == today
        )
    )
    st = user_streak(db, group, user.id, now)
    total_seconds = db.scalar(
        select(func.coalesce(func.sum(DailyProgress.active_seconds), 0.0)).where(DailyProgress.user_id == user.id)
    )
    days_completed = db.scalar(
        select(func.count(DailyProgress.id)).where(DailyProgress.user_id == user.id, DailyProgress.completed.is_(True))
    )
    sessions_count = db.scalar(select(func.count(ReadingSession.id)).where(ReadingSession.user_id == user.id))
    rs = get_reader_state(db, user.id, now)
    khatma_pages = counted_pages(db, user.id, rs.khatma)

    # Daily history (newest first) with the finalised outcome where available.
    outcomes = {
        d: o
        for d, o in db.execute(
            select(GroupDay.day, GroupDayMember.outcome)
            .join(GroupDayMember, GroupDayMember.group_day_id == GroupDay.id)
            .where(GroupDay.group_id == group.id, GroupDayMember.user_id == user.id)
        ).all()
    }
    history = []
    for dp in db.scalars(
        select(DailyProgress)
        .where(DailyProgress.user_id == user.id, DailyProgress.group_id == group.id)
        .order_by(DailyProgress.day.desc())
        .limit(120)
    ):
        history.append(
            {
                **progress_dict(dp, settings, dp.day),
                "outcome": outcomes.get(dp.day, COMPLETED if dp.completed else ("pending" if dp.day >= today else "failed")),
            }
        )
    sessions = [
        session_dict(s)
        for s in db.scalars(
            select(ReadingSession)
            .where(ReadingSession.user_id == user.id)
            .order_by(ReadingSession.started_at.desc())
            .limit(50)
        )
    ]
    return {
        "user": {
            "id": user.id,
            "username": user.username,
            "display_name": user.display_name,
            "role": membership.role if membership else None,
            "joined_at": iso(membership.joined_at) if membership else None,
        },
        "streak": {"current": st.current, "longest": st.longest, "today_status": st.today_status},
        "today": progress_dict(dp_today, settings, today),
        "totals": {
            "pages": total_counted_pages(db, user.id),
            "active_seconds": round(float(total_seconds or 0), 1),
            "days_completed": days_completed or 0,
            "sessions": sessions_count or 0,
            "khatmas_completed": rs.khatma - 1,
        },
        "position": position_dict(db, user.id, now),
        "khatma": {
            "number": rs.khatma,
            "counted_pages": khatma_pages,
            "counted": len(khatma_pages),
            "total_pages": TOTAL_PAGES,
            "can_start_new": len(khatma_pages) >= KHATMA_MIN_PAGES,
            "min_pages_for_new": KHATMA_MIN_PAGES,
        },
        "history": history,
        "sessions": sessions,
        "deadline": day_bounds(today, settings.timezone, settings.reset_minute)[1].isoformat(),
    }


def excused_or_completed(outcome: str) -> bool:
    return outcome in (COMPLETED, EXCUSED)


__all__ = ["dashboard", "calendar", "member_stats", "settings_dict", "STALE_SESSION_SECONDS"]

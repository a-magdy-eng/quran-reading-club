"""Daily completion, individual and group streaks, day boundaries, persistence."""
from datetime import date, datetime, timedelta, timezone

import pytest

from app.models import DailyProgress, GroupDay
from app.streaks import FAILED, NEUTRAL, PENDING, SUCCESS, current_streak, longest_streak
from app.timeutil import day_bounds, day_for, day_end, day_start

UTC = timezone.utc
D = date(2026, 3, 10)


def cairo(day_offset: int, hh: int, mm: int = 0, ss: int = 0) -> datetime:
    """Africa/Cairo is UTC+2 in March 2026."""
    d = D + timedelta(days=day_offset)
    return datetime(d.year, d.month, d.day, hh, mm, ss, tzinfo=UTC) - timedelta(hours=2)


def entries(*statuses, start=D):
    return [(start + timedelta(days=i), s) for i, s in enumerate(statuses)]


# --------------------------------------------------------------------------
# Pure streak arithmetic
# --------------------------------------------------------------------------
@pytest.mark.parametrize(
    "statuses,current,longest",
    [
        ([], 0, 0),
        ([SUCCESS], 1, 1),
        ([SUCCESS, SUCCESS, SUCCESS], 3, 3),
        ([SUCCESS, FAILED, SUCCESS], 1, 1),
        ([SUCCESS, SUCCESS, FAILED], 0, 2),
        ([SUCCESS, SUCCESS, PENDING], 2, 2),  # today not done yet: streak alive
        ([SUCCESS, NEUTRAL, SUCCESS], 2, 2),  # neutral neither breaks nor extends
        ([FAILED, SUCCESS, SUCCESS, SUCCESS, FAILED, SUCCESS], 1, 3),
        ([SUCCESS, SUCCESS, SUCCESS, FAILED, SUCCESS, SUCCESS, PENDING], 2, 3),
    ],
)
def test_pure_streaks(statuses, current, longest):
    e = entries(*statuses)
    assert current_streak(e) == current
    assert longest_streak(e) == longest


def test_gap_breaks_streak():
    e = [(D, SUCCESS), (D + timedelta(days=1), SUCCESS), (D + timedelta(days=3), SUCCESS)]
    assert current_streak(e) == 1
    assert longest_streak(e) == 2


def test_reset_day_ignores_older_days():
    e = entries(SUCCESS, SUCCESS, SUCCESS, SUCCESS)
    assert current_streak(e, reset_day=D + timedelta(days=1)) == 2
    assert longest_streak(e) == 4


def test_streak_functions_are_deterministic():
    e = entries(SUCCESS, FAILED, SUCCESS, SUCCESS, NEUTRAL, SUCCESS, PENDING)
    assert {current_streak(e) for _ in range(50)} == {3}
    assert {longest_streak(e) for _ in range(50)} == {3}


# --------------------------------------------------------------------------
# Day arithmetic and timezones
# --------------------------------------------------------------------------
def test_day_for_with_reset_time():
    # 02:00 local on the 11th with a 04:00 reset still belongs to the 10th.
    assert day_for(cairo(1, 2), "Africa/Cairo", 240) == D
    assert day_for(cairo(1, 4), "Africa/Cairo", 240) == D + timedelta(days=1)
    assert day_for(cairo(0, 23, 59, 59), "Africa/Cairo", 0) == D
    assert day_for(cairo(1, 0), "Africa/Cairo", 0) == D + timedelta(days=1)


def test_same_instant_different_timezones():
    instant = datetime(2026, 3, 10, 20, 0, tzinfo=UTC)
    assert day_for(instant, "Asia/Tokyo", 0) == date(2026, 3, 11)
    assert day_for(instant, "America/New_York", 0) == date(2026, 3, 10)
    assert day_for(instant, "Africa/Cairo", 0) == date(2026, 3, 10)


def test_dst_transition_days_are_contiguous():
    # Egypt starts DST at local midnight on the last Friday of April (2026-04-24).
    for tz in ("Africa/Cairo", "America/New_York", "Europe/London"):
        d = date(2026, 3, 1)
        for _ in range(120):
            start, end = day_bounds(d, tz, 0)
            assert end == day_start(d + timedelta(days=1), tz, 0)
            assert day_for(start, tz, 0) == d
            assert day_for(end - timedelta(seconds=1), tz, 0) == d
            assert timedelta(hours=22) <= end - start <= timedelta(hours=26)
            d += timedelta(days=1)


# --------------------------------------------------------------------------
# Group / individual streaks through the API
# --------------------------------------------------------------------------
def club(env):
    admin = env.setup_group()
    omar = env.join(admin, "omar")
    ali = env.join(admin, "ali", ip="192.168.1.50")
    return admin, omar, ali


def by_name(dash):
    return {m["username"]: m for m in dash["members"]}


def test_group_streak_grows_only_when_everyone_completes(env):
    admin, omar, ali = club(env)
    page = {admin: 1, omar: 100, ali: 300}

    for day in range(3):
        env.clock.set(cairo(day, 9))
        for api in (admin, omar, ali):
            env.complete_day(api, page[api])
            page[api] += 2
        dash = admin.ok("get", "/api/dashboard")
        assert dash["completion"]["all_done"] is True
        assert dash["streak"]["current"] == day + 1
        assert dash["streak"]["today_status"] == SUCCESS
        # Reading extra does not add streak days.
        env.complete_day(admin, page[admin], minutes=30, pages=5)
        page[admin] += 5
        assert admin.ok("get", "/api/dashboard")["streak"]["current"] == day + 1

    env.clock.set(cairo(3, 9))
    dash = admin.ok("get", "/api/dashboard")
    assert dash["streak"] == {"current": 3, "longest": 3, "today_status": PENDING}
    for m in dash["members"]:
        assert m["streak"] == {"current": 3, "longest": 3}


def test_one_member_failing_resets_group_streak(env):
    admin, omar, ali = club(env)
    env.clock.set(cairo(0, 11))
    for api, p in ((admin, 1), (omar, 100), (ali, 300)):
        env.complete_day(api, p)
    env.clock.set(cairo(1, 9))
    env.complete_day(admin, 3)
    env.complete_day(ali, 302)
    env.complete_day(omar, 102, minutes=19)  # one minute short!

    dash = admin.ok("get", "/api/dashboard")
    # Day 2 is not over yet, so the group streak is still alive (1) but not extended.
    assert dash["streak"]["current"] == 1 and dash["streak"]["today_status"] == PENDING
    assert by_name(dash)["omar"]["status"] == "in_progress"
    assert dash["completion"] == {"completed": 2, "required": 3, "percent": 67, "all_done": False}

    env.clock.set(cairo(2, 9))
    dash = admin.ok("get", "/api/dashboard")
    assert dash["streak"]["current"] == 0
    assert dash["streak"]["longest"] == 1
    names = by_name(dash)
    assert names["host"]["streak"] == {"current": 2, "longest": 2}
    assert names["ali"]["streak"] == {"current": 2, "longest": 2}
    assert names["omar"]["streak"] == {"current": 0, "longest": 1}

    cal = admin.ok("get", "/api/calendar")["days"]
    statuses = [(d["day"], d["status"]) for d in cal]
    assert statuses == [("2026-03-10", SUCCESS), ("2026-03-11", FAILED), ("2026-03-12", PENDING)]
    failed_day = cal[1]
    outcome = {m["name"]: m["outcome"] for m in failed_day["members"]}
    assert outcome == {"Host": "completed", "Omar": "failed", "Ali": "completed"}


def test_day_is_not_finalised_prematurely(env):
    admin, omar, ali = club(env)
    env.clock.set(cairo(1, 23, 59))
    admin.ok("get", "/api/dashboard")
    with env.app.state.rc.db.session() as db:
        assert db.query(GroupDay).filter_by(day=D + timedelta(days=1)).count() == 0
    # Within the grace period after midnight the day is still open.
    env.clock.set(cairo(2, 0, 1))
    admin.ok("get", "/api/dashboard")
    with env.app.state.rc.db.session() as db:
        assert db.query(GroupDay).filter_by(day=D + timedelta(days=1)).count() == 0
    env.clock.set(cairo(2, 0, 3))
    admin.ok("get", "/api/dashboard")
    with env.app.state.rc.db.session() as db:
        gd = db.query(GroupDay).filter_by(day=D + timedelta(days=1)).one()
        assert gd.status == FAILED
    # Finalisation is idempotent.
    admin.ok("get", "/api/dashboard")
    admin.ok("get", "/api/calendar")
    with env.app.state.rc.db.session() as db:
        assert db.query(GroupDay).filter_by(day=D + timedelta(days=1)).count() == 1


def test_reading_across_midnight_is_split_between_days(env):
    admin = env.setup_group()
    env.clock.set(cairo(1, 23, 59, 50))
    sid = env.start(admin, 5)
    env.clock.set(cairo(2, 0, 0, 5))  # 15 s heartbeat: 10 s before, 5 s after midnight
    admin.ok(
        "post",
        f"/api/reading/sessions/{sid}/heartbeat",
        {"seq": 1, "page": 5, "active_ms": 15000, "page_ms": {"5": 15000}},
    )
    with env.app.state.rc.db.session() as db:
        rows = {r.day: r.active_seconds for r in db.query(DailyProgress)}
    assert rows[D + timedelta(days=1)] == pytest.approx(10, abs=0.01)
    assert rows[D + timedelta(days=2)] == pytest.approx(5, abs=0.01)


def test_last_minute_reading_counts_for_the_ending_day(env):
    admin = env.setup_group()
    env.clock.set(cairo(1, 23, 40, 0))
    sid = env.start(admin, 10)
    env.read(admin, 20 * 60 - 10, pages=[10, 11], session=sid)  # ends 23:59:50, 1190 s
    env.read(admin, 15, page=11, session=sid)  # heartbeat at 00:00:05: 10 s belong to the old day
    with env.app.state.rc.db.session() as db:
        dp = db.query(DailyProgress).filter_by(day=D + timedelta(days=1)).one()
        assert dp.completed is True


def test_reset_time_and_timezone_settings(env):
    admin = env.setup_group()
    admin.ok("patch", "/api/admin/settings", {"reset_time": "04:00"})
    env.clock.set(cairo(1, 2))  # 02:00 local, before the 04:00 reset
    dash = admin.ok("get", "/api/dashboard")
    assert dash["today"] == "2026-03-10"
    assert dash["deadline"] == cairo(1, 4).isoformat()
    env.clock.set(cairo(1, 5))
    assert admin.ok("get", "/api/dashboard")["today"] == "2026-03-11"
    r = admin.patch("/api/admin/settings", json={"timezone": "Mars/Olympus"})
    assert r.status_code == 422
    admin.ok("patch", "/api/admin/settings", {"timezone": "Asia/Tokyo", "reset_time": "00:00"})
    # 05:00 Cairo = 12:00 Tokyo, still the 11th there.
    assert admin.ok("get", "/api/dashboard")["today"] == "2026-03-11"


def test_timezone_change_never_rewrites_finalised_days(env):
    admin = env.setup_group(timezone="Asia/Tokyo")
    env.clock.set(datetime(2026, 3, 11, 15, 5, tzinfo=UTC))  # 00:05 on the 12th in Tokyo
    admin.ok("get", "/api/dashboard")
    admin.ok("get", "/api/calendar")
    env.clock.set(datetime(2026, 3, 11, 15, 10, tzinfo=UTC))
    admin.ok("get", "/api/dashboard")
    # Moving the group to a timezone where it is still the 11th...
    admin.ok("patch", "/api/admin/settings", {"timezone": "America/Los_Angeles"})
    dash = admin.ok("get", "/api/dashboard")
    # ...credits activity to the next open day instead of the finalised 11th.
    assert dash["today"] == "2026-03-12"


def test_requirement_changes_are_not_retroactive(env):
    admin, omar, ali = club(env)
    env.clock.set(cairo(1, 9))
    env.complete_day(admin, 1)
    env.complete_day(omar, 100, pages=3)
    env.read(ali, 5 * 60, page=300)  # ali has 1 page / 5 minutes so far
    admin.ok("patch", "/api/admin/settings", {"min_pages": 3, "min_minutes": 25})
    dash = by_name(admin.ok("get", "/api/dashboard"))
    assert dash["host"]["today"]["completed"] is True  # stays completed
    assert dash["omar"]["today"]["completed"] is True
    assert dash["ali"]["today"]["required_pages"] == 3  # still-open day uses the new rule
    # Lowering the requirement completes ali immediately.
    admin.ok("patch", "/api/admin/settings", {"min_pages": 1, "min_minutes": 5})
    assert by_name(admin.ok("get", "/api/dashboard"))["ali"]["today"]["completed"] is True
    env.clock.set(cairo(2, 9))
    dash = admin.ok("get", "/api/dashboard")
    assert dash["streak"]["current"] == 1
    cal = admin.ok("get", "/api/calendar")["days"]
    assert cal[1]["status"] == SUCCESS


def test_new_member_is_excused_on_join_day(env):
    admin = env.setup_group()
    env.clock.set(cairo(1, 9))
    env.complete_day(admin, 1)
    env.clock.set(cairo(2, 9))
    env.complete_day(admin, 3)
    omar = env.join(admin, "omar")  # joins mid-day and does not read
    dash = admin.ok("get", "/api/dashboard")
    assert by_name(dash)["omar"]["excused_today"] is True
    assert dash["completion"]["all_done"] is True
    env.clock.set(cairo(3, 9))
    dash = admin.ok("get", "/api/dashboard")
    assert dash["streak"]["current"] == 2  # day 1 (10th) neutral: nobody read; 11th+12th success
    env.complete_day(admin, 5)
    assert admin.ok("get", "/api/dashboard")["streak"]["today_status"] == PENDING  # omar now required
    env.complete_day(omar, 100)
    assert admin.ok("get", "/api/dashboard")["streak"]["current"] == 3


def test_removed_member_no_longer_blocks_streak(env):
    admin, omar, ali = club(env)
    env.clock.set(cairo(1, 9))
    env.complete_day(admin, 1)
    env.complete_day(omar, 100)
    ali_id = ali.ok("get", "/api/auth/me")["user"]["id"]
    admin.ok("delete", f"/api/admin/members/{ali_id}")
    dash = admin.ok("get", "/api/dashboard")
    assert dash["completion"]["all_done"] is True and dash["streak"]["current"] == 1


def test_manual_streak_reset_requires_confirmation(env):
    admin = env.setup_group()
    for day in range(1, 4):
        env.clock.set(cairo(day, 9))
        env.complete_day(admin, day * 2)
    assert admin.ok("get", "/api/dashboard")["streak"]["current"] == 3
    assert admin.post("/api/admin/streak/reset", json={"confirm_group_name": "wrong"}).status_code == 400
    admin.ok("post", "/api/admin/streak/reset", {"confirm_group_name": "Fajr Circle"})
    dash = admin.ok("get", "/api/dashboard")
    assert dash["streak"]["current"] == 0 and dash["streak"]["longest"] == 3
    env.clock.set(cairo(4, 9))
    env.complete_day(admin, 20)
    assert admin.ok("get", "/api/dashboard")["streak"]["current"] == 1


def test_server_restart_keeps_everything_and_catches_up(env):
    admin, omar, ali = club(env)
    env.clock.set(cairo(1, 9))
    for api, p in ((admin, 1), (omar, 100), (ali, 300)):
        env.complete_day(api, p)
    env.read(admin, 60, page=3)  # a partial session in flight

    # Laptop shuts down. It is switched back on three days later.
    env.clock.set(cairo(4, 8))
    env.restart()
    for api in (admin, omar, ali):
        api.rebind(env.app)  # same browsers, same tokens, new server process
    dash = admin.ok("get", "/api/dashboard")
    cal = {d["day"]: d["status"] for d in admin.ok("get", "/api/calendar")["days"]}
    assert cal["2026-03-11"] == SUCCESS
    assert cal["2026-03-12"] == FAILED and cal["2026-03-13"] == FAILED
    assert dash["streak"] == {"current": 0, "longest": 1, "today_status": PENDING}
    me = admin.ok("get", "/api/stats/me")
    assert me["totals"]["pages"] == 3  # pages 1, 2 and 3
    assert me["position"]["page"] == 3


def test_day_end_helper_matches_dashboard_deadline(env):
    admin = env.setup_group()
    dash = admin.ok("get", "/api/dashboard")
    assert dash["deadline"] == day_end(D, "Africa/Cairo", 0).isoformat()

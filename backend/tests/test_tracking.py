"""Reading sessions, active-time crediting, inactivity and page counting."""
from conftest import LAN_IP


def hb(api, sid, seq, page, active_ms, page_ms=None):
    return api.post(
        f"/api/reading/sessions/{sid}/heartbeat",
        json={"seq": seq, "page": page, "active_ms": active_ms, "page_ms": page_ms or {str(page): active_ms}},
    )


def test_active_time_is_credited(env):
    a = env.setup_group()
    _, last = env.read(a, 120, page=5)
    assert abs(last["today"]["active_seconds"] - 120) < 0.01
    assert last["today"]["remaining_seconds"] == 20 * 60 - 120


def test_credit_is_capped_by_wall_clock(env):
    a = env.setup_group()
    sid = env.start(a, 3)
    env.clock.advance(5)
    data = hb(a, sid, 1, 3, 60_000).json()  # claims 60 s after only 5 s
    assert data["credited_seconds"] <= 7.0
    env.clock.advance(1)
    data = hb(a, sid, 2, 3, 60_000).json()
    # Cumulative cap: total credit never exceeds session wall time + 2 s.
    assert data["today"]["active_seconds"] <= 6 + 2.0 + 1e-6


def test_credit_per_heartbeat_has_a_ceiling(env):
    a = env.setup_group()
    sid = env.start(a, 3)
    env.clock.advance(80)
    data = hb(a, sid, 1, 3, 80_000).json()
    assert data["credited_seconds"] == 60


def test_replayed_heartbeat_is_ignored(env):
    a = env.setup_group()
    sid = env.start(a, 3)
    env.clock.advance(15)
    first = hb(a, sid, 1, 3, 15_000).json()
    env.clock.advance(15)
    again = hb(a, sid, 1, 3, 15_000).json()
    assert again["duplicate"] is True
    assert again["today"]["active_seconds"] == first["today"]["active_seconds"]


def test_paused_time_is_never_counted(env):
    """The client reports 0 active ms while hidden/blurred/idle."""
    a = env.setup_group()
    sid = env.start(a, 3)
    env.clock.advance(15)
    hb(a, sid, 1, 3, 15_000)
    for seq in range(2, 6):  # one minute in another tab
        env.clock.advance(15)
        hb(a, sid, seq, 3, 0, {})
    env.clock.advance(15)
    data = hb(a, sid, 6, 3, 15_000).json()
    assert abs(data["today"]["active_seconds"] - 30) < 0.01


def test_inactivity_beyond_timeout_closes_session(env):
    a = env.setup_group()
    sid = env.start(a, 3)
    env.clock.advance(15)
    hb(a, sid, 1, 3, 15_000)
    env.clock.advance(200)  # laptop asleep / tab frozen: no heartbeats
    r = hb(a, sid, 2, 3, 200_000)
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "session_timeout"
    state = a.ok("get", "/api/reading/state")
    assert abs(state["today"]["active_seconds"] - 15) < 0.01


def test_one_active_session_per_user(env):
    """A second tab/device supersedes the first, so time is never double counted."""
    a = env.setup_group()
    phone = env.api(LAN_IP)
    phone.token = a.token
    s1 = env.start(a, 3)
    s2 = env.start(phone, 3)
    env.clock.advance(15)
    r = hb(a, s1, 1, 3, 15_000)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "session_superseded"
    assert hb(phone, s2, 1, 3, 15_000).status_code == 200
    state = a.ok("get", "/api/reading/state")
    assert abs(state["today"]["active_seconds"] - 15) < 0.01


def test_page_counts_only_after_minimum_dwell(env):
    a = env.setup_group()
    sid = env.start(a, 10)
    env.clock.advance(15)
    d = hb(a, sid, 1, 10, 15_000).json()
    assert d["newly_counted"] == [] and d["current_page_counted"] is False
    env.clock.advance(10)
    d = hb(a, sid, 2, 10, 10_000).json()
    assert d["newly_counted"] == [10]
    assert d["today"]["pages_read"] == 1


def test_fast_flipping_counts_nothing(env):
    a = env.setup_group()
    sid = env.start(a, 1)
    env.clock.advance(15)
    # 15 s spread over 10 pages = 1.5 s each: below the 20 s minimum.
    d = hb(a, sid, 1, 10, 15_000, {str(p): 1500 for p in range(1, 11)}).json()
    assert d["today"]["pages_read"] == 0


def test_revisiting_and_reloading_pages_do_not_add_pages(env):
    a = env.setup_group()
    env.read(a, 60, pages=[20, 21])  # both counted
    state = a.ok("get", "/api/reading/state")
    assert state["today"]["pages_read"] == 2
    # Back to page 20, forward to 21, reload (new session) on 21.
    env.read(a, 60, pages=[20, 21, 20])
    env.read(a, 60, page=21)
    state = a.ok("get", "/api/reading/state")
    assert state["today"]["pages_read"] == 2
    assert state["counted_pages"] == [20, 21]


def test_dwell_accumulates_across_visits(env):
    a = env.setup_group()
    env.read(a, 12, page=30)
    env.read(a, 12, page=31)
    _, last = env.read(a, 12, page=30)
    assert last["newly_counted"] == [30]


def test_daily_requirement_needs_both_pages_and_time(env):
    a = env.setup_group()
    # Lots of pages, too little time.
    env.read(a, 6 * 60, pages=[1, 2, 3, 4, 5, 6])
    st = a.ok("get", "/api/reading/state")["today"]
    assert st["pages_read"] == 6 and st["completed"] is False
    # Enough time, still the same pages -> completes.
    env.read(a, 14 * 60, page=6)
    st = a.ok("get", "/api/reading/state")["today"]
    assert st["completed"] is True

    b_admin = env.setup_group("Second", "host2")
    # Enough time on a single page -> not complete (needs 2 pages).
    env.read(b_admin, 25 * 60, page=100)
    st = b_admin.ok("get", "/api/reading/state")["today"]
    assert st["active_seconds"] >= 1200 and st["pages_read"] == 1 and st["completed"] is False


def test_session_record_contents(env):
    a = env.setup_group()
    sid, _ = env.read(a, 60, pages=[40, 41])
    end = a.ok("post", f"/api/reading/sessions/{sid}/end")
    s = end["session"]
    assert s["status"] == "ended" and s["start_page"] == 40 and s["end_page"] == 41
    assert s["pages_read"] == 2 and abs(s["active_seconds"] - 60) < 0.01
    assert s["started_at"] and s["ended_at"]
    hist = a.ok("get", "/api/stats/me")["sessions"]
    assert hist[0]["id"] == sid


def test_end_with_final_heartbeat(env):
    a = env.setup_group()
    sid = env.start(a, 7)
    env.clock.advance(10)
    end = a.ok("post", f"/api/reading/sessions/{sid}/end", {"seq": 1, "page": 7, "active_ms": 10_000, "page_ms": {"7": 10_000}})
    assert abs(end["today"]["active_seconds"] - 10) < 0.01
    assert hb(a, sid, 2, 7, 1000).status_code == 409


def test_bookmark_is_remembered(env):
    a = env.setup_group()
    env.read(a, 30, pages=[77, 78])
    assert a.ok("get", "/api/reading/state")["current_page"] == 78
    a.ok("post", "/api/reading/position", {"page": 300})
    assert a.ok("get", "/api/reading/state")["current_page"] == 300
    assert a.post("/api/reading/position", json={"page": 999}).status_code == 422


def test_new_khatma_requires_most_pages(env):
    a = env.setup_group()
    r = a.post("/api/reading/khatma/new")
    assert r.status_code == 400
    # Mark 544 pages as read directly in the DB (simulating months of reading).
    from app.models import PageProgress, User

    with env.app.state.rc.db.session() as db:
        uid = db.query(User).filter_by(username_key="host").one().id
        for p in range(1, 545):
            db.add(PageProgress(user_id=uid, khatma=1, page=p, dwell_seconds=60, counted_at=env.clock.now().replace(tzinfo=None)))
    st = a.ok("post", "/api/reading/khatma/new")
    assert st["khatma"] == 2 and st["counted_pages"] == [] and st["current_page"] == 1
    # In a new khatma, page 1 can be counted again.
    _, last = env.read(a, 30, page=1)
    assert last["newly_counted"] == [1]


def test_multiple_members_reading_simultaneously(env):
    admin = env.setup_group()
    m1 = env.join(admin, "omar")
    m2 = env.join(admin, "ali", ip="192.168.1.50")
    sids = {api: env.start(api, p) for api, p in ((admin, 1), (m1, 100), (m2, 300))}
    for seq in range(1, 9):
        env.clock.advance(15)
        for api, sid in sids.items():
            hb(api, sid, seq, {admin: 1, m1: 100, m2: 300}[api], 15_000)
    dash = admin.ok("get", "/api/dashboard")
    for row in dash["members"]:
        assert abs(row["today"]["active_seconds"] - 120) < 0.01
        assert row["today"]["pages_read"] == 1
        assert row["reading_now"] is True

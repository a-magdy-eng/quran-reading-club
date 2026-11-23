"""HTTP API (all under /api)."""
from __future__ import annotations

from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import APP_ID, APP_NAME, __version__
from .clock import naive_utc
from .deps import (
    client_ip,
    current_group,
    current_membership,
    current_user,
    get_db,
    is_host_request,
    now,
    require_admin,
    state,
)
from .groups import (
    GroupError,
    active_membership,
    add_member,
    audit,
    clear_assignment,
    create_group,
    create_user,
    find_group_by_invite,
    member_count,
    regenerate_invite,
    remove_member,
    set_assignment,
    set_role,
    validate_display_name,
    validate_password,
)
from .models import AuthToken, Group, Membership, ReadingSession, User
from .quran import TOTAL_PAGES, get_quran
from .security import (
    burn_password_check,
    hash_password,
    new_temp_password,
    new_token,
    token_digest,
    verify_password,
)
from .stats import calendar, dashboard, member_stats, session_dict, settings_dict
from .streaks import effective_today, finalize_group
from .timeutil import all_timezones, is_valid_timezone
from .tracking import (
    HEARTBEAT_INTERVAL_SECONDS,
    STALE_SESSION_SECONDS,
    TrackingError,
    apply_requirement_change,
    close_stale_sessions,
    counted_pages,
    end_session,
    get_reader_state,
    heartbeat,
    page_dwell,
    start_new_khatma,
    start_session,
    today_progress,
    validate_page,
)

router = APIRouter(prefix="/api")


def _raise(exc: Exception):
    if isinstance(exc, GroupError):
        raise HTTPException(exc.status, exc.message)
    if isinstance(exc, TrackingError):
        raise HTTPException(exc.status, {"code": exc.code, "message": exc.message})
    raise exc


def _issue_token(db: Session, request: Request, user: User) -> str:
    t = now(request)
    token = new_token()
    db.add(
        AuthToken(
            user_id=user.id,
            token_hash=token_digest(token),
            created_at=naive_utc(t),
            last_used_at=naive_utc(t),
            expires_at=naive_utc(t + timedelta(days=state(request).config.token_ttl_days)),
            user_agent=(request.headers.get("user-agent") or "")[:200],
        )
    )
    db.flush()
    return token


def _can_create_groups(request: Request) -> bool:
    return state(request).config.allow_remote_group_creation or is_host_request(request)


def _finalize(db: Session, group: Group, request: Request) -> None:
    t = now(request)
    finalize_group(db, group, t)
    close_stale_sessions(db, t)


# ---------------------------------------------------------------------------
# Health / info
# ---------------------------------------------------------------------------
@router.get("/health")
def health():
    return {"app": APP_ID, "name": APP_NAME, "version": __version__, "status": "ok"}


@router.get("/info")
def info(request: Request):
    return {
        "name": APP_NAME,
        "version": __version__,
        "can_create_group": _can_create_groups(request),
        "is_host": is_host_request(request),
        "timezones": all_timezones(),
        "attribution": get_quran().meta()["attribution"],
    }


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------
class LoginIn(BaseModel):
    username: str = Field(max_length=64)
    password: str = Field(max_length=256)


class RegisterIn(BaseModel):
    username: str = Field(max_length=64)
    password: str = Field(max_length=256)
    display_name: str | None = Field(default=None, max_length=80)
    invite_code: str = Field(max_length=32)


class CreateGroupIn(BaseModel):
    group_name: str = Field(max_length=120)
    timezone: str = Field(default="Africa/Cairo", max_length=64)
    max_members: int = 10
    min_pages: int = Field(default=2, ge=1, le=TOTAL_PAGES)
    min_minutes: int = Field(default=20, ge=1, le=600)


class SetupIn(CreateGroupIn):
    username: str = Field(max_length=64)
    password: str = Field(max_length=256)
    display_name: str | None = Field(default=None, max_length=80)


def _me_payload(db: Session, user: User, request: Request) -> dict:
    m = active_membership(db, user.id)
    group = db.get(Group, m.group_id) if m else None
    return {
        "user": {"id": user.id, "username": user.username, "display_name": user.display_name},
        "membership": {"role": m.role, "joined_at": m.joined_at.isoformat() + "Z", "group_id": m.group_id} if m else None,
        "group": {
            "id": group.id,
            "name": group.name,
            "settings": settings_dict(group),
        }
        if group
        else None,
        "can_create_group": _can_create_groups(request),
        "is_host": is_host_request(request),
    }


@router.post("/auth/login")
def login(body: LoginIn, request: Request, db: Session = Depends(get_db)):
    st = state(request)
    ip = client_ip(request)
    if st.throttle.is_locked(ip, body.username) or st.user_throttle.is_locked("*", body.username):
        raise HTTPException(429, "Too many failed attempts. Try again in a few minutes.")

    def fail():
        st.throttle.record_failure(ip, body.username)
        st.user_throttle.record_failure("*", body.username)
        raise HTTPException(401, "Wrong username or password.")

    user = db.scalar(select(User).where(User.username_key == body.username.strip().lower()))
    if user is None:
        burn_password_check(body.password)
        fail()
    if not verify_password(body.password, user.password_hash) or not user.is_active:
        fail()
    st.throttle.reset(ip, body.username)
    token = _issue_token(db, request, user)
    return {"token": token, "me": _me_payload(db, user, request)}


@router.post("/auth/register")
def register(body: RegisterIn, request: Request, db: Session = Depends(get_db)):
    """Create an account and join a group with its invitation code."""
    st = state(request)
    ip = client_ip(request)
    if st.throttle.is_locked(ip, "#invite"):
        raise HTTPException(429, "Too many wrong invitation codes. Try again in a few minutes.")
    try:
        try:
            group = find_group_by_invite(db, body.invite_code)
        except GroupError:
            st.throttle.record_failure(ip, "#invite")  # slows down guessing codes
            raise
        if member_count(db, group.id) >= group.max_members:
            raise GroupError(f"The group is full ({group.max_members} members).", 409)
        user = create_user(db, body.username, body.password, body.display_name, now(request))
        add_member(db, group, user, now(request))
    except GroupError as exc:
        _raise(exc)
    token = _issue_token(db, request, user)
    return {"token": token, "me": _me_payload(db, user, request)}


@router.post("/auth/setup")
def setup(body: SetupIn, request: Request, db: Session = Depends(get_db)):
    """Create an administrator account together with a new group (host only)."""
    if not _can_create_groups(request):
        raise HTTPException(403, "New groups can only be created on the host computer.")
    try:
        user = create_user(db, body.username, body.password, body.display_name, now(request))
        create_group(
            db, user, body.group_name, now(request), body.timezone, body.max_members, body.min_pages, body.min_minutes
        )
    except GroupError as exc:
        _raise(exc)
    token = _issue_token(db, request, user)
    return {"token": token, "me": _me_payload(db, user, request)}


@router.post("/auth/logout")
def logout(request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    at = db.get(AuthToken, request.state.token_id)
    if at is not None:
        db.delete(at)
    return {"ok": True}


@router.get("/auth/me")
def me(request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    return _me_payload(db, user, request)


class ProfileIn(BaseModel):
    display_name: str = Field(max_length=80)


@router.patch("/auth/profile")
def update_profile(body: ProfileIn, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    try:
        user.display_name = validate_display_name(body.display_name, user.username)
    except GroupError as exc:
        _raise(exc)
    return _me_payload(db, user, request)


class PasswordIn(BaseModel):
    current_password: str = Field(max_length=256)
    new_password: str = Field(max_length=256)


@router.post("/auth/password")
def change_password(body: PasswordIn, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    if not verify_password(body.current_password, user.password_hash):
        raise HTTPException(400, "Current password is wrong.")
    try:
        validate_password(body.new_password)
    except GroupError as exc:
        _raise(exc)
    user.password_hash = hash_password(body.new_password)
    # Sign out every other device.
    for at in db.scalars(select(AuthToken).where(AuthToken.user_id == user.id, AuthToken.id != request.state.token_id)):
        db.delete(at)
    return {"ok": True}


# ---------------------------------------------------------------------------
# Joining / creating a group for an existing account
# ---------------------------------------------------------------------------
class JoinIn(BaseModel):
    invite_code: str = Field(max_length=32)


@router.post("/groups/join")
def join_group(body: JoinIn, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    st = state(request)
    if st.throttle.is_locked(client_ip(request), "#invite"):
        raise HTTPException(429, "Too many wrong invitation codes. Try again in a few minutes.")
    try:
        try:
            group = find_group_by_invite(db, body.invite_code)
        except GroupError:
            st.throttle.record_failure(client_ip(request), "#invite")
            raise
        add_member(db, group, user, now(request))
    except GroupError as exc:
        _raise(exc)
    return _me_payload(db, user, request)


@router.post("/groups")
def new_group(body: CreateGroupIn, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    if not _can_create_groups(request):
        raise HTTPException(403, "New groups can only be created on the host computer.")
    try:
        create_group(db, user, body.group_name, now(request), body.timezone, body.max_members, body.min_pages, body.min_minutes)
    except GroupError as exc:
        _raise(exc)
    return _me_payload(db, user, request)


@router.post("/group/leave")
def leave_group(request: Request, m: Membership = Depends(current_membership), db: Session = Depends(get_db)):
    group = db.get(Group, m.group_id)
    try:
        remove_member(db, group, m.user_id, now(request), m.user_id)
    except GroupError as exc:
        _raise(exc)
    return {"ok": True}


# ---------------------------------------------------------------------------
# Quran text
# ---------------------------------------------------------------------------
@router.get("/quran/meta")
def quran_meta(user: User = Depends(current_user)):
    return get_quran().meta()


@router.get("/quran/page/{page}")
def quran_page(page: int, user: User = Depends(current_user)):
    if not 1 <= page <= TOTAL_PAGES:
        raise HTTPException(404, "No such page.")
    return get_quran().page(page)


# ---------------------------------------------------------------------------
# Dashboard and statistics
# ---------------------------------------------------------------------------
@router.get("/dashboard")
def get_dashboard(
    request: Request,
    user: User = Depends(current_user),
    group: Group = Depends(current_group),
    db: Session = Depends(get_db),
):
    _finalize(db, group, request)
    return dashboard(db, group, user.id, now(request))


@router.get("/calendar")
def get_calendar(
    request: Request,
    days: int = 180,
    user_id: int | None = None,
    group: Group = Depends(current_group),
    db: Session = Depends(get_db),
):
    _finalize(db, group, request)
    return calendar(db, group, now(request), days, user_id)


@router.get("/stats/me")
def my_stats(
    request: Request,
    user: User = Depends(current_user),
    m: Membership = Depends(current_membership),
    db: Session = Depends(get_db),
):
    group = db.get(Group, m.group_id)
    _finalize(db, group, request)
    return member_stats(db, group, user, m, now(request))


@router.get("/stats/members/{user_id}")
def member_detail(
    user_id: int,
    request: Request,
    m: Membership = Depends(current_membership),
    db: Session = Depends(get_db),
):
    if m.role != "admin" and m.user_id != user_id:
        raise HTTPException(403, "Only the administrator can view other members' history.")
    group = db.get(Group, m.group_id)
    target_m = db.scalar(
        select(Membership)
        .where(Membership.group_id == group.id, Membership.user_id == user_id)
        .order_by(Membership.joined_at.desc())
    )
    if target_m is None:
        raise HTTPException(404, "Member not found in this group.")
    _finalize(db, group, request)
    target = db.get(User, user_id)
    return member_stats(db, group, target, target_m if target_m.left_at is None else None, now(request))


# ---------------------------------------------------------------------------
# Reading sessions
# ---------------------------------------------------------------------------
class StartIn(BaseModel):
    client_id: str = Field(min_length=8, max_length=64)
    page: int


class HeartbeatIn(BaseModel):
    seq: int = Field(ge=1)
    page: int
    active_ms: float = Field(ge=0, le=10 * 60 * 1000)
    page_ms: dict[str, float] = Field(default_factory=dict)


def _reading_state(db: Session, user: User, group: Group, t: datetime) -> dict:
    rs = get_reader_state(db, user.id, t)
    dwell, counted = page_dwell(db, user.id, rs.khatma, rs.current_page)
    return {
        "current_page": rs.current_page,
        "khatma": rs.khatma,
        "counted_pages": counted_pages(db, user.id, rs.khatma),
        "today": today_progress(db, user.id, group, t),
        "current_page_dwell": round(dwell, 1),
        "current_page_counted": counted,
        "tracking": {
            "heartbeat_seconds": HEARTBEAT_INTERVAL_SECONDS,
            "inactivity_timeout_seconds": group.settings.inactivity_timeout_seconds,
            "min_page_seconds": group.settings.min_page_seconds,
            "stale_session_seconds": STALE_SESSION_SECONDS,
        },
    }


@router.get("/reading/state")
def reading_state(
    request: Request,
    user: User = Depends(current_user),
    group: Group = Depends(current_group),
    db: Session = Depends(get_db),
):
    _finalize(db, group, request)
    return _reading_state(db, user, group, now(request))


@router.post("/reading/sessions")
def reading_start(
    body: StartIn,
    request: Request,
    user: User = Depends(current_user),
    group: Group = Depends(current_group),
    db: Session = Depends(get_db),
):
    t = now(request)
    _finalize(db, group, request)
    try:
        sess = start_session(db, user.id, group, body.client_id, body.page, t, request.headers.get("user-agent"))
    except TrackingError as exc:
        _raise(exc)
    return {"session": session_dict(sess), "state": _reading_state(db, user, group, t)}


def _heartbeat_response(db, user, group, sess, result, t):
    rs = get_reader_state(db, user.id, t)
    dwell, counted = page_dwell(db, user.id, rs.khatma, sess.end_page)
    return {
        "session": session_dict(sess),
        "credited_seconds": round(result.credited_seconds, 2),
        "newly_counted": result.newly_counted,
        "duplicate": result.duplicate,
        "today": today_progress(db, user.id, group, t),
        "current_page_dwell": round(dwell, 1),
        "current_page_counted": counted,
    }


@router.post("/reading/sessions/{session_id}/heartbeat")
def reading_heartbeat(
    session_id: int,
    body: HeartbeatIn,
    request: Request,
    user: User = Depends(current_user),
    m: Membership = Depends(current_membership),
    db: Session = Depends(get_db),
):
    t = now(request)
    group = db.get(Group, m.group_id)
    _finalize(db, group, request)
    try:
        sess, result = heartbeat(db, user.id, m, session_id, body.seq, body.page, body.active_ms, body.page_ms, t)
    except TrackingError as exc:
        db.commit()  # persist a session closed during validation
        _raise(exc)
    return _heartbeat_response(db, user, group, sess, result, t)


@router.post("/reading/sessions/{session_id}/end")
def reading_end(
    session_id: int,
    request: Request,
    body: HeartbeatIn | None = None,
    user: User = Depends(current_user),
    m: Membership = Depends(current_membership),
    db: Session = Depends(get_db),
):
    t = now(request)
    group = db.get(Group, m.group_id)
    result = None
    if body is not None:
        try:
            _, result = heartbeat(db, user.id, m, session_id, body.seq, body.page, body.active_ms, body.page_ms, t)
        except TrackingError:
            result = None
    try:
        sess = end_session(db, user.id, session_id, t, "closed")
    except TrackingError as exc:
        _raise(exc)
    return {"session": session_dict(sess), "today": today_progress(db, user.id, group, t)}


class PositionIn(BaseModel):
    page: int


@router.post("/reading/position")
def reading_position(
    body: PositionIn,
    request: Request,
    user: User = Depends(current_user),
    group: Group = Depends(current_group),
    db: Session = Depends(get_db),
):
    try:
        validate_page(body.page)
    except TrackingError as exc:
        _raise(exc)
    rs = get_reader_state(db, user.id, now(request))
    rs.current_page = body.page
    rs.updated_at = naive_utc(now(request))
    return {"current_page": rs.current_page}


@router.post("/reading/khatma/new")
def reading_new_khatma(
    request: Request,
    user: User = Depends(current_user),
    group: Group = Depends(current_group),
    db: Session = Depends(get_db),
):
    try:
        rs = start_new_khatma(db, user.id, now(request))
    except TrackingError as exc:
        _raise(exc)
    audit(db, now(request), "khatma_started", group.id, user.id, khatma=rs.khatma)
    return _reading_state(db, user, group, now(request))


# ---------------------------------------------------------------------------
# Administration
# ---------------------------------------------------------------------------
@router.get("/admin/group")
def admin_group(
    request: Request,
    m: Membership = Depends(require_admin),
    db: Session = Depends(get_db),
):
    group = db.get(Group, m.group_id)
    members = []
    for mm in db.scalars(
        select(Membership).where(Membership.group_id == group.id, Membership.left_at.is_(None)).order_by(Membership.joined_at)
    ):
        u = db.get(User, mm.user_id)
        members.append(
            {
                "user_id": u.id,
                "username": u.username,
                "display_name": u.display_name,
                "role": mm.role,
                "joined_at": mm.joined_at.isoformat() + "Z",
            }
        )
    former = []
    for mm in db.scalars(
        select(Membership).where(Membership.group_id == group.id, Membership.left_at.is_not(None)).order_by(Membership.left_at.desc())
    ):
        u = db.get(User, mm.user_id)
        former.append({"user_id": u.id, "display_name": u.display_name, "left_at": mm.left_at.isoformat() + "Z"})
    from .stats import assignment_dict

    return {
        "group": {
            "id": group.id,
            "name": group.name,
            "invite_code": group.invite_code,
            "invite_enabled": group.invite_enabled,
            "max_members": group.max_members,
            "created_at": group.created_at.isoformat() + "Z",
        },
        "settings": settings_dict(group),
        "members": members,
        "former_members": former,
        "assignment": assignment_dict(db, group.id),
        "today": effective_today(db, group, group.settings, now(request)).isoformat(),
    }


@router.get("/admin/sharing")
def admin_sharing(request: Request, m: Membership = Depends(require_admin)):
    """Whether the host is sharing the club online, and at which address."""
    provider = state(request).sharing
    info = provider() if provider else {}
    return {
        "status": info.get("status", "unavailable"),
        "public_url": info.get("public_url"),
        "named": bool(info.get("named")),
        "lan_urls": info.get("lan_urls", []),
    }


class GroupPatch(BaseModel):
    name: str | None = Field(default=None, max_length=120)
    max_members: int | None = None
    invite_enabled: bool | None = None


@router.patch("/admin/group")
def admin_update_group(body: GroupPatch, request: Request, m: Membership = Depends(require_admin), db: Session = Depends(get_db)):
    group = db.get(Group, m.group_id)
    if body.name is not None:
        name = body.name.strip()
        if not 2 <= len(name) <= 80:
            raise HTTPException(422, "Group name must be 2-80 characters.")
        group.name = name
    if body.max_members is not None:
        if not 2 <= body.max_members <= 50:
            raise HTTPException(422, "Maximum group size must be between 2 and 50.")
        if body.max_members < member_count(db, group.id):
            raise HTTPException(409, "The group already has more members than that.")
        group.max_members = body.max_members
    if body.invite_enabled is not None:
        group.invite_enabled = body.invite_enabled
    audit(db, now(request), "group_updated", group.id, m.user_id, **body.model_dump(exclude_none=True))
    return admin_group(request, m, db)


class SettingsPatch(BaseModel):
    min_pages: int | None = Field(default=None, ge=1, le=TOTAL_PAGES)
    min_minutes: float | None = Field(default=None, ge=1, le=600)
    timezone: str | None = Field(default=None, max_length=64)
    reset_time: str | None = Field(default=None, pattern=r"^\d{1,2}:\d{2}$")
    inactivity_timeout_seconds: int | None = Field(default=None, ge=15, le=900)
    min_page_seconds: int | None = Field(default=None, ge=3, le=600)


@router.patch("/admin/settings")
def admin_update_settings(
    body: SettingsPatch, request: Request, m: Membership = Depends(require_admin), db: Session = Depends(get_db)
):
    group = db.get(Group, m.group_id)
    t = now(request)
    # Close out every finished day under the OLD rules before anything changes.
    finalize_group(db, group, t)
    s = group.settings
    if body.timezone is not None:
        if not is_valid_timezone(body.timezone):
            raise HTTPException(422, f"Unknown timezone '{body.timezone}'.")
        s.timezone = body.timezone
    if body.reset_time is not None:
        hh, mm = (int(x) for x in body.reset_time.split(":"))
        if not (0 <= hh <= 23 and 0 <= mm <= 59):
            raise HTTPException(422, "Reset time must be between 00:00 and 23:59.")
        s.reset_minute = hh * 60 + mm
    if body.min_pages is not None:
        s.min_pages = body.min_pages
    if body.min_minutes is not None:
        s.min_seconds = int(round(body.min_minutes * 60))
    if body.inactivity_timeout_seconds is not None:
        s.inactivity_timeout_seconds = body.inactivity_timeout_seconds
    if body.min_page_seconds is not None:
        s.min_page_seconds = body.min_page_seconds
    s.updated_at = naive_utc(t)
    db.flush()
    apply_requirement_change(db, group, t)
    audit(db, t, "settings_updated", group.id, m.user_id, **body.model_dump(exclude_none=True))
    return {"settings": settings_dict(group)}


@router.post("/admin/invite/regenerate")
def admin_regenerate_invite(request: Request, m: Membership = Depends(require_admin), db: Session = Depends(get_db)):
    group = db.get(Group, m.group_id)
    return {"invite_code": regenerate_invite(db, group, now(request), m.user_id)}


class NewMemberIn(BaseModel):
    username: str = Field(max_length=64)
    display_name: str | None = Field(default=None, max_length=80)
    password: str | None = Field(default=None, max_length=256)


@router.post("/admin/members")
def admin_add_member(body: NewMemberIn, request: Request, m: Membership = Depends(require_admin), db: Session = Depends(get_db)):
    group = db.get(Group, m.group_id)
    password = body.password or new_temp_password()
    try:
        if member_count(db, group.id) >= group.max_members:
            raise GroupError(f"The group is full ({group.max_members} members).", 409)
        user = create_user(db, body.username, password, body.display_name, now(request))
        add_member(db, group, user, now(request))
    except GroupError as exc:
        _raise(exc)
    return {"user_id": user.id, "username": user.username, "password": password}


@router.delete("/admin/members/{user_id}")
def admin_remove_member(user_id: int, request: Request, m: Membership = Depends(require_admin), db: Session = Depends(get_db)):
    if user_id == m.user_id:
        raise HTTPException(400, "Use 'Leave group' to remove yourself.")
    group = db.get(Group, m.group_id)
    try:
        remove_member(db, group, user_id, now(request), m.user_id)
    except GroupError as exc:
        _raise(exc)
    return {"ok": True}


class RoleIn(BaseModel):
    role: str


@router.post("/admin/members/{user_id}/role")
def admin_set_role(user_id: int, body: RoleIn, request: Request, m: Membership = Depends(require_admin), db: Session = Depends(get_db)):
    group = db.get(Group, m.group_id)
    try:
        set_role(db, group, user_id, body.role, now(request), m.user_id)
    except GroupError as exc:
        _raise(exc)
    return {"ok": True}


@router.post("/admin/members/{user_id}/reset-password")
def admin_reset_password(user_id: int, request: Request, m: Membership = Depends(require_admin), db: Session = Depends(get_db)):
    target = db.scalar(
        select(Membership).where(
            Membership.group_id == m.group_id, Membership.user_id == user_id, Membership.left_at.is_(None)
        )
    )
    if target is None:
        raise HTTPException(404, "Member not found.")
    user = db.get(User, user_id)
    password = new_temp_password()
    user.password_hash = hash_password(password)
    for at in db.scalars(select(AuthToken).where(AuthToken.user_id == user_id)):
        db.delete(at)
    audit(db, now(request), "password_reset", m.group_id, m.user_id, member=user_id)
    return {"username": user.username, "password": password}


class AssignmentIn(BaseModel):
    start_page: int
    end_page: int
    note: str = Field(default="", max_length=200)


@router.post("/admin/assignment")
def admin_set_assignment(body: AssignmentIn, request: Request, m: Membership = Depends(require_admin), db: Session = Depends(get_db)):
    group = db.get(Group, m.group_id)
    try:
        set_assignment(db, group, body.start_page, body.end_page, body.note, now(request), m.user_id)
    except GroupError as exc:
        _raise(exc)
    from .stats import assignment_dict

    db.flush()
    return {"assignment": assignment_dict(db, group.id)}


@router.delete("/admin/assignment")
def admin_clear_assignment(request: Request, m: Membership = Depends(require_admin), db: Session = Depends(get_db)):
    group = db.get(Group, m.group_id)
    clear_assignment(db, group, now(request), m.user_id)
    return {"assignment": None}


class StreakResetIn(BaseModel):
    confirm_group_name: str


@router.post("/admin/streak/reset")
def admin_reset_streak(body: StreakResetIn, request: Request, m: Membership = Depends(require_admin), db: Session = Depends(get_db)):
    group = db.get(Group, m.group_id)
    if body.confirm_group_name.strip() != group.name:
        raise HTTPException(400, "Type the exact group name to confirm the reset.")
    t = now(request)
    finalize_group(db, group, t)
    group.settings.streak_reset_day = effective_today(db, group, group.settings, t)
    audit(db, t, "streak_reset", group.id, m.user_id, day=group.settings.streak_reset_day)
    from .streaks import refresh_streak_cache

    refresh_streak_cache(db, group, t)
    return {"settings": settings_dict(group)}


@router.get("/admin/sessions")
def admin_sessions(
    request: Request,
    user_id: int | None = None,
    limit: int = 100,
    m: Membership = Depends(require_admin),
    db: Session = Depends(get_db),
):
    q = select(ReadingSession).where(ReadingSession.group_id == m.group_id)
    if user_id is not None:
        q = q.where(ReadingSession.user_id == user_id)
    q = q.order_by(ReadingSession.started_at.desc()).limit(max(1, min(limit, 500)))
    names = {u.id: u.display_name for u in db.scalars(select(User))}
    return {"sessions": [{**session_dict(s), "user_id": s.user_id, "name": names.get(s.user_id)} for s in db.scalars(q)]}

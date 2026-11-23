"""Accounts, groups, memberships and assignments."""
from __future__ import annotations

import json
import re
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .clock import naive_utc
from .models import (
    AuditLog,
    Group,
    GroupSettings,
    Membership,
    ReadingAssignment,
    ReadingSession,
    User,
)
from .quran import TOTAL_PAGES
from .security import hash_password, new_invite_code
from .timeutil import day_for, is_valid_timezone
from .tracking import close_session

USERNAME_RE = re.compile(r"^[A-Za-z0-9_.\-]{3,32}$")


class GroupError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.message = message
        self.status = status


def audit(db: Session, now: datetime, action: str, group_id: int | None = None, user_id: int | None = None, **detail) -> None:
    db.add(
        AuditLog(
            group_id=group_id,
            user_id=user_id,
            action=action,
            detail=json.dumps(detail, default=str),
            created_at=naive_utc(now),
        )
    )


def validate_username(username: str) -> str:
    username = (username or "").strip()
    if not USERNAME_RE.match(username):
        raise GroupError("Username must be 3-32 characters: letters, digits, '.', '_' or '-'.", 422)
    return username


def validate_password(password: str) -> str:
    if not isinstance(password, str) or not 8 <= len(password) <= 128:
        raise GroupError("Password must be 8-128 characters long.", 422)
    return password


def validate_display_name(name: str | None, fallback: str) -> str:
    name = (name or "").strip() or fallback
    if len(name) > 60:
        raise GroupError("Display name is too long (max 60).", 422)
    return name


def create_user(db: Session, username: str, password: str, display_name: str | None, now: datetime) -> User:
    username = validate_username(username)
    validate_password(password)
    if db.scalar(select(User.id).where(User.username_key == username.lower())) is not None:
        raise GroupError("That username is already taken.", 409)
    user = User(
        username=username,
        username_key=username.lower(),
        display_name=validate_display_name(display_name, username),
        password_hash=hash_password(password),
        is_active=True,
        created_at=naive_utc(now),
    )
    db.add(user)
    try:
        db.flush()
    except IntegrityError as exc:
        raise GroupError("That username is already taken.", 409) from exc
    return user


def active_membership(db: Session, user_id: int) -> Membership | None:
    return db.scalar(select(Membership).where(Membership.user_id == user_id, Membership.left_at.is_(None)))


def active_members(db: Session, group_id: int) -> list[Membership]:
    return list(
        db.scalars(
            select(Membership)
            .where(Membership.group_id == group_id, Membership.left_at.is_(None))
            .order_by(Membership.joined_at, Membership.id)
        )
    )


def member_count(db: Session, group_id: int) -> int:
    return db.scalar(
        select(func.count(Membership.id)).where(Membership.group_id == group_id, Membership.left_at.is_(None))
    ) or 0


def _unique_invite_code(db: Session) -> str:
    while True:
        code = new_invite_code()
        if db.scalar(select(Group.id).where(Group.invite_code == code)) is None:
            return code


def create_group(
    db: Session,
    owner: User,
    name: str,
    now: datetime,
    timezone: str = "Africa/Cairo",
    max_members: int = 10,
    min_pages: int = 2,
    min_minutes: int = 20,
) -> Group:
    name = (name or "").strip()
    if not 2 <= len(name) <= 80:
        raise GroupError("Group name must be 2-80 characters.", 422)
    if not is_valid_timezone(timezone):
        raise GroupError(f"Unknown timezone '{timezone}'.", 422)
    if not 2 <= int(max_members) <= 50:
        raise GroupError("Maximum group size must be between 2 and 50.", 422)
    if active_membership(db, owner.id) is not None:
        raise GroupError("You are already a member of a group.", 409)
    group = Group(
        name=name,
        invite_code=_unique_invite_code(db),
        invite_enabled=True,
        max_members=int(max_members),
        created_at=naive_utc(now),
        created_by=owner.id,
        first_day=day_for(now, timezone, 0),
    )
    db.add(group)
    db.flush()
    db.add(
        GroupSettings(
            group_id=group.id,
            min_pages=min_pages,
            min_seconds=min_minutes * 60,
            timezone=timezone,
            reset_minute=0,
            inactivity_timeout_seconds=60,
            min_page_seconds=20,
            updated_at=naive_utc(now),
        )
    )
    db.add(Membership(user_id=owner.id, group_id=group.id, role="admin", joined_at=naive_utc(now)))
    db.flush()
    db.refresh(group)
    audit(db, now, "group_created", group.id, owner.id, name=name)
    return group


def find_group_by_invite(db: Session, code: str) -> Group:
    code = (code or "").strip().upper().replace(" ", "").replace("-", "")
    group = db.scalar(select(Group).where(Group.invite_code == code)) if code else None
    if group is None or not group.invite_enabled:
        raise GroupError("Invalid or disabled invitation code.", 404)
    return group


def add_member(db: Session, group: Group, user: User, now: datetime, role: str = "member") -> Membership:
    if active_membership(db, user.id) is not None:
        raise GroupError("This account already belongs to a group.", 409)
    if member_count(db, group.id) >= group.max_members:
        raise GroupError(f"The group is full ({group.max_members} members).", 409)
    m = Membership(user_id=user.id, group_id=group.id, role=role, joined_at=naive_utc(now))
    db.add(m)
    try:
        db.flush()
    except IntegrityError as exc:
        raise GroupError("This account already belongs to a group.", 409) from exc
    audit(db, now, "member_joined", group.id, user.id)
    return m


def admin_count(db: Session, group_id: int) -> int:
    return db.scalar(
        select(func.count(Membership.id)).where(
            Membership.group_id == group_id, Membership.left_at.is_(None), Membership.role == "admin"
        )
    ) or 0


def remove_member(db: Session, group: Group, user_id: int, now: datetime, actor_id: int) -> None:
    m = db.scalar(
        select(Membership).where(
            Membership.group_id == group.id, Membership.user_id == user_id, Membership.left_at.is_(None)
        )
    )
    if m is None:
        raise GroupError("Member not found.", 404)
    if m.role == "admin" and admin_count(db, group.id) <= 1:
        raise GroupError("The group must keep at least one administrator.", 409)
    m.left_at = naive_utc(now)
    for sess in db.scalars(
        select(ReadingSession).where(ReadingSession.user_id == user_id, ReadingSession.status == "active")
    ):
        close_session(sess, now, "left_group")
    audit(db, now, "member_removed" if actor_id != user_id else "member_left", group.id, actor_id, member=user_id)


def set_role(db: Session, group: Group, user_id: int, role: str, now: datetime, actor_id: int) -> None:
    if role not in ("admin", "member"):
        raise GroupError("Role must be 'admin' or 'member'.", 422)
    m = db.scalar(
        select(Membership).where(
            Membership.group_id == group.id, Membership.user_id == user_id, Membership.left_at.is_(None)
        )
    )
    if m is None:
        raise GroupError("Member not found.", 404)
    if m.role == "admin" and role == "member" and admin_count(db, group.id) <= 1:
        raise GroupError("The group must keep at least one administrator.", 409)
    m.role = role
    audit(db, now, "role_changed", group.id, actor_id, member=user_id, role=role)


def regenerate_invite(db: Session, group: Group, now: datetime, actor_id: int) -> str:
    group.invite_code = _unique_invite_code(db)
    audit(db, now, "invite_regenerated", group.id, actor_id)
    return group.invite_code


def set_assignment(db: Session, group: Group, start_page: int, end_page: int, note: str, now: datetime, actor_id: int):
    if not (1 <= start_page <= end_page <= TOTAL_PAGES):
        raise GroupError(f"Pages must satisfy 1 <= start <= end <= {TOTAL_PAGES}.", 422)
    for a in db.scalars(
        select(ReadingAssignment).where(ReadingAssignment.group_id == group.id, ReadingAssignment.active.is_(True))
    ):
        a.active = False
    a = ReadingAssignment(
        group_id=group.id,
        start_page=start_page,
        end_page=end_page,
        note=(note or "").strip()[:200],
        assigned_by=actor_id,
        assigned_at=naive_utc(now),
        active=True,
    )
    db.add(a)
    audit(db, now, "assignment_set", group.id, actor_id, start=start_page, end=end_page)
    return a


def clear_assignment(db: Session, group: Group, now: datetime, actor_id: int) -> None:
    for a in db.scalars(
        select(ReadingAssignment).where(ReadingAssignment.group_id == group.id, ReadingAssignment.active.is_(True))
    ):
        a.active = False
    audit(db, now, "assignment_cleared", group.id, actor_id)


def current_assignment(db: Session, group_id: int) -> ReadingAssignment | None:
    return db.scalar(
        select(ReadingAssignment)
        .where(ReadingAssignment.group_id == group_id, ReadingAssignment.active.is_(True))
        .order_by(ReadingAssignment.assigned_at.desc())
    )

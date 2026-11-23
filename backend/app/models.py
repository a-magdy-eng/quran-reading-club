"""Database schema.

All datetimes are stored as naive UTC. All "day" columns are the group-local
reading day (see timeutil.py) as a calendar date.
"""
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class SchemaInfo(Base):
    __tablename__ = "schema_info"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    version: Mapped[int] = mapped_column(Integer)


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(40))
    username_key: Mapped[str] = mapped_column(String(40), unique=True)  # lower-cased
    display_name: Mapped[str] = mapped_column(String(60))
    password_hash: Mapped[str] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime)


class AuthToken(Base):
    __tablename__ = "auth_tokens"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    last_used_at: Mapped[datetime] = mapped_column(DateTime)
    user_agent: Mapped[str | None] = mapped_column(String(200), nullable=True)


class Group(Base):
    __tablename__ = "groups"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(80))
    invite_code: Mapped[str] = mapped_column(String(16), unique=True)
    invite_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    max_members: Mapped[int] = mapped_column(Integer, default=10)
    created_at: Mapped[datetime] = mapped_column(DateTime)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    first_day: Mapped[date] = mapped_column(Date)  # first reading day tracked for streaks

    settings: Mapped["GroupSettings"] = relationship(back_populates="group", uselist=False)


class GroupSettings(Base):
    __tablename__ = "group_settings"
    group_id: Mapped[int] = mapped_column(ForeignKey("groups.id", ondelete="CASCADE"), primary_key=True)
    min_pages: Mapped[int] = mapped_column(Integer, default=2)
    min_seconds: Mapped[int] = mapped_column(Integer, default=20 * 60)
    timezone: Mapped[str] = mapped_column(String(64), default="Africa/Cairo")
    reset_minute: Mapped[int] = mapped_column(Integer, default=0)  # minutes after local midnight
    inactivity_timeout_seconds: Mapped[int] = mapped_column(Integer, default=60)
    min_page_seconds: Mapped[int] = mapped_column(Integer, default=20)
    # Manual streak reset: only days strictly after this day count toward the current group streak.
    streak_reset_day: Mapped[date | None] = mapped_column(Date, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime)

    group: Mapped[Group] = relationship(back_populates="settings")


class Membership(Base):
    __tablename__ = "memberships"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    group_id: Mapped[int] = mapped_column(ForeignKey("groups.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(10), default="member")  # admin | member
    joined_at: Mapped[datetime] = mapped_column(DateTime)
    left_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    user: Mapped[User] = relationship()

    __table_args__ = (
        # A user can be an active member of exactly one group.
        Index("uq_active_membership", "user_id", unique=True, sqlite_where=text("left_at IS NULL")),
    )


class ReaderState(Base):
    """Where a user is in the mushaf and which khatma (complete reading) they are on."""

    __tablename__ = "reader_state"
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    current_page: Mapped[int] = mapped_column(Integer, default=1)
    khatma: Mapped[int] = mapped_column(Integer, default=1)
    updated_at: Mapped[datetime] = mapped_column(DateTime)


class ReadingAssignment(Base):
    """Reading material assigned to the group by an admin (a page range of the mushaf)."""

    __tablename__ = "reading_assignments"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    group_id: Mapped[int] = mapped_column(ForeignKey("groups.id", ondelete="CASCADE"), index=True)
    start_page: Mapped[int] = mapped_column(Integer)
    end_page: Mapped[int] = mapped_column(Integer)
    note: Mapped[str] = mapped_column(String(200), default="")
    assigned_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    assigned_at: Mapped[datetime] = mapped_column(DateTime)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class ReadingSession(Base):
    __tablename__ = "reading_sessions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    group_id: Mapped[int] = mapped_column(ForeignKey("groups.id", ondelete="CASCADE"), index=True)
    client_id: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(12), default="active")  # active | ended
    end_reason: Mapped[str | None] = mapped_column(String(20), nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime)
    last_heartbeat_at: Mapped[datetime] = mapped_column(DateTime)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_seq: Mapped[int] = mapped_column(Integer, default=0)
    start_page: Mapped[int] = mapped_column(Integer)
    end_page: Mapped[int] = mapped_column(Integer)
    pages_read: Mapped[int] = mapped_column(Integer, default=0)
    active_seconds: Mapped[float] = mapped_column(Float, default=0.0)
    client_info: Mapped[str | None] = mapped_column(String(200), nullable=True)

    __table_args__ = (Index("ix_sessions_user_status", "user_id", "status"),)


class PageProgress(Base):
    """Active time spent on each mushaf page, per khatma. A page counts once per khatma."""

    __tablename__ = "page_progress"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    khatma: Mapped[int] = mapped_column(Integer)
    page: Mapped[int] = mapped_column(Integer)
    dwell_seconds: Mapped[float] = mapped_column(Float, default=0.0)
    counted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    counted_day: Mapped[date | None] = mapped_column(Date, nullable=True)
    group_id: Mapped[int | None] = mapped_column(ForeignKey("groups.id", ondelete="SET NULL"), nullable=True)
    session_id: Mapped[int | None] = mapped_column(ForeignKey("reading_sessions.id", ondelete="SET NULL"), nullable=True)

    __table_args__ = (UniqueConstraint("user_id", "khatma", "page", name="uq_page_progress"),)


class DailyProgress(Base):
    """One row per member per group per reading day (unique) - the daily completion record."""

    __tablename__ = "daily_progress"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    group_id: Mapped[int] = mapped_column(ForeignKey("groups.id", ondelete="CASCADE"))
    day: Mapped[date] = mapped_column(Date)
    active_seconds: Mapped[float] = mapped_column(Float, default=0.0)
    pages_read: Mapped[int] = mapped_column(Integer, default=0)
    # Requirement snapshot: a completed day stays completed whatever the settings become later.
    required_pages: Mapped[int] = mapped_column(Integer)
    required_seconds: Mapped[int] = mapped_column(Integer)
    completed: Mapped[bool] = mapped_column(Boolean, default=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    __table_args__ = (
        UniqueConstraint("user_id", "group_id", "day", name="uq_daily_progress"),
        Index("ix_daily_group_day", "group_id", "day"),
    )


class GroupDay(Base):
    """A finalised group reading day (written once the day is over, never before)."""

    __tablename__ = "group_days"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    group_id: Mapped[int] = mapped_column(ForeignKey("groups.id", ondelete="CASCADE"))
    day: Mapped[date] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(10))  # success | failed | neutral
    required_count: Mapped[int] = mapped_column(Integer)
    completed_count: Mapped[int] = mapped_column(Integer)
    finalized_at: Mapped[datetime] = mapped_column(DateTime)

    members: Mapped[list["GroupDayMember"]] = relationship(back_populates="group_day", cascade="all, delete-orphan")

    __table_args__ = (UniqueConstraint("group_id", "day", name="uq_group_day"),)


class GroupDayMember(Base):
    __tablename__ = "group_day_members"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    group_day_id: Mapped[int] = mapped_column(ForeignKey("group_days.id", ondelete="CASCADE"))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    outcome: Mapped[str] = mapped_column(String(10))  # completed | failed | excused
    pages_read: Mapped[int] = mapped_column(Integer, default=0)
    active_seconds: Mapped[float] = mapped_column(Float, default=0.0)

    group_day: Mapped[GroupDay] = relationship(back_populates="members")

    __table_args__ = (UniqueConstraint("group_day_id", "user_id", name="uq_group_day_member"),)


class GroupStreak(Base):
    """Cached group streak (recomputed deterministically from group_days)."""

    __tablename__ = "group_streaks"
    group_id: Mapped[int] = mapped_column(ForeignKey("groups.id", ondelete="CASCADE"), primary_key=True)
    current: Mapped[int] = mapped_column(Integer, default=0)
    longest: Mapped[int] = mapped_column(Integer, default=0)
    last_finalized_day: Mapped[date | None] = mapped_column(Date, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime)


class UserStreak(Base):
    """Cached individual streak (recomputed deterministically from group_day_members)."""

    __tablename__ = "user_streaks"
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    group_id: Mapped[int] = mapped_column(ForeignKey("groups.id", ondelete="CASCADE"), primary_key=True)
    current: Mapped[int] = mapped_column(Integer, default=0)
    longest: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime)


class AuditLog(Base):
    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    group_id: Mapped[int | None] = mapped_column(ForeignKey("groups.id", ondelete="CASCADE"), nullable=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    action: Mapped[str] = mapped_column(String(40))
    detail: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime)

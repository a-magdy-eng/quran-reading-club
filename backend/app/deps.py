"""Shared application state and FastAPI dependencies."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Callable, Iterator

from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from .clock import Clock, naive_utc, to_utc
from .config import AppConfig, Paths
from .db import Database
from .groups import active_membership
from .models import AuthToken, Group, Membership, User
from .security import LoginThrottle, NetworkAllowList, is_loopback, token_digest


@dataclass
class AppState:
    db: Database
    config: AppConfig
    paths: Paths
    clock: Clock
    throttle: LoginThrottle = field(default_factory=LoginThrottle)
    # Per-username limit across all addresses (online sharing means many possible IPs).
    user_throttle: LoginThrottle = field(default_factory=lambda: LoginThrottle(max_failures=30))
    allowlist: NetworkAllowList | None = None
    sharing: Callable[[], dict] | None = None


def state(request: Request) -> AppState:
    return request.app.state.rc


def get_db(request: Request) -> Iterator[Session]:
    with state(request).db.session() as s:
        yield s


def now(request: Request) -> datetime:
    return state(request).clock.now()


# Headers added by Cloudflare / any reverse proxy. Their presence on a loopback
# connection means the request really came from the internet through the tunnel.
PROXY_HEADERS = ("cf-connecting-ip", "cf-ray", "cf-visitor", "x-forwarded-for", "x-forwarded-host", "forwarded")
LOCAL_HOSTNAMES = {"localhost", "127.0.0.1", "[::1]"}


def _peer(request: Request) -> str:
    return request.client.host if request.client else ""


def _host_name(request: Request) -> str:
    host = (request.headers.get("host") or "").strip().lower()
    if host.startswith("["):
        return host.split("]")[0] + "]"
    return host.split(":")[0]


def via_proxy(request: Request) -> bool:
    """True for requests forwarded by the online-sharing tunnel (or any proxy on this machine)."""
    if not is_loopback(_peer(request)):
        return False
    if any(h in request.headers for h in PROXY_HEADERS):
        return True
    return _host_name(request) not in LOCAL_HOSTNAMES


def is_host_request(request: Request) -> bool:
    """Only a browser on the host laptop itself, opened at localhost, counts as the host."""
    return is_loopback(_peer(request)) and not via_proxy(request)


def client_ip(request: Request) -> str:
    """The real client address (the visitor's IP for tunnelled requests), for throttling and logs."""
    if via_proxy(request):
        ip = request.headers.get("cf-connecting-ip") or (request.headers.get("x-forwarded-for") or "").split(",")[0]
        return (ip.strip() or "proxied")[:64]
    return _peer(request)


def _bearer(request: Request) -> str | None:
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip() or None
    return None


def current_user(request: Request, db: Session = Depends(get_db)) -> User:
    token = _bearer(request)
    if not token:
        raise HTTPException(401, "Not signed in.")
    at = db.scalar(select(AuthToken).where(AuthToken.token_hash == token_digest(token)))
    t = now(request)
    if at is None or to_utc(at.expires_at) <= t:
        raise HTTPException(401, "Your session has expired. Please sign in again.")
    user = db.get(User, at.user_id)
    if user is None or not user.is_active:
        raise HTTPException(401, "Account disabled.")
    # Sliding expiry, written at most once an hour.
    if t - to_utc(at.last_used_at) > timedelta(hours=1):
        at.last_used_at = naive_utc(t)
        at.expires_at = naive_utc(t + timedelta(days=state(request).config.token_ttl_days))
    request.state.token_id = at.id
    return user


def current_membership(user: User = Depends(current_user), db: Session = Depends(get_db)) -> Membership:
    m = active_membership(db, user.id)
    if m is None:
        raise HTTPException(403, "You are not a member of a group yet.")
    return m


def current_group(m: Membership = Depends(current_membership), db: Session = Depends(get_db)) -> Group:
    return db.get(Group, m.group_id)


def require_admin(m: Membership = Depends(current_membership)) -> Membership:
    if m.role != "admin":
        raise HTTPException(403, "Only the group administrator can do that.")
    return m

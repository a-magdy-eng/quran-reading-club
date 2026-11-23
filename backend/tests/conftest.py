from __future__ import annotations

import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.clock import FakeClock  # noqa: E402
from app.config import AppConfig  # noqa: E402
from app.main import create_app  # noqa: E402

UTC = timezone.utc
# 2026-03-10 10:00 in Cairo (UTC+2) -> 08:00 UTC
START = datetime(2026, 3, 10, 8, 0, tzinfo=UTC)
HOST_IP = "127.0.0.1"
LAN_IP = "192.168.1.23"
PASSWORD = "correct-horse-1"


class Api:
    """A browser on some device: an HTTP client with its own IP and token."""

    def __init__(self, app, ip: str = HOST_IP, headers: dict | None = None, base_url: str = "http://localhost"):
        self.ip = ip
        self.base_url = base_url
        self.extra = headers or {}
        self.client = TestClient(app, client=(ip, 50000), base_url=base_url)
        self.token: str | None = None
        self.client_id = uuid.uuid4().hex

    def rebind(self, app):
        self.client = TestClient(app, client=(self.ip, 50000), base_url=self.base_url)

    def _headers(self):
        h = dict(self.extra)
        if self.token:
            h["Authorization"] = f"Bearer {self.token}"
        return h

    def get(self, url, **kw):
        return self.client.get(url, headers=self._headers(), **kw)

    def post(self, url, json=None, **kw):
        return self.client.post(url, json=json, headers=self._headers(), **kw)

    def patch(self, url, json=None, **kw):
        return self.client.patch(url, json=json, headers=self._headers(), **kw)

    def delete(self, url, **kw):
        return self.client.delete(url, headers=self._headers(), **kw)

    def ok(self, method, url, json=None, status=200):
        r = getattr(self, method)(url, json=json) if json is not None else getattr(self, method)(url)
        assert r.status_code == status, (r.status_code, r.text)
        return r.json()


class Env:
    def __init__(self, tmp_path: Path, start: datetime = START):
        self.dir = tmp_path
        self.clock = FakeClock(start)
        self.app = self.make_app()

    def make_app(self, **cfg):
        config = AppConfig(auto_backup_hours=0, **cfg)
        return create_app(self.dir, clock=self.clock, config=config, serve_frontend=False, background_tasks=False)

    def restart(self):
        self.app.state.rc.db.dispose()
        self.app = self.make_app()
        return self.app

    def api(self, ip: str = HOST_IP) -> Api:
        return Api(self.app, ip)

    # -- scenario helpers --------------------------------------------------
    def setup_group(self, name="Fajr Circle", username="host", **extra) -> Api:
        a = self.api()
        body = {
            "username": username,
            "password": PASSWORD,
            "display_name": username.title(),
            "group_name": name,
            "timezone": "Africa/Cairo",
            **extra,
        }
        data = a.ok("post", "/api/auth/setup", body)
        a.token = data["token"]
        return a

    def invite_code(self, admin: Api) -> str:
        return admin.ok("get", "/api/admin/group")["group"]["invite_code"]

    def join(self, admin: Api, username: str, ip: str = LAN_IP) -> Api:
        a = self.api(ip)
        data = a.ok(
            "post",
            "/api/auth/register",
            {"username": username, "password": PASSWORD, "display_name": username.title(), "invite_code": self.invite_code(admin)},
        )
        a.token = data["token"]
        return a

    def start(self, a: Api, page: int = 1) -> int:
        return a.ok("post", "/api/reading/sessions", {"client_id": a.client_id, "page": page})["session"]["id"]

    def read(self, a: Api, seconds: float, page: int = 1, step: float = 15, session: int | None = None, pages=None):
        """Simulate honest active reading: heartbeat every `step` seconds.

        `pages` optionally lists pages to read in order, splitting the time evenly."""
        sid = session or self.start(a, pages[0] if pages else page)
        seq = getattr(a, "_seq", {}).get(sid, 0)
        page_list = pages or [page]
        per_page = seconds / len(page_list)
        last = None
        for p in page_list:
            remaining = per_page
            while remaining > 1e-9:
                dt = min(step, remaining)
                self.clock.advance(dt)
                seq += 1
                last = a.ok(
                    "post",
                    f"/api/reading/sessions/{sid}/heartbeat",
                    {"seq": seq, "page": p, "active_ms": dt * 1000, "page_ms": {str(p): dt * 1000}},
                )
                remaining -= dt
        a.__dict__.setdefault("_seq", {})[sid] = seq
        return sid, last

    def complete_day(self, a: Api, first_page: int, minutes: float = 20, pages: int = 2):
        """Read `pages` new pages for a total of `minutes` active minutes."""
        return self.read(a, minutes * 60, pages=list(range(first_page, first_page + pages)))


@pytest.fixture
def env(tmp_path):
    e = Env(tmp_path)
    yield e
    e.app.state.rc.db.dispose()

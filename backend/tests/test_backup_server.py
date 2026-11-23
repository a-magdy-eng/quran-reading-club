"""Backups/restore, and a real HTTP server accessed by several devices at once."""
import socket
import threading
import zipfile

import httpx
import pytest

from app.backup import BackupError, create_backup, list_backups, restore_backup
from app.config import AppConfig, Paths
from app.server import ServerController, local_addresses
from conftest import PASSWORD


def test_backup_and_restore_roundtrip(env):
    admin = env.setup_group()
    env.complete_day(admin, 1)
    paths = env.app.state.rc.paths
    backup = create_backup(paths)
    assert backup.exists() and zipfile.is_zipfile(backup)

    # More activity after the backup...
    env.join(admin, "omar")
    assert len(admin.ok("get", "/api/dashboard")["members"]) == 2

    # Restore must happen with the server stopped.
    env.app.state.rc.db.dispose()
    safety = restore_backup(paths, backup)
    assert safety is not None and safety.exists()
    env.app = env.make_app()
    admin.rebind(env.app)
    dash = admin.ok("get", "/api/dashboard")
    assert len(dash["members"]) == 1
    assert dash["members"][0]["today"]["completed"] is True


def test_restore_rejects_invalid_files(env, tmp_path):
    env.setup_group()
    bogus = tmp_path / "not-a-backup.zip"
    with zipfile.ZipFile(bogus, "w") as zf:
        zf.writestr("hello.txt", "hi")
    with pytest.raises(BackupError):
        restore_backup(env.app.state.rc.paths, bogus)
    text = tmp_path / "plain.zip"
    text.write_text("nope")
    with pytest.raises(BackupError):
        restore_backup(env.app.state.rc.paths, text)


def test_backup_rotation(env):
    env.setup_group()
    paths = env.app.state.rc.paths
    for _ in range(5):
        create_backup(paths, keep=3)
    assert len(list_backups(paths)) == 3


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_real_server_with_multiple_devices(tmp_path):
    """Start the real uvicorn server (as the launcher does) and hit it from
    several concurrent clients, then shut it down safely."""
    cfg = AppConfig(host="127.0.0.1", port=free_port(), auto_backup_hours=0)
    ctl = ServerController(Paths(tmp_path), cfg, app_kwargs={"serve_frontend": False})
    ctl.start()
    base = f"http://127.0.0.1:{cfg.port}"
    try:
        assert httpx.get(f"{base}/api/health").json()["status"] == "ok"
        r = httpx.post(
            f"{base}/api/auth/setup",
            json={"username": "host", "password": PASSWORD, "group_name": "Club", "timezone": "Africa/Cairo"},
        )
        admin_token = r.json()["token"]
        code = httpx.get(f"{base}/api/admin/group", headers={"Authorization": f"Bearer {admin_token}"}).json()["group"]["invite_code"]

        tokens = {"host": admin_token}
        for name in ("omar", "ali", "zaid"):
            r = httpx.post(f"{base}/api/auth/register", json={"username": name, "password": PASSWORD, "invite_code": code})
            assert r.status_code == 200, r.text
            tokens[name] = r.json()["token"]

        errors = []

        def device(name, token, page):
            try:
                with httpx.Client(base_url=base, headers={"Authorization": f"Bearer {token}"}, timeout=30) as c:
                    sid = c.post("/api/reading/sessions", json={"client_id": f"device-{name}-x", "page": page}).json()["session"]["id"]
                    for seq in range(1, 6):
                        c.get("/api/dashboard").raise_for_status()
                        c.get(f"/api/quran/page/{page}").raise_for_status()
                        r = c.post(
                            f"/api/reading/sessions/{sid}/heartbeat",
                            json={"seq": seq, "page": page, "active_ms": 0, "page_ms": {}},
                        )
                        r.raise_for_status()
                    c.post(f"/api/reading/sessions/{sid}/end").raise_for_status()
            except Exception as exc:  # noqa: BLE001
                errors.append((name, repr(exc)))

        threads = [threading.Thread(target=device, args=(n, t, i * 50 + 1)) for i, (n, t) in enumerate(tokens.items())]
        for t in threads:
            t.start()
        for t in threads:
            t.join(60)
        assert errors == []
        dash = httpx.get(f"{base}/api/dashboard", headers={"Authorization": f"Bearer {admin_token}"}).json()
        assert len(dash["members"]) == 4
        assert {m["position"]["page"] for m in dash["members"]} == {1, 51, 101, 151}
    finally:
        ctl.stop()
    assert not ctl.running
    with pytest.raises((httpx.ConnectError, httpx.ConnectTimeout)):  # Windows retries refused SYNs
        httpx.get(f"{base}/api/health", timeout=2)

    # Restart on the same data directory: everything is still there.
    ctl2 = ServerController(Paths(tmp_path), cfg, app_kwargs={"serve_frontend": False})
    ctl2.start()
    try:
        r = httpx.post(f"{base}/api/auth/login", json={"username": "zaid", "password": PASSWORD})
        assert r.status_code == 200
    finally:
        ctl2.stop()


def test_local_addresses_are_classified():
    for a in local_addresses():
        assert a["kind"] in ("lan", "tailscale", "other")

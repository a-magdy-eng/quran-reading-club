"""Online sharing: tunnelled requests are never treated as the host, abuse limits, tunnel controller."""
import sys
import textwrap

from conftest import PASSWORD, Api

from app.config import AppConfig, Paths
from app.main import create_app
from app.tunnel import TunnelController


def tunnelled(env, visitor_ip="203.0.113.9"):
    """A browser on the internet reaching the club through cloudflared (which connects from localhost)."""
    return Api(
        env.app,
        ip="127.0.0.1",
        base_url="https://quiet-words-here.trycloudflare.com",
        headers={"cf-connecting-ip": visitor_ip, "cf-ray": "8c1d2e3f4a5b6c7d-CDG", "x-forwarded-for": visitor_ip},
    )


def test_tunnel_requests_are_not_the_host(env):
    admin = env.setup_group()
    web = tunnelled(env)
    info = web.ok("get", "/api/info")
    assert info["is_host"] is False and info["can_create_group"] is False
    r = web.post("/api/auth/setup", json={"username": "intruder", "password": PASSWORD, "group_name": "Mine", "timezone": "UTC"})
    assert r.status_code == 403
    # But a friend with the invitation code can join and read from anywhere.
    code = env.invite_code(admin)
    data = web.ok("post", "/api/auth/register", {"username": "faraway", "password": PASSWORD, "invite_code": code})
    web.token = data["token"]
    assert web.ok("get", "/api/auth/me")["is_host"] is False
    _, last = env.read(web, 30, page=10)
    assert last["today"]["pages_read"] == 1


def test_non_local_host_header_on_loopback_is_not_the_host(env):
    env.setup_group()
    # Even without proxy headers, a loopback request for a public hostname is treated as remote.
    a = Api(env.app, ip="127.0.0.1", base_url="https://club.example.org")
    assert a.ok("get", "/api/info")["can_create_group"] is False
    assert Api(env.app, ip="127.0.0.1").ok("get", "/api/info")["can_create_group"] is True


def test_login_throttle_uses_the_real_visitor_ip(env):
    env.setup_group()
    attacker = tunnelled(env, "198.51.100.7")
    for _ in range(8):
        assert attacker.post("/api/auth/login", json={"username": "host", "password": "nope-nope"}).status_code == 401
    assert attacker.post("/api/auth/login", json={"username": "host", "password": PASSWORD}).status_code == 429
    # A different visitor (the real host travelling) is not locked out by the attacker.
    friend = tunnelled(env, "192.0.2.44")
    assert friend.post("/api/auth/login", json={"username": "host", "password": PASSWORD}).status_code == 200


def test_username_lock_across_many_addresses(env):
    env.setup_group()
    for i in range(30):
        tunnelled(env, f"198.51.100.{i}").post("/api/auth/login", json={"username": "host", "password": "bad-guess"})
    r = tunnelled(env, "198.51.100.200").post("/api/auth/login", json={"username": "host", "password": PASSWORD})
    assert r.status_code == 429


def test_invite_code_guessing_is_throttled(env):
    admin = env.setup_group()
    guesser = tunnelled(env, "198.51.100.99")
    for i in range(8):
        r = guesser.post("/api/auth/register", json={"username": f"guess{i}", "password": PASSWORD, "invite_code": f"WRONG{i:03d}"})
        assert r.status_code == 404
    r = guesser.post("/api/auth/register", json={"username": "guessx", "password": PASSWORD, "invite_code": env.invite_code(admin)})
    assert r.status_code == 429


def test_security_headers(env):
    r = env.api().get("/api/health")
    assert "frame-ancestors 'none'" in r.headers["content-security-policy"]
    assert r.headers["x-frame-options"] == "DENY"


FAKE_CLOUDFLARED = textwrap.dedent(
    """
    import sys, time
    print("2026-11-23T18:00:00Z INF Requesting new quick Tunnel on trycloudflare.com...", flush=True)
    print("2026-11-23T18:00:01Z INF |  https://brave-sample-words-demo.trycloudflare.com  |", flush=True)
    while True:
        time.sleep(0.2)
    """
)


def test_tunnel_controller_reports_public_url(tmp_path):
    script = tmp_path / "fake_cloudflared.py"
    script.write_text(FAKE_CLOUDFLARED)
    paths = Paths(tmp_path / "data")
    paths.ensure()
    t = TunnelController(8765, paths, command=[sys.executable, str(script)])
    url = t.start(timeout=20)
    try:
        assert url == "https://brave-sample-words-demo.trycloudflare.com"
        assert t.status == "online" and t.public_url() == url
        app = create_app(
            paths.data_dir,
            config=AppConfig(auto_backup_hours=0),
            serve_frontend=False,
            background_tasks=False,
            sharing_provider=lambda: {"status": t.status, "public_url": t.public_url(), "named": False, "lan_urls": []},
        )
        host = Api(app)
        host.token = host.ok(
            "post",
            "/api/auth/setup",
            {"username": "host", "password": PASSWORD, "group_name": "Club", "timezone": "UTC"},
        )["token"]
        assert host.ok("get", "/api/admin/sharing")["public_url"] == url
        app.state.rc.db.dispose()
    finally:
        t.stop()
    assert t.status == "stopped" and t.public_url() is None
    assert "trycloudflare.com" in (paths.logs_dir / "tunnel.log").read_text()


def test_tunnel_controller_reports_failure(tmp_path):
    script = tmp_path / "broken.py"
    script.write_text("import sys; print('ERR failed to connect', flush=True); sys.exit(3)")
    paths = Paths(tmp_path / "data")
    paths.ensure()
    t = TunnelController(8765, paths, command=[sys.executable, str(script)])
    try:
        t.start(timeout=20)
        raise AssertionError("should have failed")
    except Exception as exc:  # noqa: BLE001
        assert "exited" in str(exc) or "stopped" in str(exc)
    assert t.status == "error"

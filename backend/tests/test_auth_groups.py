"""Accounts, authentication, groups, invitations, membership and isolation."""
from conftest import LAN_IP, PASSWORD

from app.models import User


def test_host_creates_group_and_is_admin(env):
    admin = env.setup_group()
    me = admin.ok("get", "/api/auth/me")
    assert me["membership"]["role"] == "admin"
    assert me["group"]["name"] == "Fajr Circle"
    assert me["group"]["settings"]["min_pages"] == 2
    assert me["group"]["settings"]["min_seconds"] == 20 * 60
    assert me["group"]["settings"]["inactivity_timeout_seconds"] == 60


def test_group_creation_only_from_host_machine(env):
    remote = env.api(LAN_IP)
    r = remote.post(
        "/api/auth/setup",
        json={"username": "x_user", "password": PASSWORD, "group_name": "Other", "timezone": "UTC"},
    )
    assert r.status_code == 403
    assert remote.ok("get", "/api/info")["can_create_group"] is False


def test_register_with_invite_and_login(env):
    admin = env.setup_group()
    friend = env.join(admin, "omar")
    me = friend.ok("get", "/api/auth/me")
    assert me["membership"]["role"] == "member"
    assert me["group"]["name"] == "Fajr Circle"

    fresh = env.api(LAN_IP)
    data = fresh.ok("post", "/api/auth/login", {"username": "OMAR", "password": PASSWORD})
    assert data["token"]


def test_wrong_invite_and_disabled_invite(env):
    admin = env.setup_group()
    a = env.api(LAN_IP)
    r = a.post("/api/auth/register", json={"username": "zaid", "password": PASSWORD, "invite_code": "NOPE1234"})
    assert r.status_code == 404
    admin.ok("patch", "/api/admin/group", {"invite_enabled": False})
    code = admin.ok("get", "/api/admin/group")["group"]["invite_code"]
    r = a.post("/api/auth/register", json={"username": "zaid", "password": PASSWORD, "invite_code": code})
    assert r.status_code == 404
    # The failed registration must not leave an orphan account behind.
    with env.app.state.rc.db.session() as db:
        assert db.query(User).filter_by(username_key="zaid").count() == 0


def test_regenerated_invite_invalidates_old_code(env):
    admin = env.setup_group()
    old = env.invite_code(admin)
    new = admin.ok("post", "/api/admin/invite/regenerate")["invite_code"]
    assert new != old
    r = env.api(LAN_IP).post("/api/auth/register", json={"username": "zaid", "password": PASSWORD, "invite_code": old})
    assert r.status_code == 404


def test_duplicate_username_rejected_case_insensitive(env):
    admin = env.setup_group()
    env.join(admin, "omar")
    a = env.api(LAN_IP)
    r = a.post(
        "/api/auth/register",
        json={"username": "Omar", "password": PASSWORD, "invite_code": env.invite_code(admin)},
    )
    assert r.status_code == 409


def test_validation_of_username_and_password(env):
    admin = env.setup_group()
    a = env.api(LAN_IP)
    code = env.invite_code(admin)
    assert a.post("/api/auth/register", json={"username": "ab", "password": PASSWORD, "invite_code": code}).status_code == 422
    assert a.post("/api/auth/register", json={"username": "a b c", "password": PASSWORD, "invite_code": code}).status_code == 422
    assert a.post("/api/auth/register", json={"username": "valid", "password": "short", "invite_code": code}).status_code == 422


def test_passwords_are_hashed(env):
    env.setup_group()
    with env.app.state.rc.db.session() as db:
        u = db.query(User).filter_by(username_key="host").one()
        assert PASSWORD not in u.password_hash
        assert u.password_hash.startswith("scrypt$")


def test_wrong_password_and_lockout(env):
    env.setup_group()
    a = env.api(LAN_IP)
    for _ in range(8):
        assert a.post("/api/auth/login", json={"username": "host", "password": "wrong-pass"}).status_code == 401
    r = a.post("/api/auth/login", json={"username": "host", "password": PASSWORD})
    assert r.status_code == 429


def test_endpoints_require_authentication(env):
    env.setup_group()
    a = env.api(LAN_IP)
    for url in ("/api/dashboard", "/api/stats/me", "/api/quran/page/1", "/api/reading/state", "/api/admin/group"):
        assert a.get(url).status_code == 401, url
    a.token = "forged-token"
    assert a.get("/api/dashboard").status_code == 401


def test_logout_revokes_token(env):
    admin = env.setup_group()
    admin.ok("post", "/api/auth/logout")
    assert admin.get("/api/auth/me").status_code == 401


def test_change_password(env):
    admin = env.setup_group()
    admin.ok("post", "/api/auth/password", {"current_password": PASSWORD, "new_password": "new-password-9"})
    a = env.api()
    assert a.post("/api/auth/login", json={"username": "host", "password": PASSWORD}).status_code == 401
    assert a.post("/api/auth/login", json={"username": "host", "password": "new-password-9"}).status_code == 200


def test_max_group_size(env):
    admin = env.setup_group(max_members=3)
    env.join(admin, "omar")
    env.join(admin, "ali")
    r = env.api(LAN_IP).post(
        "/api/auth/register", json={"username": "fourth", "password": PASSWORD, "invite_code": env.invite_code(admin)}
    )
    assert r.status_code == 409
    assert "full" in r.json()["detail"]


def test_admin_member_management(env):
    admin = env.setup_group()
    created = admin.ok("post", "/api/admin/members", {"username": "yusuf", "display_name": "Yusuf"})
    assert created["password"]
    yusuf = env.api(LAN_IP)
    yusuf.token = yusuf.ok("post", "/api/auth/login", {"username": "yusuf", "password": created["password"]})["token"]
    assert yusuf.ok("get", "/api/auth/me")["membership"]["role"] == "member"

    # Members cannot administer.
    assert yusuf.get("/api/admin/group").status_code == 403
    assert yusuf.patch("/api/admin/settings", json={"min_pages": 1}).status_code == 403

    # Reset password signs the member out and issues a new one.
    reset = admin.ok("post", f"/api/admin/members/{created['user_id']}/reset-password")
    assert yusuf.get("/api/auth/me").status_code == 401
    yusuf.token = yusuf.ok("post", "/api/auth/login", {"username": "yusuf", "password": reset["password"]})["token"]

    # Promote / demote, and the last admin is protected.
    admin.ok("post", f"/api/admin/members/{created['user_id']}/role", {"role": "admin"})
    assert yusuf.get("/api/admin/group").status_code == 200
    admin.ok("post", f"/api/admin/members/{created['user_id']}/role", {"role": "member"})
    host_id = admin.ok("get", "/api/auth/me")["user"]["id"]
    assert admin.post(f"/api/admin/members/{host_id}/role", json={"role": "member"}).status_code == 409

    # Remove.
    admin.ok("delete", f"/api/admin/members/{created['user_id']}")
    assert yusuf.get("/api/dashboard").status_code == 403
    me = yusuf.ok("get", "/api/auth/me")
    assert me["membership"] is None
    group = admin.ok("get", "/api/admin/group")
    assert [m["username"] for m in group["members"]] == ["host"]
    assert group["former_members"][0]["display_name"] == "Yusuf"


def test_removed_member_can_rejoin_with_code(env):
    admin = env.setup_group()
    omar = env.join(admin, "omar")
    uid = omar.ok("get", "/api/auth/me")["user"]["id"]
    admin.ok("delete", f"/api/admin/members/{uid}")
    omar.ok("post", "/api/groups/join", {"invite_code": env.invite_code(admin)})
    assert omar.ok("get", "/api/auth/me")["membership"]["role"] == "member"


def test_groups_are_isolated(env):
    admin_a = env.setup_group("Group A", "host_a")
    admin_b = env.setup_group("Group B", "host_b")
    member_a = env.join(admin_a, "member_a")
    a_id = member_a.ok("get", "/api/auth/me")["user"]["id"]

    # Group B's admin cannot see or manage A's member.
    assert admin_b.get(f"/api/stats/members/{a_id}").status_code == 404
    assert admin_b.delete(f"/api/admin/members/{a_id}").status_code == 404
    assert admin_b.post(f"/api/admin/members/{a_id}/reset-password").status_code == 404
    names = [m["username"] for m in admin_b.ok("get", "/api/dashboard")["members"]]
    assert names == ["host_b"]
    # A member of A cannot see sessions of B.
    sessions = admin_b.ok("get", f"/api/admin/sessions?user_id={a_id}")["sessions"]
    assert sessions == []
    # A user cannot be in two groups at once.
    r = member_a.post("/api/groups/join", json={"invite_code": env.invite_code(admin_b)})
    assert r.status_code == 409


def test_non_private_networks_are_refused(env):
    public = env.api("8.8.8.8")
    assert public.get("/api/health").status_code == 403
    tailscale = env.api("100.101.102.103")
    assert tailscale.get("/api/health").status_code == 200
    lan = env.api("10.0.0.7")
    assert lan.get("/api/health").status_code == 200


def test_member_cannot_view_other_member_history(env):
    admin = env.setup_group()
    omar = env.join(admin, "omar")
    ali = env.join(admin, "ali")
    ali_id = ali.ok("get", "/api/auth/me")["user"]["id"]
    assert omar.get(f"/api/stats/members/{ali_id}").status_code == 403
    assert admin.get(f"/api/stats/members/{ali_id}").status_code == 200

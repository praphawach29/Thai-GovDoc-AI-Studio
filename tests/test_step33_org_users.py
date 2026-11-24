"""ผู้ใช้ของหน่วยงาน: เชิญด้วยอีเมล / ยกเลิกคำเชิญ / เปลี่ยนบทบาท-ระงับ (server/routers/users.py, migration 15)"""
import json
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from fastapi.testclient import TestClient

from server import auth as server_auth
from server import supabase as server_supabase
from server.main import app
from server.routers.users import invite_state
from server.settings import Settings, get_settings
from tests.fake_supabase import ORG_ID, PUBLISHABLE_KEY, URL, USER_ID, FakeSupabase

OTHER = "22222222-2222-2222-2222-222222222222"


class UsersFake(FakeSupabase):
    def __init__(self):
        super().__init__()
        self.tables["profiles"][0]["email"] = "admin@test.local"
        self.tables["profiles"].append({"user_id": OTHER, "org_id": ORG_ID, "role": "drafter", "full_name": "ผู้ร่าง",
                                        "position": "", "email": "drafter@test.local", "created_at": "2026-11-20T00:00:00Z"})
        self.tables["org_invites"] = []
        self.missing = False
        self.rpc_calls = []

    def _table(self, request, table, query):
        if self.missing and table == "org_invites":
            return httpx.Response(404, json={"code": "PGRST205", "message": "Could not find the table 'public.org_invites'"})
        if table == "profiles" and "email" in query:            # ตรวจอีเมลซ้ำก่อนเชิญ
            email = query["email"][3:]
            return self._json(200, [{"user_id": r["user_id"]} for r in self.tables["profiles"] if r.get("email") == email])
        if table == "org_invites" and request.method == "POST":
            body = json.loads(request.content)
            if any(r["email"] == body["email"] and not r.get("used_at") and not r.get("revoked_at")
                   for r in self.tables["org_invites"]):
                return self._json(409, {"code": "23505", "message": "duplicate key value violates unique constraint"})
            body.setdefault("expires_at", (datetime.now(timezone.utc) + timedelta(days=14)).isoformat())
            body.setdefault("created_at", datetime.now(timezone.utc).isoformat())
            request = httpx.Request("POST", request.url, content=json.dumps(body).encode())
        return super()._table(request, table, query)

    def _rpc(self, request, name):
        p = json.loads(request.content or b"{}")
        self.rpc_calls.append((name, p))
        if name == "admin_set_role":
            row = next((r for r in self.tables["profiles"] if r["user_id"] == p["target"]), None)
            if row is None:
                return self._json(404, {"code": "P0002", "message": "ไม่พบผู้ใช้นี้ในหน่วยงาน"})
            row["role"] = p["new_role"]
            return self._json(200, p["new_role"])
        if name == "claim_my_invite":
            return self._json(200, False)
        return super()._rpc(request, name)


@pytest.fixture
def fake(tmp_path, monkeypatch):
    fake = UsersFake()
    monkeypatch.setattr(server_supabase, "transport_factory", fake.transport)
    server_auth._jwks_cache.clear()
    app.dependency_overrides[get_settings] = lambda: Settings(
        upload_dir=tmp_path / "uploads", registry_db_path=tmp_path / "r.db",
        supabase_url=URL, supabase_publishable_key=PUBLISHABLE_KEY,
    )
    yield fake
    app.dependency_overrides.clear()


@pytest.fixture
def client():
    return TestClient(app)


def _h(fake, sub=USER_ID):
    return {"Authorization": f"Bearer {fake.token(sub)}"}


def test_admin_invites_and_lists(fake, client):
    h = _h(fake)
    r = client.post("/api/v1/users/invites", json={"email": " New.User@Bangkok.go.th ", "full_name": "นาย  ใหม่",
                                                   "position": "นักพัฒนาการกีฬา", "role": "clerk"}, headers=h)
    assert r.status_code == 201, r.text
    row = fake.tables["org_invites"][0]
    assert row["email"] == "new.user@bangkok.go.th" and row["org_id"] == ORG_ID and row["created_by"] == USER_ID
    assert row["full_name"] == "นาย ใหม่" and row["role"] == "clerk"
    body = client.get("/api/v1/users", headers=h).json()
    assert body["me"] == USER_ID and len(body["users"]) == 2
    assert body["invites"][0]["state"] == "open"


def test_invite_rejects_duplicates_and_existing_users(fake, client):
    h = _h(fake)
    assert client.post("/api/v1/users/invites", json={"email": "drafter@test.local"}, headers=h).status_code == 409
    assert client.post("/api/v1/users/invites", json={"email": "x@test.local"}, headers=h).status_code == 201
    r = client.post("/api/v1/users/invites", json={"email": "x@test.local"}, headers=h)
    assert r.status_code == 409 and "คำเชิญ" in r.json()["detail"]


def test_invite_validation(fake, client):
    h = _h(fake)
    assert client.post("/api/v1/users/invites", json={"email": "not-an-email"}, headers=h).status_code == 422
    assert client.post("/api/v1/users/invites", json={"email": "a@b.co", "role": "superuser"}, headers=h).status_code == 422
    assert client.post("/api/v1/users/invites", json={"email": "a@b.co", "role": "disabled"}, headers=h).status_code == 422


def test_revoke_invite(fake, client):
    h = _h(fake)
    inv = client.post("/api/v1/users/invites", json={"email": "x@test.local"}, headers=h).json()
    assert client.delete(f"/api/v1/users/invites/{inv['id']}", headers=h).json()["revoked"] is True
    assert fake.tables["org_invites"][0]["revoked_at"]
    assert client.get("/api/v1/users", headers=h).json()["invites"][0]["state"] == "revoked"


def test_set_role_and_disable(fake, client):
    h = _h(fake)
    r = client.patch(f"/api/v1/users/{OTHER}", json={"role": "disabled"}, headers=h)
    assert r.status_code == 200 and fake.tables["profiles"][1]["role"] == "disabled"
    assert ("admin_set_role", {"target": OTHER, "new_role": "disabled"}) in fake.rpc_calls
    assert client.patch(f"/api/v1/users/{OTHER}", json={"role": "god"}, headers=h).status_code == 422


def test_admin_cannot_demote_self(fake, client):
    r = client.patch(f"/api/v1/users/{USER_ID}", json={"role": "drafter"}, headers=_h(fake))
    assert r.status_code == 400 and fake.tables["profiles"][0]["role"] == "admin"


def test_non_admin_is_refused(fake, client):
    h = _h(fake, OTHER)
    assert client.get("/api/v1/users", headers=h).status_code == 403
    assert client.post("/api/v1/users/invites", json={"email": "x@test.local"}, headers=h).status_code == 403


def test_disabled_user_gets_clear_message(fake, client):
    fake.tables["profiles"][1]["role"] = "disabled"
    r = client.get("/api/v1/me", headers=_h(fake, OTHER))
    assert r.status_code == 403 and "ระงับ" in r.json()["detail"]


def test_user_without_profile_tries_invite_then_gets_message(fake, client):
    stranger = "33333333-3333-3333-3333-333333333333"
    r = client.get("/api/v1/me", headers=_h(fake, stranger))
    assert r.status_code == 403 and "คำเชิญ" in r.json()["detail"]
    assert ("claim_my_invite", {}) in fake.rpc_calls


def test_missing_migration_hint(fake, client):
    fake.missing = True
    r = client.get("/api/v1/users", headers=_h(fake))
    assert r.status_code == 503 and "20261123000015_org_invites.sql" in r.json()["detail"]


def test_invite_state():
    now = datetime(2026, 11, 23, tzinfo=timezone.utc)
    assert invite_state({"used_at": "x"}, now) == "used"
    assert invite_state({"revoked_at": "x"}, now) == "revoked"
    assert invite_state({"expires_at": "2026-11-22T00:00:00Z"}, now) == "expired"
    assert invite_state({"expires_at": "2026-12-01T00:00:00+00:00"}, now) == "open"

"""
Step 21: ข้อมูลหน่วยงานแก้จากหน้าเว็บ (org_profile) — บันทึก/อ่าน และใช้กับร่างใหม่/เอกสารเปล่า
"""

import httpx
import pytest
from fastapi.testclient import TestClient

from core.profile_manager import apply_org_profile, get_default_profile
from server import auth as server_auth
from server import supabase as server_supabase
from server.main import app
from server.settings import Settings, get_settings
from tests.fake_supabase import ORG_ID, PUBLISHABLE_KEY, URL, USER_ID, FakeSupabase

FIELDS = {
    "dept_name": "สำนักงานทดสอบ", "department_full": "สำนักงานทดสอบ (กองทดสอบ โทร. ๑๑๑)",
    "doc_origin_code": "กท ๙๙๙๙/", "contact_dept": "กองทดสอบ", "contact_tel": "๐ ๑๑๑๑ ๑๑๑๑",
    "contact_fax": "", "contact_email": "test@bangkok.go.th",
}


def test_apply_org_profile_overlay():
    base = get_default_profile()
    assert apply_org_profile(base, None) is base
    out = apply_org_profile(base, {**FIELDS, "dept_name": "  "})
    assert out.department_full == FIELDS["department_full"]
    assert out.dept_name == base.dept_name                 # ว่าง = ค่าตั้งต้น
    assert out.contact_fax == ""                           # โทรสารลบได้
    assert out.contact_email == "test@bangkok.go.th"
    assert apply_org_profile(base, {"contact_email": ""}).contact_email is None
    assert out.signatory_name == base.signatory_name       # ไม่แตะผู้ลงนาม


class ProfileFake(FakeSupabase):
    def __init__(self):
        super().__init__()
        self.tables["org_profile"] = []
        self.tables["org_signers"] = []
        self.missing = set()

    def _table(self, request, table, query):
        if table in self.missing:
            return httpx.Response(404, json={"code": "PGRST205", "message": f"Could not find the table 'public.{table}'"})
        return super()._table(request, table, query)


@pytest.fixture
def fake(tmp_path, monkeypatch):
    fake = ProfileFake()
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


def _h(fake):
    return {"Authorization": f"Bearer {fake.token()}"}


def test_save_then_read_and_update(fake, client):
    h = _h(fake)
    before = client.get("/api/v1/studio/profile", headers=h).json()
    assert before["editable"] is True and "issuing_units" not in before
    r = client.put("/api/v1/org-profile", json=FIELDS, headers=h)
    assert r.status_code == 200, r.text
    rows = fake.tables["org_profile"]
    assert len(rows) == 1 and rows[0]["org_id"] == ORG_ID and rows[0]["updated_by"] == USER_ID
    got = client.get("/api/v1/studio/profile", headers=h).json()
    assert got["department_full"] == FIELDS["department_full"] and got["contact_email"] == FIELDS["contact_email"]
    # บันทึกซ้ำ = แก้แถวเดิม ไม่สร้างใหม่
    client.put("/api/v1/org-profile", json={**FIELDS, "contact_tel": "๐ ๒๒๒๒ ๒๒๒๒"}, headers=h)
    assert len(fake.tables["org_profile"]) == 1
    assert client.get("/api/v1/studio/profile", headers=h).json()["contact_tel"] == "๐ ๒๒๒๒ ๒๒๒๒"


def test_validation(fake, client):
    h = _h(fake)
    assert client.put("/api/v1/org-profile", json={"contact_email": "not-an-email"}, headers=h).status_code == 422
    assert client.put("/api/v1/org-profile", json={"department_full": "[✏️ ระบุส่วนราชการ]"}, headers=h).status_code == 422
    assert client.put("/api/v1/org-profile", json={"department_full": "x" * 501}, headers=h).status_code == 422
    r = client.put("/api/v1/org-profile", json={"contact_dept": "  กอง\n ทดสอบ  "}, headers=h)
    assert r.json()["contact_dept"] == "กอง ทดสอบ"


def test_requires_login(fake, client):
    assert client.put("/api/v1/org-profile", json=FIELDS).status_code == 401


def test_local_mode_profile_not_editable(client):
    app.dependency_overrides.clear()
    assert client.get("/api/v1/studio/profile").json()["editable"] is False


def test_blank_external_uses_org_profile(fake, client):
    h = _h(fake)
    client.put("/api/v1/org-profile", json=FIELDS, headers=h)
    doc = client.post("/api/v1/studio/blank", json={"doc_type": "external"}, headers=h).json()
    assert doc["dept_name"] == FIELDS["department_full"]
    assert doc["contact_dept"] == "กองทดสอบ" and doc["contact_email"] == "test@bangkok.go.th"


def test_missing_table_hint_and_fallback(fake, client):
    fake.missing.add("org_profile")
    h = _h(fake)
    r = client.put("/api/v1/org-profile", json=FIELDS, headers=h)
    assert r.status_code == 503 and "20261116000014_org_profile.sql" in r.json()["detail"]
    assert client.get("/api/v1/studio/profile", headers=h).status_code == 200
    assert client.post("/api/v1/studio/blank", json={"doc_type": "external"}, headers=h).status_code == 200

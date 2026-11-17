"""
Step 11: หน้าแก้ไขแสดงไฟล์ต้นเรื่องจริง (PDF/ภาพ) ด้วย URL ชั่วคราวจาก Supabase Storage
"""

import pytest
from fastapi.testclient import TestClient

from server import auth as server_auth
from server import supabase as server_supabase
from server.main import app
from server.settings import Settings, get_settings
from tests.fake_supabase import ORG_ID, PUBLISHABLE_KEY, URL, FakeSupabase


@pytest.fixture
def fake(tmp_path, monkeypatch):
    fake = FakeSupabase()
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


def _source(fake, suffix: str) -> str:
    path = f"{ORG_ID}/{'b' * 32}{suffix}"
    fake.storage[f"sources/{path}"] = b"%PDF-1.7 test"
    fid = "33333333-3333-3333-3333-33333333333" + str(len(fake.tables["source_files"]))
    fake.tables["source_files"].append({"id": fid, "org_id": ORG_ID, "storage_path": path,
                                        "filename": "หนังสือต้นเรื่อง" + suffix, "mime": ""})
    return fid


@pytest.mark.parametrize("suffix, kind", [(".pdf", "pdf"), (".jpg", "image"), (".png", "image")])
def test_view_url_is_signed_inline_link(fake, client, suffix, kind):
    fid = _source(fake, suffix)
    res = client.get(f"/api/v1/sources/{fid}/view-url", headers={"Authorization": f"Bearer {fake.token()}"})
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["kind"] == kind and body["filename"] == "หนังสือต้นเรื่อง" + suffix
    assert body["url"].startswith(f"{URL}/storage/v1/object/sign/sources/{ORG_ID}/")
    assert "download=" not in body["url"]          # เปิดดูในหน้า ไม่บังคับดาวน์โหลด
    sign = [r for r in fake.requests if r.url.path.startswith("/storage/v1/object/sign/")][-1]
    assert b'"expiresIn": 3600' in sign.content or b'"expiresIn":3600' in sign.content


def test_view_url_docx_falls_back_to_text(fake, client):
    fid = _source(fake, ".docx")
    body = client.get(f"/api/v1/sources/{fid}/view-url", headers={"Authorization": f"Bearer {fake.token()}"}).json()
    assert body == {"url": None, "filename": "หนังสือต้นเรื่อง.docx", "kind": "text"}


def test_view_url_missing_or_other_org_is_404(fake, client):
    missing = "99999999-9999-9999-9999-999999999999"
    res = client.get(f"/api/v1/sources/{missing}/view-url", headers={"Authorization": f"Bearer {fake.token()}"})
    assert res.status_code == 404 and "๓๐ วัน" in res.json()["detail"]
    assert client.get(f"/api/v1/sources/not-a-uuid/view-url",
                      headers={"Authorization": f"Bearer {fake.token()}"}).status_code == 422


def test_view_url_local_mode_is_404():
    assert TestClient(app).get(f"/api/v1/sources/{'1' * 8}-1111-1111-1111-{'1' * 12}/view-url").status_code == 404

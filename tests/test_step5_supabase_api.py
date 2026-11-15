"""
Step 5: API ในโหมด Supabase — ล็อกอิน, เอกสาร, ทะเบียน, ไฟล์ต้นเรื่อง
ใช้ Supabase จำลอง (tests/fake_supabase.py); สิทธิ์ระดับฐานข้อมูลทดสอบที่ supabase/tests/run_local.sh
"""

import hashlib

import pytest
from fastapi.testclient import TestClient

from core.templates_library import PRESET_TEMPLATES
from server import auth as server_auth
from server import supabase as server_supabase
from server.main import app
from server.settings import Settings, get_settings
from tests.fake_supabase import NO_PROFILE_USER, ORG_ID, PUBLISHABLE_KEY, URL, USER_ID, FakeSupabase


@pytest.fixture
def fake(tmp_path, monkeypatch):
    fake = FakeSupabase()
    monkeypatch.setattr(server_supabase, "transport_factory", fake.transport)
    server_auth._jwks_cache.clear()
    settings = Settings(
        upload_dir=tmp_path / "uploads", registry_db_path=tmp_path / "r.db",
        supabase_url=URL, supabase_publishable_key=PUBLISHABLE_KEY,
    )
    app.dependency_overrides[get_settings] = lambda: settings
    fake.settings = settings
    return fake


@pytest.fixture
def client():
    return TestClient(app)


def _auth(fake, **kw):
    return {"Authorization": f"Bearer {fake.token(**kw)}"}


def _doc(template="procurement_approval"):
    return PRESET_TEMPLATES[template].schema.model_dump(mode="json")


# ---------------------------------------------------------------- ล็อกอิน
def test_config_is_public_and_tells_page_to_log_in(fake, client):
    body = client.get("/api/v1/config").json()
    assert body["auth_required"] is True
    assert body["supabase_url"] == URL and body["supabase_publishable_key"] == PUBLISHABLE_KEY
    assert client.get("/api/v1/health").status_code == 200


def test_local_mode_config_has_no_supabase(client):
    body = client.get("/api/v1/config").json()
    assert body == {**body, "auth_required": False, "supabase_url": None, "supabase_publishable_key": None}


@pytest.mark.parametrize("headers", [
    {},
    {"Authorization": "Bearer not-a-jwt"},
    {"Authorization": "Basic abc"},
])
def test_protected_endpoints_need_valid_login(fake, client, headers):
    for method, path in (("get", "/api/v1/studio/templates"), ("get", "/api/v1/registry/outgoing"),
                         ("post", "/api/v1/export/typst")):
        assert getattr(client, method)(path, headers=headers).status_code == 401, path


@pytest.mark.parametrize("claims", [
    {"exp": 1},                                   # หมดอายุ
    {"aud": "other"},                             # ผิด audience
    {"iss": "https://evil.example/auth/v1"},      # token จากโปรเจกต์อื่น
    {"role": "service_role"},                     # ไม่ใช่ผู้ใช้ทั่วไป
])
def test_rejects_bad_tokens(fake, client, claims):
    res = client.get("/api/v1/studio/templates", headers=_auth(fake, **claims))
    assert res.status_code == 401


def test_rejects_token_signed_by_another_key(fake, client):
    other = FakeSupabase()
    res = client.get("/api/v1/studio/templates", headers={"Authorization": f"Bearer {other.token()}"})
    assert res.status_code == 401


def test_accepts_valid_token(fake, client):
    assert client.get("/api/v1/studio/templates", headers=_auth(fake)).status_code == 200


def test_legacy_hs256_project_is_checked_with_auth_server(fake, client):
    good = {"Authorization": f"Bearer {fake.legacy_token()}"}
    bad = {"Authorization": f"Bearer {fake.legacy_token(valid=False)}"}
    assert client.get("/api/v1/studio/templates", headers=good).status_code == 200
    assert client.get("/api/v1/studio/templates", headers=bad).status_code == 401


def test_me_returns_org_and_requires_profile(fake, client):
    me = client.get("/api/v1/me", headers=_auth(fake)).json()
    assert me["organization"]["id"] == ORG_ID and me["role"] == "admin"
    assert me["email"] == "a@test.local"           # แสดงบนหน้าแรกเมื่อยังไม่ได้ตั้งชื่อ
    res = client.get("/api/v1/me", headers=_auth(fake, sub=NO_PROFILE_USER))
    assert res.status_code == 403


def test_every_supabase_call_uses_the_users_token(fake, client):
    headers = _auth(fake)
    client.get("/api/v1/me", headers=headers)
    client.post("/api/v1/documents", json={"doc": _doc()}, headers=headers)
    data_calls = [r for r in fake.requests if "/jwks.json" not in r.url.path]
    assert data_calls
    for r in data_calls:
        assert r.headers["authorization"] == headers["Authorization"]
        assert r.headers["apikey"] == PUBLISHABLE_KEY


# ---------------------------------------------------------------- เอกสาร
def test_document_create_autosave_and_versions(fake, client):
    h = _auth(fake)
    created = client.post("/api/v1/documents", json={"doc": _doc(), "workspace": {"prompt": "ขออนุมัติ"}}, headers=h)
    assert created.status_code == 201
    doc_id = created.json()["id"]
    row = fake.tables["documents"][0]
    assert row["org_id"] == ORG_ID and row["owner_id"] == USER_ID
    assert row["workspace"]["prompt"] == "ขออนุมัติ" and row["workspace"]["doc"]["subject"]
    assert created.json()["version"] == 1

    changed = _doc()
    changed["subject"] = "เรื่องที่แก้แล้ว"
    assert client.patch(f"/api/v1/documents/{doc_id}", json={"doc": changed}, headers=h).status_code == 200
    assert row["subject"] == "เรื่องที่แก้แล้ว" and row["workspace"]["doc"]["subject"] == "เรื่องที่แก้แล้ว"
    assert len(fake.tables["document_versions"]) == 1          # autosave ไม่สร้างเวอร์ชัน

    v = client.post(f"/api/v1/documents/{doc_id}/versions", json={"doc": changed, "note": "ก่อนร่างใหม่"}, headers=h)
    assert v.json()["version"] == 2
    assert client.get(f"/api/v1/documents/{doc_id}", headers=h).json()["workspace"]["doc"]["subject"] == "เรื่องที่แก้แล้ว"


def test_document_rejects_invalid_ids_and_content(fake, client):
    h = _auth(fake)
    assert client.get("/api/v1/documents/not-a-uuid", headers=h).status_code == 422
    assert client.post("/api/v1/documents", json={"doc": {"doc_type": "nonsense"}}, headers=h).status_code == 422


def test_database_errors_become_clear_http_errors(fake, client):
    fake.rpc_errors["save_document_version"] = {"code": "42501", "message": "ไม่พบเอกสารนี้ในหน่วยงาน"}
    res = client.post("/api/v1/documents/22222222-2222-2222-2222-222222222222/versions",
                      json={"doc": _doc()}, headers=_auth(fake))
    assert res.status_code == 403 and res.json()["detail"] == "ไม่พบเอกสารนี้ในหน่วยงาน"


def test_documents_api_is_unavailable_in_local_mode(client):
    assert client.get("/api/v1/documents").status_code == 404


# ---------------------------------------------------------------- ทะเบียน
def test_registry_uses_database_functions(fake, client):
    h = _auth(fake)
    res = client.post("/api/v1/registry/reserve", json={"prefix": "กท ๐๐๐๑/", "subject": "ทดสอบ"}, headers=h)
    assert res.json()["reserved_number"] == "กท ๐๐๐๑/1"
    entry_id = res.json()["entry"]["id"]
    assert client.post(f"/api/v1/registry/outgoing/{entry_id}/issue", json={}, headers=h).json()["status"] == "issued"
    assert client.post(f"/api/v1/registry/outgoing/{entry_id}/cancel", json={"reason": "ผิด"}, headers=h).json()["status"] == "cancelled"
    assert len(client.get("/api/v1/registry/outgoing", headers=h).json()) == 1
    # โหมด Supabase ห้ามกำหนดเลขเอง
    assert client.post("/api/v1/registry/outgoing", headers=h, json={
        "doc_number": "ปลอม/1", "doc_type": "external", "subject": "x", "recipient": "y", "doc_date": "z",
    }).status_code == 405
    inc = client.post("/api/v1/registry/incoming", json={"subject": "รับเรื่อง"}, headers=h)
    assert inc.json()["receive_number"] == "1"
    assert client.post("/api/v1/registry/incoming", json={"remark": "ไม่มีเรื่อง"}, headers=h).status_code == 422


def test_next_number_peek_formats_like_database(fake, client):
    from core.thai_date import current_be_year
    fake.tables["number_sequences"].append({"book": "outgoing:กท ๐๐๐๑/", "year_be": current_be_year(), "last_value": 41})
    res = client.get("/api/v1/registry/next-number", params={"prefix": "กท ๐๐๐๑/"}, headers=_auth(fake))
    assert res.json()["doc_number"] == "กท ๐๐๐๑/๔๒"
    res = client.get("/api/v1/registry/next-number", params={"prefix": "กท ๐๐๐๑/", "is_circular": True}, headers=_auth(fake))
    assert res.json()["doc_number"] == "กท ๐๐๐๑/ว ๑"


# ---------------------------------------------------------------- ไฟล์ต้นเรื่อง
def test_upload_url_is_scoped_to_users_org(fake, client):
    h = _auth(fake)
    res = client.post("/api/v1/sources/upload-url", json={"filename": "../../x.pdf", "size_bytes": 1000}, headers=h)
    body = res.json()
    assert res.status_code == 200
    assert body["path"].startswith(ORG_ID + "/") and body["path"].endswith(".pdf") and ".." not in body["path"]
    assert body["upload_url"].startswith(URL + "/storage/v1/object/upload/sign/sources/")
    assert client.post("/api/v1/sources/upload-url", json={"filename": "a.exe", "size_bytes": 10}, headers=h).status_code == 400
    too_big = fake.settings.max_upload_bytes + 1
    assert client.post("/api/v1/sources/upload-url", json={"filename": "a.pdf", "size_bytes": too_big}, headers=h).status_code == 413


def test_register_source_reads_from_storage_and_records_it(fake, client):
    h = _auth(fake)
    path = f"{ORG_ID}/{'a' * 32}.txt"
    data = "ด้วยสมาคมกีฬาขอความอนุเคราะห์ใช้สนามกีฬา ในวันที่ ๓๐ มกราคม ๒๕๗๐".encode("utf-8")
    fake.storage[f"sources/{path}"] = data
    res = client.post("/api/v1/sources/register", json={"path": path, "filename": "หนังสือ.txt"}, headers=h)
    assert res.status_code == 200, res.text
    row = fake.tables["source_files"][0]
    assert row["sha256"] == hashlib.sha256(data).hexdigest() and row["size_bytes"] == len(data)
    assert "สมาคมกีฬา" in row["extracted_text"] and row["filename"] == "หนังสือ.txt"
    assert list(fake.settings.upload_dir.iterdir()) == []      # ไฟล์ชั่วคราวถูกลบ


@pytest.mark.parametrize("path", [
    "22222222-2222-2222-2222-222222222222/" + "a" * 32 + ".txt",   # หน่วยงานอื่น
    ORG_ID + "/../etc/passwd",
    ORG_ID + "/" + "a" * 32 + ".exe",
])
def test_register_source_rejects_foreign_or_odd_paths(fake, client, path):
    res = client.post("/api/v1/sources/register", json={"path": path, "filename": "x"}, headers=_auth(fake))
    assert res.status_code == 400


def test_studio_draft_stores_uploaded_file_in_storage(fake, client):
    res = client.post(
        "/api/v1/studio/draft",
        files={"file": ("ต้นเรื่อง.txt", "ด้วยสมาคมกีฬาขอความอนุเคราะห์ใช้สนามกีฬา".encode("utf-8"), "text/plain")},
        headers=_auth(fake),
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["source_file_id"] and body["context"]["source_filename"] == "ต้นเรื่อง.txt"
    stored = [k for k in fake.storage if k.startswith(f"sources/{ORG_ID}/")]
    assert len(stored) == 1
    assert fake.tables["source_files"][0]["storage_path"] == stored[0][len("sources/"):]
    assert list(fake.settings.upload_dir.iterdir()) == []


def test_legal_library_uses_org_table(fake, client):
    h = _auth(fake)
    res = client.post("/api/v1/legal/references", json={"title": "ระเบียบงานสารบรรณ", "quote": "ข้อ ๑๖"}, headers=h)
    assert res.json()["reference"]["org_id"] == ORG_ID
    assert len(client.get("/api/v1/legal/references", headers=h).json()["references"]) == 1


def test_cloud_without_supabase_fails_closed(tmp_path, client):
    """ขึ้น Vercel แล้วลืมตั้ง Supabase → API ต้องปฏิเสธ ไม่ใช่เปิดให้ใช้โดยไม่ล็อกอิน"""
    settings = Settings(upload_dir=tmp_path / "u", registry_db_path=tmp_path / "r.db", require_auth=True)
    app.dependency_overrides[get_settings] = lambda: settings
    assert client.get("/api/v1/studio/templates").status_code == 503
    assert client.post("/api/v1/export/typst", json=_doc()).status_code == 503
    assert client.get("/api/v1/health").status_code == 200
    assert client.get("/api/v1/config").json()["misconfigured"] is True


def test_settings_accept_supabase_connect_names_and_report_missing(monkeypatch, client, tmp_path):
    for name in ("SUPABASE_URL", "SUPABASE_PUBLISHABLE_KEY", "SUPABASE_ANON_KEY"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("NEXT_PUBLIC_SUPABASE_URL", " https://x.supabase.co/ ")
    monkeypatch.setenv("NEXT_PUBLIC_SUPABASE_PUBLISHABLE_DEFAULT_KEY", "sb_publishable_x")
    s = Settings(upload_dir=tmp_path / "u", registry_db_path=tmp_path / "r.db")
    assert s.supabase_url == "https://x.supabase.co" and s.supabase_publishable_key == "sb_publishable_x"

    monkeypatch.delenv("NEXT_PUBLIC_SUPABASE_PUBLISHABLE_DEFAULT_KEY")
    half = Settings(upload_dir=tmp_path / "u", registry_db_path=tmp_path / "r.db", require_auth=True)
    app.dependency_overrides[get_settings] = lambda: half
    body = client.get("/api/v1/config").json()
    assert body["misconfigured"] is True and body["missing_settings"] == ["SUPABASE_PUBLISHABLE_KEY"]

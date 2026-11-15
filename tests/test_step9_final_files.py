"""
Step 9: ฉบับจริง — แก้ไฟล์ Word เสร็จแล้วอัปโหลดกลับเข้าระบบ
เก็บไฟล์ตามที่ได้รับทุกไบต์ (ไม่แปลงกลับ), ตรวจว่าเป็นไฟล์จริง, อ่าน ที่/วันที่/เรื่อง, อัปโหลดใหม่ = ฉบับถัดไป
"""

import hashlib

import pytest
from fastapi.testclient import TestClient

from core.final_file import FinalFileError, inspect_final_file
from core.templates_library import PRESET_TEMPLATES
from core.word_exporter import export_govdoc_to_docx
from server import auth as server_auth
from server import supabase as server_supabase
from server.main import app
from server.settings import Settings, get_settings
from tests.fake_supabase import ORG_ID, PUBLISHABLE_KEY, URL, FakeSupabase


def _docx_bytes(tmp_path, **changes) -> bytes:
    doc = PRESET_TEMPLATES["bma_cohost_request"].schema.model_copy(deep=True, update=changes)
    out = tmp_path / "final.docx"
    export_govdoc_to_docx(doc, str(out))
    return out.read_bytes()


# ---------------------------------------------------------------- core
def test_inspect_reads_header_from_exported_word(tmp_path):
    data = _docx_bytes(tmp_path, doc_number="กท 1205/456", doc_date="15 พฤศจิกายน 2569",
                       subject="ขออนุมัติจัดการแข่งขันกีฬา", use_thai_numerals=False)
    info = inspect_final_file(data, "บันทึก.DOCX")
    assert info.suffix == ".docx" and info.sha256 == hashlib.sha256(data).hexdigest()
    assert info.doc_number == "กท 1205/456" and info.doc_date == "15 พฤศจิกายน 2569"
    assert info.subject == "ขออนุมัติจัดการแข่งขันกีฬา"
    assert "​" not in info.text and "ต้นเรื่อง" in info.text


@pytest.mark.parametrize("data, name, message", [
    (b"not a zip", "x.docx", "ไม่ใช่ Word"),
    (b"PK\x03\x04broken", "x.docx", "Word"),
    (b"hello", "x.pdf", "ไม่ใช่ PDF"),
    (b"%PDF-1.7", "x.doc", "เฉพาะไฟล์ Word"),
    (b"", "x.docx", "ไฟล์ว่าง"),
])
def test_inspect_rejects_bad_files(data, name, message):
    with pytest.raises(FinalFileError, match=message):
        inspect_final_file(data, name)


# ---------------------------------------------------------------- API (Supabase)
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


def _new_document(client, h) -> str:
    doc = PRESET_TEMPLATES["bma_cohost_request"].schema.model_dump(mode="json")
    return client.post("/api/v1/documents", json={"doc": doc}, headers=h).json()["id"]


def _upload(fake, client, h, doc_id, data, filename, note=None):
    res = client.post(f"/api/v1/documents/{doc_id}/finals/upload-url",
                      json={"filename": filename, "size_bytes": len(data)}, headers=h)
    assert res.status_code == 200, res.text
    path = res.json()["path"]
    assert path.startswith(f"{ORG_ID}/finals/") and res.json()["upload_url"].startswith(URL)
    fake.storage[f"sources/{path}"] = data                      # เบราว์เซอร์ PUT ตรงเข้า Storage
    return client.post(f"/api/v1/documents/{doc_id}/finals",
                       json={"path": path, "filename": filename, "note": note}, headers=h)


def test_upload_word_back_keeps_bytes_and_numbers_revisions(fake, client, tmp_path):
    h = {"Authorization": f"Bearer {fake.token()}"}
    doc_id = _new_document(client, h)
    data = _docx_bytes(tmp_path, doc_number="กท 1205/456", use_thai_numerals=False)

    first = _upload(fake, client, h, doc_id, data, "ฉบับลงนาม.docx", note="ผอ.ลงนามแล้ว")
    assert first.status_code == 201, first.text
    body = first.json()
    assert body["revision"] == 1 and body["doc_number"] == "กท 1205/456" and body["note"] == "ผอ.ลงนามแล้ว"
    assert body["sha256"] == hashlib.sha256(data).hexdigest() and body["size_bytes"] == len(data)
    stored = fake.tables["final_files"][0]
    assert fake.storage[f"sources/{stored['storage_path']}"] == data   # ไม่แปลงไฟล์
    assert "ต้นเรื่อง" in stored["extracted_text"]                     # ค้นหาได้ภายหลัง

    second = _upload(fake, client, h, doc_id, data + b"", "แก้คำผิด.docx")
    assert second.json()["revision"] == 2
    listed = client.get(f"/api/v1/documents/{doc_id}/finals", headers=h).json()
    assert [r["revision"] for r in listed] == [2, 1] and "extracted_text" not in listed[0]

    url = client.get(f"/api/v1/documents/{doc_id}/finals/{listed[0]['id']}/download", headers=h).json()["url"]
    assert url.startswith(f"{URL}/storage/v1/object/sign/sources/{ORG_ID}/finals/") and "download=" in url
    # ทุกคำขอใช้ token ของผู้ใช้ (RLS ของ Supabase ตัดสินสิทธิ์)
    assert all(r.headers.get("authorization", "").startswith("Bearer ") for r in fake.requests
               if r.url.path.startswith(("/rest/", "/storage/")))


def test_rejects_bad_uploads(fake, client, tmp_path):
    h = {"Authorization": f"Bearer {fake.token()}"}
    doc_id = _new_document(client, h)
    # ไม่ใช่ Word/PDF
    assert client.post(f"/api/v1/documents/{doc_id}/finals/upload-url",
                       json={"filename": "x.doc", "size_bytes": 10}, headers=h).status_code == 400
    # เอกสารที่ไม่มี (หรือของหน่วยงานอื่น ซึ่ง RLS ซ่อนไว้)
    missing = "99999999-9999-9999-9999-999999999999"
    assert client.post(f"/api/v1/documents/{missing}/finals/upload-url",
                       json={"filename": "x.docx", "size_bytes": 10}, headers=h).status_code == 404
    # ไฟล์ที่อัปโหลดเสีย → 422 และไม่บันทึก
    res = _upload(fake, client, h, doc_id, b"this is not a word file", "เสีย.docx")
    assert res.status_code == 422 and "Word" in res.json()["detail"]
    assert fake.tables["final_files"] == []
    assert not [k for k in fake.storage if "/finals/" in k]               # ไฟล์ที่ตรวจไม่ผ่านถูกลบทิ้ง
    # path ที่ไม่ได้ออกให้ (นอกโฟลเดอร์หน่วยงาน)
    bad = client.post(f"/api/v1/documents/{doc_id}/finals",
                      json={"path": f"{ORG_ID}/{'a' * 32}.docx", "filename": "x.docx"}, headers=h)
    assert bad.status_code == 400


def test_local_mode_has_no_finals(client):
    res = client.post("/api/v1/documents/11111111-1111-1111-1111-111111111111/finals/upload-url",
                      json={"filename": "x.docx", "size_bytes": 1})
    assert res.status_code == 404

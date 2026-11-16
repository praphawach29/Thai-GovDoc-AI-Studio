"""
Step 19: ลบถาวรจากถังขยะ — ลบเอกสาร เวอร์ชัน และไฟล์ต้นเรื่องใน Storage (คืนพื้นที่)
เงื่อนไขอยู่ในฐานข้อมูล (purge_document) ที่นี่ทดสอบการเรียกและการลบไฟล์ตามคิว
"""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from core.templates_library import PRESET_TEMPLATES
from server import auth as server_auth
from server import supabase as server_supabase
from server.main import app
from server.settings import Settings, get_settings
from tests.fake_supabase import ORG_ID, PUBLISHABLE_KEY, URL, FakeSupabase

MIGRATION = Path(__file__).resolve().parents[1] / "supabase/migrations/20261116000009_purge_documents.sql"


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


def _create(client, h, fake, with_file=True):
    ws = {}
    if with_file:
        path = f"{ORG_ID}/src-{len(fake.storage)}.pdf"
        fake.storage["sources/" + path] = b"%PDF-1.4 x"
        fake.tables["source_files"].append({"id": f"sf-{len(fake.storage)}", "org_id": ORG_ID, "storage_path": path})
        ws["sourceFileId"] = f"sf-{len(fake.storage)}"
    doc = PRESET_TEMPLATES["bma_cohost_request"].schema.model_dump(mode="json")
    return client.post("/api/v1/documents", json={"doc": doc, "workspace": ws}, headers=h).json()["id"]


def test_purge_removes_document_versions_and_files(fake, client):
    h = {"Authorization": f"Bearer {fake.token()}"}
    doc_id = _create(client, h, fake)
    assert len(fake.storage) == 1
    client.patch(f"/api/v1/documents/{doc_id}/status", json={"status": "archived"}, headers=h)
    res = client.delete(f"/api/v1/documents/{doc_id}", headers=h)
    assert res.status_code == 200, res.text
    assert res.json() == {"id": doc_id, "files_removed": 1, "files_pending": 0}
    assert not fake.tables["documents"] and not fake.tables["document_versions"]
    assert not fake.storage and not fake.tables["source_files"] and not fake.tables["storage_purge_queue"]
    assert fake.tables["audit_log"][-1]["action"] == "purge"


def test_purge_retries_leftover_queue(fake, client):
    """ไฟล์ที่ลบไม่สำเร็จครั้งก่อน (ค้างในคิว) ถูกลบตอนลบถาวรครั้งถัดไป"""
    h = {"Authorization": f"Bearer {fake.token()}"}
    old = f"{ORG_ID}/old.pdf"
    fake.storage["sources/" + old] = b"x"
    fake.tables["storage_purge_queue"].append({"bucket": "sources", "storage_path": old})
    doc_id = _create(client, h, fake, with_file=False)
    client.patch(f"/api/v1/documents/{doc_id}/status", json={"status": "archived"}, headers=h)
    assert client.delete(f"/api/v1/documents/{doc_id}", headers=h).json()["files_removed"] == 1
    assert not fake.storage and not fake.tables["storage_purge_queue"]


def test_purge_refuses_document_not_in_trash(fake, client):
    h = {"Authorization": f"Bearer {fake.token()}"}
    doc_id = _create(client, h, fake)
    res = client.delete(f"/api/v1/documents/{doc_id}", headers=h)
    assert res.status_code == 400 and "ถังขยะ" in res.json()["detail"]
    assert fake.tables["documents"] and fake.storage


def test_purge_refuses_official_documents(fake, client):
    h = {"Authorization": f"Bearer {fake.token()}"}
    doc_id = _create(client, h, fake)
    client.patch(f"/api/v1/documents/{doc_id}/status", json={"status": "archived"}, headers=h)
    fake.tables["final_files"].append({"document_id": doc_id, "revision": 1})
    res = client.delete(f"/api/v1/documents/{doc_id}", headers=h)
    assert res.status_code == 403 and "ฉบับจริง" in res.json()["detail"]
    assert fake.tables["documents"]


def test_migration_keeps_records_protected():
    """ปลดล็อกการลบเฉพาะใน purge_document ของเอกสารฉบับนั้น และยังบันทึก audit"""
    sql = MIGRATION.read_text(encoding="utf-8")
    assert "current_setting('govdoc.purge_document', true)" in sql
    assert "tg_table_name = 'documents' and old.id::text = v_purge" in sql
    for guard in ("v_doc.status <> 'archived'", "public.final_files", "public.outgoing_register",
                  "current_role_is('admin')", "write_audit(v_org, 'purge'"):
        assert guard in sql
    assert sql.rstrip().endswith("notify pgrst, 'reload schema';")

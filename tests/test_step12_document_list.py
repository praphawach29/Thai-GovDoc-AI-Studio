"""
Step 12: รายการงานบนหน้าแรก — สรุปประเภท/หน่วย/สถานะ/จุดที่ต้องแก้ และเก็บฉบับทดลองออกจากรายการ
"""

import pytest
from fastapi.testclient import TestClient

from core.templates_library import PRESET_TEMPLATES
from server import auth as server_auth
from server import supabase as server_supabase
from server.main import app
from server.settings import Settings, get_settings
from tests.fake_supabase import PUBLISHABLE_KEY, URL, FakeSupabase


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


def _doc():
    return PRESET_TEMPLATES["bma_cohost_request"].schema.model_dump(mode="json")


def _create(client, h, workspace):
    return client.post("/api/v1/documents", json={"doc": _doc(), "workspace": workspace}, headers=h).json()["id"]


def test_list_summarises_workspace(fake, client):
    h = {"Authorization": f"Bearer {fake.token()}"}
    doc_id = _create(client, h, {
        "unitKey": "division", "sourceName": "ต้นเรื่อง.pdf", "context": {"raw_text": "ต้นเรื่องยาวมาก " * 500},
        "check": {"placeholders": ["เรื่อง: [✏️ ระบุเรื่อง]", "เรียน: [✏️ ระบุผู้รับ]"],
                  "lint": {"is_valid": False, "issues": [{"rule_id": "x", "severity": "warning", "field": "doc_date",
                                                         "message": "m", "suggestion": "s"}]},
                  "facts": [{"field": "memo_facts", "kind": "number", "text": "๕,๐๐๐", "message": "m"}]},
    })
    rows = client.get("/api/v1/documents", headers=h).json()
    assert len(rows) == 1
    row = rows[0]
    assert row["id"] == doc_id and row["doc_type"] == "internal"
    assert row["unit_key"] == "division" and row["source_name"] == "ต้นเรื่อง.pdf"
    assert row["todo"] == 4                                   # ต้องระบุ ๒ + ข้อควรแก้ ๑ + ข้อเท็จจริง ๑
    assert "workspace" not in row and not {"placeholders", "issues", "facts"} & set(row)   # ไม่ส่งต้นเรื่องทั้งฉบับ
    sent = [r for r in fake.requests if r.method == "GET" and r.url.path == "/rest/v1/documents"][-1]
    assert sent.url.params["status"] == "neq.archived"


def test_list_without_check_counts_zero(fake, client):
    h = {"Authorization": f"Bearer {fake.token()}"}
    _create(client, h, {})
    row = client.get("/api/v1/documents", headers=h).json()[0]
    assert row["todo"] == 0 and row["unit_key"] is None


def test_archive_hides_and_restore_brings_back(fake, client):
    h = {"Authorization": f"Bearer {fake.token()}"}
    keep = _create(client, h, {})
    trial = _create(client, h, {})
    res = client.patch(f"/api/v1/documents/{trial}/status", json={"status": "archived"}, headers=h)
    assert res.status_code == 200 and res.json()["status"] == "archived"
    assert [r["id"] for r in client.get("/api/v1/documents", headers=h).json()] == [keep]
    assert [r["id"] for r in client.get("/api/v1/documents?archived=true", headers=h).json()] == [trial]
    assert client.patch(f"/api/v1/documents/{trial}/status", json={"status": "draft"}, headers=h).status_code == 200
    assert {r["id"] for r in client.get("/api/v1/documents", headers=h).json()} == {keep, trial}
    # เวอร์ชันที่เก็บไว้ยังอยู่ (เก็บ ≠ ลบ)
    assert any(v["document_id"] == trial for v in fake.tables["document_versions"])


@pytest.mark.parametrize("status", ["sent", "numbered", "deleted", ""])
def test_status_only_archive_or_draft(fake, client, status):
    h = {"Authorization": f"Bearer {fake.token()}"}
    doc_id = _create(client, h, {})
    assert client.patch(f"/api/v1/documents/{doc_id}/status", json={"status": status}, headers=h).status_code == 422


def test_status_missing_document_404(fake, client):
    h = {"Authorization": f"Bearer {fake.token()}"}
    missing = "99999999-9999-9999-9999-999999999999"
    assert client.patch(f"/api/v1/documents/{missing}/status", json={"status": "archived"}, headers=h).status_code == 404

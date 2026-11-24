"""แจ้งปัญหา / ความเห็นของผู้ใช้ (server/routers/feedback.py, migration 16)"""
import httpx
import pytest
from fastapi.testclient import TestClient

from server import auth as server_auth
from server import supabase as server_supabase
from server.main import app
from server.routers.feedback import _trim_context
from server.settings import Settings, get_settings
from tests.fake_supabase import ORG_ID, PUBLISHABLE_KEY, URL, USER_ID, FakeSupabase

OTHER = "22222222-2222-2222-2222-222222222222"
DOC_ID = "33333333-3333-3333-3333-333333333333"


class FeedbackFake(FakeSupabase):
    def __init__(self):
        super().__init__()
        self.tables["profiles"][0].update({"email": "admin@test.local", "full_name": "ผู้ดูแล"})
        self.tables["profiles"].append({"user_id": OTHER, "org_id": ORG_ID, "role": "drafter", "full_name": "ผู้ทดสอบ",
                                        "position": "", "email": "drafter@test.local"})
        self.tables["documents"].append({"id": DOC_ID, "org_id": ORG_ID, "subject": "ขอเชิญเป็นเจ้าภาพร่วม", "kind": "internal_memo"})
        self.tables["feedback"] = []
        self.missing = False

    def _table(self, request, table, query):
        if self.missing and table == "feedback":
            return httpx.Response(404, json={"code": "PGRST205", "message": "Could not find the table 'public.feedback'"})
        return super()._table(request, table, query)


@pytest.fixture
def fake(tmp_path, monkeypatch):
    fake = FeedbackFake()
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


def test_drafter_sends_feedback_linked_to_document(fake, client):
    r = client.post("/api/v1/feedback", headers=_h(fake, OTHER), json={
        "rating": "minor", "category": "content", "message": "  ภาคความประสงค์อ้างข้อผิด  ",
        "document_id": DOC_ID, "page": "editor",
        "context": {"doc_type": "internal", "unit_key": "culture-sports-bureau", "steps": ["ร่าง · เหลือ 2 จุด"]},
    })
    assert r.status_code == 201, r.text
    row = fake.tables["feedback"][0]
    assert row["user_id"] == OTHER and row["org_id"] == ORG_ID and row["document_id"] == DOC_ID
    assert row["message"] == "ภาคความประสงค์อ้างข้อผิด" and row["context"]["unit_key"] == "culture-sports-bureau"


def test_local_document_id_is_not_linked(fake, client):
    r = client.post("/api/v1/feedback", headers=_h(fake), json={
        "rating": "ok", "document_id": "local-123", "context": {"local_id": "local-123"}})
    assert r.status_code == 201
    row = fake.tables["feedback"][0]
    assert row["document_id"] is None and row["context"]["local_id"] == "local-123"


def test_validation(fake, client):
    h = _h(fake)
    assert client.post("/api/v1/feedback", headers=h, json={"rating": "broken"}).status_code == 400   # ต้องเล่าปัญหา
    assert client.post("/api/v1/feedback", headers=h, json={"rating": "idea"}).status_code == 400
    assert client.post("/api/v1/feedback", headers=h, json={"rating": "great", "message": "x"}).status_code == 422
    assert client.post("/api/v1/feedback", headers=h, json={"rating": "minor", "category": "x", "message": "x"}).status_code == 422
    assert client.post("/api/v1/feedback", headers=h, json={"rating": "minor", "message": "x" * 4001}).status_code == 422


def test_list_admin_sees_all_drafter_sees_own(fake, client):
    client.post("/api/v1/feedback", headers=_h(fake, OTHER), json={"rating": "major", "message": "ส่งออก Word ฟอนต์เพี้ยน",
                                                                    "category": "export", "document_id": DOC_ID})
    client.post("/api/v1/feedback", headers=_h(fake), json={"rating": "idea", "message": "อยากได้ปุ่มคัดลอก"})
    admin = client.get("/api/v1/feedback", headers=_h(fake)).json()
    assert admin["admin"] is True and len(admin["items"]) == 2 and admin["counts"]["new"] == 2
    mine = next(i for i in admin["items"] if i["user_id"] == OTHER)
    assert mine["reporter"] == "ผู้ทดสอบ" and mine["document_subject"] == "ขอเชิญเป็นเจ้าภาพร่วม"
    own = client.get("/api/v1/feedback", headers=_h(fake, OTHER)).json()
    assert own["admin"] is False and [i["user_id"] for i in own["items"]] == [OTHER]


def test_only_admin_changes_status(fake, client):
    client.post("/api/v1/feedback", headers=_h(fake, OTHER), json={"rating": "minor", "message": "x"})
    fid = fake.tables["feedback"][0]["id"]
    assert client.patch(f"/api/v1/feedback/{fid}", headers=_h(fake, OTHER), json={"status": "done"}).status_code == 403
    assert client.patch(f"/api/v1/feedback/{fid}", headers=_h(fake), json={"status": "archived"}).status_code == 422
    r = client.patch(f"/api/v1/feedback/{fid}", headers=_h(fake), json={"status": "done"})
    assert r.status_code == 200 and fake.tables["feedback"][0]["status"] == "done"
    assert client.get("/api/v1/feedback?status=done", headers=_h(fake)).json()["counts"]["done"] == 1


def test_missing_table_explains_migration(fake, client):
    fake.missing = True
    r = client.post("/api/v1/feedback", headers=_h(fake), json={"rating": "ok"})
    assert r.status_code == 503 and "20261124000016_feedback.sql" in r.json()["detail"]


def test_local_mode_has_no_feedback(client, tmp_path):
    app.dependency_overrides[get_settings] = lambda: Settings(upload_dir=tmp_path / "u", registry_db_path=tmp_path / "r.db")
    try:
        assert client.post("/api/v1/feedback", json={"rating": "ok"}).status_code == 404
    finally:
        app.dependency_overrides.clear()


def test_trim_context_limits_size():
    out = _trim_context({"steps": ["ก" * 1000] * 5, "note": "ข" * 2000, "n": 3})
    assert len(out["note"]) == 500 and all(len(s) == 300 for s in out["steps"]) and out["n"] == 3
    out = _trim_context({"steps": ["ก" * 1000] * 50, "note": "ข"})        # เกินขนาด = ทิ้งรายการ เก็บค่าธรรมดา
    assert "steps" not in out and out["note"] == "ข" and out["truncated"] is True

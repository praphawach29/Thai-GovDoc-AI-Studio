"""
Step 4: ปิดช่องโหว่และบั๊กที่พบก่อนนำขึ้นคลาวด์
(ชื่อไฟล์อัปโหลด, ออกเลขซ้ำ, ทะเบียนถูกเขียนทับ, เวลาประเทศไทย, HTML injection, CORS)
"""

import concurrent.futures
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from core import api, thai_date
from core.pdf_exporter import generate_govdoc_html
from core.registry import DocumentRegistry, DuplicateRegistryEntry, OutgoingRecord
from core.templates_library import PRESET_TEMPLATES


@pytest.fixture
def client():
    return TestClient(api.app)


# ---------------------------------------------------------------- อัปโหลดไฟล์
def test_extract_ignores_client_filename_path(client, tmp_path, monkeypatch):
    tmp_path = tmp_path / "uploads"
    tmp_path.mkdir()
    monkeypatch.setattr(api, "uploads_dir", tmp_path)
    res = client.post(
        "/api/v1/extract",
        files={"file": ("../../evil.txt", "ด้วยกรมทดสอบขอเชิญประชุม".encode("utf-8"), "text/plain")},
    )
    assert res.status_code == 200
    saved = list(tmp_path.iterdir())
    assert len(saved) == 1 and saved[0].parent == tmp_path
    assert saved[0].name != "evil.txt" and saved[0].suffix == ".txt"
    assert not (tmp_path.parent / "evil.txt").exists()
    assert res.json()["source_filename"] == "evil.txt"


def test_extract_rejects_unknown_type_and_oversize(client, tmp_path, monkeypatch):
    tmp_path = tmp_path / "uploads"
    tmp_path.mkdir()
    monkeypatch.setattr(api, "uploads_dir", tmp_path)
    assert client.post("/api/v1/extract", files={"file": ("x.exe", b"MZ", "application/octet-stream")}).status_code == 400
    monkeypatch.setattr(api, "_MAX_UPLOAD_BYTES", 10)
    assert client.post("/api/v1/extract", files={"file": ("x.txt", b"a" * 11, "text/plain")}).status_code == 413
    assert list(tmp_path.iterdir()) == []


# ---------------------------------------------------------------- ทะเบียน/เลขที่
def test_concurrent_numbering_never_duplicates(tmp_path):
    reg = DocumentRegistry(db_path=str(tmp_path / "r.db"))
    with concurrent.futures.ThreadPoolExecutor(16) as pool:
        numbers = list(pool.map(lambda _: reg.get_next_doc_number("TEST/"), range(200)))
    assert len(set(numbers)) == 200


def test_get_next_number_endpoint_does_not_consume(client):
    first = client.get("/api/v1/registry/next-number", params={"prefix": "ทส/"}).json()["doc_number"]
    second = client.get("/api/v1/registry/next-number", params={"prefix": "ทส/"}).json()["doc_number"]
    assert first == second == "ทส/1"
    reserved = client.post("/api/v1/registry/reserve", json={"prefix": "ทส/", "subject": "ทดสอบ"}).json()
    assert reserved["reserved_number"] == "ทส/1"
    assert client.get("/api/v1/registry/next-number", params={"prefix": "ทส/"}).json()["doc_number"] == "ทส/2"


def test_numbering_restarts_each_calendar_year(tmp_path, monkeypatch):
    reg = DocumentRegistry(db_path=str(tmp_path / "r.db"))
    monkeypatch.setattr(DocumentRegistry, "get_current_be_year", staticmethod(lambda: 2569))
    assert reg.get_next_doc_number("ทส/") == "ทส/1"
    assert reg.get_next_doc_number("ทส/") == "ทส/2"
    monkeypatch.setattr(DocumentRegistry, "get_current_be_year", staticmethod(lambda: 2570))
    assert reg.get_next_doc_number("ทส/") == "ทส/1"


def test_registry_never_overwrites_existing_entry(tmp_path, client):
    reg = DocumentRegistry(db_path=str(tmp_path / "r.db"))
    rec = OutgoingRecord(doc_number="ทส/9", doc_type="external", subject="ฉบับแรก",
                         recipient="กรมทดสอบ", doc_date="1 มกราคม 2570")
    reg.register_outgoing(rec)
    with pytest.raises(DuplicateRegistryEntry):
        reg.register_outgoing(rec.model_copy(update={"subject": "ฉบับปลอม"}))
    assert [r["subject"] for r in reg.list_outgoing()] == ["ฉบับแรก"]

    body = rec.model_dump()
    assert client.post("/api/v1/registry/outgoing", json=body).status_code == 200
    assert client.post("/api/v1/registry/outgoing", json=body).status_code == 409


# ---------------------------------------------------------------- เวลาประเทศไทย
def test_dates_follow_bangkok_time_not_server_time(monkeypatch):
    # 31 ธ.ค. 2026 เวลา 18:00 UTC = 1 ม.ค. 2027 เวลา 01:00 น. ในประเทศไทย
    fixed_utc = datetime(2026, 12, 31, 18, 0, tzinfo=timezone.utc)

    class FrozenDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return fixed_utc.astimezone(tz) if tz else fixed_utc.replace(tzinfo=None)

    monkeypatch.setattr(thai_date, "datetime", FrozenDatetime)
    assert thai_date.format_thai_date() == "1 มกราคม 2570"
    assert thai_date.current_be_year() == 2570
    assert DocumentRegistry.get_current_be_year() == 2570


# ---------------------------------------------------------------- HTML / API
@pytest.mark.parametrize("template_id", ["speaker_request", "procurement_approval"])
def test_html_pdf_escapes_user_text(template_id):
    doc = PRESET_TEMPLATES[template_id].schema.model_copy(deep=True)
    doc.subject = 'ทดสอบ <iframe src="file:///etc/passwd"></iframe> & "อ้าง"'
    html = generate_govdoc_html(doc)
    assert "<iframe" not in html
    assert "&lt;iframe" in html
    assert "&amp;amp;" not in html  # ไม่ escape ซ้ำสองชั้น


def test_api_ignores_server_signature_path(client):
    doc = PRESET_TEMPLATES["speaker_request"].schema.model_copy(deep=True)
    doc.signature_image_path = "/etc/passwd"
    res = client.post("/api/v1/export/typst", json=doc.model_dump(mode="json"))
    assert res.status_code == 200
    assert "/etc/passwd" not in res.text


def test_cors_rejects_unknown_origin(client):
    res = client.get("/api/v1/health", headers={"Origin": "https://evil.example"})
    assert "access-control-allow-origin" not in res.headers
    ok = client.get("/api/v1/health", headers={"Origin": "http://localhost:8600"})
    assert ok.headers.get("access-control-allow-origin") == "http://localhost:8600"

"""ทดสอบ endpoint ของหน้าเว็บ GovDoc Studio (web/studio)"""

from fastapi.testclient import TestClient

from server.main import app

client = TestClient(app)


def test_draft_from_prompt_returns_document_and_checks():
    res = client.post("/api/v1/studio/draft", data={
        "prompt": "ร่างบันทึกข้อความขออนุมัติเป็นเจ้าภาพร่วมจัดการแข่งขันกีฬาเยาวชน",
        "doc_type": "internal",
        "urgency": "very_urgent",
    })
    assert res.status_code == 200
    body = res.json()
    doc = body["document"]
    assert doc["doc_type"] == "internal"
    assert doc["urgency"] == "very_urgent"
    # บันทึกข้อความต้องมี memo_* ให้หน้าแก้ไขใช้ชุดเดียวกับ exporter
    assert doc["memo_intro"] and doc["memo_request"]
    assert [s["key"] for s in body["steps"]] == ["extract", "classify", "draft"]
    assert "placeholders" in body["check"] and "lint" in body["check"]
    assert "วันที่" not in doc["doc_date"]


def test_secret_document_blocks_cloud_ai():
    res = client.post("/api/v1/studio/draft", data={"prompt": "ขอความอนุเคราะห์ใช้สถานที่", "secret": "secret"})
    assert res.status_code == 200
    body = res.json()
    assert body["cloud_ai_blocked"] is True
    assert body["document"]["secret"] == "secret"


def test_draft_requires_prompt_or_file():
    assert client.post("/api/v1/studio/draft", data={"prompt": "   "}).status_code == 400


def test_upload_uses_generated_filename(test_settings):
    uploads_dir = test_settings.upload_dir
    uploads_dir.mkdir(parents=True, exist_ok=True)
    before = set(uploads_dir.iterdir())
    res = client.post(
        "/api/v1/studio/draft",
        files={"file": ("../../evil.txt", "ด้วยสมาคมกีฬาขอความอนุเคราะห์ใช้สนามกีฬา".encode("utf-8"), "text/plain")},
    )
    assert res.status_code == 200
    created = set(uploads_dir.iterdir()) - before
    assert all(p.parent == uploads_dir and p.name != "evil.txt" for p in created)
    assert res.json()["context"]["source_filename"] == "evil.txt"
    for p in created:
        p.unlink()


def test_upload_rejects_unsupported_type():
    res = client.post("/api/v1/studio/draft", files={"file": ("a.exe", b"MZ", "application/octet-stream")})
    assert res.status_code == 400


def test_blank_and_pdf_export():
    for doc_type in ("internal", "external"):
        doc = client.post("/api/v1/studio/blank", json={"doc_type": doc_type}).json()
        assert doc["doc_type"] == doc_type
        check = client.post("/api/v1/studio/check", json=doc).json()
        assert len(check["placeholders"]) > 0
        pdf = client.post("/api/v1/export/pdf", json=doc)
        assert pdf.status_code == 200
        assert pdf.content.startswith(b"%PDF-")
        assert b"THSarabunPSK" in pdf.content          # TH SarabunIT๙ (ชื่อภายในไฟล์)


def test_templates_list_and_get():
    items = client.get("/api/v1/studio/templates").json()
    assert items and {"id", "title", "category", "doc_type"} <= set(items[0])
    doc = client.get(f"/api/v1/studio/templates/{items[0]['id']}").json()
    assert doc["subject"]
    assert client.get("/api/v1/studio/templates/does-not-exist").status_code == 404


def test_studio_pages_are_served():
    assert client.get("/studio/").status_code == 200
    assert client.get("/studio/editor.html").status_code == 200
    assert client.get("/assets/garuda.svg").status_code == 200

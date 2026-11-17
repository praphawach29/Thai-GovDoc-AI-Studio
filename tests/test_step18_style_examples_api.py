"""
Step 18 (API): คลังตัวอย่างของหน่วย — อัปโหลด/อ่านทีละหน้า/นี่คือฉบับจริง/ลบ และการใส่ few-shot ตอนร่าง
"""

import io

import httpx
import pytest
from fastapi.testclient import TestClient

from core import llm_drafter
from core.models import DocType
from server import auth as server_auth
from server import supabase as server_supabase
from server.main import app
from server.settings import Settings, get_settings
from tests.fake_supabase import ORG_ID, PUBLISHABLE_KEY, URL, FakeSupabase
from tests.test_step18_style_examples import LETTER, MEMO


class ExamplesFake(FakeSupabase):
    """เพิ่มตาราง style_examples และ DELETE แถว (ส่วนที่ fake หลักยังไม่มี)"""

    def __init__(self):
        super().__init__()
        self.tables["style_examples"] = []

    def _table(self, request, table, query):
        if request.method == "DELETE":
            target = {k: v[3:] for k, v in query.items() if v.startswith("eq.")}
            rows = self.tables[table]
            self.tables[table] = [r for r in rows if not all(str(r.get(k)) == v for k, v in target.items())]
            return httpx.Response(204)
        return super()._table(request, table, query)


@pytest.fixture
def fake(tmp_path, monkeypatch):
    fake = ExamplesFake()
    monkeypatch.setattr(server_supabase, "transport_factory", fake.transport)
    server_auth._jwks_cache.clear()
    app.dependency_overrides[get_settings] = lambda: Settings(
        upload_dir=tmp_path / "uploads", registry_db_path=tmp_path / "r.db",
        supabase_url=URL, supabase_publishable_key=PUBLISHABLE_KEY, gemini_api_key="k",
    )
    yield fake
    app.dependency_overrides.clear()


@pytest.fixture
def client():
    return TestClient(app)


def _scan_pdf(pages=2):
    from PIL import Image
    imgs = [Image.new("RGB", (300, 420), "white") for _ in range(pages)]
    buf = io.BytesIO()
    imgs[0].save(buf, format="PDF", save_all=True, append_images=imgs[1:])
    return buf.getvalue()


def _docx(text):
    from docx import Document
    d = Document()
    for line in text.splitlines():
        d.add_paragraph(line)
    buf = io.BytesIO()
    d.save(buf)
    return buf.getvalue()


def _upload(fake, client, h, filename, data):
    r = client.post("/api/v1/examples/upload-url", json={"filename": filename, "size_bytes": len(data)}, headers=h)
    assert r.status_code == 200, r.text
    path = r.json()["path"]
    assert path.startswith(f"{ORG_ID}/examples/")
    fake.storage[f"sources/{path}"] = data
    return path


def test_upload_docx_example_list_and_delete(fake, client):
    h = {"Authorization": f"Bearer {fake.token()}"}
    path = _upload(fake, client, h, "ตอบรับ.docx", _docx(LETTER))
    r = client.post("/api/v1/examples", json={"path": path, "filename": "ตอบรับ.docx"}, headers=h)
    assert r.status_code == 201, r.text
    ex = r.json()
    assert ex["doc_type"] == "external" and ex["subject"] == "ตอบรับการขอใช้สนามกีฬา"
    assert ex["part_purpose"] == "จึงเรียนมาเพื่อโปรดทราบ"
    stored = fake.tables["style_examples"][0]
    assert stored["origin"] == "upload" and "สนาม" in stored["keywords"] and stored["org_id"] == ORG_ID

    listed = client.get("/api/v1/examples", headers=h).json()
    assert [x["id"] for x in listed] == [ex["id"]] and "keywords" not in listed[0]
    assert client.get(f"/api/v1/examples/{ex['id']}/file-url", headers=h).status_code == 200

    r = client.delete(f"/api/v1/examples/{ex['id']}", headers=h)
    assert r.status_code == 200 and fake.tables["style_examples"] == []
    assert f"sources/{path}" not in fake.storage
    assert client.delete(f"/api/v1/examples/{ex['id']}", headers=h).status_code == 404


def test_scanned_pdf_needs_ocr_then_page_texts(fake, client, monkeypatch):
    h = {"Authorization": f"Bearer {fake.token()}"}
    path = _upload(fake, client, h, "บันทึก.pdf", _scan_pdf(2))
    r = client.post("/api/v1/examples", json={"path": path, "filename": "บันทึก.pdf"}, headers=h)
    assert r.status_code == 200 and r.json()["needs_ocr"] is True and r.json()["page_count"] == 2
    assert fake.tables["style_examples"] == []

    from PIL import Image
    jpg = io.BytesIO()
    Image.new("RGB", (100, 140), "white").save(jpg, format="JPEG")
    monkeypatch.setattr(llm_drafter, "_ocr_gemini", lambda images, config, timeout: MEMO)
    r = client.post("/api/v1/examples/ocr-page", data={"page": "1"},
                    files={"image": ("p.jpg", jpg.getvalue(), "image/jpeg")}, headers=h)
    assert r.status_code == 200 and "บันทึกข้อความ" in r.json()["text"]

    bad = client.post("/api/v1/examples", json={"path": path, "filename": "x.pdf", "page_texts": ["a"]}, headers=h)
    assert bad.status_code == 400
    r = client.post("/api/v1/examples", json={"path": path, "filename": "บันทึก.pdf", "page_texts": [MEMO, ""]}, headers=h)
    assert r.status_code == 201, r.text
    assert r.json()["doc_type"] == "internal" and r.json()["page_count"] == 2


def test_unreadable_and_bad_paths(fake, client):
    h = {"Authorization": f"Bearer {fake.token()}"}
    assert client.post("/api/v1/examples/upload-url", json={"filename": "x.jpg", "size_bytes": 5}, headers=h).status_code == 400
    bad = client.post("/api/v1/examples", json={"path": f"{ORG_ID}/legal/{'a' * 32}.pdf", "filename": "x.pdf"}, headers=h)
    assert bad.status_code == 400
    path = _upload(fake, client, h, "ว่าง.docx", _docx("สวัสดี"))
    r = client.post("/api/v1/examples", json={"path": path, "filename": "ว่าง.docx"}, headers=h)
    assert r.status_code == 422 and f"sources/{path}" not in fake.storage


def _memo_doc(**kw):
    from core.studio import create_blank_document, normalize_for_editor
    doc = normalize_for_editor(create_blank_document(DocType.INTERNAL))
    doc.subject = "ขอความอนุเคราะห์ใช้สนามกีฬาจัดการแข่งขันฟุตบอล"
    doc.memo_intro = "๑. สมาคมกีฬาฟุตบอลแห่งประเทศไทย ได้มีหนังสือขอความอนุเคราะห์ใช้สนามกีฬาไทย-ญี่ปุ่น"
    doc.memo_facts = "๑. การแข่งขันฟุตบอลเยาวชน"
    doc.memo_consideration = "กลุ่มงานส่งเสริมกีฬาพิจารณาแล้ว เห็นควรอนุญาตให้ใช้สนามกีฬา"
    for k, v in kw.items():
        setattr(doc, k, v)
    return doc


def test_mark_document_as_final_creates_then_updates(fake, client):
    h = {"Authorization": f"Bearer {fake.token()}"}
    doc = _memo_doc()
    r = client.post("/api/v1/documents", json={"doc": doc.model_dump(mode="json"), "workspace": {}}, headers=h)
    doc_id = r.json()["id"]
    r = client.post("/api/v1/examples/from-document", json={"document_id": doc_id}, headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["created"] is True and r.json()["example"]["origin"] == "document"
    # กดซ้ำหลังแก้ = อัปเดตตัวเดิม
    doc.subject = "ขอใช้สนามกีฬา (แก้แล้ว)"
    client.patch(f"/api/v1/documents/{doc_id}", json={"doc": doc.model_dump(mode="json"), "workspace": {}}, headers=h)
    r = client.post("/api/v1/examples/from-document", json={"document_id": doc_id}, headers=h)
    assert r.json()["created"] is False and len(fake.tables["style_examples"]) == 1
    assert fake.tables["style_examples"][0]["subject"] == "ขอใช้สนามกีฬา (แก้แล้ว)"
    assert client.get(f"/api/v1/examples?document_id={doc_id}", headers=h).json()[0]["document_id"] == doc_id

    # ร่างที่ยังมีจุดต้องระบุ เก็บเป็นตัวอย่างไม่ได้
    rough = _memo_doc(memo_facts="[✏️ ระบุข้อเท็จจริง]")
    rid = client.post("/api/v1/documents", json={"doc": rough.model_dump(mode="json"), "workspace": {}}, headers=h).json()["id"]
    assert client.post("/api/v1/examples/from-document", json={"document_id": rid}, headers=h).status_code == 422


def test_draft_uses_closest_examples_as_few_shot(fake, client, monkeypatch):
    h = {"Authorization": f"Bearer {fake.token()}"}
    path = _upload(fake, client, h, "บันทึก.docx", _docx(MEMO))
    client.post("/api/v1/examples", json={"path": path, "filename": "บันทึก.docx"}, headers=h)
    other = (MEMO.replace("ขอความอนุเคราะห์ใช้สนามกีฬาจัดการแข่งขันฟุตบอลเยาวชน", "ขออนุมัติจัดซื้อวัสดุสำนักงาน")
             .replace("สนามกีฬา", "พัสดุ").replace("ฟุตบอล", "ครุภัณฑ์").replace("การแข่งขัน", "การจัดซื้อ"))
    path = _upload(fake, client, h, "อื่น.docx", _docx(other))
    client.post("/api/v1/examples", json={"path": path, "filename": "อื่น.docx"}, headers=h)
    assert len(fake.tables["style_examples"]) == 2

    prompts = []

    def fake_gemini(prompt, config, timeout):
        prompts.append(prompt)
        return llm_drafter.DraftContent(
            subject="ขอใช้สนามกีฬา", memo_intro="๑. สมาคมวอลเลย์บอล ได้มีหนังสือ ลงวันที่ [วันที่]",
            memo_facts="๑. ผู้ประสาน [ชื่อบุคคล]", memo_consideration="พิจารณาแล้ว เห็นควรอนุญาต",
            paragraph_reason="", paragraph_details="", paragraph_purpose="", reference="", source_summary="")

    monkeypatch.setattr(llm_drafter, "_call_gemini", fake_gemini)
    r = client.post("/api/v1/studio/draft", data={
        "prompt": "สมาคมกีฬาวอลเลย์บอลขอความอนุเคราะห์ใช้สนามกีฬาไทย-ญี่ปุ่นจัดการแข่งขัน ร่างบันทึกข้อความเสนอ"}, headers=h)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["style_examples"][0]["subject"] == "ขอความอนุเคราะห์ใช้สนามกีฬาจัดการแข่งขันฟุตบอลเยาวชน"
    assert any(s["key"] == "style" for s in body["steps"])
    p = prompts[0]
    assert '<example n="1" type="บันทึกข้อความ">' in p
    assert "สมชาย" not in p and "๑๒๓๔" not in p                     # ข้อเท็จจริงของฉบับเก่าถูกปิด
    assert p.index("<example") < p.index("<source>")                  # เรื่องใหม่อยู่ท้าย
    doc = body["document"]
    assert "[✏️ ระบุวันที่]" in doc["memo_intro"] and "[✏️ ระบุชื่อ]" in doc["memo_facts"]   # ส่วนที่ปิดไว้ไม่หลุดเข้าร่าง


def test_draft_without_examples_table_still_works(fake, client, monkeypatch):
    h = {"Authorization": f"Bearer {fake.token()}"}
    orig = ExamplesFake._table

    def missing(self, request, table, query):
        if table == "style_examples":
            return httpx.Response(404, json={"code": "PGRST205", "message": "Could not find the table"})
        return orig(self, request, table, query)

    monkeypatch.setattr(ExamplesFake, "_table", missing)
    monkeypatch.setattr(llm_drafter, "_call_gemini", lambda *a: (_ for _ in ()).throw(RuntimeError("x")))
    r = client.post("/api/v1/studio/draft", data={"prompt": "ร่างบันทึกข้อความขอใช้สนามกีฬา"}, headers=h)
    assert r.status_code == 200 and r.json()["style_examples"] == []
    assert client.get("/api/v1/examples", headers=h).status_code == 503


def test_local_mode_has_no_examples():
    assert TestClient(app).get("/api/v1/examples").status_code == 404

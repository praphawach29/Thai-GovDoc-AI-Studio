"""
Step 21: ทะเบียนรับ-ส่ง และออกเลขที่หนังสือ
- core: รูปแบบเลขที่จากช่อง "ที่", ค่าที่ลงทะเบียน, ค้นหา, แบบทะเบียน Excel/PDF
- API (Supabase จำลอง): ออกเลขจากหน้าแก้ไข, ใช้เลขที่จอง, ยกเลิก, ลงรับ, เชื่อมหนังสือตอบ, audit, ส่งออก
ฐานข้อมูลจริง (atomic/ไม่ซ้ำ/ห้ามลบ) ทดสอบที่ supabase/tests/run_local.sh
"""

import io
import uuid
import zipfile
from xml.etree import ElementTree

import pytest
from fastapi.testclient import TestClient

from core.models import DocType, HANDWRITE_GAP
from core.register_export import (
    build_incoming_sheet, build_outgoing_sheet, parse_timestamp, sheet_to_pdf, sheet_to_xlsx,
)
from core.registry import (
    NumberTemplate, issue_draft_for, recipient_from_salutation, search_rows, split_number_template,
)
from core.studio import create_blank_document
from server import auth as server_auth
from server import supabase as server_supabase
from server.main import app
from server.settings import Settings, get_settings
from tests.fake_supabase import ORG_ID, PUBLISHABLE_KEY, URL, USER_ID, FakeSupabase


# ---------------------------------------------------------------- core: รูปแบบเลขที่
@pytest.mark.parametrize("text, expected", [
    ("กท 1205/" + HANDWRITE_GAP, ("กท 1205/", "", False)),
    (HANDWRITE_GAP + "/2569", ("", "/2569", False)),
    ("......../๒๕๖๙", ("", "/๒๕๖๙", False)),
    ("ที่ กท 1205/[✏️ ระบุเลขที่]", ("กท 1205/", "", False)),
    ("กท ๑๒๓๔/ว ___", ("กท ๑๒๓๔/", "", True)),
    ("กท 1205/", ("กท 1205/", "", False)),
])
def test_split_number_template(text, expected):
    t = split_number_template(text)
    assert (t.prefix, t.suffix, t.is_circular) == expected


@pytest.mark.parametrize("text", ["กท 1205/45", "12/2569", "", "___"])
def test_split_number_template_none_when_numbered_or_no_code(text):
    assert split_number_template(text) is None


def test_template_formats_with_matching_digits():
    assert NumberTemplate(prefix="กท ๑๒๓๔/").format(12) == "กท ๑๒๓๔/๑๒"
    assert NumberTemplate(prefix="กท 1205/").format(12) == "กท 1205/12"
    assert NumberTemplate(suffix="/๒๕๖๙").format(3) == "๓/๒๕๖๙"
    assert NumberTemplate(prefix="กท ๑๒๓๔/", is_circular=True).format(1) == "กท ๑๒๓๔/ว ๑"


def test_recipient_from_salutation():
    assert recipient_from_salutation("เรียน ผู้อำนวยการสำนัก") == "ผู้อำนวยการสำนัก"
    assert recipient_from_salutation("กราบเรียน นายกรัฐมนตรี") == "นายกรัฐมนตรี"
    assert recipient_from_salutation("เรียน [✏️ ระบุ]") == ""


def _doc(**kw):
    doc = create_blank_document(DocType.EXTERNAL)
    for k, v in kw.items():
        setattr(doc, k, v)
    return doc


def test_issue_draft_uses_document_fields_and_today_for_blank_date():
    doc = _doc(doc_number="กท 1205/" + HANDWRITE_GAP, subject="ขอความอนุเคราะห์", salutation="เรียน อธิบดีกรม ค",
               doc_date=HANDWRITE_GAP + "พฤศจิกายน 2569", dept_name="กองการกีฬา")
    d = issue_draft_for(doc, today="17 พฤศจิกายน 2569")
    assert d.template.prefix == "กท 1205/"
    assert (d.subject, d.to_recipient, d.doc_date, d.from_unit) == ("ขอความอนุเคราะห์", "อธิบดีกรม ค", "17 พฤศจิกายน 2569", "กองการกีฬา")
    numbered = issue_draft_for(_doc(doc_number="กท 1205/45", doc_date="16 พฤศจิกายน 2569"))
    assert numbered.template is None and numbered.current_number == "กท 1205/45"
    assert numbered.doc_date == "16 พฤศจิกายน 2569"


def test_search_rows_ignores_thai_arabic_digits_and_spaces():
    rows = [{"doc_number": "กท 1205/12", "subject": "ขอใช้สนาม"}, {"doc_number": "กท 1205/13", "subject": "ประชุม"}]
    assert search_rows(rows, "๑๒๐๕/๑๒", ["doc_number", "subject"]) == [rows[0]]
    assert search_rows(rows, "กท1205 ประชุม", ["doc_number", "subject"]) == [rows[1]]
    assert search_rows(rows, "  ", ["doc_number"]) == rows


# ---------------------------------------------------------------- core: แบบทะเบียน
_OUT = [
    {"id": 2, "reg_no": 2, "year_be": 2569, "doc_number": "กท 1205/2", "doc_date": "16 พฤศจิกายน 2569",
     "from_unit": "กองการกีฬา", "to_recipient": "กรม ค", "subject": "ตอบ <หนังสือ> & ขอบคุณ", "status": "issued",
     "issued_at": "2026-11-16T03:30:00.123456789+00:00", "incoming_id": 5},
    {"id": 1, "reg_no": 1, "year_be": 2569, "doc_number": "กท 1205/1", "status": "cancelled", "cancel_reason": "พิมพ์ผิด",
     "cancelled_at": "2026-11-16T04:00:00Z", "cancelled_by": "u1", "created_at": "2026-11-15T20:00:00Z"},
    {"id": 3, "reg_no": 3, "year_be": 2569, "doc_number": "กท 1205/3", "status": "reserved", "created_by": "u1",
     "created_at": "2026-11-17T02:00:00Z"},
]


def test_timestamps_are_bangkok_time():
    assert parse_timestamp("2026-11-15T20:00:00Z").day == 16      # 03.00 น. วันที่ ๑๖ ตามเวลาไทย
    assert parse_timestamp("2026-11-16T03:30:00.123456789+00:00").hour == 10
    assert parse_timestamp("ไม่ใช่วันที่") is None


def test_outgoing_sheet_follows_regulation_form():
    sheet = build_outgoing_sheet(_OUT, org_name="หน่วยงานทดสอบ", year_be=2569,
                                 incoming_by_id={5: {"reg_no": 3, "year_be": 2569}}, names={"u1": "นาย ก"})
    assert sheet.headers == ["เลขทะเบียนส่ง", "ที่", "ลงวันที่", "จาก", "ถึง", "เรื่อง", "การปฏิบัติ", "หมายเหตุ"]
    assert [g.heading for g in sheet.groups] == ["วันที่ ๑๖ พฤศจิกายน ๒๕๖๙", "วันที่ ๑๗ พฤศจิกายน ๒๕๖๙"]
    first, second = sheet.groups[0].rows
    assert first[0] == "๑" and first[7].startswith("ยกเลิกเลข: พิมพ์ผิด (นาย ก")     # เลขยกเลิกยังอยู่พร้อมเหตุผล
    assert second[1] == "กท ๑๒๐๕/๒" and second[6] == "ตอบหนังสือรับเลข ๓/๒๕๖๙"
    assert sheet.groups[1].rows[0][6] == "จองเลข โดย นาย ก"
    assert build_outgoing_sheet(_OUT, thai_digits=False).groups[0].rows[1][1] == "กท 1205/2"


def test_incoming_sheet_shows_time_and_reply():
    rows = [{"id": 7, "reg_no": 4, "year_be": 2569, "received_at": "2026-11-16T02:15:00Z", "source_doc_number": "ศธ 04/7",
             "source_doc_date": "1 พฤศจิกายน 2569", "from_org": "กรม ค", "to_unit": "กลุ่มงาน", "subject": "ขอข้อมูล"}]
    sheet = build_incoming_sheet(rows, replies_by_incoming={7: [
        {"status": "cancelled", "doc_number": "กท 1205/1"},
        {"status": "issued", "doc_number": "กท 1205/2", "doc_date": "16 พฤศจิกายน 2569"}]})
    row = sheet.groups[0].rows[0]
    assert sheet.headers[0] == "เลขทะเบียนรับ" and sheet.title == "ทะเบียนหนังสือรับ"
    assert row[6] == "ตอบแล้ว ที่ กท ๑๒๐๕/๒ ลว. ๑๖ พฤศจิกายน ๒๕๖๙"
    assert row[7] == "รับเวลา ๐๙.๑๕ น."


def test_xlsx_is_valid_workbook_with_escaped_text():
    data = sheet_to_xlsx(build_outgoing_sheet(_OUT, org_name="หน่วยงาน", year_be=2569))
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        assert zf.testzip() is None
        names = set(zf.namelist())
        assert {"[Content_Types].xml", "xl/workbook.xml", "xl/worksheets/sheet1.xml", "xl/styles.xml"} <= names
        sheet = ElementTree.fromstring(zf.read("xl/worksheets/sheet1.xml"))   # XML ถูกต้อง (escape แล้ว)
        ElementTree.fromstring(zf.read("xl/workbook.xml"))
        text = zf.read("xl/worksheets/sheet1.xml").decode()
    assert "ตอบ &lt;หนังสือ&gt; &amp; ขอบคุณ" in text
    assert 'orientation="landscape"' in text and "TH SarabunIT๙" in zipfile.ZipFile(io.BytesIO(data)).read("xl/styles.xml").decode()
    ns = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
    assert len(sheet.find(f"{ns}sheetData")) == 3 + 2 + 3     # ชื่อ+หน่วยงาน+หัวตาราง, หัววัน ๒ กลุ่ม, ๓ แถว


def test_pdf_register_compiles_landscape():
    pypdf = pytest.importorskip("pypdf")
    data = sheet_to_pdf(build_outgoing_sheet(_OUT, org_name="หน่วยงาน", year_be=2569))
    page = pypdf.PdfReader(io.BytesIO(data)).pages[0]
    assert float(page.mediabox.width) > float(page.mediabox.height)
    assert len(pypdf.PdfReader(io.BytesIO(data)).pages) == 1


def test_pdf_register_handles_empty_year():
    assert sheet_to_pdf(build_incoming_sheet([], year_be=2569)).startswith(b"%PDF")


# ---------------------------------------------------------------- API (Supabase จำลอง)
@pytest.fixture
def fake(tmp_path, monkeypatch):
    fake = FakeSupabase()
    monkeypatch.setattr(server_supabase, "transport_factory", fake.transport)
    server_auth._jwks_cache.clear()
    settings = Settings(upload_dir=tmp_path / "uploads", registry_db_path=tmp_path / "r.db",
                        supabase_url=URL, supabase_publishable_key=PUBLISHABLE_KEY)
    app.dependency_overrides[get_settings] = lambda: settings
    yield fake
    app.dependency_overrides.pop(get_settings, None)


@pytest.fixture
def client():
    return TestClient(app)


def _h(fake):
    return {"Authorization": f"Bearer {fake.token()}"}


def _add_doc(fake, doc_number="กท 1205/" + HANDWRITE_GAP, source=None, **fields):
    doc = _doc(doc_number=doc_number, subject=fields.pop("subject", "ขอความอนุเคราะห์"),
               salutation="เรียน อธิบดีกรม ค", dept_name="กองการกีฬา", **fields)
    row = {"id": str(uuid.uuid4()), "org_id": ORG_ID, "status": "draft", "doc_number": None,
           "workspace": {"doc": doc.model_dump(mode="json"), **({"sourceFileId": source} if source else {})}}
    fake.tables["documents"].append(row)
    return row


def test_issue_button_numbers_document_and_registers(fake, client):
    doc = _add_doc(fake, subject="ขอใช้สนามกีฬา")
    status = client.get(f"/api/v1/registry/documents/{doc['id']}", headers=_h(fake)).json()
    assert status["active"] is None and status["draft"]["template"]["prefix"] == "กท 1205/"

    res = client.post(f"/api/v1/registry/documents/{doc['id']}/issue", json={"doc_date": "17 พฤศจิกายน 2569"}, headers=_h(fake))
    assert res.status_code == 200, res.text
    assert res.json()["doc_number"] == "กท 1205/1"
    entry = fake.tables["outgoing_register"][0]
    assert (entry["status"], entry["subject"], entry["to_recipient"], entry["doc_date"], entry["from_unit"]) == \
        ("issued", "ขอใช้สนามกีฬา", "อธิบดีกรม ค", "17 พฤศจิกายน 2569", "กองการกีฬา")
    assert entry["document_id"] == doc["id"] and entry["issued_by"] == USER_ID

    again = client.post(f"/api/v1/registry/documents/{doc['id']}/issue", json={}, headers=_h(fake))
    assert again.status_code == 409                                    # กดซ้ำไม่ได้เลขที่สอง
    status = client.get(f"/api/v1/registry/documents/{doc['id']}", headers=_h(fake)).json()
    assert status["active"]["doc_number"] == "กท 1205/1" and status["active"]["issued_by_name"] == "ผู้ทดสอบ"


def test_cancel_then_reissue_never_reuses_number(fake, client):
    doc = _add_doc(fake)
    first = client.post(f"/api/v1/registry/documents/{doc['id']}/issue", json={}, headers=_h(fake)).json()["entry"]
    assert client.post(f"/api/v1/registry/outgoing/{first['id']}/cancel", json={"reason": "  "}, headers=_h(fake)).status_code == 400
    res = client.post(f"/api/v1/registry/outgoing/{first['id']}/cancel", json={"reason": "ผู้รับผิด"}, headers=_h(fake))
    assert res.json()["status"] == "cancelled" and res.json()["cancelled_by"] == USER_ID
    second = client.post(f"/api/v1/registry/documents/{doc['id']}/issue", json={}, headers=_h(fake)).json()
    assert second["doc_number"] == "กท 1205/2"
    listed = client.get("/api/v1/registry/outgoing", params={"q": "ผู้รับผิด"}, headers=_h(fake)).json()
    assert [r["doc_number"] for r in listed] == ["กท 1205/1"] and listed[0]["cancelled_by_name"] == "ผู้ทดสอบ"
    audit = client.get("/api/v1/registry/audit", params={"entity": "outgoing", "entity_id": first["id"]}, headers=_h(fake)).json()
    assert [a["action_label"] for a in audit] == ["ออกเลข", "ยกเลิกเลข"] and audit[0]["actor_name"] == "ผู้ทดสอบ"


def test_number_first_format_and_document_without_code(fake, client):
    doc = _add_doc(fake, doc_number=HANDWRITE_GAP + "/2569")
    assert client.post(f"/api/v1/registry/documents/{doc['id']}/issue", json={}, headers=_h(fake)).json()["doc_number"] == "1/2569"
    numbered = _add_doc(fake, doc_number="กท 1205/45")
    res = client.post(f"/api/v1/registry/documents/{numbered['id']}/issue", json={}, headers=_h(fake))
    assert res.status_code == 409 and "กท 1205/45" in res.json()["detail"]
    custom = client.post(f"/api/v1/registry/documents/{numbered['id']}/issue", json={"prefix": "กท 9999/"}, headers=_h(fake))
    assert custom.json()["doc_number"] == "กท 9999/1"


def test_reserve_in_advance_then_use_on_document(fake, client):
    reserved = client.post("/api/v1/registry/reserve", json={"prefix": "กท 1205/", "subject": "จองไว้ประชุม"}, headers=_h(fake)).json()
    assert reserved["entry"]["status"] == "reserved"
    doc = _add_doc(fake, subject="เรื่องจริง")
    status = client.get(f"/api/v1/registry/documents/{doc['id']}", headers=_h(fake)).json()
    assert [r["doc_number"] for r in status["reserved"]] == ["กท 1205/1"]
    res = client.post(f"/api/v1/registry/documents/{doc['id']}/issue", json={"reserved_id": reserved["entry"]["id"]}, headers=_h(fake))
    assert res.json()["doc_number"] == "กท 1205/1"
    row = fake.tables["outgoing_register"][0]
    assert (row["status"], row["subject"], row["document_id"]) == ("issued", "เรื่องจริง", doc["id"])
    other = _add_doc(fake)
    assert client.post(f"/api/v1/registry/documents/{other['id']}/issue", json={"reserved_id": row["id"]}, headers=_h(fake)).status_code == 404


def test_receive_source_and_link_reply(fake, client):
    source = str(uuid.uuid4())
    doc = _add_doc(fake, source=source)
    body = {"source_doc_number": "ศธ 04/7", "source_doc_date": "1 พฤศจิกายน 2569", "from_org": "กรม ค",
            "subject": "ขอความอนุเคราะห์", "source_file_id": source, "document_id": doc["id"]}
    assert client.get(f"/api/v1/registry/incoming/by-source/{source}", headers=_h(fake)).json() == {"entry": None}
    res = client.post("/api/v1/registry/incoming", json=body, headers=_h(fake))
    assert res.json()["receive_number"] == "1"
    assert client.post("/api/v1/registry/incoming", json=body, headers=_h(fake)).status_code == 409   # ลงรับซ้ำไม่ได้

    # หนังสือตอบที่ร่างจากต้นเรื่องเดียวกัน (เช่นฉบับเสนอขั้นถัดไป) เชื่อมกับเลขรับเอง
    reply = _add_doc(fake, source=source)
    issued = client.post(f"/api/v1/registry/documents/{reply['id']}/issue", json={}, headers=_h(fake)).json()
    assert issued["incoming"]["reg_no"] == 1 and issued["entry"]["incoming_id"] == 1
    received = client.get(f"/api/v1/registry/incoming/by-source/{source}", headers=_h(fake)).json()["entry"]
    assert [r["doc_number"] for r in received["replies"]] == ["กท 1205/1"]
    listed = client.get("/api/v1/registry/outgoing", headers=_h(fake)).json()
    assert listed[0]["incoming"]["reg_no"] == 1


def test_years_and_export(fake, client):
    doc = _add_doc(fake, subject="ส่งออกทะเบียน")
    client.post(f"/api/v1/registry/documents/{doc['id']}/issue", json={}, headers=_h(fake))
    client.post("/api/v1/registry/incoming", json={"subject": "รับ", "from_org": "กรม ค"}, headers=_h(fake))
    years = client.get("/api/v1/registry/years", headers=_h(fake)).json()
    assert 2569 in years["years"]
    xlsx = client.get("/api/v1/registry/outgoing/export", params={"format": "xlsx", "year": 2569}, headers=_h(fake))
    assert xlsx.status_code == 200 and xlsx.headers["x-govdoc-rows"] == "1"
    assert "spreadsheetml" in xlsx.headers["content-type"] and "filename*=UTF-8''" in xlsx.headers["content-disposition"]
    assert "ส่งออกทะเบียน" in zipfile.ZipFile(io.BytesIO(xlsx.content)).read("xl/worksheets/sheet1.xml").decode()
    none = client.get("/api/v1/registry/outgoing/export", params={"format": "xlsx", "year": 2569, "q": "ไม่มีคำนี้"}, headers=_h(fake))
    assert none.headers["x-govdoc-rows"] == "0"
    pdf = client.get("/api/v1/registry/incoming/export", params={"format": "pdf", "year": 2569}, headers=_h(fake))
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")
    assert client.get("/api/v1/registry/other/export", headers=_h(fake)).status_code == 404


def test_missing_migration_gives_clear_message(fake, client):
    fake.rpc_errors["issue_outgoing_number"] = {"code": "PGRST202", "message": "Could not find the function"}
    doc = _add_doc(fake)
    res = client.post(f"/api/v1/registry/documents/{doc['id']}/issue", json={}, headers=_h(fake))
    assert res.status_code == 503 and "20261116000013" in res.json()["detail"]


def test_new_registry_endpoints_need_supabase(client):
    assert client.get("/api/v1/registry/years").status_code == 501
    assert client.post(f"/api/v1/registry/documents/{uuid.uuid4()}/issue", json={}).status_code == 501

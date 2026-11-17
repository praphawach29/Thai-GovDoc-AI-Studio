"""
Step 13: ตรวจข้อเท็จจริงในร่างเทียบต้นเรื่อง (วันที่ เวลา ตัวเลข) — AI อ่านไฟล์สแกนคลาดได้
"""

import pytest
from fastapi.testclient import TestClient

from core.fact_check import check_facts, source_text_of
from core.models import DocType
from core.templates_library import PRESET_TEMPLATES

SOURCE = """กลุ่มเซ็นทรัล
ที่ CG 123/2568
22 กรกฎาคม 2568
เรื่อง ขออนุญาตจัดกิจกรรมเซ็นทรัลกรุ๊ป มินิมาราธอน ครั้งที่ 17
กลุ่มเซ็นทรัลกำหนดจัดกิจกรรมในวันอาทิตย์ที่ 14 กันยายน 2568 เวลา 05.00 - 09.00 น.
ณ ลานด้านหน้าศูนย์การค้าเซ็นทรัลเวิลด์ ผู้เข้าร่วมกิจกรรมทั้งสิ้น 4,000 คน
ค่าสมัคร ๕๐๐ บาท ประชุมเตรียมงาน 1-3 ส.ค. 68
"""


def _memo(**fields):
    doc = PRESET_TEMPLATES["bma_cohost_request"].schema.model_copy(deep=True)
    doc.doc_type = DocType.INTERNAL
    base = dict(subject="ขออนุญาตจัดกิจกรรม", references=None, attachments=None,
                memo_intro="", memo_facts="", memo_consideration="")
    base.update(fields)
    for k, v in base.items():
        setattr(doc, k, v)
    return doc


def _texts(issues):
    return [(i.field, i.kind, i.text) for i in issues]


def test_matching_facts_pass_in_any_digit_style():
    doc = _memo(memo_facts=(
        "๑. กลุ่มเซ็นทรัล กำหนดจัดกิจกรรม ครั้งที่ ๑๗ ในวันอาทิตย์ที่ ๑๔ กันยายน ๒๕๖๘ เวลา ๐๕.๐๐ – ๐๙.๐๐ น.\n"
        "๒. ผู้เข้าร่วม ๔,๐๐๐ คน ค่าสมัคร 500 บาท\n"
        "๒.๑ ประชุมเตรียมงาน ๒ สิงหาคม ๒๕๖๘"),
        references=["หนังสือกลุ่มเซ็นทรัล ที่ CG 123/2568 ลงวันที่ ๒๒ กรกฎาคม ๒๕๖๘"])
    assert check_facts(doc, SOURCE) == []


def test_misread_date_time_and_number_are_flagged():
    doc = _memo(memo_facts="วันอาทิตย์ที่ ๑๘ กันยายน ๒๕๖๘ เวลา ๐๖.๐๐ น. ผู้เข้าร่วม ๕,๐๐๐ คน",
                subject="มินิมาราธอน ครั้งที่ ๑๑")
    got = _texts(check_facts(doc, SOURCE))
    assert ("memo_facts", "date", "๑๘ กันยายน ๒๕๖๘") in got
    assert ("memo_facts", "time", "เวลา ๐๖.๐๐ น.") in got
    assert ("memo_facts", "number", "๕,๐๐๐") in got
    assert ("subject", "number", "๑๑") in got
    assert len(got) == 4


def test_wrong_year_flagged_but_missing_year_accepted():
    assert _texts(check_facts(_memo(memo_intro="ลงวันที่ ๒๒ กรกฎาคม ๒๕๖๗"), SOURCE)) == [
        ("memo_intro", "date", "๒๒ กรกฎาคม ๒๕๖๗")]
    assert check_facts(_memo(memo_intro="ในวันที่ ๑๔ กันยายน"), SOURCE) == []


def test_list_markers_placeholders_and_small_numbers_ignored():
    doc = _memo(memo_consideration="๑. เห็นควรอนุญาต ทั้ง ๒ ฝ่าย\n๑.๑ ภายในวันที่ [✏️ ระบุวันที่ 99 ธันวาคม]\n๒.๓ ประสานงาน")
    assert check_facts(doc, SOURCE) == []


def test_header_fields_and_request_not_checked():
    doc = _memo(memo_facts="")
    doc.doc_date = "๑๖ พฤศจิกายน ๒๕๖๙"
    doc.doc_number = "กท ๑๒๐๕/๙๙๙"
    doc.memo_request = "จึงเรียนมาเพื่อโปรดพิจารณา ภายใน ๓๐ วัน"
    assert check_facts(doc, SOURCE) == []


def test_no_source_means_no_check():
    assert check_facts(_memo(memo_facts="ผู้เข้าร่วม ๕,๐๐๐ คน"), "") == []
    assert check_facts(_memo(memo_facts="ผู้เข้าร่วม ๕,๐๐๐ คน"), "สั้น") == []


def test_prompt_counts_as_source():
    src = source_text_of(SOURCE, "เพิ่มเติม: งบประมาณ 120,000 บาท")
    assert check_facts(_memo(memo_facts="งบประมาณ ๑๒๐,๐๐๐ บาท"), src) == []


def test_external_letter_checks_paragraphs():
    doc = PRESET_TEMPLATES["bma_cohost_request"].schema.model_copy(deep=True)
    doc.doc_type = DocType.EXTERNAL
    doc.subject, doc.references, doc.attachments = "ขอใช้สถานที่", None, None
    doc.paragraph_reason, doc.paragraph_details, doc.paragraph_purpose = "ผู้เข้าร่วม ๗,๐๐๐ คน", None, "โปรดพิจารณา"
    assert _texts(check_facts(doc, SOURCE)) == [("paragraph_reason", "number", "๗,๐๐๐")]


# ---------------------------------------------------------------- API
def test_fact_check_api():
    from server.main import app
    doc = _memo(memo_facts="ผู้เข้าร่วม ๕,๐๐๐ คน").model_dump(mode="json")
    res = TestClient(app).post("/api/v1/studio/fact-check", json={"doc": doc, "source_text": SOURCE})
    assert res.status_code == 200
    body = res.json()
    assert body["checked"] is True
    assert [(i["field"], i["kind"], i["text"]) for i in body["issues"]] == [("memo_facts", "number", "๕,๐๐๐")]
    empty = TestClient(app).post("/api/v1/studio/fact-check", json={"doc": doc, "source_text": ""}).json()
    assert empty == {"checked": False, "issues": []}


def test_studio_draft_includes_facts_in_check():
    from server.main import app
    body = TestClient(app).post("/api/v1/studio/draft", data={
        "prompt": SOURCE, "doc_type": "internal"}).json()
    assert "facts" in body["check"] and isinstance(body["check"]["facts"], list)

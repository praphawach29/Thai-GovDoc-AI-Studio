"""
Step 6: หน่วยออกหนังสือ — ส่วนราชการ/เลขที่เว้นเขียนมือ/วันที่เว้นเลขวัน ตามหน่วยที่เลือก
(ตามตัวอย่างบันทึกข้อความของกองการกีฬา สำนักวัฒนธรรม กีฬา และการท่องเที่ยว)
"""

from datetime import date

import pytest
from fastapi.testclient import TestClient

from core.issuing_units import (
    AUTHORITY_PLACEHOLDER,
    apply_issuing_unit,
    auto_top_request,
    blank_day_date,
    format_doc_number,
    pick_unit,
    proposal_items,
    unit_named_in_prompt,
)
from core.linter import lint_gov_document
from core.models import HANDWRITE_GAP, default_issuing_units, is_blank_doc_number
from core.templates_library import PRESET_TEMPLATES
from server import auth as server_auth
from server import supabase as server_supabase
from server.main import app
from server.settings import Settings, get_settings
from tests.fake_supabase import ORG_ID, PUBLISHABLE_KEY, URL, FakeSupabase

DAY = date(2026, 8, 15)


def test_number_formats_from_samples():
    units = {u.key: u for u in default_issuing_units()}
    group = format_doc_number(units["sport-promotion"].doc_number_format, DAY)
    division = format_doc_number(units["sports-division"].doc_number_format, DAY)
    assert group == HANDWRITE_GAP + "/2569"               # ที่ ......../2569 แต่เว้นว่างไม่มีจุด
    assert division == "กท 1205/" + HANDWRITE_GAP          # ที่ กท 1205/ แล้วเว้นเลขลำดับ
    assert "." not in group
    assert is_blank_doc_number(group) and is_blank_doc_number(division)
    assert not is_blank_doc_number("กท 1205/123")


def test_blank_day_date_has_no_day_and_no_prefix():
    text = blank_day_date(DAY)
    assert text == HANDWRITE_GAP + "สิงหาคม 2569"
    assert not text.strip().startswith("วันที่")


def test_default_unit_is_sport_promotion():
    units = default_issuing_units()
    assert pick_unit(units).key == "sport-promotion"
    assert pick_unit(units, "sports-division").label == "กองการกีฬา"
    assert pick_unit(units, "nope").key == "sport-promotion"


def test_apply_unit_sets_header_fields_and_lints_as_warning_only():
    doc = PRESET_TEMPLATES["procurement_approval"].schema
    unit = pick_unit(default_issuing_units(), "sports-division")
    out = apply_issuing_unit(doc, unit, DAY)
    assert out.dept_name.startswith("กองการกีฬา (กลุ่มงานส่งเสริมกีฬา โทร.")
    assert out.doc_number.startswith("กท 1205/") and out.doc_date.endswith("สิงหาคม 2569")
    assert doc.dept_name != out.dept_name                  # ไม่แก้เอกสารต้นฉบับ
    issues = {i.rule_id: i.severity for i in lint_gov_document(out).issues}
    assert issues.get("RULE_DOC_NUMBER_PLACEHOLDER") == "warning"
    assert "RULE_NO_PREFIX_DATE" not in issues and "RULE_THAI_MONTH_NAME" not in issues


# ---------------------------------------------------------------- API โหมดเครื่องเดียว
@pytest.fixture
def client():
    return TestClient(app)


def test_units_endpoint_and_apply(client):
    units = client.get("/api/v1/studio/units").json()
    assert [u["key"] for u in units] == ["sport-promotion", "sports-division", "culture-sports-bureau"]
    doc = PRESET_TEMPLATES["procurement_approval"].schema.model_dump(mode="json")
    res = client.post("/api/v1/studio/apply-unit", json={"doc": doc, "unit_key": "sports-division"})
    assert res.status_code == 200 and res.json()["doc_number"].startswith("กท 1205/")
    assert client.post("/api/v1/studio/apply-unit", json={"doc": doc, "unit_key": "nope"}).status_code == 404


def test_draft_and_blank_use_selected_unit(client):
    res = client.post("/api/v1/studio/draft", data={
        "prompt": "ร่างบันทึกข้อความขออนุมัติจัดอบรมเจ้าหน้าที่ วันที่ ๑๐ ธันวาคม ๒๕๖๙", "doc_type": "internal",
        "unit_key": "sports-division",
    })
    doc = res.json()["document"]
    assert doc["dept_name"].startswith("กองการกีฬา (") and doc["doc_number"].startswith("กท 1205/")
    assert doc["salutation"] == "เรียน ผู้อำนวยการสำนักวัฒนธรรม กีฬา และการท่องเที่ยว"
    assert doc["memo_request"].startswith("จึงเรียนมาเพื่อโปรดพิจารณาลงนามหนังสือเรียนปลัด")
    blank = client.post("/api/v1/studio/blank", json={"doc_type": "internal"}).json()
    assert blank["dept_name"].startswith("กลุ่มงานส่งเสริมกีฬา โทร.")
    assert blank["doc_number"].endswith("/" + str(date.today().year + 543)) or blank["doc_number"].endswith("/2570")


def test_unit_named_in_prompt():
    units = default_issuing_units()
    assert unit_named_in_prompt(units, "ร่างบันทึกข้อความเสนอปลัดกรุงเทพมหานคร").key == "culture-sports-bureau"
    assert unit_named_in_prompt(units, "บันทึกถึง ผู้อำนวยการสำนักวัฒนธรรม กีฬา และการท่องเที่ยว").key == "sports-division"
    # 'เรียน ...' ในหนังสือต้นเรื่องที่วางมาไม่นับ
    assert unit_named_in_prompt(units, "หนังสือของสมาคม เรียน ปลัดกรุงเทพมหานคร ขอใช้สถานที่") is None
    assert unit_named_in_prompt(units, "ขออนุมัติจัดอบรม") is None


def test_prompt_recipient_overrides_default_unit(client):
    res = client.post("/api/v1/studio/draft", data={
        "prompt": "ร่างบันทึกข้อความเสนอปลัดกรุงเทพมหานคร ขออนุมัติจัดอบรมเจ้าหน้าที่ วันที่ ๑๐ ธันวาคม ๒๕๖๙",
        "doc_type": "internal", "unit_key": "sport-promotion",
    })
    body = res.json()
    assert body["unit_key"] == "culture-sports-bureau"
    assert body["document"]["salutation"] == "เรียน ปลัดกรุงเทพมหานคร"
    assert body["document"]["signatory_position"] == "ผู้อำนวยการสำนักวัฒนธรรม กีฬา และการท่องเที่ยว"
    # จุดที่ต้องระบุนับจากฉบับที่ใส่ค่าหน่วยแล้ว: คำขึ้นต้นเป็นปลัดฯ แล้ว ไม่ค้างเป็น placeholder
    placeholders = body["check"]["placeholders"]
    assert not any(p.startswith("คำขึ้นต้น") for p in placeholders)
    draft_step = next(s for s in body["steps"] if s["key"] == "draft")
    assert draft_step["detail"] == f"เหลือจุดที่ต้องระบุ {len(placeholders)} จุด"


def test_refresh_check_counts_unit_request_placeholder():
    from core.studio import StudioDraftResult, StudioStep, check_document, refresh_check

    units = default_issuing_units()
    doc = PRESET_TEMPLATES["bma_cohost_request"].schema.model_copy(deep=True)
    doc.memo_request_top = None
    doc.memo_consideration = CONSIDERATION
    before = check_document(doc)
    result = StudioDraftResult(document=doc, check=before,
                               steps=[StudioStep(key="draft", label="ร่าง", detail="เหลือจุดที่ต้องระบุ 0 จุด")])
    result.document = apply_issuing_unit(doc, units[-1], DAY, units=units, replace_request=True)
    refresh_check(result)
    assert any(AUTHORITY_PLACEHOLDER in p for p in result.check.placeholders)
    assert result.steps[0].detail == f"เหลือจุดที่ต้องระบุ {len(result.check.placeholders)} จุด"


CONSIDERATION = """สำนักวัฒนธรรม กีฬา และการท่องเที่ยวพิจารณาแล้ว เห็นควร ดังนี้
๑. เห็นชอบ อนุญาต และอนุมัติ ดังนี้
	๑.๑ เห็นชอบให้กรุงเทพมหานครเป็นเจ้าภาพร่วม
	๑.๒ อนุญาตให้ใช้ตราสัญลักษณ์กรุงเทพมหานคร
	๑.๓ อนุมัติยกเว้นค่าธรรมเนียมให้กับสมาคม
๒. มอบหมายหน่วยงานที่เกี่ยวข้องพิจารณาให้การสนับสนุน ดังนี้
	๒.๑ สำนักการโยธา ดำเนินการตามข้อเท็จจริง ๖
	๒.๒ สำนักการแพทย์ ดำเนินการตามข้อเท็จจริง ๗"""


def test_proposal_items_prefer_sub_items_with_their_own_verb():
    assert proposal_items(CONSIDERATION) == [
        ("๑.๑", "approve", "ให้ความเห็นชอบ"), ("๑.๒", "approve", "อนุญาต"),
        ("๑.๓", "approve", "อนุมัติ"), ("๒", "command", "สั่งการ"),
    ]


def test_auto_top_request_lists_items_and_leaves_authority_blank():
    top = default_issuing_units()[-1]
    text = auto_top_request(CONSIDERATION, top)
    assert text == (
        "จึงเรียนมาเพื่อโปรดพิจารณา หากเห็นชอบโปรดนำเรียนผู้ว่าราชการกรุงเทพมหานคร "
        "เพื่อโปรดพิจารณาให้ความเห็นชอบตามข้อ ๑.๑ อนุญาตตามข้อ ๑.๒ และอนุมัติตามข้อ ๑.๓ "
        "อำนาจในการเห็นชอบ อนุญาต และอนุมัติเป็นของผู้ว่าราชการกรุงเทพมหานคร "
        f"ตาม{AUTHORITY_PLACEHOLDER} และปลัดกรุงเทพมหานครได้โปรดสั่งการตามข้อ ๒"
    )
    two = auto_top_request("พิจารณาแล้ว เห็นควร\n๑. อนุญาตให้ใช้ตรา\n๒. อนุญาตให้ใช้สถานที่", top)
    assert "อนุญาตตามข้อ ๑ และ ๒ อำนาจในการอนุญาตเป็นของ" in two and "สั่งการ" not in two
    assert auto_top_request("พิจารณาแล้ว เห็นควรแจ้งสมาคมทราบ", top) is None
    # หน่วยที่ไม่ได้ "นำเรียน<ผู้มีอำนาจ>" ไม่สร้าง
    assert auto_top_request(CONSIDERATION, default_issuing_units()[0]) is None


def test_auto_top_request_only_at_last_unit_and_replaced_when_going_down():
    units = default_issuing_units()
    doc = PRESET_TEMPLATES["bma_cohost_request"].schema.model_copy(deep=True)
    doc.memo_request_top = None
    doc.memo_consideration = CONSIDERATION
    top = apply_issuing_unit(doc, units[-1], DAY, units=units, replace_request=True)
    assert top.memo_request.endswith("ได้โปรดสั่งการตามข้อ ๒")
    down = apply_issuing_unit(top, units[1], DAY, units=units)
    assert down.memo_request == units[1].request_text


# ---------------------------------------------------------------- API โหมด Supabase
def test_supabase_mode_reads_org_units(tmp_path, monkeypatch, client):
    fake = FakeSupabase()
    monkeypatch.setattr(server_supabase, "transport_factory", fake.transport)
    server_auth._jwks_cache.clear()
    app.dependency_overrides[get_settings] = lambda: Settings(
        upload_dir=tmp_path / "u", registry_db_path=tmp_path / "r.db",
        supabase_url=URL, supabase_publishable_key=PUBLISHABLE_KEY,
    )
    fake.tables["org_units"].append({
        "org_id": ORG_ID, "key": "custom", "label": "หน่วยทดสอบ", "dept_name": "หน่วยทดสอบ (โทร.๑)",
        "doc_number_format": "ทส 1/{gap}", "contact_dept": "", "contact_tel": "", "contact_fax": "",
        "blank_day": False, "is_default": True,
    })
    h = {"Authorization": f"Bearer {fake.token()}"}
    assert [u["key"] for u in client.get("/api/v1/studio/units", headers=h).json()] == ["custom"]
    doc = PRESET_TEMPLATES["procurement_approval"].schema.model_dump(mode="json")
    out = client.post("/api/v1/studio/apply-unit", json={"doc": doc}, headers=h).json()
    assert out["dept_name"] == "หน่วยทดสอบ (โทร.๑)" and out["doc_number"].startswith("ทส 1/")
    assert out["doc_date"] == doc["doc_date"]              # blank_day=False ไม่แตะวันที่

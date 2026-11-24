"""
Step 6: หน่วยออกหนังสือ — ส่วนราชการ/เลขที่เว้นเขียนมือ/วันที่เว้นเลขวัน ตามหน่วยที่เลือก
(ตามตัวอย่างบันทึกข้อความของกองการกีฬา สำนักวัฒนธรรม กีฬา และการท่องเที่ยว)
"""

from datetime import date

import pytest
from fastapi.testclient import TestClient

from core.issuing_units import (
    apply_issuing_unit,
    blank_day_date,
    format_doc_number,
    pick_unit,
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

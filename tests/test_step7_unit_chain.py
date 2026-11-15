"""
Step 7: สายการเสนอ กลุ่มงาน -> กอง -> สำนัก (ตามตัวอย่างบันทึกเสนอจริงของกองการกีฬา)
แต่ละขั้นเปลี่ยน ส่วนราชการ/เลขที่/ผู้รับ/ผู้ลงนาม/ผู้พิจารณา/ภาคความประสงค์ และรวม PDF ชุดเสนอได้
"""

from datetime import date
from io import BytesIO

import pdfplumber
import pytest
from fastapi.testclient import TestClient

from core.issuing_units import SIGNER_NAME_PLACEHOLDER, apply_issuing_unit, build_unit_chain, next_unit
from core.models import Signer, default_issuing_units
from core.templates_library import PRESET_TEMPLATES
from core.typst_exporter import generate_typst_content
from server.main import app
from tests.fake_supabase import ORG_ID, PUBLISHABLE_KEY, URL, FakeSupabase

DAY = date(2026, 11, 15)
AUTHOR = Signer(name="(นายทดสอบ ระบบ)", position="นักพัฒนาการกีฬาชำนาญการ", is_author=True)


def _base():
    doc = PRESET_TEMPLATES["bma_cohost_request"].schema.model_copy(deep=True)
    doc.memo_consideration = "กลุ่มงานส่งเสริมกีฬาพิจารณาแล้ว เห็นว่าการจัดการแข่งขันเป็นประโยชน์ จึงเห็นควรพิจารณา ดังนี้"
    doc.memo_request = ""
    return doc


def test_three_levels_follow_the_sample_memos():
    chain = build_unit_chain(_base(), default_issuing_units(), day=DAY, author=AUTHOR)
    assert [u.key for u, _ in chain] == ["sport-promotion", "sports-division", "culture-sports-bureau"]
    (_, group), (_, division), (_, bureau) = chain

    assert group.dept_name == "กลุ่มงานส่งเสริมกีฬา โทร.๐ ๒๒๔๖ ๘๐๗๙ โทรสาร ๐ ๒๒๔๖ ๐๒๘๒"
    assert group.doc_number.endswith("/2569") and group.salutation == "เรียน หัวหน้ากลุ่มงานส่งเสริมกีฬา"
    # ต้นเรื่อง: ผู้เสนอเรื่องลงนาม แล้วหัวหน้ากลุ่มงานลงนามต่อ
    assert (group.signatory_name, group.signatory_position) == (AUTHOR.name, AUTHOR.position)
    assert [c.position for c in group.co_signers] == ["หัวหน้ากลุ่มงานส่งเสริมกีฬา"]
    assert group.memo_request == "จึงเรียนมาเพื่อโปรดพิจารณานำเรียนผู้อำนวยการกองการกีฬาลงนามในหนังสือที่แนบ"

    assert division.dept_name.startswith("กองการกีฬา (กลุ่มงานส่งเสริมกีฬา โทร.")
    assert division.doc_number.startswith("กท 1205/")
    assert division.salutation == "เรียน ผู้อำนวยการสำนักวัฒนธรรม กีฬา และการท่องเที่ยว"
    assert division.signatory_position == "ผู้อำนวยการกองการกีฬา" and not division.co_signers
    assert division.memo_consideration.startswith("กองการกีฬาพิจารณาแล้ว")
    assert division.memo_request == "จึงเรียนมาเพื่อโปรดพิจารณาลงนามหนังสือเรียนปลัดกรุงเทพมหานครที่แนบ"

    assert bureau.dept_name.startswith("สำนักวัฒนธรรม กีฬา และการท่องเที่ยว (กองการกีฬา โทร.")
    assert bureau.salutation == "เรียน ปลัดกรุงเทพมหานคร"
    assert bureau.signatory_position == "ผู้อำนวยการสำนักวัฒนธรรม กีฬา และการท่องเที่ยว"
    assert bureau.memo_consideration.startswith("สำนักวัฒนธรรม กีฬา และการท่องเที่ยวพิจารณาแล้ว")
    for _, d in chain:
        assert d.memo_intro == _base().memo_intro            # เนื้อหาเดิมทุกขั้น


def test_unknown_names_become_placeholders_and_custom_request_is_kept():
    units = default_issuing_units()
    doc = _base()
    doc.memo_request = "จึงเรียนมาเพื่อโปรดทราบ (ข้อความที่ผู้ใช้เขียนเอง)"
    out = apply_issuing_unit(doc, units[1], DAY, units=units)
    assert out.signatory_name == SIGNER_NAME_PLACEHOLDER
    assert out.memo_request == doc.memo_request              # ไม่ทับข้อความที่เขียนเอง
    fresh = apply_issuing_unit(doc, units[1], DAY, units=units, replace_request=True)
    assert fresh.memo_request == units[1].request_text
    assert next_unit(units, "sports-division").key == "culture-sports-bureau"
    assert next_unit(units, "culture-sports-bureau") is None


def test_typst_renders_co_signers():
    (_, group), *_ = build_unit_chain(_base(), default_issuing_units(), day=DAY, author=AUTHOR)
    code = generate_typst_content(group)
    assert 'co_signers: ((name: "([✏️ ระบุชื่อผู้ลงนาม])", position: "หัวหน้ากลุ่มงานส่งเสริมกีฬา"), )' in code


@pytest.fixture
def client():
    return TestClient(app)


def test_pdf_bundle_puts_highest_level_first_and_dept_line_on_one_line(client):
    arabic = str.maketrans("๐๑๒๓๔๕๖๗๘๙", "0123456789")
    base = _base()
    base.use_thai_numerals = False
    chain = build_unit_chain(base, default_issuing_units(), day=DAY, author=AUTHOR)
    docs = []
    for _, d in reversed(chain):
        d.dept_name = d.dept_name.translate(arabic)           # ให้ค้นหาเลขโทรศัพท์ใน PDF ได้
        docs.append(d.model_dump(mode="json"))
    res = client.post("/api/v1/export/pdf-bundle", json={"documents": docs})
    assert res.status_code == 200 and res.headers["content-type"] == "application/pdf"
    with pdfplumber.open(BytesIO(res.content)) as pdf:
        heads = []
        for page in pdf.pages:
            words = page.extract_words()
            fax = [w for w in words if w["text"].startswith("0282")]
            if not fax:
                continue                                       # หน้าต่อ (-๒-)
            tel = next(w for w in words if w["text"] == "8079")
            number = next(w for w in words if "1205/" in w["text"] or w["text"].startswith("/2569"))
            # เลขโทรสาร (ท้ายบรรทัดส่วนราชการ) อยู่บรรทัดเดียวกับเลขโทรศัพท์ และอยู่เหนือบรรทัด "ที่"
            assert abs(fax[0]["bottom"] - tel["bottom"]) < 1 and fax[0]["bottom"] < number["bottom"] - 10
            heads.append(number["text"])
    # ชุดเสนอ: สำนัก (กท 1205/) -> กอง (กท 1205/) -> กลุ่มงาน (/2569)
    assert len(heads) == 3 and heads[2].startswith("/2569") and all("1205/" in h for h in heads[:2])


def test_pdf_bundle_rejects_empty(client):
    assert client.post("/api/v1/export/pdf-bundle", json={"documents": []}).status_code == 422


def test_supabase_mode_author_comes_from_login_profile(tmp_path, monkeypatch, client):
    from server import auth as server_auth
    from server import supabase as server_supabase
    from server.settings import Settings, get_settings

    fake = FakeSupabase()
    monkeypatch.setattr(server_supabase, "transport_factory", fake.transport)
    server_auth._jwks_cache.clear()
    app.dependency_overrides[get_settings] = lambda: Settings(
        upload_dir=tmp_path / "u", registry_db_path=tmp_path / "r.db",
        supabase_url=URL, supabase_publishable_key=PUBLISHABLE_KEY,
    )
    try:
        fake.tables["org_units"].append({
            "org_id": ORG_ID, "key": "group", "label": "กลุ่มงาน", "dept_name": "กลุ่มงาน โทร.๑",
            "doc_number_format": "{gap}/{year}", "contact_dept": "", "contact_tel": "", "contact_fax": "",
            "blank_day": True, "is_default": True, "recipient": "หัวหน้ากลุ่มงาน", "review_party": "กลุ่มงาน",
            "request_text": "จึงเรียนมาเพื่อโปรดพิจารณา",
            "signers": [{"name": "", "position": "ผู้เสนอเรื่อง", "is_author": True},
                        {"name": "(นายหัวหน้า ทดสอบ)", "position": "หัวหน้ากลุ่มงาน", "is_author": False}],
        })
        h = {"Authorization": f"Bearer {fake.token()}"}
        doc = PRESET_TEMPLATES["bma_cohost_request"].schema.model_dump(mode="json")
        out = client.post("/api/v1/studio/apply-unit", json={"doc": doc}, headers=h).json()
        assert out["salutation"] == "เรียน หัวหน้ากลุ่มงาน"
        assert (out["signatory_name"], out["signatory_position"]) == ("(ผู้ทดสอบ)", "นักวิชาการ")
        assert out["co_signers"] == [{"name": "(นายหัวหน้า ทดสอบ)", "position": "หัวหน้ากลุ่มงาน", "is_author": False, "stamp": False}]
    finally:
        app.dependency_overrides.clear()

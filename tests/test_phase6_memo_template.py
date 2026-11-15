"""
test_phase6_memo_template.py — ชุดทดสอบแม่แบบหนังสือบันทึกข้อความ (แบบบันทึกเสนอพิจารณา)

รูปแบบ "bma" (ค่าเริ่มต้น) ตามบันทึกข้อความจริงของกรุงเทพมหานคร:
    ต้นเรื่อง -> ข้อกฎหมาย (ถ้ามี) -> ข้อเท็จจริง -> ข้อพิจารณาและเสนอแนะ -> ภาคความประสงค์
    หัวข้อขีดเส้นใต้ ไม่มีเลขกำกับ; ข้อเท็จจริง/ข้อพิจารณาฯ เขียนนำหน้าข้อความในบรรทัดเดียวกัน
รูปแบบ "numbered":
    ๑. ต้นเรื่อง ๒. ข้อเท็จจริง ๓. ข้อกฎหมาย ๔. ข้อพิจารณาและเสนอแนะ (ตัวหนา)
"""

import pytest
import docx

from core.models import GovDocumentSchema, DocType, UrgencyLevel, SecretLevel, SourceDocumentContext, MemoHierarchyLevel
from core.templates_library import PRESET_TEMPLATES
from core.word_exporter import export_govdoc_to_docx
from legacy.pdf_exporter import generate_govdoc_html
from core.typst_exporter import generate_typst_content
from core.ai_drafter import draft_from_context_rule_based, DraftingIntent
from core.memo_layout import line_indent_cm, split_consideration_and_request
from core.linter import lint_gov_document


BMA_ORDER = ["ต้นเรื่อง", "ข้อกฎหมาย", "ข้อเท็จจริง", "ข้อพิจารณาและเสนอแนะ"]


@pytest.fixture
def bma_cohost_doc():
    return PRESET_TEMPLATES["bma_cohost_request"].schema.model_copy(deep=True)


@pytest.fixture
def bma_general_doc():
    return PRESET_TEMPLATES["bma_general_memo"].schema.model_copy(deep=True)


@pytest.fixture
def legacy_doc():
    """บันทึกข้อความแบบเดิมที่มีเฉพาะ paragraph_reason/details/purpose"""
    return GovDocumentSchema(
        doc_type=DocType.INTERNAL,
        urgency=UrgencyLevel.NORMAL,
        secret=SecretLevel.NORMAL,
        doc_number="กท ๐๑๐๑/๑๐",
        dept_name="สำนักการศึกษา",
        doc_date="๑๕ มีนาคม ๒๕๖๙",
        subject="รายงานผลการดำเนินงาน",
        salutation="เรียน  ผู้อำนวยการสำนักการศึกษา",
        paragraph_reason="ด้วย ฝ่ายวิชาการ ได้ดำเนินการจัดการแข่งขันทางวิชาการเสร็จสิ้นแล้ว",
        paragraph_details="ผลการแข่งขันมีนักเรียนเข้าร่วมจำนวน ๕๐๐ คนจาก ๕๐ โรงเรียน",
        paragraph_purpose="จึงเรียนมาเพื่อโปรดทราบและพิจารณาต่อไป",
        signatory_name="(นายวิชาการ เรียนดี)",
        signatory_position="หัวหน้าฝ่ายวิชาการ",
        contact_dept="ฝ่ายวิชาการ",
    )


# ---------- โครงสร้างหัวข้อ ----------

def test_bma_section_order_matches_source_memo(bma_cohost_doc):
    """ลำดับหัวข้อต้องเป็น ต้นเรื่อง -> ข้อกฎหมาย -> ข้อเท็จจริง -> ข้อพิจารณาและเสนอแนะ ตามบันทึกต้นแบบ"""
    sections = bma_cohost_doc.get_memo_sections()
    assert [t for t, _ in sections] == BMA_ORDER
    # Step 0: ข้อกฎหมายเป็น placeholder จนกว่าจะเลือกจากคลังที่ยืนยันแหล่ง
    assert "ระบุข้อกฎหมาย" in sections[1][1]
    assert bma_cohost_doc.get_memo_request().startswith("จึงเรียนมาเพื่อโปรดพิจารณา")


def test_bma_sections_without_law(bma_general_doc):
    bma_general_doc.memo_law = ""
    titles = [t for t, _ in bma_general_doc.get_memo_sections()]
    assert titles == ["ต้นเรื่อง", "ข้อเท็จจริง", "ข้อพิจารณาและเสนอแนะ"]


def test_numbered_style_renumbers_sections(bma_general_doc):
    bma_general_doc.memo_heading_style = "numbered"
    titles = [t for t, _ in bma_general_doc.get_memo_sections()]
    assert titles == ["๑. ต้นเรื่อง", "๒. ข้อเท็จจริง", "๓. ข้อกฎหมาย", "๔. ข้อพิจารณาและเสนอแนะ"]

    bma_general_doc.memo_law = None
    titles = [t for t, _ in bma_general_doc.get_memo_sections()]
    assert titles == ["๑. ต้นเรื่อง", "๒. ข้อเท็จจริง", "๓. ข้อพิจารณาและเสนอแนะ"]


def test_legacy_doc_purpose_becomes_request(legacy_doc):
    """ข้อมูลเดิมที่ paragraph_purpose เป็นประโยค 'จึงเรียนมา...' ล้วน ต้องกลายเป็นภาคความประสงค์ ไม่ใช่ข้อพิจารณา"""
    titles = [t for t, _ in legacy_doc.get_memo_sections()]
    assert titles == ["ต้นเรื่อง", "ข้อเท็จจริง"]
    assert legacy_doc.get_memo_request() == "จึงเรียนมาเพื่อโปรดทราบและพิจารณาต่อไป"


def test_memo_only_fields_backfill_paragraphs():
    """กรอกเฉพาะ memo_* ก็ต้องสร้าง paragraph_* ให้อัตโนมัติ (ใช้โดย linter/copilot)"""
    d = GovDocumentSchema(
        doc_type=DocType.INTERNAL, doc_number="กท ๑/๑", dept_name="กอง", doc_date="๑ มกราคม ๒๕๖๙",
        subject="ทดสอบ", salutation="เรียน  ผู้อำนวยการ",
        paragraph_reason="", paragraph_purpose="",
        memo_intro="ต้นเรื่อง", memo_consideration="เห็นควร", memo_request="จึงเรียนมาเพื่อโปรดพิจารณา",
        signatory_name="(ก)", signatory_position="ข", contact_dept="กอง",
    )
    assert d.paragraph_reason == "ต้นเรื่อง"
    assert "เห็นควร" in d.paragraph_purpose and "จึงเรียน" in d.paragraph_purpose


# ---------- การจัดย่อหน้า ----------

@pytest.mark.parametrize("line, expected", [
    ("ข้อความทั่วไป", 2.5),
    ("๑. สมาคมกีฬา", 2.5),
    ("1. สมาคมกีฬา", 2.5),
    ("๑.๑ เห็นชอบ", 3.5),
    ("1.๒ อนุญาต", 3.5),
    ("มาตรา ๖ ห้ามมิให้", 3.5),
    ("ข้อ ๒๑ ในกรณี", 3.5),
    ("๑.๑.๑ ข้อย่อย", 4.5),
    ("ข้อพิจารณา", 2.5),  # คำว่า "ข้อ" ที่ไม่ตามด้วยตัวเลข ไม่ใช่การอ้างข้อกฎหมาย
])
def test_line_indent_levels(line, expected):
    assert line_indent_cm(line) == expected


def test_split_request_from_consideration():
    c, r = split_consideration_and_request("เห็นควรอนุมัติ\n\nจึงเรียนมาเพื่อโปรดพิจารณา", None)
    assert c == "เห็นควรอนุมัติ" and r == "จึงเรียนมาเพื่อโปรดพิจารณา"
    c, r = split_consideration_and_request("เห็นควรอนุมัติ จึงเรียนมาเพื่อโปรดพิจารณา", None)
    assert c == "เห็นควรอนุมัติ" and r == "จึงเรียนมาเพื่อโปรดพิจารณา"
    c, r = split_consideration_and_request("เห็นควรอนุมัติ", "จึงเรียนมาเพื่อทราบ")
    assert c == "เห็นควรอนุมัติ" and r == "จึงเรียนมาเพื่อทราบ"


def test_bma_blocks_heading_and_run_in(bma_cohost_doc):
    blocks = bma_cohost_doc.get_memo_blocks()
    headings = [b for b in blocks if b.kind == "heading"]
    # หัวข้อเป็นบรรทัดเดี่ยว เริ่มตรงกับเนื้อความ (2.5 ซม.) ตามแบบบันทึกข้อความของหน่วยงาน
    assert [b.lead for b in headings] == ["ต้นเรื่อง", "ข้อกฎหมาย", "ข้อเท็จจริง", "ข้อพิจารณาและเสนอแนะ"]
    assert all(b.indent_cm == 2.5 and not b.text for b in headings)
    assert not [b for b in blocks if b.kind == "body" and b.lead]
    assert all(b.lead_style == "underline" for b in blocks if b.lead)
    assert blocks[-1].kind == "request"
    # Step 0: ข้อกฎหมายเป็น placeholder จนกว่าจะเลือกจากคลังที่ยืนยันแหล่ง
    assert any("ระบุข้อกฎหมาย" in b.text for b in blocks)
    # ข้อย่อย ๑.๑ เยื้องลึกกว่าข้อหลัก
    assert any(b.text.startswith("๑.๑") and b.indent_cm == 3.5 for b in blocks)


# ---------- การส่งออก ----------

def test_word_export_memo(bma_cohost_doc, tmp_path):
    out = tmp_path / "memo.docx"
    export_govdoc_to_docx(bma_cohost_doc, str(out))
    d = docx.Document(str(out))
    paras = d.paragraphs
    text = "\n".join(p.text for p in paras).replace("​", "")

    for title in BMA_ORDER:
        assert title in text
    assert text.index("ข้อกฎหมาย") < text.index("ข้อเท็จจริง")

    # หัวข้อต้องขีดเส้นใต้
    heading_runs = [r for p in paras for r in p.runs if r.text == "ต้นเรื่อง"]
    assert heading_runs and heading_runs[0].underline

    # หัวข้อ ส่วนราชการ 20pt ตัวหนา พร้อมเส้นจุดไข่ปลา (dot leader tab)
    dept_p = next(p for p in paras if p.text.startswith("ส่วนราชการ"))
    assert dept_p.runs[0].bold and dept_p.runs[0].font.size.pt == 20
    assert "w:leader=\"dot\"" in dept_p._p.xml

    # เลขหน้า -๒- เริ่มหน้าที่ ๒ (หน้าแรกต่างจากหน้าอื่น) ด้วยฟิลด์ PAGE เลขไทย
    sec = d.sections[0]
    assert sec.different_first_page_header_footer
    assert "PAGE \\* ThaiArabic" in sec.header._element.xml

    # ย่อหน้าข้อย่อย ๑.๑ เยื้อง 3.5 ซม.
    sub_p = next(p for p in paras if p.text.replace("​", "").startswith("๑.๑"))
    assert round(sub_p.paragraph_format.first_line_indent.cm, 1) == 3.5


def test_word_export_legacy_internal(legacy_doc, tmp_path):
    out = tmp_path / "legacy.docx"
    export_govdoc_to_docx(legacy_doc, str(out))
    text = "\n".join(p.text for p in docx.Document(str(out)).paragraphs).replace("​", "")
    assert "ต้นเรื่อง" in text and "จึงเรียนมาเพื่อโปรดทราบ" in text


@pytest.mark.requires_browser
def test_pdf_html_memo(bma_cohost_doc, export_pdf):
    html_code = generate_govdoc_html(bma_cohost_doc)
    for title in BMA_ORDER:
        assert title in html_code
    assert "ตราครุฑ 1.5 ซม." in html_code
    assert 'class="memo-label">ส่วนราชการ' in html_code
    assert "text-decoration: underline" in html_code
    assert "counter(page, thai)" in html_code  # เลขหน้าเลขไทย
    assert "@page :first" in html_code

    pdf_bytes = export_pdf(bma_cohost_doc)
    assert pdf_bytes.startswith(b"%PDF-")
    assert len(pdf_bytes) > 20000


def test_typst_memo_blocks(bma_cohost_doc):
    code = generate_typst_content(bma_cohost_doc)
    assert "memo_blocks: (" in code
    assert 'lead: "ข้อกฎหมาย", lead_style: "underline"' in code
    assert "indent: 3.50cm" in code
    assert "thai_page_numbers: true" in code
    # ห้ามมี newline ดิบในสตริง Typst
    for line in code.splitlines():
        assert line.count('"') % 2 == 0, line


# ---------- คลังแม่แบบ / AI ----------

def test_bma_preset_templates_registered():
    assert "bma_general_memo" in PRESET_TEMPLATES
    tmpl = PRESET_TEMPLATES["bma_cohost_request"]
    assert tmpl.doc_type == DocType.INTERNAL
    s = tmpl.schema
    assert s.memo_intro and s.memo_facts and s.memo_law and s.memo_consideration and s.memo_request
    assert s.memo_heading_style == "bma"


def test_ai_drafter_rule_based_memo():
    ctx = SourceDocumentContext(
        source_filename="request_cohost.pdf",
        source_dept="สมาคมกีฬาแห่งประเทศไทย",
        source_doc_no="สกท ๑๒/๒๕๖๙",
        source_date="๑ มีนาคม ๒๕๖๙",
        source_subject="ขอความอนุเคราะห์เป็นเจ้าภาพร่วมและขอใช้สถานที่จัดแข่งขันกีฬา",
        summary="ขอเป็นเจ้าภาพร่วมและขอใช้สถานที่",
        raw_text="สมาคมมีความประสงค์ขอรับการสนับสนุนเป็นเจ้าภาพร่วมและขอใช้สถานที่จัดกิจกรรม",
    )
    draft = draft_from_context_rule_based(ctx, doc_type=DocType.INTERNAL, intent=DraftingIntent.ACCEPT)
    assert draft.doc_type == DocType.INTERNAL
    assert draft.memo_intro and draft.memo_consideration is not None
    # Step 0: ระบบต้องไม่เติมข้อกฎหมายจาก keyword — ต้องมาจากต้นเรื่อง + ผู้ใช้ยืนยันเท่านั้น
    assert draft.memo_law is None
    assert draft.get_memo_sections()[0][0] == "ต้นเรื่อง"


def test_ai_drafter_does_not_invent_law_for_unknown_topic():
    ctx = SourceDocumentContext(
        source_filename="x.pdf", source_subject="ขอเชิญประชุมคณะทำงาน",
        summary="เชิญประชุม", raw_text="ขอเชิญประชุม",
    )
    draft = draft_from_context_rule_based(ctx, doc_type=DocType.INTERNAL, intent=DraftingIntent.ACCEPT)
    assert not draft.memo_law


# ---------- การทดสอบแม่แบบบันทึกข้อความตามลำดับชั้นและข้อกำหนด ๔ ส่วน ----------

def test_memo_hierarchy_templates_registered():
    """ตรวจสอบว่าแม่แบบบันทึกข้อความ ๓ ระดับชั้นและแบบมาตรฐานถูกลงทะเบียนครบถ้วน"""
    keys = ["bma_memo_kickboxing_dept", "bma_memo_kickboxing_division", "bma_memo_kickboxing_section", "bma_memo_standard_template"]
    for k in keys:
        assert k in PRESET_TEMPLATES
        tmpl = PRESET_TEMPLATES[k]
        assert tmpl.doc_type == DocType.INTERNAL
        assert tmpl.schema.memo_intro
        assert tmpl.schema.memo_facts
        assert tmpl.schema.memo_consideration
        assert tmpl.schema.memo_request
        # ตรวจสอบว่าผ่าน linter โดยไม่มี error
        res = lint_gov_document(tmpl.schema)
        assert res.is_valid is True, f"Template {k} has errors: {res.errors}"


def test_memo_hierarchy_closings():
    """ตรวจสอบประโยคลงท้ายมาตรฐานตามระดับชั้นทั้ง ๔ ระดับ"""
    assert "นำเรียนผู้อำนวยการกอง" in MemoHierarchyLevel.SECTION_TO_DIV.default_closing()
    assert "ลงนามหนังสือเรียนปลัดกรุงเทพมหานครที่แนบ" in MemoHierarchyLevel.DIV_TO_DEPT.default_closing()
    assert "นำเรียนผู้ว่าราชการกรุงเทพมหานคร" in MemoHierarchyLevel.DEPT_TO_PERM_SEC.default_closing()
    assert "โปรดลงนามในหนังสือที่แนบมาพร้อมนี้" in MemoHierarchyLevel.FINAL_APPROVAL.default_closing()


def test_linter_enforces_mandatory_memo_sections():
    """
    ตรวจสอบว่า Linter บังคับ:
    - ต้นเรื่อง (ต้องมีทุกครั้ง)
    - ข้อเท็จจริง (ต้องมีทุกครั้ง)
    - ข้อพิจารณาและเสนอแนะ (ต้องมีทุกครั้ง)
    - ประโยคลงท้าย (ต้องมีทุกครั้ง)
    - ข้อกฎหมาย (ถ้ามี — ว่างได้ ไม่ถือเป็น error)
    """
    doc = PRESET_TEMPLATES["bma_memo_standard_template"].schema.model_copy(deep=True)
    assert lint_gov_document(doc).is_valid is True

    # 1. ขาดต้นเรื่อง -> Error
    d_no_intro = doc.model_copy(deep=True)
    d_no_intro.memo_intro = ""
    res = lint_gov_document(d_no_intro)
    assert any(e.rule_id == "RULE_MEMO_REQUIRED_INTRO" for e in res.errors)

    # 2. ขาดข้อเท็จจริง -> Error
    d_no_facts = doc.model_copy(deep=True)
    d_no_facts.memo_facts = ""
    res = lint_gov_document(d_no_facts)
    assert any(e.rule_id == "RULE_MEMO_REQUIRED_FACTS" for e in res.errors)

    # 3. ขาดข้อพิจารณา -> Error
    d_no_cons = doc.model_copy(deep=True)
    d_no_cons.memo_consideration = ""
    res = lint_gov_document(d_no_cons)
    assert any(e.rule_id == "RULE_MEMO_REQUIRED_CONSIDERATION" for e in res.errors)

    # 4. ไม่มีข้อกฎหมาย -> ยังคง Valid (เพราะข้อกฎหมายเป็น 'ถ้ามี')
    d_no_law = doc.model_copy(deep=True)
    d_no_law.memo_law = None
    res = lint_gov_document(d_no_law)
    assert res.is_valid is True

    # 5. ขาดประโยคลงท้าย -> Error
    d_no_req = doc.model_copy(deep=True)
    d_no_req.memo_request = ""
    res = lint_gov_document(d_no_req)
    assert any(e.rule_id == "RULE_MEMO_REQUIRED_CLOSING" for e in res.errors)


def test_validate_memo_completeness():
    """ตรวจสอบ method validate_memo_completeness ในโมเดล"""
    doc = PRESET_TEMPLATES["bma_memo_kickboxing_dept"].schema.model_copy(deep=True)
    assert doc.validate_memo_completeness() == []

    doc.memo_intro = ""
    doc.memo_law = None  # law can be None, still should not be in missing
    assert doc.validate_memo_completeness() == ["ต้นเรื่อง"]


def test_word_export_kickboxing_memo(tmp_path):
    """ทดสอบส่งออก Word เอกสารคิกบ็อกซิ่งระดับสำนัก มีครบทุกหัวข้อ"""
    doc = PRESET_TEMPLATES["bma_memo_kickboxing_dept"].schema.model_copy(deep=True)
    out_file = tmp_path / "kickboxing_memo.docx"
    export_govdoc_to_docx(doc, str(out_file))
    assert out_file.exists() and out_file.stat().st_size > 5000
    d = docx.Document(str(out_file))
    full_text = "\n".join(p.text for p in d.paragraphs).replace("\u200b", "")
    assert "ต้นเรื่อง" in full_text
    assert "ข้อกฎหมาย" in full_text
    assert "ข้อเท็จจริง" in full_text
    assert "ข้อพิจารณาและเสนอแนะ" in full_text
    assert "พระราชบัญญัติเครื่องหมายราชการ" in full_text
    assert "ผู้ว่าราชการกรุงเทพมหานคร" in full_text

"""
test_phase7_ocr_and_profile.py — การทดสอบระบบ Multi-Engine OCR, Fail-Safe Ingestion,
User Organization Profile และ Linter Rule ตรวจจับชื่อไฟล์ดิบ
"""

import os
import pytest
from pathlib import Path

from core.models import (
    GovDocumentSchema,
    DocType,
    SourceDocumentContext,
    UserProfileSchema,
    MemoHierarchyLevel
)
from core.profile_manager import (
    get_user_profile,
    save_user_profile,
    get_default_profile,
    reset_to_default_profile
)
from core.linter import lint_gov_document
from core.ai_drafter import draft_from_context_rule_based, DraftingIntent
from core.extractor import (
    clean_thai_intra_word_spaces,
    parse_govdoc_metadata,
    extract_source_document,
    extract_from_raw_text
)


def test_user_profile_schema_and_persistence(tmp_path):
    """ทดสอบการสร้าง บันทึก และโหลดโปรไฟล์หน่วยงานของผู้ใช้"""
    reset_to_default_profile()
    prof = get_user_profile()
    assert "สำนักวัฒนธรรม" in prof.dept_name
    assert "กองการกีฬา" in prof.division_name
    assert prof.signatory_name == "(นายสิงห์ ลิ้มพิรัตน์)"

    # ปรับแต่งโปรไฟล์
    prof.signatory_name = "(นายสมชาย พัฒนารัฐ)"
    prof.division_name = "กองการกีฬาและนันทนาการ"
    save_user_profile(prof)

    loaded = get_user_profile()
    assert loaded.signatory_name == "(นายสมชาย พัฒนารัฐ)"
    assert loaded.division_name == "กองการกีฬาและนันทนาการ"

    # รีเซ็ตกลับค่าเริ่มต้น
    reset_to_default_profile()
    restored = get_user_profile()
    assert restored.signatory_name == "(นายสิงห์ ลิ้มพิรัตน์)"


def test_linter_rule_filename_in_metadata():
    """ทดสอบ Linter Rule: RULE_FILENAME_IN_METADATA ตรวจจับชื่อไฟล์ดิบใน Subject และ References"""
    # 1. กรณีพบ .pdf ใน subject
    doc_bad_sub = GovDocumentSchema(
        doc_number="กท ๐๒๐๔/๑๒๓",
        dept_name="สำนักวัฒนธรรม กีฬา และการท่องเที่ยว",
        doc_date="๑๕ มีนาคม ๒๕๖๙",
        subject="รายงานการพิจารณาหนังสืองานวิ่งเปี้ยว-2569.pdf",
        salutation="เรียน ผู้ว่าราชการกรุงเทพมหานคร",
        paragraph_reason="ด้วย มีหนังสือประสานงานเรื่องดังกล่าว",
        paragraph_purpose="จึงเรียนมาเพื่อโปรดทราบ",
        signatory_name="(นายสิงห์ ลิ้มพิรัตน์)",
        signatory_position="ผู้อำนวยการสำนักวัฒนธรรม กีฬา และการท่องเที่ยว",
        contact_dept="กองการกีฬา"
    )
    res_sub = lint_gov_document(doc_bad_sub)
    assert not res_sub.is_valid
    rule_ids = [i.rule_id for i in res_sub.errors]
    assert "RULE_FILENAME_IN_METADATA" in rule_ids

    # 2. กรณีพบ .docx ใน references
    doc_bad_ref = GovDocumentSchema(
        doc_number="กท ๐๒๐๔/๑๒๓",
        dept_name="สำนักวัฒนธรรม กีฬา และการท่องเที่ยว",
        doc_date="๑๕ มีนาคม ๒๕๖๙",
        subject="รายงานการพิจารณาคำขอใช้สถานที่",
        salutation="เรียน ผู้ว่าราชการกรุงเทพมหานคร",
        references=["เอกสารคำร้อง_2569.docx"],
        paragraph_reason="ด้วย มีหนังสือประสานงานเรื่องดังกล่าว",
        paragraph_purpose="จึงเรียนมาเพื่อโปรดทราบ",
        signatory_name="(นายสิงห์ ลิ้มพิรัตน์)",
        signatory_position="ผู้อำนวยการสำนักวัฒนธรรม กีฬา และการท่องเที่ยว",
        contact_dept="กองการกีฬา"
    )
    res_ref = lint_gov_document(doc_bad_ref)
    assert not res_ref.is_valid
    assert any(i.rule_id == "RULE_FILENAME_IN_METADATA" for i in res_ref.errors)

    # 3. กรณีถูกต้อง ไม่มีชื่อไฟล์
    doc_clean = GovDocumentSchema(
        doc_number="กท ๐๒๐๔/๑๒๓",
        dept_name="สำนักวัฒนธรรม กีฬา และการท่องเที่ยว",
        doc_date="๑๕ มีนาคม ๒๕๖๙",
        subject="รายงานการพิจารณาคำขอใช้สถานที่",
        salutation="เรียน ผู้ว่าราชการกรุงเทพมหานคร",
        references=["หนังสือสมาคมวิ่งเปี้ยวประเทศไทย ที่ สวปท. ๑๕/๒๕๖๙ ลงวันที่ ๒๓ กันยายน ๒๕๖๙"],
        paragraph_reason="ด้วย มีหนังสือประสานงานเรื่องดังกล่าว",
        paragraph_purpose="จึงเรียนมาเพื่อโปรดทราบ",
        signatory_name="(นายสิงห์ ลิ้มพิรัตน์)",
        signatory_position="ผู้อำนวยการสำนักวัฒนธรรม กีฬา และการท่องเที่ยว",
        contact_dept="กองการกีฬา"
    )
    res_clean = lint_gov_document(doc_clean)
    assert not any(i.rule_id == "RULE_FILENAME_IN_METADATA" for i in res_clean.issues)


def test_ai_drafter_fail_safe_blocks_empty_extraction():
    """ทดสอบ Fail-Safe: ห้ามยกร่างหาก extraction_failed=True หรือไม่มีข้อความสกัดได้"""
    ctx_failed = SourceDocumentContext(
        source_filename="งานสแกนที่อ่านไม่ออก.pdf",
        raw_text="",
        summary="",
        extraction_failed=True,
        extraction_error="OCR Failed"
    )
    with pytest.raises(ValueError, match="ไม่สามารถยกร่างหนังสือได้"):
        draft_from_context_rule_based(ctx_failed, doc_type=DocType.INTERNAL)

    ctx_empty = SourceDocumentContext(
        source_filename="empty.pdf",
        raw_text="   ",
        summary=""
    )
    with pytest.raises(ValueError, match="ไม่สามารถยกร่างหนังสือได้"):
        draft_from_context_rule_based(ctx_empty, doc_type=DocType.INTERNAL)


def test_ai_drafter_never_uses_filename_in_subject_or_ref():
    """ทดสอบว่า AI Drafter จะไม่นำชื่อไฟล์ดิบมาใส่ใน Subject หรือ References เด็ดขาด"""
    ctx = SourceDocumentContext(
        source_filename="เจ้าภาพวิ่งเปี้ยว-2569.pdf",
        source_dept="สมาคมวิ่งเปี้ยวประเทศไทย",
        source_doc_no=None,
        source_date=None,
        source_subject=None,
        raw_text="สมาคมวิ่งเปี้ยวประเทศไทยขอความอนุเคราะห์ใช้อาคารกีฬาเวสน์ ๑ ศูนย์เยาวชนกรุงเทพมหานคร",
        summary="ขอความอนุเคราะห์ใช้อาคารกีฬาเวสน์ ๑"
    )
    draft = draft_from_context_rule_based(ctx, doc_type=DocType.INTERNAL, intent=DraftingIntent.MEMO_REVIEW)
    
    assert ".pdf" not in draft.subject
    assert "เจ้าภาพวิ่งเปี้ยว-2569" not in draft.subject
    assert "[✏️ ระบุเรื่อง]" in draft.subject

    if draft.references:
        for ref in draft.references:
            assert ".pdf" not in ref
            assert "เจ้าภาพวิ่งเปี้ยว-2569" not in ref


def test_ai_drafter_uses_user_profile_defaults():
    """ทดสอบว่า AI Drafter ดึงค่าจาก User Organization Profile แทนค่า Hardcode DGA"""
    reset_to_default_profile()
    ctx = SourceDocumentContext(
        source_filename="test.txt",
        source_dept="กระทรวงมหาดไทย",
        source_doc_no="มท ๐๒๐๑/๕๕",
        source_date="๑๐ มกราคม ๒๕๖๙",
        source_subject="ขอความร่วมมือจัดกิจกรรม",
        raw_text="ข้อความทดสอบ",
        summary="สรุป"
    )
    draft_internal = draft_from_context_rule_based(ctx, doc_type=DocType.INTERNAL)
    # ต้องมีชื่อสำนักวัฒนธรรม กีฬา และการท่องเที่ยว
    assert "สำนักวัฒนธรรม กีฬา และการท่องเที่ยว" in draft_internal.dept_name
    assert draft_internal.signatory_name == "(นายสิงห์ ลิ้มพิรัตน์)"
    assert "กองการกีฬา" in draft_internal.contact_dept


def test_ocr_space_cleaning_and_date_parsing():
    """ทดสอบการยุบช่องว่างตัวอักษรไทยจากการ OCR และการสกัดวันที่แบบไม่มีช่องว่าง"""
    spaced_thai = "ส ม า ค ม ว ิ ่ ง เบ ี ้ ย ว ป ร ะ เท ศ ไท ย"
    cleaned = clean_thai_intra_word_spaces(spaced_thai)
    assert cleaned == "สมาคมวิ่งเบี้ยวประเทศไทย"

    sample_ocr = (
        "สมาคมวิ่งเบี้ยวประเทศไทย\n"
        "ที่สวปท . ๑๕ / ๒๕๒๑\n"
        "วันที่๒๓กันยายน๒๕๒๑\n"
        "เรียนผู้ว่าราชการกรุงเทพมหานคร\n"
        "มีแผนดำเนินการจัดการแข่งขันกีฬาวิ่งเบี้ยวชิงแชมป์แห่งประเทศไทย\n"
    )
    meta = parse_govdoc_metadata(sample_ocr)
    assert meta["dept"] == "สมาคมวิ่งเบี้ยวประเทศไทย"
    assert "สวปท" in meta["doc_no"]
    assert "๒๓ กันยายน ๒๕๒๑" == meta["doc_date"]
    assert meta["salutation"] == "ผู้ว่าราชการกรุงเทพมหานคร"
    assert "การจัดการแข่งขัน" in meta["subject"]


@pytest.mark.requires_ocr
def test_extract_source_document_real_scanned_pdf():
    """ทดสอบการประมวลผลไฟล์สแกนจริง งานวิ่งเปี้ยว-2569.pdf ผ่าน Docker Tesseract"""
    pdf_path = Path("uploads/งานวิ่งเปี้ยว-2569.pdf")
    if not pdf_path.exists():
        pytest.skip("ไฟล์ uploads/งานวิ่งเปี้ยว-2569.pdf ไม่มีอยู่ในเครื่อง")

    ctx = extract_source_document(str(pdf_path))
    assert not ctx.extraction_failed
    assert ctx.ocr_engine_used is not None
    assert ctx.source_dept == "สมาคมวิ่งเบี้ยวประเทศไทย"
    assert "สวปท" in (ctx.source_doc_no or "")
    assert len(ctx.raw_text) > 500

"""
test_phase4_ekkasarn_features.py — ชุดทดสอบสำหรับฟีเจอร์ที่พัฒนาตามโมเดล Ekkasarn / Modern GovDoc Studio
ครอบคลุม:
1. Smart Placeholder Detection & Counting ([ระบุ...])
2. Intent ใหม่: MEMO_REVIEW (รายงานการพิจารณา / เกษียนหนังสือรวมเรื่องเดิม)
3. การส่งออก references / attachments ในหนังสือภายใน (Word DOCX & Typst)
4. Inline Paragraph Copilot Refinement (เกลาภาษาระดับย่อหน้า)
5. API Placeholders Endpoint
"""

import os
import pytest
from pathlib import Path
from docx import Document

from core.models import GovDocumentSchema, DocType, UrgencyLevel, SecretLevel, SourceDocumentContext
from core.ai_drafter import draft_from_context_rule_based, DraftingIntent
from core.copilot import copilot_refine_paragraph
from core.word_exporter import export_govdoc_to_docx
from core.typst_exporter import generate_typst_content
from core.api import check_placeholders


@pytest.fixture
def sample_context():
    return SourceDocumentContext(
        source_filename="หนังสือขอเชิญเป็นเจ้าภาพร่วม.pdf",
        source_dept="สมาคมวิ่งเปรี้ยวประเทศไทย",
        source_doc_no="สวปท. ๑๑/๒๕๖๘",
        source_date="๒๓ กันยายน ๒๕๖๙",
        source_subject="ขอเชิญเป็นเจ้าภาพร่วมจัดการแข่งขันกีฬาวิ่งเปรี้ยวชิงแชมป์ประเทศไทย",
        source_salutation="เรียน ผู้ว่าราชการกรุงเทพมหานคร",
        is_scanned=False,
        page_count=2,
        raw_text="ด้วย สมาคมวิ่งเปรี้ยวประเทศไทย มีความประสงค์ขอเชิญกรุงเทพมหานครเป็นเจ้าภาพร่วม...",
        summary="สมาคมฯ ขอเชิญ กทม. ร่วมเป็นเจ้าภาพจัดแข่งขันกีฬาวิ่งเปรี้ยวและขอยกเว้นค่าสถานที่",
        core_issues=["ขอเชิญเป็นเจ้าภาพร่วม", "ขอใช้สถานที่อาคารกีฬาเวสน์ ๑", "ขอยกเว้นค่าเช่า"],
        requested_action="ขอความอนุเคราะห์พิจารณาเป็นเจ้าภาพร่วมและสนับสนุนสถานที่"
    )


def test_smart_placeholder_detection():
    """ทดสอบระบบตรวจจับ Smart Placeholder Chips"""
    doc_with_chips = GovDocumentSchema(
        doc_type=DocType.INTERNAL,
        urgency=UrgencyLevel.NORMAL,
        secret=SecretLevel.NORMAL,
        use_thai_numerals=True,
        doc_number="๔ [ระบุเลขที่หนังสือ]",
        dept_name="[✏️ ระบุส่วนราชการ]",
        doc_date="๑๕ พฤศจิกายน ๒๕๖๙",
        subject="รายงานการพิจารณาหนังสือขอเชิญเป็นเจ้าภาพร่วม",
        salutation="เรียน  [✏️ ระบุตำแหน่งผู้บังคับบัญชา]",
        paragraph_reason="ตามที่ สมาคมฯ ได้มีหนังสือขอเชิญร่วมกิจกรรม นั้น",
        paragraph_details="จากการตรวจสอบพบว่ามีความพร้อม",
        paragraph_purpose="ข้อพิจารณาและข้อเสนอ เห็นควรดำเนินการ จึงเรียนมาเพื่อโปรดพิจารณา",
        closing="",
        signatory_name="(นายสมชาย พัฒนารัฐ)",
        signatory_position="นักจัดการงานสารบรรณ",
        contact_dept="กลุ่มงานสารบรรณ"
    )

    placeholders = doc_with_chips.find_placeholders()
    count = doc_with_chips.count_placeholders()

    assert count == 3
    assert any("เลขที่หนังสือ" in p for p in placeholders)
    assert any("ส่วนราชการ" in p for p in placeholders)
    assert any("คำขึ้นต้น" in p for p in placeholders)

    # ทดสอบเอกสารที่ไม่มี placeholder
    doc_clean = doc_with_chips.model_copy(deep=True)
    doc_clean.doc_number = "กท ๐๔๐๑/๑๒๓"
    doc_clean.dept_name = "สำนักวัฒนธรรม กีฬา และการท่องเที่ยว"
    doc_clean.salutation = "เรียน  ผู้ว่าราชการกรุงเทพมหานคร"

    assert doc_clean.count_placeholders() == 0
    assert len(doc_clean.find_placeholders()) == 0


def test_memo_review_intent(sample_context):
    """ทดสอบการยกร่างด้วย Intent: MEMO_REVIEW (เกษียนสั่งการรวมกับเรื่องเดิมตามโมเดล Ekkasarn)"""
    draft = draft_from_context_rule_based(
        sample_context, 
        doc_type=DocType.INTERNAL, 
        intent=DraftingIntent.MEMO_REVIEW
    )

    assert draft.doc_type == DocType.INTERNAL
    assert "รายงานการพิจารณา" in draft.subject
    assert "วิ่งเปรี้ยว" in draft.subject
    assert "เรียน" in draft.salutation
    assert "ตามที่ สมาคมวิ่งเปรี้ยวประเทศไทย" in draft.paragraph_reason
    assert "หนังสือที่อ้างถึง" in draft.paragraph_reason
    assert any("สวปท. ๑๑/๒๕๖๘" in ref for ref in draft.references)
    assert "ข้อพิจารณาและข้อเสนอ" in draft.paragraph_purpose
    assert draft.attachments is not None
    assert len(draft.attachments) > 0


def test_internal_doc_references_and_attachments_docx(tmp_path):
    """ทดสอบว่าหนังสือภายใน (.docx) รองรับการแสดงผล อ้างถึง และ สิ่งที่ส่งมาด้วย"""
    out_docx = str(tmp_path / "test_internal_refs.docx")
    doc = GovDocumentSchema(
        doc_type=DocType.INTERNAL,
        urgency=UrgencyLevel.NORMAL,
        secret=SecretLevel.NORMAL,
        use_thai_numerals=True,
        doc_number="กท ๐๔๐๑/ว ๔๕๖",
        dept_name="สำนักการแพทย์ กรุงเทพมหานคร",
        doc_date="๒๐ พฤศจิกายน ๒๕๖๙",
        subject="ขออนุมัติจัดซื้อเวชภัณฑ์ยาเพิ่มเติม",
        salutation="เรียน  ผู้อำนวยการสำนักการแพทย์",
        references=["หนังสือโรงพยาบาลกลาง ที่ กท ๐๕๐๒/๘๙ ลงวันที่ ๑๐ พฤศจิกายน ๒๕๖๙"],
        attachments=["ตารางรายการเวชภัณฑ์ยา จำนวน ๑ ชุด"],
        paragraph_reason="ตามที่ โรงพยาบาลกลาง ได้แจ้งความประสงค์ขอรับการสนับสนุนเวชภัณฑ์ยา นั้น",
        paragraph_details="กลุ่มงานเภสัชกรรมได้ตรวจสอบสต็อกยาแล้วพบว่ามีปริมาณไม่เพียงพอ",
        paragraph_purpose="จึงเรียนมาเพื่อโปรดพิจารณาอนุมัติงบประมาณจัดซื้อเพิ่มเติม",
        closing="",
        signatory_name="(นายแพทย์สมศักดิ์ รักษาดี)",
        signatory_position="หัวหน้ากลุ่มงานเภสัชกรรม",
        contact_dept="กลุ่มงานเภสัชกรรม"
    )

    export_govdoc_to_docx(doc, out_docx)
    assert os.path.exists(out_docx)

    # ตรวจสอบเนื้อหาในไฟล์ Word (ทั้งย่อหน้าและตารางหัวกระดาษ)
    word_doc = Document(out_docx)
    all_text = " ".join([p.text.replace("\u200b", "") for p in word_doc.paragraphs])
    table_text = " ".join([cell.text.replace("\u200b", "") for table in word_doc.tables for row in table.rows for cell in row.cells])
    full_doc_text = f"{all_text} {table_text}"

    assert "บันทึกข้อความ" in full_doc_text
    assert "อ้างถึง" in full_doc_text
    assert "หนังสือโรงพยาบาลกลาง" in full_doc_text
    assert "สิ่งที่ส่งมาด้วย" in full_doc_text
    assert "ตารางรายการเวชภัณฑ์ยา" in full_doc_text


def test_internal_doc_references_and_attachments_typst():
    """ทดสอบว่าโค้ด Typst สำหรับหนังสือภายในมี references และ attachments ครบถ้วน"""
    doc = GovDocumentSchema(
        doc_type=DocType.INTERNAL,
        urgency=UrgencyLevel.NORMAL,
        secret=SecretLevel.NORMAL,
        use_thai_numerals=False,
        doc_number="123/2569",
        dept_name="สำนักวัฒนธรรม",
        doc_date="15 พฤศจิกายน 2569",
        subject="การจัดงานสัปดาห์หนังสือ",
        salutation="เรียน  ผู้อำนวยการกอง",
        references=["หนังสืออ้างอิง ที่ ๑/๒๕๖๙"],
        attachments=["กำหนดการ จำนวน ๑ ฉบับ"],
        paragraph_reason="ตามที่ได้รับมอบหมาย...",
        paragraph_details="ได้เตรียมการเรียบร้อย",
        paragraph_purpose="จึงเรียนมาเพื่อโปรดทราบ",
        closing="",
        signatory_name="(นายวิชัย ชำนาญ)",
        signatory_position="นักวิชาการ",
        contact_dept="กองการศึกษา"
    )

    typst_code = generate_typst_content(doc)
    assert "references:" in typst_code
    assert "หนังสืออ้างอิง ที่ ๑/๒๕๖๙" in typst_code
    assert "attachments:" in typst_code
    assert "กำหนดการ จำนวน ๑ ฉบับ" in typst_code


def test_inline_copilot_refine_paragraph():
    """ทดสอบฟังก์ชันผู้ช่วยเกลาภาษาระดับย่อหน้า (Inline Paragraph Copilot)"""
    # 1. ปรับเป็นทางการ (formal)
    informal_reason = "ด้วยหน่วยงานมีงานเยอะมาก และต้องการความช่วยเหลือจากท่าน"
    formal_reason = copilot_refine_paragraph("reason", informal_reason, "formal")
    assert "จำนวนมาก" in formal_reason
    assert "มีความประสงค์" in formal_reason

    # 2. ย่อให้กระชับ (concise)
    long_text = "ในการนี้ หน่วยงานได้ดำเนินการประชุมหารือร่วมกับทุกฝ่ายแล้ว และมีความยินดีเป็นอย่างยิ่งที่จะสนับสนุน"
    concise_text = copilot_refine_paragraph("details", long_text, "concise")
    assert len(concise_text) <= len(long_text)

    # 3. อ้างอิงระเบียบ (law)
    details_text = "การดำเนินการดังกล่าวได้จัดทำตามขั้นตอนที่ถูกต้อง"
    law_text = copilot_refine_paragraph("details", details_text, "law")
    assert "ระเบียบสำนักนายกรัฐมนตรีว่าด้วยงานสารบรรณ" in law_text

    # 4. ใส่ข้อพิจารณาและข้อเสนอ (propose)
    purpose_text = "จึงเรียนมาเพื่อโปรดพิจารณา"
    propose_text = copilot_refine_paragraph("purpose", purpose_text, "propose")
    assert "ข้อพิจารณาและข้อเสนอ" in propose_text


def test_api_placeholders_endpoint():
    """ทดสอบ API Endpoint /api/v1/placeholders"""
    doc = GovDocumentSchema(
        doc_type=DocType.INTERNAL,
        urgency=UrgencyLevel.NORMAL,
        secret=SecretLevel.NORMAL,
        use_thai_numerals=True,
        doc_number="๔ [ระบุเลขที่หนังสือ]",
        dept_name="[✏️ ระบุส่วนราชการ]",
        doc_date="๑๕ พฤศจิกายน ๒๕๖๙",
        subject="ทดสอบ API",
        salutation="เรียน  [ระบุตำแหน่งผู้รับ]",
        paragraph_reason="เหตุ...",
        paragraph_details="รายละเอียด...",
        paragraph_purpose="จึงเรียนมาเพื่อโปรดทราบ",
        closing="",
        signatory_name="(นายทดสอบ)",
        signatory_position="นักวิชาการ",
        contact_dept="กลุ่มงานทดสอบ"
    )

    res = check_placeholders(doc)
    assert res["count"] == 3
    assert res["has_placeholders"] is True
    assert len(res["placeholders"]) == 3

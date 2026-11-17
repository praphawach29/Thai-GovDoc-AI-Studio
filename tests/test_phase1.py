"""
test_phase1.py — ชุดทดสอบการทำงานของระบบแกนหลัก (Phase 1)
"""

import os
import tempfile
from pathlib import Path
import pytest
from docx import Document
from docx.shared import Cm

from core.models import GovDocumentSchema, DocType, UrgencyLevel, SecretLevel, SourceDocumentContext
from core.thai_segmenter import segment_thai_words, insert_zwsp, to_thai_numerals, to_arabic_numerals
from core.word_exporter import export_govdoc_to_docx
from core.typst_exporter import generate_typst_content, export_govdoc_to_typst
from core.linter import lint_gov_document
from core.extractor import extract_source_document


@pytest.fixture
def sample_external_doc():
    return GovDocumentSchema(
        doc_type=DocType.EXTERNAL,
        urgency=UrgencyLevel.NORMAL,
        secret=SecretLevel.NORMAL,
        use_thai_numerals=False,
        doc_number="ดพร ๐๑๐๒/ว ๑๒๓",
        dept_name="สำนักงานพัฒนารัฐบาลดิจิทัล (องค์การมหาชน)",
        doc_date="๑๕ มีนาคม ๒๕๖๙",
        subject="การขอความอนุเคราะห์วิทยากร",
        salutation="เรียน  อธิบดีกรมสรรพากร",
        references=["หนังสือกรมสรรพากร ที่ กค ๐๗๐๑/๑ ลงวันที่ ๑ มกราคม ๒๕๖๙"],
        attachments=["กำหนดการ จำนวน ๑ ฉบับ"],
        paragraph_reason="ตามที่ กรมสรรพากร ได้มีหนังสือที่อ้างถึง แจ้งความประสงค์ขอความอนุเคราะห์วิทยากร นั้น",
        paragraph_details="สำนักงานพัฒนารัฐบาลดิจิทัล มีความยินดีและไม่ขัดข้องในการให้ความอนุเคราะห์",
        paragraph_purpose="จึงเรียนมาเพื่อโปรดทราบ และดำเนินการต่อไป",
        closing="ขอแสดงความนับถือ",
        signatory_name="(นายสมชาย ดิจิทัล)",
        signatory_position="ผู้อำนวยการฝ่ายพัฒนาเทคโนโลยี",
        contact_dept="ฝ่ายพัฒนาเทคโนโลยี",
        contact_tel="0 2612 6000",
        contact_fax="0 2612 6001",
        contact_email="contact@dga.or.th"
    )


@pytest.fixture
def sample_internal_doc():
    return GovDocumentSchema(
        doc_type=DocType.INTERNAL,
        urgency=UrgencyLevel.NORMAL,
        secret=SecretLevel.NORMAL,
        use_thai_numerals=False,
        doc_number="๑๒๓/๒๕๖๙",
        dept_name="ฝ่ายพัฒนาเทคโนโลยี สำนักงานพัฒนารัฐบาลดิจิทัล",
        doc_date="๑๕ มีนาคม ๒๕๖๙",
        subject="ขออนุมัติจัดโครงการสัมมนาเชิงปฏิบัติการ",
        salutation="เรียน  ผู้อำนวยการสำนักงานพัฒนารัฐบาลดิจิทัล",
        paragraph_reason="ด้วย ฝ่ายพัฒนาเทคโนโลยี มีความประสงค์จะจัดโครงการสัมมนาเชิงปฏิบัติการ",
        paragraph_details="การจัดสัมมนาดังกล่าวมีวัตถุประสงค์เพื่อยกระดับทักษะบุคลากร",
        paragraph_purpose="จึงเรียนมาเพื่อโปรดพิจารณาอนุมัติงบประมาณ",
        closing="",
        signatory_name="(นายวิชาการ มุ่งมั่น)",
        signatory_position="หัวหน้าฝ่ายพัฒนาเทคโนโลยี",
        contact_dept="ฝ่ายพัฒนาเทคโนโลยี",
        contact_tel="0 2612 6000"
    )


# -------------------------------------------------------------
# 1. ทดสอบ Thai Segmenter & ZWSP
# -------------------------------------------------------------
def test_thai_segmenter():
    text = "หนังสือราชการตามระเบียบสำนักนายกรัฐมนตรี"
    tokens = segment_thai_words(text)
    assert len(tokens) > 1
    # PyThaiNLP อาจคงคำประสม "หนังสือราชการ" เป็นคำเดียว ส่วน fallback จะแยกคำ
    assert "".join(tokens) == text
    assert any(t in tokens for t in ("หนังสือ", "ราชการ", "หนังสือราชการ"))

    # ทดสอบการแทรก ZWSP (\u200b)
    zwsp_text = insert_zwsp(text)
    assert "\u200b" in zwsp_text


def test_numeral_conversion():
    arabic = "12345"
    thai = to_thai_numerals(arabic)
    assert thai == "๑๒๓๔๕"
    assert to_arabic_numerals(thai) == arabic


# -------------------------------------------------------------
# 2. ทดสอบ Word Export (หนังสือภายนอก และ ภายใน)
# -------------------------------------------------------------
def test_word_export_external(sample_external_doc, tmp_path):
    out_file = tmp_path / "test_external.docx"
    result_path = export_govdoc_to_docx(sample_external_doc, str(out_file))
    assert Path(result_path).exists()
    assert Path(result_path).stat().st_size > 0

    # เปิดไฟล์ Word และตรวจสอบคุณสมบัติตามระเบียบ
    doc = Document(result_path)
    section = doc.sections[0]
    
    # ตรวจสอบขอบกระดาษ (ซ้าย 3 ซม., ขวา 2 ซม., บน 2.5 ซม., ล่าง 2 ซม.)
    assert round(section.left_margin.cm, 1) == 3.0
    assert round(section.right_margin.cm, 1) == 2.0
    assert round(section.top_margin.cm, 1) == 2.5
    assert round(section.bottom_margin.cm, 1) == 2.0

    # ตรวจสอบข้อความสำคัญและยืนยันว่ามีการแทรก ZWSP (\u200b) สำหรับการตัดคำ
    full_text = "\n".join([p.text for p in doc.paragraphs])
    assert "\u200b" in full_text
    clean_text = full_text.replace("\u200b", "")
    assert "การขอความอนุเคราะห์วิทยากร" in clean_text
    assert "ขอแสดงความนับถือ" in clean_text


def test_word_export_internal(sample_internal_doc, tmp_path):
    out_file = tmp_path / "test_internal.docx"
    result_path = export_govdoc_to_docx(sample_internal_doc, str(out_file))
    assert Path(result_path).exists()
    assert Path(result_path).stat().st_size > 0

    doc = Document(result_path)
    section = doc.sections[0]
    
    # ตรวจสอบขอบกระดาษหนังสือภายใน (บน 1.5 ซม. ตามแบบ กทม./ช่วง 1.5–2.0 ซม.)
    assert round(section.top_margin.cm, 1) == 1.5

    # "เรื่อง" ของบันทึกข้อความอยู่ในตาราง ๒ ช่อง (เส้นประเฉพาะบรรทัดแรก) — รวมข้อความในตารางด้วย
    cell_text = [p.text for t in doc.tables for c in t._cells for p in c.paragraphs]
    full_text = "\n".join([p.text for p in doc.paragraphs] + cell_text)
    assert "\u200b" in full_text
    clean_text = full_text.replace("\u200b", "")
    assert "ขออนุมัติจัดโครงการสัมมนาเชิงปฏิบัติการ" in clean_text
    assert "จึงเรียนมาเพื่อโปรดพิจารณาอนุมัติงบประมาณ" in clean_text


# -------------------------------------------------------------
# 3. ทดสอบ Typst Template Generation
# -------------------------------------------------------------
def test_typst_template_generation(sample_external_doc, sample_internal_doc, tmp_path):
    # ทดสอบหนังสือภายนอก
    ext_content = generate_typst_content(sample_external_doc)
    assert "#import \"templates/typst/external.typ\"" in ext_content
    assert "govdoc_external" in ext_content
    assert sample_external_doc.subject in ext_content

    # ทดสอบบันทึกไฟล์ .typ
    out_typ = tmp_path / "test_ext.typ"
    export_govdoc_to_typst(sample_external_doc, str(out_typ))
    assert out_typ.exists()
    assert out_typ.stat().st_size > 0

    # ทดสอบหนังสือภายใน
    int_content = generate_typst_content(sample_internal_doc)
    assert "#import \"templates/typst/internal.typ\"" in int_content
    assert "govdoc_internal" in int_content


# -------------------------------------------------------------
# 4. ทดสอบ Sarabun Rules Linter
# -------------------------------------------------------------
def test_linter_valid_document(sample_external_doc):
    res = lint_gov_document(sample_external_doc)
    assert res.is_valid is True
    assert len(res.errors) == 0


def test_linter_invalid_date_prefix(sample_external_doc):
    # ทดสอบใส่คำว่า "วันที่" นำหน้าวัน
    sample_external_doc.doc_date = "วันที่ ๑๕ มีนาคม ๒๕๖๙"
    res = lint_gov_document(sample_external_doc)
    assert res.is_valid is False
    assert any(e.rule_id == "RULE_NO_PREFIX_DATE" for e in res.errors)


def test_linter_high_official_mismatch(sample_external_doc):
    # ส่งถึงนายกรัฐมนตรี แต่ใช้คำขึ้นต้น "เรียน"
    sample_external_doc.salutation = "เรียน  นายกรัฐมนตรี"
    sample_external_doc.closing = "ขอแสดงความนับถือ"
    res = lint_gov_document(sample_external_doc)
    assert res.is_valid is False
    assert any(e.rule_id == "RULE_HIGH_OFFICIAL_SALUTATION" for e in res.errors)
    assert any(e.rule_id == "RULE_HIGH_OFFICIAL_CLOSING" for e in res.errors)


# -------------------------------------------------------------
# 5. ทดสอบ Ingestion Extractor & AI Drafter
# -------------------------------------------------------------
def test_extractor_with_text_file(tmp_path):
    sample_text = """
    ที่ กค ๐๑๐๐/๕๕๕
    กระทรวงการคลัง ถนนพระรามที่ ๖ กรุงเทพฯ
    ๒๐ กุมภาพันธ์ ๒๕๖๙
    เรื่อง ขอเชิญร่วมประชุมคณะกรรมการ
    เรียน อธิบดีกรมบัญชีกลาง
    
    ด้วย กระทรวงการคลัง มีกำหนดจัดประชุม...
    """
    txt_file = tmp_path / "source_doc.txt"
    txt_file.write_text(sample_text, encoding="utf-8")

    ctx = extract_source_document(str(txt_file))
    assert ctx.source_filename == "source_doc.txt"
    assert "กระทรวงการคลัง" in ctx.source_dept or "ไม่ระบุ" in ctx.source_dept
    assert len(ctx.raw_text) > 0


def test_extractor_with_docx_file(sample_external_doc, tmp_path):
    docx_file = tmp_path / "source_letter.docx"
    export_govdoc_to_docx(sample_external_doc, str(docx_file))
    
    ctx = extract_source_document(str(docx_file))
    assert ctx.source_filename == "source_letter.docx"
    assert len(ctx.raw_text) > 0
    assert "การขอความอนุเคราะห์วิทยากร" in ctx.raw_text.replace("\u200b", "")


def test_ai_drafter_from_context(tmp_path):
    sample_text = "เรื่อง ขอความอนุเคราะห์วิทยากร จาก มหาวิทยาลัยเชียงใหม่ วันที่ ๕ มีนาคม ๒๕๖๙"
    txt_file = tmp_path / "request.txt"
    txt_file.write_text(sample_text, encoding="utf-8")
    
    ctx = extract_source_document(str(txt_file))
    from core.ai_drafter import draft_from_context_rule_based, copilot_refine_text
    
    draft = draft_from_context_rule_based(ctx, doc_type=DocType.EXTERNAL)
    assert draft.doc_type == DocType.EXTERNAL
    assert draft.paragraph_reason.startswith("ตามที่") or draft.paragraph_reason.startswith("ด้วย")
    assert draft.paragraph_purpose.startswith("จึงเรียนมาเพื่อ")

    # ทดสอบ Copilot Refine
    refined = copilot_refine_text("มีงานเยอะมาก ช่วยดำเนินการด้วย", "formal")
    assert "จำนวนมาก" in refined
    assert "โปรดให้ความอนุเคราะห์" in refined


def test_linter_mixed_numerals(sample_external_doc):
    # ปนเลขไทยและเลขอารบิกในเนื้อความ
    sample_external_doc.paragraph_reason = "ตามที่ ได้ส่งหนังสือ ที่ 1234 เมื่อวันที่ ๑๕ มกราคม"
    res = lint_gov_document(sample_external_doc)
    assert any(w.rule_id == "RULE_MIXED_NUMERALS" for w in res.warnings)

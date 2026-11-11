"""
test_phase2.py — ชุดทดสอบการทำงานของระบบ Phase 2: Ingestion & AI Drafting Engine
"""

import os
from pathlib import Path
import pytest
import numpy as np
import cv2

from core.models import GovDocumentSchema, DocType, UrgencyLevel, SecretLevel, SourceDocumentContext
from core.ocr_preprocessor import deskew_image, enhance_document_contrast, binarize_adaptive, render_pdf_to_images
from core.extractor import parse_govdoc_metadata, extract_source_document
from core.ai_drafter import draft_from_context_rule_based, DraftingIntent
from core.registry import DocumentRegistry, OutgoingRecord, IncomingRecord


# -------------------------------------------------------------
# 1. ทดสอบ OCR Preprocessor
# -------------------------------------------------------------
def test_deskew_image():
    # สร้างภาพจำลองที่มีเส้นข้อความเอียง 5 องศา
    img = np.ones((300, 400), dtype=np.uint8) * 255
    cv2.putText(img, "THAILAND GOV DOC", (50, 150), cv2.FONT_HERSHEY_SIMPLEX, 1.2, 0, 3)
    
    # หมุนภาพ 5 องศา
    M = cv2.getRotationMatrix2D((200, 150), 5.0, 1.0)
    skewed = cv2.warpAffine(img, M, (400, 300), borderValue=255)

    corrected, angle = deskew_image(skewed)
    assert corrected.shape == skewed.shape
    # ต้องตรวจจับองศาความเอียงได้
    assert abs(angle) > 0.1


def test_enhance_contrast_and_binarize():
    img = np.ones((200, 200, 3), dtype=np.uint8) * 200
    cv2.putText(img, "TEST", (30, 100), cv2.FONT_HERSHEY_SIMPLEX, 1, (50, 50, 50), 2)
    
    enhanced = enhance_document_contrast(img)
    assert enhanced.shape == (200, 200)

    binary = binarize_adaptive(enhanced)
    unique_vals = np.unique(binary)
    assert 0 in unique_vals or 255 in unique_vals


# -------------------------------------------------------------
# 2. ทดสอบ Advanced Header Metadata Parsing
# -------------------------------------------------------------
def test_metadata_parsing_complex_govdoc():
    sample_text = """
    ที่ ศธ ๐๒๑๐.๐๔/๑๒๓๔
    กระทรวงศึกษาธิการ ถนนราชดำเนินนอก กรุงเทพฯ ๑๐๓๐๐
    ๑๕ มีนาคม ๒๕๖๙
    เรื่อง ขอเชิญเข้าร่วมการประชุมเชิงปฏิบัติการการใช้เทคโนโลยี AI
    เรียน อธิบดีกรมสรรพากร
    อ้างถึง หนังสือกรมสรรพากร ที่ กค ๐๗๐๑/๙๙๙ ลงวันที่ ๑ มกราคม ๒๕๖๙
    สิ่งที่ส่งมาด้วย กำหนดการประชุม จำนวน ๑ ชุด
    
    ตามที่ กระทรวงศึกษาธิการ ได้มีหนังสือที่อ้างถึง แจ้งความประสงค์... ความละเอียดแจ้งแล้ว นั้น
    """
    meta = parse_govdoc_metadata(sample_text)

    # ตรวจสอบว่าสกัด "ที่" ได้ถูกต้อง และไม่สับสนกับ "ตามที่"
    assert meta["doc_no"] == "ศธ ๐๒๑๐.๐๔/๑๒๓๔"
    assert "๑๕ มีนาคม ๒๕๖๙" in meta["doc_date"]
    assert "ขอเชิญเข้าร่วมการประชุม" in meta["subject"]
    assert "อธิบดีกรมสรรพากร" in meta["salutation"]
    assert "กระทรวงศึกษาธิการ" in meta["dept"]
    assert len(meta["references"]) > 0
    assert "กค ๐๗๐๑/๙๙๙" in meta["references"][0]
    assert len(meta["attachments"]) > 0


# -------------------------------------------------------------
# 3. ทดสอบ AI Drafting Intents
# -------------------------------------------------------------
def test_ai_drafting_intents():
    ctx = SourceDocumentContext(
        source_filename="request.pdf",
        source_dept="มหาวิทยาลัยเชียงใหม่",
        source_doc_no="อว ๑๒๓/๒๕๖๙",
        source_date="๑๐ มีนาคม ๒๕๖๙",
        source_subject="ขอความอนุเคราะห์วิทยากร",
        raw_text="ตามที่ได้ขอความอนุเคราะห์วิทยากร...",
        summary="ขอวิทยากรบรรยาย"
    )

    # 1. เจตนา: ตอบรับ (ACCEPT)
    draft_accept = draft_from_context_rule_based(ctx, doc_type=DocType.EXTERNAL, intent=DraftingIntent.ACCEPT)
    assert "ยินดีและไม่ขัดข้อง" in draft_accept.paragraph_details
    assert "จึงเรียนมาเพื่อโปรดทราบ" in draft_accept.paragraph_purpose

    # 2. เจตนา: ปฏิเสธอย่างสุภาพ (DECLINE)
    draft_decline = draft_from_context_rule_based(ctx, doc_type=DocType.EXTERNAL, intent=DraftingIntent.DECLINE)
    assert "มีความจำเป็นต้องขออภัยที่ไม่สามารถ" in draft_decline.paragraph_details

    # 3. เจตนา: ส่งต่อเรื่อง (FORWARD)
    draft_forward = draft_from_context_rule_based(ctx, doc_type=DocType.EXTERNAL, intent=DraftingIntent.FORWARD)
    assert "อยู่ในอำนาจหน้าที่และความรับผิดชอบของหน่วยงานท่าน" in draft_forward.paragraph_details

    # 4. เจตนา: บันทึกข้อความเสนอผู้บังคับบัญชา (PROPOSAL)
    draft_prop = draft_from_context_rule_based(ctx, doc_type=DocType.INTERNAL, intent=DraftingIntent.PROPOSAL)
    assert draft_prop.doc_type == DocType.INTERNAL
    assert "จึงเรียนมาเพื่อโปรดพิจารณาอนุมัติ" in draft_prop.paragraph_purpose


# -------------------------------------------------------------
# 4. ทดสอบ Registry Workflow
# -------------------------------------------------------------
def test_document_registry(tmp_path):
    test_db = str(tmp_path / "test_edoc.db")
    reg = DocumentRegistry(db_path=test_db)

    # 1. ทดสอบการรันเลขที่หนังสืออัตโนมัติ
    no1 = reg.get_next_doc_number(prefix="กค ๐๔๐๖/")
    no2 = reg.get_next_doc_number(prefix="กค ๐๔๐๖/")
    assert no1 == "กค ๐๔๐๖/1"
    assert no2 == "กค ๐๔๐๖/2"

    # 2. ทดสอบการรันเลขหนังสือเวียน (มี ว.)
    no_cir = reg.get_next_doc_number(prefix="กค ๐๔๐๖/", is_circular=True)
    assert no_cir == "กค ๐๔๐๖/ว 3"

    # 3. ทดสอบการจองเลขหนังสือ
    res_no = reg.reserve_doc_number(prefix="กค ๐๔๐๖/", subject="จองเลขโครงการ AI", reserved_by="นายสมชาย")
    assert "กค ๐๔๐๖/4" in res_no

    # 4. ทดสอบบันทึกทะเบียนส่ง
    rec = OutgoingRecord(
        doc_number=no1,
        doc_type="external",
        subject="ทดสอบการส่งหนังสือ",
        recipient="อธิบดีกรมสรรพากร",
        doc_date="๑๕ มีนาคม ๒๕๖๙",
        status="sent"
    )
    row_id = reg.register_outgoing(rec)
    assert row_id > 0

    outgoing_list = reg.list_outgoing()
    assert len(outgoing_list) >= 2  # รายการส่ง + รายการจองเลข


# -------------------------------------------------------------
# 5. ทดสอบการอ่านไฟล์ต้นเรื่อง DOCX จริง End-to-End
# -------------------------------------------------------------
def test_real_docx_ingestion():
    sample_file = Path("examples/หนังสือภายนอก_ตัวอย่าง.docx")
    if sample_file.exists():
        ctx = extract_source_document(str(sample_file))
        assert ctx.source_filename == "หนังสือภายนอก_ตัวอย่าง.docx"
        assert len(ctx.raw_text) > 0
        assert ctx.source_subject is not None
        assert "วิทยากร" in ctx.source_subject


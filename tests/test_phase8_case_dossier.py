"""
test_phase8_case_dossier.py — การทดสอบระบบแฟ้มสำนวนเรื่องสารบรรณหลายฉบับและสายเกษียนสั่งการ (Phase 8 Case Dossier)
"""

import pytest
from core.models import SourceCase, SourceItem, RoutingNote, SourceDocumentContext, DocType
from core.case_dossier import parse_case_dossier
from core.ai_drafter import draft_from_context_rule_based, DraftingIntent


SAMPLE_DOSSIER_TEXT = """
สมาคมกีฬาวิ่งเปี้ยวแห่งประเทศไทย
ที่ สกวป. ๐๑/๒๕๗๐
วันที่ ๓๐ มกราคม ๒๕๗๐
เรื่อง ขอรับการสนับสนุนการจัดแข่งขันวิ่งเปี้ยวชิงชนะเลิศแห่งประเทศไทย ประจำปี ๒๕๗๐
เรียน ผู้ว่าราชการกรุงเทพมหานคร

ด้วย สมาคมกีฬาวิ่งเปี้ยวแห่งประเทศไทย มีกำหนดจัดการแข่งขันวิ่งเปี้ยวชิงชนะเลิศแห่งประเทศไทย ในวันที่ ๑๕-๑๖ มีนาคม ๒๕๗๐
สมาคมฯ ขอความอนุเคราะห์ใช้สถานที่ อาคารกีฬาเวสน์ ๑ และขอใช้ตราสัญลักษณ์ของกรุงเทพมหานคร ในการประชาสัมพันธ์การแข่งขัน
ทั้งนี้ ขอยกเลิกหนังสือฉบับเดิม ที่ สกวป. ๒๕/๒๕๖๙ ลงวันที่ ๑๖ มกราคม ๒๕๗๐ เนื่องจากมีการเปลี่ยนแปลงวันเวลาจัดการแข่งขัน

--- [PAGE BREAK] ---

บันทึกข้อความเกษียนสั่งการ
เรียน ปลัดกรุงเทพมหานคร
เห็นควรมอบกองการกีฬา สำนักวัฒนธรรม กีฬา และการท่องเที่ยว พิจารณาประสานงานและดำเนินการตามระเบียบต่อไป
(ลงชื่อ) นายวินัย สมบูรณ์
ผอ.สำนักวัฒนธรรม กีฬา และการท่องเที่ยว
๓๑ ม.ค. ๗๐
"""


def test_parse_case_dossier_items():
    case = parse_case_dossier(SAMPLE_DOSSIER_TEXT, filename="วิ่งเปี้ยว-แฟ้มเรื่อง.pdf")
    assert case.case_title == "ขอรับการสนับสนุนการจัดแข่งขันวิ่งเปี้ยวชิงชนะเลิศแห่งประเทศไทย ประจำปี ๒๕๗๐"
    assert len(case.items) >= 1
    
    first_item = case.items[0]
    assert "วิ่งเปี้ยว" in first_item.sender
    assert first_item.doc_no == "สกวป.๐๑/๒๕๗๐"
    assert "๓๐ มกราคม ๒๕๗๐" in first_item.doc_date


def test_case_dossier_routing_notes():
    case = parse_case_dossier(SAMPLE_DOSSIER_TEXT, filename="วิ่งเปี้ยว-แฟ้มเรื่อง.pdf")
    assert len(case.routing_notes) >= 1
    
    note = case.routing_notes[0]
    assert "ปลัดกรุงเทพมหานคร" in note.target
    assert "เห็นควรมอบกองการกีฬา" in note.order_text
    assert note.signature_present is True


def test_case_dossier_requested_items_and_deadlines():
    case = parse_case_dossier(SAMPLE_DOSSIER_TEXT, filename="วิ่งเปี้ยว-แฟ้มเรื่อง.pdf")
    assert any("ขอความอนุเคราะห์ใช้สถานที่" in req for req in case.requested_items)
    assert any("ขอใช้ตราสัญลักษณ์" in req for req in case.requested_items)
    assert len(case.deadlines) >= 1
    assert any("มีนาคม ๒๕๗๐" in dl for dl in case.deadlines)


def test_synthesize_memo_intro():
    case = parse_case_dossier(SAMPLE_DOSSIER_TEXT, filename="วิ่งเปี้ยว-แฟ้มเรื่อง.pdf")
    intro = case.synthesize_memo_intro()
    
    assert "ตามที่ สมาคมกีฬาวิ่งเปี้ยวแห่งประเทศไทย" in intro
    assert "สกวป.๐๑/๒๕๗๐" in intro
    assert "๓๐ มกราคม ๒๕๗๐" in intro
    assert "ความละเอียดแจ้งแล้ว นั้น" in intro
    assert "บันทึกเกษียนสั่งการตามลำดับชั้น" in intro
    assert "ปลัดกรุงเทพมหานคร" in intro


def test_ai_drafter_integrates_case_dossier():
    case = parse_case_dossier(SAMPLE_DOSSIER_TEXT, filename="วิ่งเปี้ยว-แฟ้มเรื่อง.pdf")
    context = SourceDocumentContext(
        source_filename="งานวิ่งเปี้ยว-2569.pdf",
        source_dept="สมาคมกีฬาวิ่งเปี้ยวแห่งประเทศไทย",
        source_doc_no="สกวป.๐๑/๒๕๗๐",
        source_date="๓๐ มกราคม ๒๕๗๐",
        source_subject="ขอรับการสนับสนุนการจัดแข่งขันวิ่งเปี้ยวชิงชนะเลิศแห่งประเทศไทย",
        raw_text=SAMPLE_DOSSIER_TEXT,
        source_case=case
    )

    doc = draft_from_context_rule_based(
        ctx=context,
        intent=DraftingIntent.MEMO_REVIEW,
        doc_type=DocType.INTERNAL
    )

    # ต้องมีต้นเรื่องที่สังเคราะห์จากสายการเกษียนสั่งการ
    assert doc.memo_intro is not None
    assert "ตามที่ สมาคมกีฬาวิ่งเปี้ยวแห่งประเทศไทย" in doc.memo_intro
    assert "เกษียนสั่งการ" in doc.memo_intro
    
    # ข้อกฎหมายตราสัญลักษณ์ต้องมี (เพราะเรื่องมีตราสัญลักษณ์)
    assert doc.memo_law is not None
    assert "พระราชบัญญัติเครื่องหมายราชการ" in doc.memo_law

    # ข้อเท็จจริงต้องบรรจุคำขอความอนุเคราะห์
    assert doc.memo_facts is not None
    assert "ขอความอนุเคราะห์ใช้สถานที่" in doc.memo_facts or "ตราสัญลักษณ์" in doc.memo_facts


def test_effective_incoming_item_handles_replacement():
    item1 = SourceItem(item_id="doc-old", title="ฉบับเดิม", doc_no="1/2569", doc_date="16 ม.ค. 70", sender="สมาคม", doc_type="external")
    item2 = SourceItem(item_id="doc-new", title="ฉบับใหม่", doc_no="2/2570", doc_date="30 ม.ค. 70", sender="สมาคม", doc_type="external", replaces_item_id="doc-old")
    case = SourceCase(case_title="เรื่องทดสอบ", items=[item1, item2])
    
    effective = case.get_effective_incoming_item()
    assert effective is not None
    assert effective.item_id == "doc-new"
    assert effective.doc_no == "2/2570"

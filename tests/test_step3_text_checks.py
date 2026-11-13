"""
test_step3_text_checks.py — Step 3: ตรวจคำสะกด/ความสอดคล้อง
"""

from core.models import DocType, GovDocumentSchema, SourceDocumentContext
from core.text_checks import check_document_text, check_spelling


def _doc(reason="ข้อความปกติ", details=None, purpose="จึงเรียนมาเพื่อโปรดพิจารณา"):
    return GovDocumentSchema(
        doc_type=DocType.INTERNAL,
        doc_number="......../2569",
        dept_name="สำนักทดสอบ",
        doc_date="13 พฤศจิกายน 2569",
        subject="ทดสอบ",
        salutation="เรียน ผู้อำนวยการ",
        paragraph_reason=reason,
        paragraph_details=details or "",
        paragraph_purpose=purpose,
        closing="",
        signatory_name="(นายทดสอบ)",
        signatory_position="ตำแหน่ง",
        contact_dept="ฝ่าย",
    )


def test_spelling_flags_known_typo():
    doc = _doc(reason="งบประมาณจำนวนทั้งสิน ๑๐๐ บาท")
    issues = check_spelling(doc)
    assert any(i.rule_id == "TEXT_TYPO" for i in issues)


def test_consistency_flags_mixed_numerals():
    doc = _doc(reason="งบประมาณ ๑๐๐ บาท และ 50 ชุด")
    issues = check_document_text(doc)
    assert any(i.rule_id == "TEXT_MIXED_NUMERALS" for i in issues)


def test_consistency_flags_missing_entity():
    doc = _doc(reason="ไม่มีชื่อหน่วยงาน")
    ctx = SourceDocumentContext(
        source_filename="x.txt", source_dept="สมาคมกีฬา", source_subject="เรื่อง",
        raw_text="สมาคมกีฬา ขอใช้สถานที่",
    )
    issues = check_document_text(doc, ctx)
    assert any(i.rule_id == "TEXT_ENTITY_MISSING" for i in issues)

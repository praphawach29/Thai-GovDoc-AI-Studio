"""
test_step2_verification.py — Step 2: ตรวจร่างเทียบต้นเรื่อง
"""

from core.models import DocType, GovDocumentSchema, SourceDocumentContext
from core.verification import verify_draft_against_source


def _doc(subject="ขอความอนุเคราะห์ใช้สถานที่", memo_law=None, references=None, attachments=None,
         reason="ด้วยเหตุผล", details="", purpose="จึงเรียนมาเพื่อโปรดพิจารณา"):
    return GovDocumentSchema(
        doc_type=DocType.INTERNAL,
        doc_number="......../2569",
        dept_name="สำนักทดสอบ",
        doc_date="13 พฤศจิกายน 2569",
        subject=subject,
        salutation="เรียน ผู้อำนวยการ",
        references=references,
        attachments=attachments,
        paragraph_reason=reason,
        paragraph_details=details,
        paragraph_purpose=purpose,
        memo_law=memo_law,
        closing="",
        signatory_name="(นายทดสอบ)",
        signatory_position="ตำแหน่ง",
        contact_dept="ฝ่าย",
    )


def _ctx():
    return SourceDocumentContext(
        source_filename="x.txt",
        source_dept="สมาคมกีฬา",
        source_doc_no="สกท ๑๒/๒๕๖๙",
        source_date="๑๕ มีนาคม ๒๕๖๙",
        source_subject="ขอความอนุเคราะห์ใช้สถานที่",
        raw_text="สมาคมกีฬา ขอความอนุเคราะห์ใช้สถานที่ งบประมาณ ๑๐๐,๐๐๐ บาท วันที่ ๑๕ มีนาคม ๒๕๖๙ ที่ สกท ๑๒/๒๕๖๙",
    )


def test_verification_flags_missing_amount_and_doc_no():
    doc = _doc()
    result = verify_draft_against_source(doc, _ctx())
    ids = {f.rule_id: f for f in result.findings}
    assert "VERIFY_DOC_NO_MISSING" in ids
    assert ids["VERIFY_DOC_NO_MISSING"].evidence_status == "not_found"


def test_verification_flags_unsourced_law():
    doc = _doc(memo_law="พระราชบัญญัติปลอม พ.ศ. ๒๕๐๐")
    result = verify_draft_against_source(doc, _ctx())
    law = next(f for f in result.findings if f.rule_id == "VERIFY_LAW_UNSOURCED")
    assert law.severity == "critical"
    assert result.is_ready is False


def test_verification_ready_when_no_critical():
    doc = _doc(memo_law=None)
    result = verify_draft_against_source(doc, _ctx())
    assert result.is_ready is True

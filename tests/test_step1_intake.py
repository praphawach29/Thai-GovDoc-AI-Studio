"""
test_step1_intake.py — Step 1: ตรวจข้อมูลขาด/ถามกลับ, entity extraction, คลังข้อกฎหมาย
"""

from core.entity_extractor import extract_entities, find_unclear_spans
from core.intake import assess_intake
from core.legal_sources import LegalLibrary, LegalReference, format_legal_citation
from core.models import DocumentKind, SourceDocumentContext


def _ctx(subject="", dept="", requested_action="", entities=None):
    return SourceDocumentContext(
        source_filename="x.txt",
        source_dept=dept or None,
        source_subject=subject or None,
        requested_action=requested_action or None,
        raw_text="",
        entities=entities or [],
    )


def test_assess_intake_asks_for_missing_required_fields():
    result = assess_intake(_ctx(), DocumentKind.EXTERNAL_LETTER)
    fields = [q.field for q in result.questions]
    assert "source_subject" in fields
    assert "source_dept" in fields
    assert result.ready is False


def test_assess_intake_ready_when_required_filled():
    result = assess_intake(
        _ctx(subject="ขอความอนุเคราะห์วิทยากร", dept="มหาวิทยาลัยเชียงใหม่"),
        DocumentKind.EXTERNAL_LETTER,
    )
    assert result.ready is True


def test_assess_intake_conditional_questions():
    ctx = _ctx(subject="ขอความอนุเคราะห์วิทยากร", dept="มหาวิทยาลัยเชียงใหม่")
    result = assess_intake(
        ctx,
        DocumentKind.EXTERNAL_LETTER,
        include_references=True,
        include_attachments=True,
    )
    fields = [q.field for q in result.questions]
    assert "source_doc_no" in fields
    assert "source_date" in fields
    assert "attachments" in fields


def test_extract_entities_and_unclear_spans():
    text = (
        "นายสมชาย ใจดี ขออนุมัติงบประมาณ ๑๐๐,๐๐๐ บาท "
        "ภายในวันที่ ๑๕ มีนาคม ๒๕๖๙ ที่ กท ๑/๒๕๖๙ "
        "สิ่งที่ส่งมาด้วย เอกสาร จำนวน ๑ ชุด จากสำนักวัฒนธรรม"
    )
    entities = extract_entities(text, method="regex")
    kinds = {e.kind for e in entities}
    assert "person" in kinds
    assert "amount" in kinds
    assert "date" in kinds
    assert "doc_no" in kinds
    assert "attachment" in kinds
    assert "agency" in kinds

    unclear = find_unclear_spans("ข้อความ � และ ### ที่อ่านไม่ออก")
    assert len(unclear) >= 2


def test_legal_library_crud_and_citation(tmp_path):
    path = tmp_path / "legal.json"
    lib = LegalLibrary(path=path)

    ref = lib.add(LegalReference(
        title="ระเบียบกรุงเทพมหานครว่าด้วยการทดสอบ",
        section="ข้อ ๑",
        quote="ข้อความอ้างอิงตัวอย่าง",
        verified=False,
        recorded_by="ผู้ทดสอบ",
    ))
    assert lib.list() == [ref]
    assert lib.list(verified_only=True) == []

    updated = lib.update(ref.id, verified=True)
    assert updated is not None
    assert lib.list(verified_only=True)[0].verified is True

    citation = format_legal_citation(lib.list(verified_only=True)[0])
    assert "ระเบียบกรุงเทพมหานครว่าด้วยการทดสอบ" in citation
    assert "ข้อความอ้างอิงตัวอย่าง" in citation

    assert lib.delete(ref.id) is True
    assert lib.list() == []

"""
test_phase12_classifier.py — P1: จำแนกหนังสือ 6 ชนิดและแบบ 1–11
"""

from core.classifier import DocumentKind, classify_source_document
from core.models import SourceDocumentContext


def _ctx(text: str, subject: str = "") -> SourceDocumentContext:
    return SourceDocumentContext(
        source_filename="source.txt",
        source_subject=subject or text[:40],
        raw_text=text,
    )


def test_classify_internal_memo():
    result = classify_source_document(
        _ctx("บันทึกข้อความ เรียน ผู้อำนวยการกอง ขออนุมัติจัดโครงการ")
    )
    assert result.kind == DocumentKind.INTERNAL_MEMO
    assert result.form_no == 2
    assert result.supported is True
    assert result.doc_type.value == "internal"


def test_classify_external_letter():
    result = classify_source_document(
        _ctx("ด้วย มหาวิทยาลัยขอความอนุเคราะห์วิทยากร จึงเรียนมาเพื่อโปรดพิจารณา")
    )
    assert result.kind == DocumentKind.EXTERNAL_LETTER
    assert result.form_no == 1
    assert result.supported is True


def test_classify_directive_and_public_relations():
    directive = classify_source_document(_ctx("คำสั่ง อาศัยอำนาจตามระเบียบ"))
    assert directive.kind == DocumentKind.DIRECTIVE
    assert directive.form_no in (4, 5)
    assert directive.supported is True

    announcement = classify_source_document(_ctx("ประกาศ ประชาสัมพันธ์ แจ้งให้ทราบ"))
    assert announcement.kind == DocumentKind.PUBLIC_RELATIONS
    assert announcement.form_no == 7


def test_classify_stamp_and_evidence():
    stamp = classify_source_document(_ctx("หนังสือประทับตรา ตราประทับแทนการลงชื่อ"))
    assert stamp.kind == DocumentKind.STAMP_LETTER
    assert stamp.form_no == 3

    minutes = classify_source_document(_ctx("รายงานการประชุม ผู้จดบันทึก"))
    assert minutes.kind == DocumentKind.EVIDENCE
    assert minutes.form_no == 11


def test_forced_kind_sets_confidence_one():
    result = classify_source_document(
        _ctx("ข้อความทั่วไป"), forced_kind=DocumentKind.DIRECTIVE
    )
    assert result.kind == DocumentKind.DIRECTIVE
    assert result.confidence == 1.0
    assert result.reasons == ["เลือกชนิดโดยผู้ใช้"]


def test_no_keywords_defaults_to_external_with_low_confidence():
    result = classify_source_document(_ctx("abcdef 12345"))
    assert result.kind == DocumentKind.EXTERNAL_LETTER
    assert result.confidence <= 0.4

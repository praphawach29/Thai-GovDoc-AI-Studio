"""
test_phase13_special_generators.py — P1 ต่อ: generator เอกสารชนิดพิเศษ 4 ชนิด
"""

import zipfile

import pytest

from core.models import DocumentKind, SourceDocumentContext, UserProfileSchema
from core.special_drafter import draft_special_from_context
from core.word_exporter import export_govdoc_to_docx


@pytest.fixture
def ctx():
    return SourceDocumentContext(
        source_filename="source.txt",
        source_dept="สำนักทดสอบ",
        source_subject="การทดสอบเอกสารชนิดพิเศษ",
        raw_text="สำนักทดสอบแจ้งเรื่องทดสอบ",
        summary="การทดสอบเอกสารชนิดพิเศษ",
        core_issues=["ข้อที่หนึ่ง", "ข้อที่สอง"],
    )


@pytest.fixture
def profile():
    return UserProfileSchema()


@pytest.mark.parametrize(
    "kind,form_no,prefix",
    [
        (DocumentKind.STAMP_LETTER, 3, "หนังสือประทับตรา"),
        (DocumentKind.DIRECTIVE, 4, "คำสั่ง"),
        (DocumentKind.PUBLIC_RELATIONS, 7, "ประกาศ"),
        (DocumentKind.EVIDENCE, 10, "หนังสือรับรอง"),
    ],
)
def test_special_generator_creates_draft(ctx, profile, kind, form_no, prefix):
    doc = draft_special_from_context(ctx, kind, form_no, profile)
    assert doc.kind == kind
    assert doc.special_title.startswith(prefix)
    assert doc.doc_number == "[✏️ เลขที่หนังสือ]"
    assert doc.special_items
    assert doc.special_preamble
    assert doc.special_note


def test_special_docx_exports(ctx, profile, tmp_path):
    doc = draft_special_from_context(
        ctx, DocumentKind.DIRECTIVE, 4, profile
    )
    out = tmp_path / "order.docx"
    export_govdoc_to_docx(doc, str(out))
    assert out.exists()
    with zipfile.ZipFile(out) as archive:
        xml = archive.read("word/document.xml").decode("utf-8").replace("\u200b", "")
    assert "คำสั่ง" in xml
    assert "ข้อที่หนึ่ง" in xml


def test_special_drafter_rejects_normal_kinds(ctx, profile):
    with pytest.raises(ValueError):
        draft_special_from_context(
            ctx, DocumentKind.EXTERNAL_LETTER, 1, profile
        )

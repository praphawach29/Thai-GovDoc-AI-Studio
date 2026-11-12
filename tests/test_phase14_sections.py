"""
test_phase14_sections.py — หัวข้อเอกสารอิสระ: เพิ่ม/ลบ/แก้ไข/สลับลำดับ
"""

import zipfile

from core.models import DocumentSection, SectionKind
from core.sections import ensure_sections, sections_from_document, sync_fields_from_sections
from core.templates_library import PRESET_TEMPLATES
from core.word_exporter import export_govdoc_to_docx


def _memo():
    return ensure_sections(
        PRESET_TEMPLATES["bma_general_memo"].schema.model_copy(deep=True)
    )


def test_default_sections_cover_twelve_part_structure():
    doc = _memo()
    kinds = [sec.kind for sec in doc.sections]
    assert kinds[0] == SectionKind.DEPT
    assert SectionKind.NUMBER_DATE in kinds
    assert SectionKind.SUBJECT in kinds
    assert SectionKind.SALUTATION in kinds
    assert SectionKind.INTRO in kinds
    assert SectionKind.LAW in kinds
    assert SectionKind.FACTS in kinds
    assert SectionKind.CONSIDERATION in kinds
    assert SectionKind.CLOSING in kinds
    assert SectionKind.SIGNATURE in kinds


def test_remove_section_updates_legacy_fields_and_export(tmp_path):
    doc = _memo()
    doc.sections = [sec for sec in doc.sections if sec.kind != SectionKind.LAW]
    sync_fields_from_sections(doc)
    assert doc.memo_law is None

    out = tmp_path / "no_law.docx"
    export_govdoc_to_docx(doc, str(out))
    with zipfile.ZipFile(out) as archive:
        xml = archive.read("word/document.xml").decode("utf-8").replace("\u200b", "")
    assert "พระราชบัญญัติ" not in xml


def test_add_custom_section_and_export(tmp_path):
    doc = _memo()
    doc.sections.append(
        DocumentSection(
            kind=SectionKind.CUSTOM,
            label="ข้อสังเกตเพิ่มเติม",
            content="ข้อความทดสอบหัวข้อใหม่",
        )
    )
    sync_fields_from_sections(doc)

    out = tmp_path / "custom.docx"
    export_govdoc_to_docx(doc, str(out))
    with zipfile.ZipFile(out) as archive:
        xml = archive.read("word/document.xml").decode("utf-8").replace("\u200b", "")
    assert "ข้อสังเกตเพิ่มเติม" in xml
    assert "ข้อความทดสอบหัวข้อใหม่" in xml


def test_reorder_sections_changes_export_order(tmp_path):
    doc = _memo()
    intro_idx = next(i for i, s in enumerate(doc.sections) if s.kind == SectionKind.INTRO)
    custom = DocumentSection(kind=SectionKind.CUSTOM, label="หัวข้อแรก", content="ข้อความแรกสุด")
    doc.sections.insert(0, custom)
    sync_fields_from_sections(doc)

    out = tmp_path / "reordered.docx"
    export_govdoc_to_docx(doc, str(out))
    with zipfile.ZipFile(out) as archive:
        xml = archive.read("word/document.xml").decode("utf-8").replace("\u200b", "")
    assert xml.find("หัวข้อแรก") < xml.find("ต้นเรื่อง")


def test_sections_from_document_is_reversible():
    doc = PRESET_TEMPLATES["bma_general_memo"].schema.model_copy(deep=True)
    sections = sections_from_document(doc)
    doc.sections = sections
    sync_fields_from_sections(doc)
    assert doc.subject
    assert doc.signatory_name


def test_disabled_section_is_omitted_from_export(tmp_path):
    doc = _memo()
    law = next(sec for sec in doc.sections if sec.kind == SectionKind.LAW)
    law.enabled = False
    sync_fields_from_sections(doc)

    out = tmp_path / "disabled_law.docx"
    export_govdoc_to_docx(doc, str(out))
    with zipfile.ZipFile(out) as archive:
        xml = archive.read("word/document.xml").decode("utf-8").replace("\u200b", "")
    assert "พระราชบัญญัติ" not in xml


def test_long_department_header_is_compressed(tmp_path):
    doc = _memo()
    dept = next(sec for sec in doc.sections if sec.kind == SectionKind.DEPT)
    dept.content = (
        "สำนักวัฒนธรรม กีฬา และการท่องเที่ยว (กองการกีฬา โทร. ๐ ๒๒๔๖ ๘๐๗๙ "
        "โทรสาร ๐ ๒๒๔๖ ๑๒๘๒) กรุงเทพมหานคร"
    )
    sync_fields_from_sections(doc)

    out = tmp_path / "long_dept.docx"
    export_govdoc_to_docx(doc, str(out))
    with zipfile.ZipFile(out) as archive:
        xml = archive.read("word/document.xml").decode("utf-8")
    assert "w:w w:val=" in xml

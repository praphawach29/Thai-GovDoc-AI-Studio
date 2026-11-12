"""sections.py — แปลงฟิลด์เอกสารเป็นหัวข้ออิสระ และซิงก์กลับ"""

from typing import List, Optional

from core.models import (
    DocumentSection,
    DocumentKind,
    DocType,
    GovDocumentSchema,
    SectionKind,
)


def _sec(kind: SectionKind, content: str, secondary: str = "", label: Optional[str] = None) -> DocumentSection:
    return DocumentSection(
        kind=kind,
        label=label or kind.default_label(),
        content=content or "",
        secondary=secondary or "",
    )


def sections_from_document(doc: GovDocumentSchema) -> List[DocumentSection]:
    """สร้างรายการหัวข้อมาตรฐานจากฟิลด์เดิม (ใช้เมื่อยังไม่มี sections)"""
    sections: List[DocumentSection] = [
        _sec(SectionKind.DEPT, doc.dept_name),
        _sec(SectionKind.NUMBER_DATE, doc.doc_number, doc.doc_date),
        _sec(SectionKind.SUBJECT, doc.subject),
        _sec(SectionKind.SALUTATION, doc.salutation),
    ]
    if doc.references:
        sections.append(_sec(SectionKind.REFERENCES, "\n".join(doc.references)))
    if doc.attachments:
        sections.append(_sec(SectionKind.ATTACHMENTS, "\n".join(doc.attachments)))

    if doc.kind == DocumentKind.INTERNAL_MEMO or doc.doc_type == DocType.INTERNAL:
        sections.extend(
            [
                _sec(SectionKind.INTRO, doc.memo_intro or doc.paragraph_reason),
                _sec(SectionKind.LAW, doc.memo_law or ""),
                _sec(SectionKind.FACTS, doc.memo_facts or doc.paragraph_details or ""),
                _sec(SectionKind.CONSIDERATION, doc.memo_consideration or doc.paragraph_purpose),
                _sec(SectionKind.CLOSING, doc.memo_request or ""),
            ]
        )
    else:
        sections.extend(
            [
                _sec(SectionKind.INTRO, doc.paragraph_reason),
                _sec(SectionKind.DETAILS, doc.paragraph_details or ""),
                _sec(SectionKind.PURPOSE, doc.paragraph_purpose),
                _sec(SectionKind.CLOSING, doc.closing or ""),
            ]
        )

    sections.append(_sec(SectionKind.SIGNATURE, doc.signatory_name, doc.signatory_position))
    return sections


def ensure_sections(doc: GovDocumentSchema) -> GovDocumentSchema:
    if doc.sections is None:
        doc.sections = sections_from_document(doc)
    return doc


def _join_values(values: List[str]) -> str:
    return "\n".join(value for value in values if value).strip()


def sync_fields_from_sections(doc: GovDocumentSchema) -> GovDocumentSchema:
    """เขียนค่าจาก sections กลับไปยังฟิลด์เดิมเพื่อให้ Linter/export เดิมยังทำงานได้"""
    if doc.sections is None:
        return doc

    grouped = {}
    for section in doc.sections:
        grouped.setdefault(section.kind, []).append(section)

    def first(kind: SectionKind) -> str:
        items = grouped.get(kind, [])
        return items[0].content.strip() if items else ""

    doc.dept_name = first(SectionKind.DEPT) or doc.dept_name

    number_sections = grouped.get(SectionKind.NUMBER_DATE, [])
    if number_sections:
        doc.doc_number = number_sections[0].content.strip()
        doc.doc_date = number_sections[0].secondary.strip()
    else:
        doc.doc_number = ""
        doc.doc_date = ""

    doc.subject = first(SectionKind.SUBJECT)
    doc.salutation = first(SectionKind.SALUTATION)

    refs = first(SectionKind.REFERENCES)
    doc.references = [line.strip() for line in refs.splitlines() if line.strip()] or None
    atts = first(SectionKind.ATTACHMENTS)
    doc.attachments = [line.strip() for line in atts.splitlines() if line.strip()] or None

    intro = first(SectionKind.INTRO)
    facts = first(SectionKind.FACTS)
    law = first(SectionKind.LAW)
    consideration = first(SectionKind.CONSIDERATION)
    details = first(SectionKind.DETAILS)
    purpose = first(SectionKind.PURPOSE)
    closing = first(SectionKind.CLOSING)

    if doc.kind == DocumentKind.INTERNAL_MEMO or doc.doc_type == DocType.INTERNAL:
        doc.memo_intro = intro or None
        doc.memo_law = law or None
        doc.memo_facts = facts or None
        doc.memo_consideration = consideration or None
        doc.memo_request = closing or None
        doc.paragraph_reason = intro or ""
        doc.paragraph_details = facts or None
        doc.paragraph_purpose = consideration or ""
        doc.closing = ""
    else:
        doc.paragraph_reason = intro or ""
        doc.paragraph_details = details or None
        doc.paragraph_purpose = purpose or ""
        doc.closing = closing

    sig = grouped.get(SectionKind.SIGNATURE, [])
    if sig:
        doc.signatory_name = sig[0].content.strip()
        doc.signatory_position = sig[0].secondary.strip()
    else:
        doc.signatory_name = ""
        doc.signatory_position = ""
    return doc

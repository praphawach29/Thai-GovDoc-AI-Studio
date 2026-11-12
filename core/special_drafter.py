"""
special_drafter.py — สร้างร่างเอกสารชนิดพิเศษ 4 ชนิด
(หนังสือประทับตรา / หนังสือสั่งการ / หนังสือประชาสัมพันธ์ / หนังสือรับรอง-รายงานการประชุม)

ใช้ template แบบกฎ (rule-based) เพื่อให้ได้โครงสร้างเริ่มต้นที่ผู้ใช้แก้ต่อได้
"""

from typing import List

from core.models import (
    DocType,
    DocumentKind,
    GovDocumentSchema,
    SourceDocumentContext,
    UserProfileSchema,
)
from core.thai_date import blank_doc_number, format_thai_date


PREFIX_BY_FORM = {
    3: "หนังสือประทับตรา",
    4: "คำสั่ง",
    5: "ระเบียบ",
    6: "ข้อบังคับ",
    7: "ประกาศ",
    8: "แถลงการณ์",
    9: "ข่าว",
    10: "หนังสือรับรอง",
    11: "รายงานการประชุม",
}


def _clean_items(ctx: SourceDocumentContext) -> List[str]:
    items = [line.strip(" -•\t") for line in (ctx.core_issues or []) if line.strip()]
    return items[:6] or ["[✏️ ระบุข้อความข้อที่ ๑]", "[✏️ ระบุข้อความข้อที่ ๒]"]


def _preamble_for(kind: DocumentKind, form_no: int, ctx: SourceDocumentContext) -> str:
    sender = ctx.source_dept or "[✏️ ระบุหน่วยงาน]"
    summary = (ctx.summary or "").strip() or "[✏️ ระบุเหตุผล/ความเป็นมา]"
    if kind == DocumentKind.DIRECTIVE:
        return (
            f"อาศัยอำนาจตาม[✏️ ระบุกฎหมาย/ระเบียบที่ให้อำนาจ] และเพื่อให้การดำเนินงาน"
            f"ของ{sender}เป็นไปด้วยความเรียบร้อย จึงกำหนดหลักเกณฑ์ดังต่อไปนี้"
        )
    if kind == DocumentKind.PUBLIC_RELATIONS:
        return f"ด้วย {sender} มีกำหนดดำเนินการเรื่อง{summary} จึงประกาศให้ทราบโดยทั่วกัน"
    if kind == DocumentKind.EVIDENCE:
        if form_no == 11:
            return "การประชุมได้พิจารณาเรื่องต่าง ๆ ตามระเบียบวาระ และมีมติดังต่อไปนี้"
        return "ขอรับรองว่าข้อความต่อไปนี้เป็นความจริงทุกประการ"
    if kind == DocumentKind.STAMP_LETTER:
        return f"ด้วย {sender} มีความประสงค์จะแจ้งเรื่อง{summary} จึงเรียนมาเพื่อโปรดทราบ"
    return summary


def _note_for(kind: DocumentKind, form_no: int) -> str:
    if kind == DocumentKind.DIRECTIVE:
        return "ทั้งนี้ ตั้งแต่บัดนี้เป็นต้นไป"
    if kind == DocumentKind.PUBLIC_RELATIONS:
        return "ประกาศ ณ วันที่[✏️ ระบุวันที่ประกาศ]"
    if kind == DocumentKind.EVIDENCE and form_no == 11:
        return "จึงเรียนมาเพื่อโปรดทราบ"
    if kind == DocumentKind.STAMP_LETTER:
        return "จึงเรียนมาเพื่อโปรดทราบ"
    return "ขอรับรองว่าข้อความข้างต้นถูกต้องตรงกับความเป็นจริง"


def draft_special_from_context(
    ctx: SourceDocumentContext,
    kind: DocumentKind,
    form_no: int,
    profile: UserProfileSchema,
    use_thai_numerals: bool = False,
) -> GovDocumentSchema:
    """สร้างร่างเอกสารชนิดพิเศษจากบริบทต้นเรื่อง (ผู้ใช้แก้ต่อได้)"""
    if kind in (DocumentKind.EXTERNAL_LETTER, DocumentKind.INTERNAL_MEMO):
        raise ValueError("kind นี้ต้องใช้ draft_from_context_rule_based/llm")

    prefix = PREFIX_BY_FORM.get(form_no, kind.thai_label())
    title = f"{prefix}{profile.dept_name}"
    subject = (ctx.source_subject or "[✏️ ระบุเรื่อง]").strip()
    preamble = _preamble_for(kind, form_no, ctx)
    items = _clean_items(ctx)
    note = _note_for(kind, form_no)

    return GovDocumentSchema(
        doc_type=DocType.EXTERNAL,
        kind=kind,
        special_title=title,
        special_preamble=preamble,
        special_items=items,
        special_note=note,
        urgency="normal",
        secret="normal",
        use_thai_numerals=use_thai_numerals,
        doc_number=blank_doc_number(use_thai_numerals=use_thai_numerals),
        dept_name=profile.department_full or profile.dept_name,
        doc_date=format_thai_date(use_thai_numerals=use_thai_numerals),
        subject=subject,
        salutation="เรียน [✏️ ระบุผู้รับ/ผู้เกี่ยวข้อง]",
        references=None,
        attachments=None,
        paragraph_reason=preamble,
        paragraph_details="\n".join(items),
        paragraph_purpose=note,
        closing="ขอแสดงความนับถือ",
        signatory_name=profile.signatory_name,
        signatory_position=profile.signatory_position,
        contact_dept=profile.contact_dept,
        contact_tel=profile.contact_tel,
        contact_fax=profile.contact_fax,
        contact_email=profile.contact_email,
    )

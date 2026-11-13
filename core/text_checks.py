"""
text_checks.py — ตรวจคำสะกดและความสอดคล้องของข้อความ (ไม่แก้ข้อความอัตโนมัติ)

ให้ผลเป็นข้อเสนอแนะที่ผู้ใช้เลือกยอมรับ/ปฏิเสธ โดยแยก severity: critical / warning / info
"""

import re
from typing import List, Literal, Optional

from pydantic import BaseModel, Field

from core.models import GovDocumentSchema, SourceDocumentContext
from core.entity_extractor import extract_entities
from core.thai_segmenter import to_arabic_numerals


# คำที่พบบ่อยในงานราชการ — พิมพ์ผิด → คำที่ควรเป็น (แก้แบบอนุรักษ์นิยม)
COMMON_TYPOS = {
    "กทม.": "กรุงเทพมหานคร",
    "โทรสับ": "โทรสาร",
    "โทรสับ": "โทรสาร",
    "จำนวนทั้งสิน": "จำนวนทั้งสิ้น",
    "จึงเรียนมาเพื่อโปรดทราบ": "จึงเรียนมาเพื่อโปรดทราบ",
    "ข้าพเจ้า": "ข้าพเจ้า",
}


class TextCheckIssue(BaseModel):
    rule_id: str
    field: str
    severity: Literal["critical", "warning", "info"] = "warning"
    text: str = ""
    suggestion: str = ""
    message: str = ""
    status: Literal["pending", "accepted", "rejected"] = "pending"


def _norm(text: Optional[str]) -> str:
    if not text:
        return ""
    return re.sub(r"[\s\u200b]+", "", to_arabic_numerals(text)).lower()


def _all_text(doc: GovDocumentSchema) -> str:
    parts = [
        doc.subject, doc.dept_name, doc.salutation,
        doc.paragraph_reason, doc.paragraph_details or "", doc.paragraph_purpose,
        doc.memo_intro or "", doc.memo_facts or "", doc.memo_law or "",
        doc.memo_consideration or "", doc.memo_request or "",
        doc.signatory_name, doc.signatory_position, doc.contact_dept,
    ]
    if doc.references:
        parts.extend(doc.references)
    if doc.attachments:
        parts.extend(doc.attachments)
    return "\n".join(p for p in parts if p)


def check_spelling(doc: GovDocumentSchema) -> List[TextCheckIssue]:
    """ตรวจคำที่สะกดผิดจากคลังคำที่พบบ่อย (อนุรักษ์นิยม ลด false positive)"""
    issues: List[TextCheckIssue] = []
    text = _all_text(doc)
    norm = _norm(text)
    for wrong, right in COMMON_TYPOS.items():
        if wrong == right:
            continue
        if wrong in text:
            issues.append(TextCheckIssue(
                rule_id="TEXT_TYPO", field="body", severity="warning",
                text=wrong, suggestion=right,
                message=f"พบคำที่อาจสะกดผิด: '{wrong}'",
            ))
    return issues


def check_consistency(doc: GovDocumentSchema, ctx: Optional[SourceDocumentContext] = None) -> List[TextCheckIssue]:
    """ตรวจความสอดคล้อง: ชื่อ/หน่วยงานจากต้นเรื่องถูกสะกดตรงกัน และตัวเลขไม่ปนกัน"""
    issues: List[TextCheckIssue] = []
    text = _all_text(doc)
    norm = _norm(text)

    entities = None
    if ctx:
        entities = getattr(ctx, "entities", None) or extract_entities(ctx.raw_text or "", method="regex")
    if entities:
        for ent in entities:
            if ent.kind not in ("person", "agency"):
                continue
            v_norm = _norm(ent.normalized or ent.value)
            if v_norm and v_norm not in norm:
                issues.append(TextCheckIssue(
                    rule_id="TEXT_ENTITY_MISSING", field="body", severity="info",
                    text=ent.value, suggestion="",
                    message=f"ชื่อ/หน่วยงาน '{ent.value}' จากต้นเรื่องไม่ปรากฏในฉบับร่าง — ตรวจสอบว่าไม่ตกหล่น",
                ))

    # เลขไทย/อารบิกปนในย่อหน้าเดียวกัน (เฉพาะข้อความสำคัญ) — ส่งต่อให้ผู้ใช้ดู ไม่แก้เอง
    for field_name, value in [("reason", doc.paragraph_reason), ("details", doc.paragraph_details or ""), ("purpose", doc.paragraph_purpose)]:
        if not value:
            continue
        has_thai = any(ch in "๐๑๒๓๔๕๖๗๘๙" for ch in value)
        has_arab = any(ch.isdigit() for ch in value)
        if has_thai and has_arab:
            issues.append(TextCheckIssue(
                rule_id="TEXT_MIXED_NUMERALS", field=field_name, severity="warning",
                text="", suggestion="เลือกใช้เลขไทยหรืออารบิกอย่างเดียวในย่อหน้านี้",
                message="พบเลขไทยและอารบิกปนกันในย่อหน้าเดียวกัน",
            ))
    return issues


def check_document_text(doc: GovDocumentSchema, ctx: Optional[SourceDocumentContext] = None) -> List[TextCheckIssue]:
    return check_spelling(doc) + check_consistency(doc, ctx)

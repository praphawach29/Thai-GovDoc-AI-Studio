"""
verification.py — ตรวจร่างเทียบต้นเรื่อง (Source-grounded verification)

เป้าหมาย: ลดข้อเท็จจริงที่คลาดเคลื่อน โดยเทียบชื่อ/หน่วยงาน/วันที่/เลขที่/จำนวนเงิน/ตัวเลข/
กำหนดการ/สิ่งที่ส่งมาด้วย และข้อกฎหมาย ระหว่างฉบับร่างกับต้นเรื่อง + โปรไฟล์หน่วยงาน

หลักการ:
- ไม่แสดงเปอร์เซ็นต์ OCR confidence ที่ไม่มีแหล่ง; ใช้สถานะ "พบหลักฐาน / ไม่พบหลักฐาน / ต้องยืนยัน"
- ไม่แก้ข้อความอัตโนมัติ; ให้ผู้ใช้ยอมรับ/ปฏิเสธ
"""

import re
from typing import List, Literal, Optional

from pydantic import BaseModel, Field

from core.models import GovDocumentSchema, SourceDocumentContext
from core.entity_extractor import extract_entities, normalize_thai_number
from core.thai_segmenter import to_arabic_numerals

EvidenceStatus = Literal["found", "not_found", "confirm"]


def _norm(text: Optional[str]) -> str:
    if not text:
        return ""
    return re.sub(r"[\s\u200b]+", "", to_arabic_numerals(text)).lower()


def _find_quote(haystack: str, needle: str) -> tuple[Optional[str], Optional[int], Optional[int]]:
    if not needle:
        return None, None, None
    idx = haystack.find(needle)
    if idx < 0:
        return None, None, None
    start = max(0, idx - 30)
    end = min(len(haystack), idx + len(needle) + 40)
    return haystack[start:end], idx, idx + len(needle)


class VerificationFinding(BaseModel):
    rule_id: str
    field: str
    severity: Literal["critical", "warning", "info"] = "warning"
    draft_value: str = ""
    evidence_status: EvidenceStatus = "confirm"
    source_quote: Optional[str] = None
    source_start: Optional[int] = None
    source_end: Optional[int] = None
    confidence: Optional[float] = None
    message: str = ""
    suggestion: str = ""
    status: Literal["pending", "accepted", "rejected"] = "pending"


class VerificationResult(BaseModel):
    findings: List[VerificationFinding] = Field(default_factory=list)
    verified_count: int = 0
    unverified_count: int = 0
    is_ready: bool = False

    @property
    def has_critical(self) -> bool:
        return any(f.severity == "critical" and f.status != "accepted" for f in self.findings)


def _draft_body(doc: GovDocumentSchema) -> str:
    parts = [
        doc.paragraph_reason or "",
        doc.paragraph_details or "",
        doc.paragraph_purpose or "",
        doc.memo_intro or "",
        doc.memo_facts or "",
        doc.memo_consideration or "",
        doc.memo_request or "",
        doc.subject or "",
        doc.salutation or "",
    ]
    if doc.references:
        parts.extend(doc.references)
    if doc.attachments:
        parts.extend(doc.attachments)
    return "\n".join(parts)


def verify_draft_against_source(doc: GovDocumentSchema, ctx: SourceDocumentContext) -> VerificationResult:
    findings: List[VerificationFinding] = []
    source_raw = ctx.raw_text or ""
    source_norm = _norm(source_raw)
    body = _draft_body(doc)
    body_norm = _norm(body)

    def add(rule_id, field, severity, draft_value, status, message, suggestion, quote=None, start=None, end=None, confidence=None):
        findings.append(VerificationFinding(
            rule_id=rule_id, field=field, severity=severity, draft_value=draft_value,
            evidence_status=status, source_quote=quote, source_start=start, source_end=end,
            confidence=confidence, message=message, suggestion=suggestion,
        ))

    # 1. เรื่อง (subject) ควรตรงกับต้นเรื่อง
    if ctx.source_subject and ctx.source_subject.strip() and not ctx.source_subject.strip().startswith("[✏️"):
        subject_norm = _norm(doc.subject)
        src_subj_norm = _norm(ctx.source_subject)
        if src_subj_norm and src_subj_norm not in subject_norm and subject_norm not in src_subj_norm:
            quote, start, end = _find_quote(source_raw, ctx.source_subject)
            add(
                "VERIFY_SUBJECT_DIFFERS", "subject", "warning", doc.subject, "confirm",
                "เรื่องของฉบับร่างอาจไม่ตรงกับเรื่องต้นเรื่อง",
                "ตรวจสอบเรื่องให้ตรงกับต้นเรื่อง หรือปรับต้นเรื่อง",
                quote, start, end, 0.9,
            )

    # 2. จำนวนเงิน/ตัวเลข/วันที่ ในร่างต้องมีหลักฐานในต้นเรื่อง (ยกเว้นวันที่ออกหนังสือปัจจุบัน)
    source_entities = ctx.entities or extract_entities(source_raw, method="regex")
    date_today_norm = _norm(doc.doc_date)
    for ent in source_entities:
        if ent.kind == "amount":
            v_norm = _norm(ent.normalized or ent.value)
            if v_norm and v_norm not in body_norm:
                add("VERIFY_AMOUNT_MISSING", "amount", "info", ent.value, "not_found",
                    "จำนวนเงินจากต้นเรื่องไม่ปรากฏในฉบับร่าง", "ตรวจว่ายังต้องระบุจำนวนเงินนี้หรือไม่",
                    ent.evidence.source_quote if ent.evidence else None,
                    ent.evidence.start if ent.evidence else None,
                    ent.evidence.end if ent.evidence else None, 0.9)
        elif ent.kind == "date":
            v_norm = _norm(ent.normalized or ent.value)
            if v_norm and v_norm not in body_norm and v_norm != date_today_norm:
                add("VERIFY_DATE_MISSING", "date", "warning", ent.value, "not_found",
                    "วันที่จากต้นเรื่องไม่ปรากฏในฉบับร่าง", "ตรวจสอบวันที่ให้ตรงกับต้นเรื่อง",
                    ent.evidence.source_quote if ent.evidence else None,
                    ent.evidence.start if ent.evidence else None,
                    ent.evidence.end if ent.evidence else None, 0.9)

    # 3. เลขที่หนังสือต้นเรื่องควรปรากฏในอ้างถึง/ภาคเหตุ (ถ้ามีอ้างถึง)
    if ctx.source_doc_no and ctx.source_doc_no.strip():
        if _norm(ctx.source_doc_no) not in body_norm:
            quote, start, end = _find_quote(source_raw, ctx.source_doc_no)
            add("VERIFY_DOC_NO_MISSING", "references", "warning", ctx.source_doc_no, "not_found",
                "เลขที่หนังสือต้นเรื่องไม่ปรากฏในหัวข้ออ้างถึง/ภาคเหตุ", "เพิ่มหนังสือที่อ้างถึงพร้อมเลขที่",
                quote, start, end, 0.9)

    # 4. ข้อกฎหมาย: ต้องปรากฏในต้นเรื่องหรือมาจากคลังที่ยืนยัน (ไม่ตรวจ % ที่ไม่มีแหล่ง)
    if doc.memo_law and doc.memo_law.strip() and not doc.memo_law.strip().startswith("[✏️"):
        law_norm = _norm(doc.memo_law)
        if law_norm not in source_norm:
            add("VERIFY_LAW_UNSOURCED", "memo_law", "critical", doc.memo_law, "not_found",
                "ข้อกฎหมายนี้ไม่พบในต้นเรื่อง และยังไม่มีแหล่งยืนยัน", "เว้นข้อกฎหมาย หรือยืนยันแหล่งในคลังข้อกฎหมาย",
                confidence=None)

    # 5. สิ่งที่ส่งมาด้วยที่ต้นเรื่องพบ แต่ร่างยังไม่มี
    if any(e.kind == "attachment" for e in source_entities) and not (doc.attachments or []):
        add("VERIFY_ATTACHMENTS_MISSING", "attachments", "info", "", "confirm",
            "ต้นเรื่องมีสิ่งที่ส่งมาด้วย แต่ฉบับร่างยังไม่ระบุ", "เพิ่มสิ่งที่ส่งมาด้วยหรือยืนยันว่าไม่ต้องมี")

    unverified = sum(1 for f in findings if f.evidence_status != "found")
    verified = len(findings) - unverified
    result = VerificationResult(
        findings=findings,
        verified_count=verified,
        unverified_count=unverified,
        is_ready=not any(f.severity == "critical" and f.status != "accepted" for f in findings),
    )
    return result

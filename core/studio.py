"""
studio.py — Business logic สำหรับหน้าเว็บ GovDoc Studio (web/studio)

รวมขั้นตอน "รับมอบหมาย → สกัดข้อความ → จำแนกชนิด → ร่าง → ตรวจ" ไว้ในที่เดียว
เพื่อให้ frontend เรียกผ่าน API ครั้งเดียว โดยไม่ผูกกับ Streamlit session state
"""

from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field

from core.ai_drafter import draft_from_context_rule_based
from core.classifier import ClassificationResult, classify_source_document
from core.extractor import extract_from_raw_text, extract_source_document
from core.linter import LintResult, lint_gov_document
from core.models import (
    DocType,
    GovDocumentSchema,
    MemoHierarchyLevel,
    SecretLevel,
    SourceDocumentContext,
    UrgencyLevel,
    UserProfileSchema,
)
from core.profile_manager import get_user_profile
from core.security import cloud_ai_allowed
from core.thai_date import blank_doc_number, format_thai_date


class StudioStep(BaseModel):
    """ขั้นตอนที่ระบบทำจริง เพื่อแสดงเป็นบทสนทนา/สถานะใน UI"""
    key: str
    label: str
    ok: bool = True
    detail: str = ""


class StudioCheck(BaseModel):
    """ผลตรวจเอกสาร: placeholder ที่ค้าง + Linter ระเบียบสารบรรณ"""
    placeholders: List[str] = Field(default_factory=list)
    lint: LintResult


class StudioDraftResult(BaseModel):
    context: Optional[SourceDocumentContext] = None
    classification: Optional[ClassificationResult] = None
    document: Optional[GovDocumentSchema] = None
    check: Optional[StudioCheck] = None
    steps: List[StudioStep] = Field(default_factory=list)
    cloud_ai_blocked: bool = False


def normalize_for_editor(doc: GovDocumentSchema) -> GovDocumentSchema:
    """
    บันทึกข้อความ: เติม memo_* จาก paragraph_* (ตัวเดียวกับที่ exporter ใช้)
    เพื่อให้หน้าแก้ไขแก้ฟิลด์ชุดเดียวกับที่ Word/PDF เรนเดอร์จริง
    """
    if doc.doc_type == DocType.INTERNAL:
        intro, facts, law, consideration, request = doc._memo_parts()
        doc.memo_intro = intro
        doc.memo_facts = facts
        doc.memo_law = law or None
        doc.memo_consideration = consideration
        doc.memo_request = request
    return doc


def check_document(doc: GovDocumentSchema) -> StudioCheck:
    return StudioCheck(placeholders=doc.find_placeholders(), lint=lint_gov_document(doc))


def create_blank_document(doc_type: DocType, profile: Optional[UserProfileSchema] = None) -> GovDocumentSchema:
    """เอกสารเปล่าพร้อม placeholder — ข้อมูลหน่วยงาน/ผู้ลงนามมาจากโปรไฟล์เท่านั้น"""
    p = profile or get_user_profile()
    internal = doc_type == DocType.INTERNAL
    reason = "[✏️ ระบุต้นเรื่อง]" if internal else "[✏️ ระบุภาคเหตุ]"
    details = "[✏️ ระบุข้อเท็จจริง]" if internal else "[✏️ ระบุภาคข้อเท็จจริง]"
    purpose = "[✏️ ระบุข้อพิจารณาและเสนอแนะ]" if internal else "[✏️ ระบุภาคความประสงค์]"
    return GovDocumentSchema(
        doc_type=doc_type,
        urgency=UrgencyLevel.NORMAL,
        secret=SecretLevel.NORMAL,
        use_thai_numerals=False,
        doc_number=blank_doc_number(use_thai_numerals=False),
        dept_name=p.department_full,
        doc_date=format_thai_date(use_thai_numerals=False),
        subject="[✏️ ระบุเรื่อง]",
        salutation="เรียน  [✏️ ระบุผู้รับ]",
        paragraph_reason=reason,
        paragraph_details=details,
        paragraph_purpose=purpose,
        memo_intro=reason if internal else None,
        memo_facts=details if internal else None,
        memo_consideration=purpose if internal else None,
        memo_request="จึงเรียนมาเพื่อโปรดพิจารณา" if internal else None,
        memo_hierarchy_level=MemoHierarchyLevel.DIV_TO_DEPT,
        closing="" if internal else "ขอแสดงความนับถือ",
        signatory_name=p.signatory_name,
        signatory_position=p.signatory_position,
        contact_dept=p.contact_dept,
        contact_tel=p.contact_tel,
        contact_fax=p.contact_fax,
        contact_email=p.contact_email,
    )


def start_draft(
    *,
    prompt: str = "",
    file_path: Optional[str] = None,
    doc_type_hint: Optional[DocType] = None,
    urgency: UrgencyLevel = UrgencyLevel.NORMAL,
    secret: SecretLevel = SecretLevel.NORMAL,
    api_key: Optional[str] = None,
) -> StudioDraftResult:
    """
    เริ่มร่างจากคำสั่งที่พิมพ์และ/หรือไฟล์ต้นเรื่อง
    - ชั้นความลับไม่ใช่ปกติ → ห้ามใช้ AI ภายนอก (fail-closed) ทั้งตอน OCR และร่าง
    - สกัดข้อความไม่สำเร็จ → ไม่สร้างร่าง (ห้ามแต่งเนื้อหาจากชื่อไฟล์)
    """
    allow_cloud = cloud_ai_allowed(secret)
    result = StudioDraftResult(cloud_ai_blocked=not allow_cloud)
    profile = get_user_profile()

    if file_path:
        ctx = extract_source_document(file_path, api_key=api_key, allow_cloud=allow_cloud, secret=secret)
        engine = ctx.ocr_engine_used or "ข้อความในไฟล์"
        result.steps.append(StudioStep(
            key="extract", label="อ่านไฟล์ต้นเรื่อง", ok=not ctx.extraction_failed,
            detail=(ctx.extraction_error or "อ่านไม่สำเร็จ") if ctx.extraction_failed
            else f"{ctx.page_count} หน้า · {engine}",
        ))
    elif prompt.strip():
        ctx = extract_from_raw_text(prompt.strip(), filename="คำสั่งผู้ใช้.txt")
        result.steps.append(StudioStep(key="extract", label="อ่านคำสั่งที่พิมพ์", detail=f"{len(prompt.strip())} ตัวอักษร"))
    else:
        result.steps.append(StudioStep(key="extract", label="ไม่มีข้อมูลต้นเรื่อง", ok=False,
                                       detail="พิมพ์คำสั่งหรือแนบไฟล์ก่อนเริ่มร่าง"))
        return result

    result.context = ctx
    if ctx.extraction_failed:
        return result

    cls = classify_source_document(ctx)
    result.classification = cls
    doc_type = doc_type_hint or cls.doc_type
    result.steps.append(StudioStep(
        key="classify", label="จำแนกชนิดหนังสือ",
        detail=f"แบบที่ {cls.form_no} · ความมั่นใจ {round(cls.confidence * 100)}%"
        + (" · ผู้ใช้เลือกประเภทเอง" if doc_type_hint else ""),
    ))

    doc = draft_from_context_rule_based(
        ctx,
        doc_type=doc_type,
        intent=cls.intent,
        my_dept=profile.department_full,
        my_signatory=profile.signatory_name,
        my_position=profile.signatory_position,
        contact_dept=profile.contact_dept,
        contact_tel=profile.contact_tel,
        secret=secret,
    )
    doc.urgency = urgency
    doc.secret = secret
    result.document = normalize_for_editor(doc)
    result.check = check_document(doc)
    result.steps.append(StudioStep(
        key="draft", label="ร่างหนังสือตามโครงสร้าง ๓ ภาค",
        detail=f"เหลือจุดที่ต้องระบุ {len(result.check.placeholders)} จุด",
    ))
    return result

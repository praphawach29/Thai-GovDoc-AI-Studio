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
import time

from core.llm_drafter import LLMConfig, apply_draft_content, draft_content_with_llm, ocr_images_with_llm
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


_PROVIDER_LABEL = {"claude": "Claude", "gemini": "Gemini"}


def _ai_step(ai) -> StudioStep:
    """สรุปการใช้ AI เป็นขั้นตอนเดียว เช่น 'Claude หมดเวลารอคำตอบ → ร่างด้วย Gemini'"""
    failed = [f"{_PROVIDER_LABEL.get(a.provider, a.provider)} {a.error}" for a in ai.attempts if not a.ok]
    if ai.content is not None:
        used = f"{_PROVIDER_LABEL.get(ai.provider, ai.provider)} ({ai.model})"
        detail = " · ".join(failed + [f"เรียบเรียงด้วย {used}"])
        if ai.truncated:
            detail += " · ต้นเรื่องยาวมาก ส่งเฉพาะส่วนต้น"
        return StudioStep(key="ai", label="AI เรียบเรียงเนื้อความ", detail=detail)
    reason = ai.skipped_reason or " · ".join(failed) or "ไม่สำเร็จ"
    return StudioStep(key="ai", label="ใช้ร่างตามกฎแทน AI", ok=not failed,
                      detail=reason + (" — เนื้อความเป็นโครงให้กรอกเอง" if failed or ai.skipped_reason else ""))


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
    ai_provider: Optional[str] = None      # "claude" | "gemini" | None (ร่างตามกฎ)


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


def _clean_summary(text: str) -> str:
    """สรุปต้นเรื่องจาก AI: ตัดบรรทัดว่าง/สัญลักษณ์นำหน้า/placeholder, ไม่เกิน ๔ บรรทัด"""
    lines = []
    for raw in (text or "").splitlines():
        line = raw.strip().lstrip("-*•·").strip()
        if not line or "[✏️" in line or "ระบุ" in line and line.startswith("["):
            continue
        lines.append(line[:300])
    return "\n".join(lines[:4])


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


DOC_TYPE_THAI = {DocType.INTERNAL: "บันทึกข้อความ (หนังสือภายใน)", DocType.EXTERNAL: "หนังสือภายนอก"}
_ASK_INTERNAL = ("บันทึกข้อความ", "หนังสือภายใน", "บันทึกเสนอ", "เสนอผู้บังคับบัญชา", "เสนอตามสายงาน",
                 "เสนอ ผอ", "เสนอผู้อำนวยการ", "เสนอหัวหน้า", "เสนอปลัด")
_ASK_EXTERNAL = ("หนังสือภายนอก", "หนังสือตอบ", "ตอบหนังสือ", "ตอบกลับ", "มีหนังสือถึง", "แจ้งตอบ")


def requested_doc_type(prompt: str) -> Optional[DocType]:
    """ประเภทที่ผู้ใช้ระบุในคำสั่ง เช่น 'ช่วยร่างบันทึกข้อความ...' (ไม่ระบุ = None)"""
    text = (prompt or "").replace(" ", "")
    internal = any(k.replace(" ", "") in text for k in _ASK_INTERNAL)
    external = any(k.replace(" ", "") in text for k in _ASK_EXTERNAL)
    if internal != external:
        return DocType.INTERNAL if internal else DocType.EXTERNAL
    return None


def choose_output_type(hint: Optional[DocType], prompt: str, *, has_source_file: bool,
                       classified: DocType) -> tuple:
    """ประเภทหนังสือที่จะร่าง (ไม่ใช่ประเภทของต้นเรื่อง):
    ผู้ใช้เลือก > คำสั่งที่พิมพ์ > มีไฟล์ต้นเรื่อง = บันทึกข้อความเสนอตามสายงาน > ตัวจำแนก"""
    if hint is not None:
        return hint, "ผู้ใช้เลือกเอง"
    asked = requested_doc_type(prompt)
    if asked is not None:
        return asked, "ตามคำสั่งที่พิมพ์"
    if has_source_file:
        # ต้นเรื่องที่รับเข้ามา (มักเป็นหนังสือภายนอก) ต้องเสนอผู้บังคับบัญชาด้วยบันทึกข้อความก่อน
        return DocType.INTERNAL, "ต้นเรื่องรับเข้า จึงร่างบันทึกเสนอตามสายงาน (เปลี่ยนประเภทได้ในหน้าแก้ไข)"
    return classified, "จำแนกจากเนื้อหา (เปลี่ยนประเภทได้ในหน้าแก้ไข)"


def start_draft(
    *,
    prompt: str = "",
    file_path: Optional[str] = None,
    doc_type_hint: Optional[DocType] = None,
    urgency: UrgencyLevel = UrgencyLevel.NORMAL,
    secret: SecretLevel = SecretLevel.NORMAL,
    api_key: Optional[str] = None,
    llm: Optional[LLMConfig] = None,
    recipient: str = "",
    review_party: str = "",
) -> StudioDraftResult:
    """
    เริ่มร่างจากคำสั่งที่พิมพ์และ/หรือไฟล์ต้นเรื่อง
    - ชั้นความลับไม่ใช่ปกติ → ห้ามใช้ AI ภายนอก (fail-closed) ทั้งตอน OCR และร่าง
    - สกัดข้อความไม่สำเร็จ → ไม่สร้างร่าง (ห้ามแต่งเนื้อหาจากชื่อไฟล์)
    """
    allow_cloud = cloud_ai_allowed(secret)
    result = StudioDraftResult(cloud_ai_blocked=not allow_cloud)
    profile = get_user_profile()
    # เวลารวมของคำขอ (อ่านไฟล์ + ร่าง) ต้องทันเพดาน 120 วินาทีของ Vercel (vercel.json)
    started = time.monotonic()
    request_budget = 105.0

    # ไฟล์สแกน: AI อ่านทุกหน้าในคำขอเดียว (Gemini → Claude)
    ocr_attempts = []

    def ai_ocr(images):
        ocr = ocr_images_with_llm(images, llm, budget_s=llm.ocr_timeout_s)
        ocr_attempts.extend(ocr.attempts)
        label = {"gemini": "Gemini", "claude": "Claude"}.get(ocr.provider, ocr.provider)
        return ocr.text, (f"{label} ({ocr.model})" if ocr.text else None)

    use_ai_ocr = llm is not None and llm.any_provider and allow_cloud

    if file_path:
        ctx = extract_source_document(file_path, api_key=api_key, allow_cloud=allow_cloud, secret=secret,
                                      ocr_fn=ai_ocr if use_ai_ocr else None)
        engine = ctx.ocr_engine_used or "ข้อความในไฟล์"
        failed_ocr = [f"{'Gemini' if a.provider == 'gemini' else 'Claude'} {a.error}" for a in ocr_attempts if not a.ok]
        detail = (ctx.extraction_error or "อ่านไม่สำเร็จ") if ctx.extraction_failed else f"{ctx.page_count} หน้า · {engine}"
        result.steps.append(StudioStep(
            key="extract", label="อ่านไฟล์ต้นเรื่อง", ok=not ctx.extraction_failed,
            detail=" · ".join(failed_ocr + [detail]),
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
    doc_type, why = choose_output_type(doc_type_hint, prompt, has_source_file=bool(file_path), classified=cls.doc_type)
    result.steps.append(StudioStep(
        key="classify", label="เลือกประเภทหนังสือที่จะร่าง",
        detail=f"{DOC_TYPE_THAI[doc_type]} · {why}",
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

    # AI เรียบเรียงเนื้อความ (Claude → Gemini) ไม่สำเร็จ/ไม่ได้ตั้งค่า = ใช้ร่างตามกฎข้างบน
    if llm is not None:
        ai = draft_content_with_llm(
            doc_type=doc.doc_type,
            budget_s=min(llm.total_timeout_s, max(0.0, request_budget - (time.monotonic() - started))),
            instruction=prompt if file_path else "",
            source_text=ctx.raw_text or "",
            config=llm, secret=secret,
            # ใช้ตัวที่อ่านไฟล์สำเร็จร่างต่อ ตัวที่เพิ่งล้มเหลวไว้ท้ายสุด
            prefer=next((a.provider for a in ocr_attempts if a.ok), None),
            avoid=tuple(a.provider for a in ocr_attempts if not a.ok),
            recipient=recipient if doc.doc_type == DocType.INTERNAL else "",
            review_party=review_party if doc.doc_type == DocType.INTERNAL else "",
        )
        result.ai_provider = ai.provider or None
        if ai.content is not None:
            doc = apply_draft_content(doc, ai.content)
            # สรุปต้นเรื่องที่ AI เขียนมาพร้อมร่าง (ไม่เรียก AI เพิ่ม) แทนบรรทัดที่ตัดมาจากต้นเรื่อง
            summary = _clean_summary(ai.content.source_summary)
            if summary:
                ctx.summary, ctx.summary_by_ai = summary, True
        result.steps.append(_ai_step(ai))
    result.document = normalize_for_editor(doc)
    result.check = check_document(doc)
    result.steps.append(StudioStep(
        key="draft", label="ร่างหนังสือตามโครงสร้าง ๓ ภาค",
        detail=f"เหลือจุดที่ต้องระบุ {len(result.check.placeholders)} จุด",
    ))
    return result

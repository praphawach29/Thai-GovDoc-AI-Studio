"""
intake.py — ตรวจข้อมูลที่ขาดและสร้างคำถามก่อนร่าง (deterministic, ไม่เรียก LLM)
ใช้กฎ required matrix แยกตามชนิดหนังสือ + ตัวเลือกองค์ประกอบ (ข้อกฎหมาย/อ้างถึง/สิ่งที่ส่งมาด้วย)
"""

from typing import List, Optional

from core.models import (
    DocumentKind,
    IntakeAssessment,
    IntakeQuestion,
    SourceDocumentContext,
    UserProfileSchema,
)


def _is_missing(value: Optional[str]) -> bool:
    text = (value or "").strip()
    if not text:
        return True
    return "ระบุ" in text or text.startswith("[✏️") or "หน่วยงานต้นเรื่อง" in text


def assess_intake(
    ctx: SourceDocumentContext,
    kind: DocumentKind,
    include_law: bool = False,
    include_references: bool = False,
    include_attachments: bool = False,
    profile: Optional[UserProfileSchema] = None,
) -> IntakeAssessment:
    """สร้างรายการคำถามเฉพาะข้อมูลที่ขาด/ควรยืนยัน โดยยึดกฎที่ตรวจสอบได้"""
    questions: List[IntakeQuestion] = []
    missing: List[str] = []

    # องค์ประกอบเอกสารที่ผู้ใช้เลือกเอง (ไม่บังคับให้มี)
    questions.append(IntakeQuestion(
        field="include_law", question="เอกสารนี้มีข้อกฎหมาย/ระเบียบที่ต้องอ้างอิงไหม?",
        required=False, kind="boolean", options=["ไม่มี", "มี"],
        reason="ถ้าไม่มี ระบบจะไม่แสดงหัวข้อ 'ข้อกฎหมาย'",
    ))
    questions.append(IntakeQuestion(
        field="include_references", question="มีหนังสือ/เรื่องที่อ้างถึงไหม?",
        required=False, kind="boolean", options=["ไม่มี", "มี"],
        reason="ถ้ามี ระบบจะแสดงหัวข้อ 'อ้างถึง'",
    ))
    questions.append(IntakeQuestion(
        field="include_attachments", question="มีสิ่งที่ส่งมาด้วยไหม?",
        required=False, kind="boolean", options=["ไม่มี", "มี"],
        reason="ถ้ามี ระบบจะแสดงหัวข้อ 'สิ่งที่ส่งมาด้วย'",
    ))

    # ข้อมูลจำเป็นแกน (ต้องตอบหรือเลือก placeholder)
    if _is_missing(ctx.source_subject):
        missing.append("source_subject")
        questions.append(IntakeQuestion(
            field="source_subject", question="เรื่องของหนังสือคืออะไร?",
            required=True, placeholder="[✏️ ระบุเรื่อง]",
            reason="เรื่องต้องมีก่อนร่าง",
        ))
    if _is_missing(ctx.source_dept):
        missing.append("source_dept")
        questions.append(IntakeQuestion(
            field="source_dept", question="หน่วยงาน/บุคคลต้นเรื่องคือใคร?",
            required=True, placeholder="[✏️ ระบุหน่วยงานต้นเรื่อง]",
            reason="ต้นเรื่องต้องระบุหน่วยงาน/ผู้ส่ง",
        ))

    # ข้อมูลที่แนะนำแต่ไม่บังคับ (เติมภายหลังได้)
    if _is_missing(ctx.requested_action):
        questions.append(IntakeQuestion(
            field="requested_action", question="ต้นเรื่องต้องการให้ดำเนินการอะไร (คำขอ/ประสงค์)?",
            required=False, placeholder="[✏️ ระบุสิ่งที่ต้นเรื่องประสงค์]",
            reason="ใช้สรุปภาคความประสงค์",
        ))

    if include_references:
        if _is_missing(ctx.source_doc_no):
            questions.append(IntakeQuestion(
                field="source_doc_no", question="เลขที่หนังสือต้นเรื่องคืออะไร?",
                required=False, placeholder="[✏️ ระบุเลขที่]",
                reason="ใช้ในหัวข้อ 'อ้างถึง'",
            ))
        if _is_missing(ctx.source_date):
            questions.append(IntakeQuestion(
                field="source_date", question="วันที่ของหนังสือต้นเรื่องคือเมื่อใด?",
                required=False, placeholder="[✏️ ระบุวันที่]",
                reason="ใช้ในหัวข้อ 'อ้างถึง'",
            ))

    if include_attachments:
        if not ctx.entities or not any(e.kind == "attachment" for e in ctx.entities):
            questions.append(IntakeQuestion(
                field="attachments", question="สิ่งที่ส่งมาด้วยมีอะไรบ้าง (คั่นด้วยบรรทัดใหม่)?",
                required=False, placeholder="[✏️ ระบุสิ่งที่ส่งมาด้วย จำนวนฉบับ/ชุด]",
                reason="ใช้ในหัวข้อ 'สิ่งที่ส่งมาด้วย'",
            ))

    ready = not any(q.required for q in questions)
    return IntakeAssessment(questions=questions, missing_fields=missing, ready=ready)

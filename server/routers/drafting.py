"""ยกร่าง ตรวจ และขัดเกลาหนังสือราชการ"""

from typing import Optional

from fastapi import APIRouter
from pydantic import BaseModel

from core.ai_drafter import (
    DraftingIntent,
    copilot_refine_text,
    draft_from_context_llm,
    draft_from_context_rule_based,
)
from core.intake import assess_intake
from core.linter import LintResult, lint_gov_document
from core.models import (
    DocType,
    DocumentKind,
    GovDocumentSchema,
    IntakeAssessment,
    SecretLevel,
    SourceDocumentContext,
)

router = APIRouter(tags=["drafting"])


class DraftRequest(BaseModel):
    context: SourceDocumentContext
    doc_type: DocType = DocType.EXTERNAL
    intent: DraftingIntent = DraftingIntent.ACCEPT
    use_llm: bool = False
    api_key: Optional[str] = None
    secret: SecretLevel = SecretLevel.NORMAL
    allow_cloud: bool = True


class IntakeRequest(BaseModel):
    context: SourceDocumentContext
    kind: DocumentKind = DocumentKind.EXTERNAL_LETTER
    include_law: bool = False
    include_references: bool = False
    include_attachments: bool = False


class RefineRequest(BaseModel):
    text: str
    command: str  # formal, concise, to_thai_nums, to_arabic_nums


@router.post("/api/v1/draft", response_model=GovDocumentSchema)
def draft_document(req: DraftRequest):
    """ร่างหนังสือตามโครงสร้าง 3 ภาค ตามเจตนา (ตอบรับ / ปฏิเสธ / ส่งต่อ / เสนออนุมัติ)"""
    if req.use_llm:
        return draft_from_context_llm(
            req.context,
            doc_type=req.doc_type,
            intent=req.intent,
            api_key=req.api_key,
            secret=req.secret,
            allow_cloud=req.allow_cloud,
        )
    return draft_from_context_rule_based(
        req.context, doc_type=req.doc_type, intent=req.intent, secret=req.secret
    )


@router.post("/api/v1/copilot/refine")
def copilot_refine(req: RefineRequest):
    """ขัดเกลาข้อความเฉพาะจุด"""
    result = copilot_refine_text(req.text, req.command)
    return {"original": req.text, "refined": result, "command": req.command}


@router.post("/api/v1/validate", response_model=LintResult)
def validate_document(doc: GovDocumentSchema):
    """ตรวจตามระเบียบงานสารบรรณ (วันที่, โครงสร้าง 3 ภาค, คำขึ้นต้น-ลงท้าย, ตัวเลข)"""
    return lint_gov_document(doc)


@router.post("/api/v1/placeholders")
def check_placeholders(doc: GovDocumentSchema):
    """ช่องที่ยังต้องกรอก (placeholder) ที่ค้างอยู่ในเอกสาร"""
    placeholders = doc.find_placeholders()
    return {"count": len(placeholders), "has_placeholders": len(placeholders) > 0, "placeholders": placeholders}


@router.post("/api/v1/intake/questions", response_model=IntakeAssessment)
def intake_questions(req: IntakeRequest):
    """ตรวจข้อมูลที่ขาดและสร้างคำถามก่อนร่าง"""
    return assess_intake(
        req.context,
        req.kind,
        include_law=req.include_law,
        include_references=req.include_references,
        include_attachments=req.include_attachments,
    )

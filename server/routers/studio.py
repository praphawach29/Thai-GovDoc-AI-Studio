"""API ของหน้าเว็บ GovDoc Studio (หน้าแรก + หน้าแก้ไขเอกสาร)"""

from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

from core.models import DocType, GovDocumentSchema, SecretLevel, UrgencyLevel
from core.profile_manager import get_user_profile
from core.studio import (
    StudioCheck,
    StudioDraftResult,
    check_document,
    create_blank_document,
    normalize_for_editor,
    start_draft,
)
from core.templates_library import get_preset_template, list_preset_templates
from server.deps import save_upload
from server.settings import Settings, get_settings

router = APIRouter(tags=["studio"])


class BlankRequest(BaseModel):
    doc_type: DocType = DocType.INTERNAL


@router.get("/api/v1/studio/profile")
def studio_profile():
    """โปรไฟล์หน่วยงาน/ผู้ลงนาม สำหรับแสดงบนหน้าแรก"""
    return get_user_profile()


@router.post("/api/v1/studio/draft", response_model=StudioDraftResult)
async def studio_draft(
    prompt: str = Form(""),
    doc_type: Optional[DocType] = Form(None),
    urgency: UrgencyLevel = Form(UrgencyLevel.NORMAL),
    secret: SecretLevel = Form(SecretLevel.NORMAL),
    file: Optional[UploadFile] = File(None),
    settings: Settings = Depends(get_settings),
):
    """เริ่มร่างจากคำสั่งที่พิมพ์และ/หรือไฟล์ต้นเรื่อง (สกัด → จำแนก → ร่าง → ตรวจ)"""
    saved_path: Optional[Path] = None
    if file is not None and file.filename:
        saved_path = await save_upload(file, settings)
    elif not prompt.strip():
        raise HTTPException(status_code=400, detail="พิมพ์คำสั่งหรือแนบไฟล์ต้นเรื่องก่อนเริ่มร่าง")

    result = start_draft(
        prompt=prompt,
        file_path=str(saved_path) if saved_path else None,
        doc_type_hint=doc_type,
        urgency=urgency,
        secret=secret,
    )
    if result.context is not None and file is not None and file.filename:
        result.context.source_filename = Path(file.filename).name
    return result


@router.post("/api/v1/studio/blank", response_model=GovDocumentSchema)
def studio_blank(req: BlankRequest):
    """เอกสารเปล่า (บันทึกข้อความ / หนังสือภายนอก) พร้อม placeholder"""
    return normalize_for_editor(create_blank_document(req.doc_type))


@router.get("/api/v1/studio/templates")
def studio_templates():
    """รายการแม่แบบมาตรฐาน (ไม่รวมเนื้อหา)"""
    return [
        {"id": t.template_id, "title": t.title, "category": t.category, "doc_type": t.doc_type.value}
        for t in list_preset_templates()
    ]


@router.get("/api/v1/studio/templates/{template_id}", response_model=GovDocumentSchema)
def studio_template(template_id: str):
    t = get_preset_template(template_id)
    if t is None:
        raise HTTPException(status_code=404, detail="ไม่พบแม่แบบ")
    return normalize_for_editor(t.schema.model_copy(deep=True))


@router.post("/api/v1/studio/check", response_model=StudioCheck)
def studio_check(doc: GovDocumentSchema):
    """ตรวจ placeholder ที่ค้าง + ระเบียบสารบรรณ ในครั้งเดียว"""
    return check_document(doc)

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
from server import source_store
from server.auth import CurrentUser, get_current_user, get_profile, get_supabase
from server.deps import save_upload
from server.settings import Settings, get_settings
from server.supabase import SupabaseClient

router = APIRouter(tags=["studio"])


class StudioDraftResponse(StudioDraftResult):
    # โหมด Supabase: แถวใน source_files ของไฟล์ต้นเรื่อง (ผูกกับเอกสารภายหลังได้)
    source_file_id: Optional[str] = None


class BlankRequest(BaseModel):
    doc_type: DocType = DocType.INTERNAL


@router.get("/api/v1/studio/profile")
def studio_profile():
    """โปรไฟล์หน่วยงาน/ผู้ลงนาม สำหรับแสดงบนหน้าแรก"""
    return get_user_profile()


@router.post("/api/v1/studio/draft", response_model=StudioDraftResponse)
async def studio_draft(
    prompt: str = Form(""),
    doc_type: Optional[DocType] = Form(None),
    urgency: UrgencyLevel = Form(UrgencyLevel.NORMAL),
    secret: SecretLevel = Form(SecretLevel.NORMAL),
    file: Optional[UploadFile] = File(None),
    source_path: Optional[str] = Form(None),     # โหมด Supabase: ไฟล์ที่อัปโหลดตรงเข้า Storage แล้ว
    source_name: Optional[str] = Form(None),
    settings: Settings = Depends(get_settings),
    user: Optional[CurrentUser] = Depends(get_current_user),
):
    """เริ่มร่างจากคำสั่งที่พิมพ์และ/หรือไฟล์ต้นเรื่อง (สกัด → จำแนก → ร่าง → ตรวจ)

    โหมด Supabase: ไฟล์ต้นเรื่องทุกไฟล์ถูกเก็บใน Storage + ตาราง source_files
    และไฟล์ชั่วคราวบนเซิร์ฟเวอร์ถูกลบทันทีหลังอ่านเสร็จ
    """
    has_file = file is not None and bool(file.filename)
    if not has_file and not source_path and not prompt.strip():
        raise HTTPException(status_code=400, detail="พิมพ์คำสั่งหรือแนบไฟล์ต้นเรื่องก่อนเริ่มร่าง")

    stored = None   # (path, filename, bytes) ที่ต้องบันทึกลง source_files
    saved_path: Optional[Path] = None
    if user is None:
        if source_path:
            raise HTTPException(status_code=400, detail="source_path ใช้ได้เมื่อเชื่อมต่อ Supabase เท่านั้น")
        if has_file:
            saved_path = await save_upload(file, settings)
    else:
        client = get_supabase(user, settings)
        profile = get_profile(user, client)
        if source_path:
            data, saved_path = source_store.download_source(client, settings, profile, source_path)
            stored = (source_path, source_name or Path(source_path).name, data)
        elif has_file:
            saved_path = await save_upload(file, settings)
            data = saved_path.read_bytes()
            path = source_store.new_storage_path(profile, file.filename)
            client.upload(settings.source_bucket, path, data, source_store.MIME_BY_SUFFIX[saved_path.suffix])
            stored = (path, file.filename, data)

    try:
        result = start_draft(
            prompt=prompt,
            file_path=str(saved_path) if saved_path else None,
            doc_type_hint=doc_type,
            urgency=urgency,
            secret=secret,
        )
    finally:
        if user is not None and saved_path is not None:
            saved_path.unlink(missing_ok=True)

    response = StudioDraftResponse(**result.model_dump())
    display_name = Path(file.filename).name if has_file else (Path(stored[1]).name if stored else None)
    if response.context is not None and display_name:
        response.context.source_filename = display_name
    if stored is not None:
        response.source_file_id = source_store.record_source_file(
            client, user, profile, path=stored[0], filename=stored[1], data=stored[2],
            ctx=response.context, secret=secret,
        )
    return response


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

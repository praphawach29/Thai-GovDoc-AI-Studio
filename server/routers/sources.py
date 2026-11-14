"""ไฟล์ต้นเรื่อง: อัปโหลดแล้วสกัดข้อความ/Metadata

โหมด Supabase (ไฟล์ใหญ่ได้ถึง 50 MB):
  1. POST /api/v1/sources/upload-url   → ได้ URL ให้เบราว์เซอร์ PUT ไฟล์ตรงเข้า Storage
  2. POST /api/v1/sources/register     → เซิร์ฟเวอร์อ่านไฟล์จาก Storage, สกัดข้อความ, บันทึก source_files
โหมดเครื่องเดียว / ไฟล์เล็ก: POST /api/v1/extract (multipart)
"""

import logging
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field

from core.extractor import extract_source_document
from core.models import SecretLevel, SourceDocumentContext
from core.security import cloud_ai_allowed
from server.auth import CurrentUser, Profile, get_current_user, get_profile, get_supabase, require_supabase_user
from server.deps import save_upload
from server.settings import Settings, get_settings
from server import source_store
from server.supabase import SupabaseClient

router = APIRouter(tags=["sources"])
logger = logging.getLogger("govdoc.api")


class UploadUrlRequest(BaseModel):
    filename: str
    size_bytes: int = Field(ge=1)


class RegisterSourceRequest(BaseModel):
    path: str
    filename: str
    secret: SecretLevel = SecretLevel.NORMAL
    document_id: Optional[str] = None


def _extract(path: Path, secret: SecretLevel, allow_cloud: bool = True) -> SourceDocumentContext:
    try:
        return extract_source_document(str(path), allow_cloud=allow_cloud, secret=secret)
    except Exception:
        logger.exception("extract failed for %s", path.name)
        raise HTTPException(status_code=500, detail="สกัดข้อความจากไฟล์ไม่สำเร็จ")


@router.post("/api/v1/extract", response_model=SourceDocumentContext)
async def extract_document(
    file: UploadFile = File(...),
    secret: SecretLevel = Form(SecretLevel.NORMAL),
    allow_cloud: bool = Form(True),
    settings: Settings = Depends(get_settings),
):
    """อัปโหลดไฟล์ต้นเรื่อง (PDF, Scan, Image, DOCX, TXT) เพื่อสกัดข้อความและ Metadata"""
    target_path = await save_upload(file, settings)
    ctx = _extract(target_path, secret, allow_cloud)
    ctx.source_filename = Path(file.filename or "").name
    return ctx


@router.post("/api/v1/sources/upload-url")
def create_upload_url(
    req: UploadUrlRequest,
    profile: Profile = Depends(get_profile),
    client: SupabaseClient = Depends(get_supabase),
    settings: Settings = Depends(get_settings),
):
    if req.size_bytes > settings.max_upload_bytes:
        raise HTTPException(status_code=413, detail=f"ไฟล์ใหญ่เกิน {settings.max_upload_bytes // (1024 * 1024)} MB")
    path = source_store.new_storage_path(profile, req.filename)
    return {"path": path, "upload_url": client.signed_upload_url(settings.source_bucket, path),
            "content_type": source_store.MIME_BY_SUFFIX[Path(path).suffix]}


@router.post("/api/v1/sources/register")
def register_source(
    req: RegisterSourceRequest,
    user: CurrentUser = Depends(require_supabase_user),
    profile: Profile = Depends(get_profile),
    client: SupabaseClient = Depends(get_supabase),
    settings: Settings = Depends(get_settings),
):
    data, temp = source_store.download_source(client, settings, profile, req.path)
    try:
        ctx = _extract(temp, req.secret, allow_cloud=cloud_ai_allowed(req.secret))
    finally:
        temp.unlink(missing_ok=True)
    ctx.source_filename = Path(req.filename).name
    source_id = source_store.record_source_file(
        client, user, profile, path=req.path, filename=req.filename, data=data, ctx=ctx,
        secret=req.secret, document_id=req.document_id,
    )
    return {"source_file_id": source_id, "context": ctx}

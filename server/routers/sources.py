"""ไฟล์ต้นเรื่อง: อัปโหลดแล้วสกัดข้อความ/Metadata"""

import logging
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile

from core.extractor import extract_source_document
from core.models import SecretLevel, SourceDocumentContext
from server.deps import save_upload
from server.settings import Settings, get_settings

router = APIRouter(tags=["sources"])
logger = logging.getLogger("govdoc.api")


@router.post("/api/v1/extract", response_model=SourceDocumentContext)
async def extract_document(
    file: UploadFile = File(...),
    secret: SecretLevel = Form(SecretLevel.NORMAL),
    allow_cloud: bool = Form(True),
    settings: Settings = Depends(get_settings),
):
    """อัปโหลดไฟล์ต้นเรื่อง (PDF, Scan, Image, DOCX, TXT) เพื่อสกัดข้อความและ Metadata"""
    target_path = await save_upload(file, settings)
    try:
        ctx = extract_source_document(str(target_path), allow_cloud=allow_cloud, secret=secret)
    except Exception:
        logger.exception("extract failed for %s", target_path.name)
        raise HTTPException(status_code=500, detail="สกัดข้อความจากไฟล์ไม่สำเร็จ")
    ctx.source_filename = Path(file.filename or "").name
    return ctx
